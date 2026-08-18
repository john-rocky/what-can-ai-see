#!/usr/bin/env python3
"""What the models SAID, not just whether they said Yes.

Every prompt in this benchmark asks for a verdict *and* a sentence of evidence:

    Answer with the single word Yes or No on the first line, then one short
    sentence of evidence.

The sentence has been on disk since the first streaming run and was never read.
Only the Yes/No was scored, which is how a model that reports events in specific,
confident, fabricated detail scored the same as one that shrugs — both land at
0.50 (F17), and the reason they get there is the whole story.

Three things here are mechanical, with no language model and no keyword list
deciding anything:

  fabrication   The model said Yes on a window that ENDS BEFORE the event began.
                Its sentence is then a description of something that has not
                happened yet, whatever it says. Reported with the sentences, so
                the claim can be read rather than believed.

  cited panel   Models name panels — "in panel 4, the person is on the ground".
                Each window's panels have known timestamps, so a citation inside
                a pre-onset window points at a frame that provably does not
                contain the event. This is the difference between "false alarm"
                and "documented fabrication".

  repeat        Byte-identical sentences on consecutive windows. Consecutive
                windows share 3 of 4 panels but never all 4, so the image the
                model is looking at has changed. A model repeating itself word
                for word across a changed image is not re-reading it.

  mute          A model that emits a bare "Yes"/"No" and no sentence, having been
                asked for one. LFM2.5-VL 450M does this on 100% of windows, and
                it is also the only model at exactly chance. That is a signal
                available with NO ground truth at all: a model ignoring half the
                instruction is not reading the image either.

Deliberately NOT done here: deciding whether a sentence "means" the event
happened. That needs negation handling ("without any indication of a fall"
contains the word fall) and would put a fragile keyword rule under the headline
number. The three above need none of it.

usage:
  described.py --clips spill-pos,fall-live-pos
  described.py --all --examples 3
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STREAM = ROOT / "runs" / "stream"

PANEL = re.compile(r"\bpanel\s*([1-9])\b", re.I)
LEAD = re.compile(r"^\s*(yes|no)\b[\.,:;]?\s*", re.I)
LABEL = re.compile(r"^(evidence|reason)\s*[:\-]\s*", re.I)
BOXED = re.compile(r"\\boxed\{\s*(yes|no)\s*\}", re.I)


def verdict(answer: str) -> bool | None:
    a = (answer or "").strip()
    if not a:
        return None
    m = BOXED.search(a)
    if m:
        return m.group(1).lower() == "yes"
    m = LEAD.match(a)
    return None if not m else m.group(1).lower() == "yes"


def sentence(answer: str) -> str:
    """The evidence half: everything after the verdict token."""
    a = LEAD.sub("", (answer or "").strip(), count=1)
    a = LABEL.sub("", a).strip()
    return " ".join(a.split())


def scan(clip: str):
    d = STREAM / clip
    spec_path = d / "windows.json"
    if not spec_path.exists():
        return None
    spec = json.loads(spec_path.read_text())
    onset = spec.get("onset_s")
    win = {w["i"]: w for w in spec["windows"]}
    per_model = defaultdict(lambda: {"n": 0, "mute": 0, "fab": [], "denied": [],
                                     "pre": 0, "post": 0, "cited_pre": 0,
                                     "seq": [], "repeat": 0})
    for p in sorted(d.glob("*.jsonl")):
        if p.stem.startswith(("tasks", "frames", "detect-", "baseline")):
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("ok") or "model" not in r:
                continue
            parts = r["id"].split("|")
            if len(parts) != 3:
                continue
            w = win.get(int(parts[1][1:]))
            if w is None:
                continue
            s = per_model[r["model"]]
            s["n"] += 1
            txt = sentence(r.get("answer", ""))
            s["seq"].append((w["i"], txt))
            if not txt:
                s["mute"] += 1
            v = verdict(r.get("answer", ""))
            if onset is None:
                continue
            before = w["t_end"] < onset
            s["pre" if before else "post"] += 1
            if before and v is True:
                s["fab"].append((w["t_end"], txt))
                if PANEL.search(txt):
                    s["cited_pre"] += 1
            if not before and v is False and txt:
                s["denied"].append((w["t_end"], txt))
    for s in per_model.values():
        # consecutive by window index, so a gap does not count as a repeat
        seq = sorted(s["seq"])
        s["repeat"] = sum(1 for (i0, a), (i1, b) in zip(seq, seq[1:])
                          if a and i1 == i0 + 1 and a == b)
        s["repeat_of"] = max(0, len(seq) - 1)
    return spec, onset, per_model


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default=None, help="comma-separated clip ids")
    ap.add_argument("--all", action="store_true", help="every positive clip with an onset")
    ap.add_argument("--examples", type=int, default=2,
                    help="fabricated sentences to print per model per clip")
    args = ap.parse_args()

    if args.all:
        clips = []
        for d in sorted(STREAM.iterdir()):
            wj = d / "windows.json"
            if wj.exists() and json.loads(wj.read_text()).get("onset_s") is not None:
                clips.append(d.name)
    else:
        clips = [c.strip() for c in (args.clips or "").split(",") if c.strip()]
    if not clips:
        raise SystemExit("no clips — pass --clips or --all")

    tot = defaultdict(lambda: {"n": 0, "mute": 0, "pre": 0, "fab": 0, "cited_pre": 0,
                               "post": 0, "denied": 0, "repeat": 0, "repeat_of": 0})
    for clip in clips:
        got = scan(clip)
        if not got:
            continue
        spec, onset, per_model = got
        print(f"\n=== {clip}   onset {onset}s   \"{spec['question']}\"")
        for m, s in sorted(per_model.items()):
            t = tot[m]
            for k in ("n", "mute", "pre", "post", "repeat", "repeat_of"):
                t[k] += s[k]
            t["fab"] += len(s["fab"]); t["denied"] += len(s["denied"])
            t["cited_pre"] += s["cited_pre"]
            bits = [f"{len(s['fab'])}/{s['pre']} before the event"]
            if s["mute"]:
                bits.append(f"{s['mute']}/{s['n']} mute")
            if s["denied"]:
                bits.append(f"{len(s['denied'])} denied while describing")
            print(f"  {m:<22} claimed it {', '.join(bits)}")
            for t_end, txt in s["fab"][: args.examples]:
                mark = "  [cites a panel]" if PANEL.search(txt) else ""
                print(f"      {t_end:>5.1f}s  \u201c{txt[:110]}\u201d{mark}")

    print("\n\nTOTALS — every window whose correct answer is No because the event "
          "has not started yet")
    print(f"{'model':<22}{'windows':>9}{'mute':>7}{'pre-onset':>11}{'claimed':>9}"
          f"{'rate':>7}{'w/panel':>9}{'repeats':>9}")
    print("-" * 85)
    for m, s in sorted(tot.items(), key=lambda kv: -(kv[1]["fab"] / max(1, kv[1]["pre"]))):
        rate = 100 * s["fab"] / s["pre"] if s["pre"] else 0
        rep = f"{100*s['repeat']/s['repeat_of']:.0f}%" if s["repeat_of"] else "-"
        print(f"{m:<22}{s['n']:>9}{s['mute']:>7}{s['pre']:>11}{s['fab']:>9}"
              f"{rate:>6.0f}%{s['cited_pre']:>9}{rep:>9}")
    print("\nA cited panel inside a pre-onset window points at a frame recorded "
          "before the event.\nThe sentence describes something that is not in the "
          "picture it is citing.")


if __name__ == "__main__":
    main()
