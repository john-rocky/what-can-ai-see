#!/usr/bin/env python3
"""Turn model answers into the four numbers a PoC decision actually turns on.

The headline metric here is NOT recall. Recall alone is the oldest way to make a
detector look good: a model that answers Yes to everything scores 1.00 on it. Two
of the three models in the first floor run did exactly that — one always Yes, one
always No — and a recall column would have shown one of them as perfect.

So the unit of measurement is the matched PAIR: a positive clip and the hard
negative built to look like it. Four outcomes per pair, and only one is a
detection:

    pos=Yes neg=No     discriminated   the model can tell them apart
    pos=Yes neg=Yes    trigger-happy   fires on the look-alike too
    pos=No  neg=No     blind           misses it
    pos=No  neg=Yes    inverted        worse than a coin

`pair_discrimination` is the fraction that land in the first box. Chance is 0.25.
A model that answers the same word to both clips scores 0 no matter which word.

Reported alongside, because they answer different questions:
  recall            of positives called Yes                 "will it catch the event"
  false_alarm_rate  of negatives called Yes                 "will it cry wolf"
  fa_per_hour       false alarms per camera-hour            the operations number
  latency_s         named panel time minus true onset       "how late"
  unparseable       answers with no extractable verdict     never silently dropped
  degenerate        the model gave one answer to everything the disqualifier

usage: score.py --index runs/floor/tasks.index.json --results runs/floor/*.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# Verdict extraction. The prompt asks for a bare Yes/No on the first line; small
# models comply loosely, so this reads the first line, then the first sentence, and
# gives up rather than guessing. `unparseable` is reported, never coerced to No —
# scoring a refusal as a miss would flatter every model that hedges.
_YES = re.compile(r"^\W*(yes|yeah|correct|true)\b", re.I)
_NO = re.compile(r"^\W*(no|nope|false|none)\b", re.I)
_INLINE_YES = re.compile(r"\b(yes)\b", re.I)
_INLINE_NO = re.compile(r"\b(no|not|does not|doesn't|never)\b", re.I)
# MiniCPM-V 4.6 ignores "answer Yes or No on the first line" and instead reasons,
# then puts the verdict in \boxed{} — the format its checkpoint was tuned for. A
# harness that caps tokens for terse models and parses only the first line scores
# that as a refusal. It is not: the answer is there, further down and in a
# different wrapper. Check the box first, before any positional heuristic.
_BOXED = re.compile(r"\\boxed\s*\{\s*(yes|no)", re.I)



def verdict(answer: str) -> bool | None:
    text = (answer or "").strip()
    if not text:
        return None
    if (m := _BOXED.search(text)):
        return m.group(1).lower() == "yes"
    first = text.splitlines()[0].strip()
    if _YES.match(first):
        return True
    if _NO.match(first):
        return False
    # Fall back to the first sentence of the whole answer.
    head = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if _YES.search(head) and not _INLINE_NO.search(head):
        return True
    if _INLINE_NO.search(head) and not _INLINE_YES.search(head):
        return False
    return None


def panel_number(answer: str, panels: int) -> int | None:
    text = (answer or "").strip()
    if re.search(r"\bnone\b", text, re.I):
        return None
    m = re.search(r"\b([0-9]{1,2})\b", text)
    if not m:
        return None
    k = int(m.group(1))
    return k if 1 <= k <= panels else None


def event_vocabulary(sources: Path) -> dict[str, re.Pattern]:
    """The positive title regex from sources.yaml, reused as event vocabulary.

    It already encodes "what words name this event" — `smoke|fire|flame|burn` for
    smoke-fire, `fall|slip|trip|tumble` for fall — which is exactly what is needed
    to ask whether a model's own free description named the thing its yes/no
    answer then denied.
    """
    if not sources.exists():
        return {}
    doc = yaml.safe_load(sources.read_text()).get("queries", {})
    out = {}
    for event, spec in doc.items():
        pattern = (spec.get("positive") or {}).get("title")
        if pattern:
            out[event] = re.compile(pattern)
    return out


def load_results(paths: list[Path]) -> dict[tuple[str, str], dict]:
    """Result lines only. A `runs/<batch>/*.jsonl` glob also matches the batch's
    own tasks.jsonl, whose lines have no `model`; skip those rather than making
    the caller spell out every result file."""
    out = {}
    for p in paths:
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if "model" not in r or "id" not in r:
                continue
            out[(r["model"], r["id"])] = r
    if not out:
        raise SystemExit("no result records found — did you pass only the task file?")
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", type=Path, required=True)
    ap.add_argument("--results", type=Path, nargs="+", required=True)
    ap.add_argument("--sources", type=Path, default=ROOT / "events" / "sources.yaml",
                    help="supplies each event's vocabulary for the contradiction check")
    ap.add_argument("--out", type=Path, default=None, help="write scores as JSON")
    args = ap.parse_args()

    index = {row["task_id"]: row for row in json.loads(args.index.read_text())}
    vocabulary = event_vocabulary(args.sources)
    results = load_results(args.results)
    models = sorted({m for m, _ in results})

    scored: list[dict] = []
    for model in models:
        # cell = (encoding, event) -> per-clip verdicts
        by_cell: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
        gate_answers: list[bool | None] = []

        for row in index.values():
            key = (model, row["task_id"])
            if key not in results:
                continue
            r = results[key]
            answer = r.get("answer", "") if r.get("ok") else ""
            if not r.get("ok"):
                entry["runtime_failed"] = True
            cell = (row["encoding"], row["event"])
            entry = by_cell[cell].setdefault(
                row["clip"], {"label": row["label"], "row": row})
            if row["question"].startswith("gate"):
                v = verdict(answer)
                entry.setdefault("gates", {})[row["question"]] = v
                if row["question"] == "gate":  # v1 is the scoring variant
                    entry["gate"] = v
                    entry["gate_text"] = answer
                    entry["ms"] = r.get("ms")
                    gate_answers.append(v)
            elif row["question"] == "when":
                entry["when"] = panel_number(answer, row["panels"])
                entry["when_text"] = answer
            elif row["question"] == "open":
                entry["open_text"] = answer

        # A model that answered every gate question the same way is not detecting
        # anything; flag it before any per-cell number is read.
        non_null = [v for v in gate_answers if v is not None]
        degenerate = bool(non_null) and len(set(non_null)) == 1

        for (encoding, event), clips in sorted(by_cell.items()):
            pos = [c for c in clips.values() if c["label"] == "positive"]
            neg = [c for c in clips.values() if c["label"] == "negative"]

            def rate(group, want=True):
                seen = [c.get("gate") for c in group if c.get("gate") is not None]
                return (sum(1 for v in seen if v is want) / len(seen)) if seen else None

            recall = rate(pos, True)
            far = rate(neg, True)

            # Pair outcomes: only pairs where BOTH clips produced a verdict count.
            outcomes = {"discriminated": 0, "trigger_happy": 0, "blind": 0, "inverted": 0}
            pairs = 0
            for c in pos:
                mate_id = c["row"].get("pair")
                mate = clips.get(mate_id)
                if mate is None or c.get("gate") is None or mate.get("gate") is None:
                    continue
                pairs += 1
                p, n = c["gate"], mate["gate"]
                outcomes["discriminated" if (p and not n) else
                         "trigger_happy" if (p and n) else
                         "blind" if (not p and not n) else "inverted"] += 1

            # Latency: the model's named panel, converted to that panel's timestamp,
            # minus the true onset. Only defined for positives it actually called.
            delays = []
            for c in pos:
                onset, k = c["row"].get("onset_s"), c.get("when")
                if onset is None or k is None or not c.get("gate"):
                    continue
                delays.append(round(c["row"]["panel_times"][k - 1] - onset, 2))

            # Self-contradiction: on a POSITIVE clip, the gate says No while the
            # model's own open description names the event. Restricted to positives
            # because there the two answers cannot both be right — the event is
            # present, so naming it and denying it is a contradiction, not a
            # judgement call. This is the failure F5 and F7 are both instances of,
            # promoted from anecdote to a counted column.
            vocab = vocabulary.get(event)
            denied = 0
            for c in pos:
                if c.get("gate") is False and vocab and vocab.search(c.get("open_text") or ""):
                    denied += 1

            # A cell is only a transition test if its POSITIVES contain the
            # before-state. Where they do not, the question collapses to "is the
            # event in this image", which one frame answers as well as twelve —
            # and comparing `f1` against `g6` on such a cell measures nothing.
            trans = [c["row"].get("shows_transition") for c in pos]
            transition_cell = (all(t is True for t in trans) if trans and
                               all(t is not None for t in trans) else None)

            total_gate = len(pos) + len(neg)
            unparseable = sum(
                1 for c in list(pos) + list(neg)
                if c.get("gate") is None and not c.get("runtime_failed"))
            runtime_failures = sum(
                1 for c in list(pos) + list(neg) if c.get("runtime_failed"))

            # Stability: of the clips asked with more than one phrasing of the same
            # question, the fraction where every phrasing gave the same verdict.
            # Decoding is greedy, so a disagreement is prompt sensitivity, not noise.
            multi = [c for c in list(pos) + list(neg)
                     if len([v for v in c.get("gates", {}).values() if v is not None]) > 1]
            stability = None
            if multi:
                agreed = sum(
                    1 for c in multi
                    if len({v for v in c["gates"].values() if v is not None}) == 1)
                stability = round(agreed / len(multi), 3)

            # Clips here are 6s; a system polling once per clip-length window runs
            # 600 inferences an hour. This is a projection from that stated rate,
            # not a measurement of a deployed camera.
            clip_s = 6.0
            fa_h = round(far * (3600 / clip_s), 1) if far is not None else None

            scored.append({
                "model": model, "encoding": encoding, "event": event,
                "positives": len(pos), "negatives": len(neg), "pairs": pairs,
                "recall": recall, "false_alarm_rate": far,
                "fa_per_hour_at_1_per_6s": fa_h,
                "balanced_accuracy": (
                    round((recall + (1 - far)) / 2, 3)
                    if recall is not None and far is not None else None),
                "pair_discrimination": (
                    round(outcomes["discriminated"] / pairs, 3) if pairs else None),
                "pair_outcomes": outcomes,
                "latency_s": (round(sum(delays) / len(delays), 2) if delays else None),
                "prompt_stability": stability, "stability_n": len(multi),
                "transition_cell": transition_cell,
                "denied_own_description": denied,
                "unparseable": unparseable, "runtime_failures": runtime_failures,
                "gate_answers": total_gate,
                "degenerate_model": degenerate,
                "tokens_per_panel": next(iter(clips.values()))["row"][
                    "tokens_per_panel_at_196"],
            })

    # ── report ────────────────────────────────────────────────────────────────
    def fmt(v, spec="{:.2f}"):
        return "  -  " if v is None else spec.format(v)

    print(f"{'model':<22} {'enc':<5} {'event':<15} {'recall':>7} {'FA':>7} "
          f"{'pairOK':>7} {'balAcc':>7} {'lat_s':>7} {'stab':>6} {'unp':>4} {'deny':>4}")
    print("-" * 100)
    for s in scored:
        print(f"{s['model']:<22} {s['encoding']:<5} {s['event']:<15} "
              f"{fmt(s['recall']):>7} {fmt(s['false_alarm_rate']):>7} "
              f"{fmt(s['pair_discrimination']):>7} {fmt(s['balanced_accuracy']):>7} "
              f"{fmt(s['latency_s'], '{:+.1f}'):>7} "
              f"{fmt(s['prompt_stability']):>6} {s['unparseable']:>4} "
              f"{s['denied_own_description'] or '':>4}")

    broken = {}
    for s in scored:
        if s["runtime_failures"]:
            broken[s["model"]] = broken.get(s["model"], 0) + s["runtime_failures"]
    if broken:
        print("\nRUNTIME FAILURES — the model produced no output at all. Not scored as "
              "wrong answers:")
        for m, n_ in sorted(broken.items()):
            print(f"  {m}: {n_} task(s)")

    tcells = [s for s in scored if s["transition_cell"] is True]
    scells = [s for s in scored if s["transition_cell"] is False]
    def mean_pd(rows):
        v = [r["pair_discrimination"] for r in rows if r["pair_discrimination"] is not None]
        return sum(v) / len(v) if v else None
    if tcells and scells:
        mt, ms = mean_pd(tcells), mean_pd(scells)
        print(f"\ntransition cells (positive shows the before-state): {len(tcells)}, "
              f"mean pair discrimination {mt if mt is None else round(mt, 3)}")
        print(f"state cells      (event present from panel 1):       {len(scells)}, "
              f"mean pair discrimination {ms if ms is None else round(ms, 3)}")
        print("  a state cell does not test transition detection; one frame answers it.")

    denials = [s for s in scored if s["denied_own_description"]]
    if denials:
        print("\nDENIED ITS OWN DESCRIPTION — on a positive clip the model named the "
              "event in its\nfree description and answered No to the yes/no question:")
        for s in denials:
            print(f"  {s['model']} / {s['encoding']} / {s['event']}: "
                  f"{s['denied_own_description']} of {s['positives']}")

    flagged = sorted({s["model"] for s in scored if s["degenerate_model"]})
    if flagged:
        print("\nDEGENERATE — one answer to every gate question, so no number above "
              "is a detection:")
        for m in flagged:
            print(f"  {m}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(scored, indent=2))
        print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
