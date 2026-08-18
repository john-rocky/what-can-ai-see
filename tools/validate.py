#!/usr/bin/env python3
"""Check the corpus for the errors that look like model failures.

A benchmark's worst failure mode is not a wrong number, it is a wrong number that
looks right. Every check here exists because the mistake it catches would have
been scored as a model getting something wrong:

  duration drift   meta.yaml said 6.0s after a 6s trim was silently rejected on a
                   4.04s source. The clip stayed 4.04s and the metadata lied.
  broken pairs     pair_discrimination is computed per pair; a one-way or missing
                   `pair` link drops the pair silently and the cell reads "-".
  same-label pairs a positive paired with a positive scores as `blind` forever.
  duration cues    if negatives are systematically shorter than positives, a model
                   can score above chance from clip length alone.
  missing onset    latency_s is silently skipped without it, so a `motion`
                   positive with no onset publishes no latency and says nothing.

Exit code is 1 if anything is wrong, so this can gate a run.

usage: validate.py [--clips clips] [--strict]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DURATION_TOLERANCE = 0.15  # seconds
PAIR_DURATION_RATIO = 1.25  # positive/negative length may differ by at most this


def probe(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
         str(video)], capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=Path, default=ROOT / "clips")
    ap.add_argument("--events", type=Path, default=ROOT / "events" / "events.yaml")
    ap.add_argument("--strict", action="store_true",
                    help="also report unverified clips as problems")
    args = ap.parse_args()

    events = {e["id"]: e for e in yaml.safe_load(args.events.read_text())["events"]}
    metas: dict[str, dict] = {}
    for d in sorted(args.clips.iterdir()):
        meta_path = d / "meta.yaml"
        if meta_path.exists() and (d / "clip.mp4").exists():
            metas[d.name] = yaml.safe_load(meta_path.read_text())

    problems: list[str] = []
    verified = {k: m for k, m in metas.items()
                if m.get("label") in ("positive", "negative")}

    for cid, meta in metas.items():
        if cid not in verified:
            if args.strict:
                problems.append(f"{cid}: label is {meta.get('label')!r}, not curated")
            continue

        event = events.get(meta.get("event"))
        if event is None:
            problems.append(f"{cid}: unknown event {meta.get('event')!r}")
            continue

        actual = probe(args.clips / cid / "clip.mp4")
        claimed = meta.get("duration_s")
        if claimed is None:
            problems.append(f"{cid}: no duration_s")
        elif abs(float(claimed) - actual) > DURATION_TOLERANCE:
            problems.append(
                f"{cid}: duration_s says {claimed}s, clip.mp4 is {actual:.2f}s "
                f"— a trim probably failed")
        meta["_actual"] = actual

        # A `motion` or `change` positive without an onset publishes no latency.
        # `diffuse` and `state` events are present throughout, so null is correct.
        if (meta["label"] == "positive"
                and event["evidence"] in ("motion", "change")
                and meta.get("onset_s") is None):
            problems.append(f"{cid}: positive {event['evidence']} event has no onset_s")

        # Question/event mismatch. Assigned twice by hand and wrong twice: a hand
        # entering a machine was filed under `ppe-missing` ("is there a person not
        # wearing a hard hat?") and a coffee spill under `damage` ("is the object
        # cracked, crushed or torn?"). The model then answers a question the clip
        # does not pose, and the low score reads as a model failure. Cheap guard:
        # the hand-written ground truth should share some vocabulary with the
        # event's own positive definition.
        # Positives only: a negative's ground truth describes the ABSENCE of the
        # event ("the table stays clean"), so sharing no vocabulary with the event
        # definition is correct there, not a defect.
        gt = " ".join(str(meta.get("ground_truth", "")).lower().split())
        if meta["label"] == "positive" and gt and not gt.startswith("todo"):
            import re as _re
            stop = {"the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "is",
                    "it", "for", "with", "that", "this", "its", "be", "are", "was",
                    "not", "no", "from", "by", "has", "have", "into", "over", "than",
                    "then", "there", "their", "them", "they", "which", "while", "as"}
            def stem(w: str) -> str:
                for suf in ("ings", "ing", "ies", "ied", "es", "ed", "s"):
                    if len(w) - len(suf) >= 3 and w.endswith(suf):
                        return w[: -len(suf)]
                return w

            def words(s):
                # three characters, not four: the link between "Is the ground wet?"
                # and "wet cobblestones" is a three-letter word, and a guard that
                # cannot see it fires on every correctly-labelled material clip.
                return {stem(w) for w in _re.findall(r"[a-z]{3,}", s.lower())
                        if w not in stop}

            def related(a: set[str], b: set[str]) -> bool:
                """Prefix overlap, not set intersection.

                Two passes, because neither alone is enough. Prefix containment
                catches fall/falls once both are stemmed; a shared
                five-character head catches
                shatters/shattered, where neither word contains the other. This is
                deliberately crude — it only has to notice that a clip and its
                event are talking about completely different things."""
                return any(x.startswith(y) or y.startswith(x) or x[:5] == y[:5]
                           for x in a for y in b)

            ev_words = words(str(event.get("positive", "")) + " "
                             + str(event.get("question", "")))
            if ev_words and not related(words(gt), ev_words):
                problems.append(
                    f"{cid}: ground truth shares no vocabulary with event "
                    f"{meta['event']!r} — check the question actually asks about "
                    f"what this clip shows")

        onset = meta.get("onset_s")
        if onset is not None and not (0 <= float(onset) <= actual):
            problems.append(f"{cid}: onset_s {onset}s is outside the clip (0-{actual:.2f}s)")

    for cid, meta in verified.items():
        mate_id = meta.get("pair")
        if not mate_id:
            # A pair is one way to be scoreable, not the only one. A positive clip
            # on a FIXED camera with a measured onset is scored on its own
            # before/after — the scene is then held perfectly constant, which the
            # cross-scene stock pairs never manage (F19). A negative on a fixed
            # camera is scored as quiet footage, for false alarms per hour. Both
            # need the camera to be still; on a moving camera "before" and "after"
            # differ by the pan.
            fixed = str(meta.get("camera")) == "fixed"
            # A STABLE clip has no onset by design: the scene holds and the correct
            # answer never changes. What it measures is whether the model's answer
            # holds too. That is judgement stability — one of the four metrics this
            # benchmark set out to report — and it needs an expected answer, not an
            # onset. Counting people in a still cafe shot is not a worse test than a
            # spill; it is a different genre of reading, and a model that flips
            # between "two" and "more than two" across identical windows has told
            # you something no latency number would.
            if fixed and str(meta.get("kind")) == "stable":
                if str(meta.get("expected")) not in ("yes", "no"):
                    problems.append(f"{cid}: kind: stable needs expected: yes|no")
                continue
            if fixed and meta.get("label") == "positive" and meta.get("onset_s") is not None:
                continue
            if fixed and meta.get("label") == "negative":
                continue
            why = ("no pair, and " + (
                "camera is not recorded as fixed" if not fixed else
                "no measured onset, so there is no before/after to score"))
            problems.append(f"{cid}: {why} — it will never be scored")
            continue
        mate = verified.get(mate_id)
        if mate is None:
            problems.append(f"{cid}: pairs with {mate_id!r}, which is not a verified clip")
            continue
        if mate.get("pair") != cid:
            problems.append(f"{cid}: pairs with {mate_id}, but it pairs with "
                            f"{mate.get('pair')!r} — the link is one-way")
        if mate.get("label") == meta.get("label"):
            problems.append(f"{cid} and {mate_id} are both {meta['label']}")
        if mate.get("event") != meta.get("event"):
            problems.append(f"{cid} ({meta['event']}) is paired across events with "
                            f"{mate_id} ({mate.get('event')})")
        a, b = meta.get("_actual"), mate.get("_actual")
        if a and b and max(a, b) / min(a, b) > PAIR_DURATION_RATIO:
            problems.append(f"{cid} is {a:.1f}s and {mate_id} is {b:.1f}s — clip length "
                            f"alone is a cue to the answer")

    n_pairs = len({tuple(sorted((c, m["pair"]))) for c, m in verified.items()
                   if m.get("pair") in verified}) if verified else 0
    print(f"{len(metas)} clip(s), {len(verified)} curated, {n_pairs} complete pair(s)")
    by_event: dict[str, int] = {}
    for m in verified.values():
        by_event[m["event"]] = by_event.get(m["event"], 0) + 1
    for ev, n in sorted(by_event.items()):
        print(f"  {ev:<16} {n}")

    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  ✗ {p}")
        sys.exit(1)
    print("\nno problems")


if __name__ == "__main__":
    main()
