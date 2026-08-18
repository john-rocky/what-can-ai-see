#!/usr/bin/env python3
"""Of the things a model says are there, how many are actually there?

`coverage.py` measures what a model volunteers. It deliberately does not ask
whether any of it is true: a model that says "a person is holding a cup" with no
cup in frame counts under PEOPLE and OBJECT exactly like one that is right. This
is the other half.

An object detector gives an independent inventory of what is present. RF-DETR
returns COCO classes, so the check is limited to the ~80 things COCO knows — it
can confirm a person, a cup, a bottle, a car; it can say nothing about "the floor
is wet" or "she starts writing". Within that limit two numbers are computable
without a single hand annotation:

  named and there   the model named a COCO object the detector also found
  named, not there  the model named one the detector did not find anywhere in
                    the frame

The second is the interesting one and it is NOT simply hallucination. The detector
misses things — it is a 2020s model with a score threshold, run on one frame of
four, and a cup behind an arm is invisible to it and obvious to a person. So a
mismatch means "unconfirmed", not "invented". What makes it usable anyway is the
comparison BETWEEN models: they all face the same detector, on the same frames,
with the same blind spots. A model with twice the unconfirmed rate of another is
saying twice as much that cannot be checked.

usage: grounding.py [--examples 3]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEUTRAL = ROOT / "runs" / "neutral"

# COCO names as they appear in ordinary prose, mapped to the detector's label.
SPOKEN = {
    "person": ["person", "people", "man", "men", "woman", "women", "worker",
               "someone", "individual", "child", "boy", "girl", "customer"],
    "cup": ["cup", "mug", "glass of"], "bottle": ["bottle"], "bowl": ["bowl"],
    "chair": ["chair"], "couch": ["couch", "sofa"], "bed": ["bed"],
    "dining table": ["table", "desk", "workbench", "bench"],
    "tv": ["screen", "monitor", "television"], "laptop": ["laptop"],
    "cell phone": ["phone"], "keyboard": ["keyboard"], "mouse": ["mouse"],
    "book": ["book", "notebook"], "clock": ["clock"], "vase": ["vase"],
    "potted plant": ["plant"], "car": ["car"], "truck": ["truck", "forklift"],
    "bicycle": ["bicycle", "bike"], "motorcycle": ["motorcycle"],
    "skateboard": ["skateboard"], "cat": ["cat"], "dog": ["dog"],
    "bird": ["bird"], "backpack": ["backpack"], "handbag": ["handbag", "bag"],
    "umbrella": ["umbrella"], "knife": ["knife"], "spoon": ["spoon"],
    "fork": ["fork"], "sink": ["sink"], "oven": ["oven"], "refrigerator": ["fridge"],
    "microwave": ["microwave"], "toaster": ["toaster"], "scissors": ["scissors"],
    "banana": ["banana"], "apple": ["apple"], "orange": ["orange"],
    "sandwich": ["sandwich"], "pizza": ["pizza"], "cake": ["cake"],
    "traffic light": ["traffic light"], "bus": ["bus"], "train": ["train"],
}
LEAD = re.compile(r"^\s*(yes|no)\b[\.,:;]?\s*", re.I)
ECHO = re.compile(r"(the image is a contact sheet[^.]*\.|contact sheet of \d+ frames[^.]*\.|"
                  r"covering the last [\d.]+s of a camera feed[^.]*\.|in time order[^.]*\.|"
                  r"panel \d+ is the (earliest|latest)[^.]*\.)", re.I)


def body(a: str) -> str:
    return " ".join(ECHO.sub(" ", LEAD.sub("", (a or "").strip(), count=1)).split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=0)
    args = ap.parse_args()

    present = defaultdict(set)
    for line in (NEUTRAL / "detect-rf-detr.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("ok"):
            present[r["id"]] = {b["label"] for b in r.get("boxes", [])}

    stat = defaultdict(lambda: [0, 0, 0])   # confirmed, unconfirmed, windows
    ex = defaultdict(list)
    for f in sorted(NEUTRAL.glob("*.jsonl")):
        if f.stem in ("tasks", "frames", "detect-rf-detr"):
            continue
        m = f.stem
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("ok") or r["id"] not in present:
                continue
            txt = body(r.get("answer", "")).lower()
            if not txt:
                continue
            stat[m][2] += 1
            there = present[r["id"]]
            for coco, spoken in SPOKEN.items():
                if not any(re.search(rf"\b{re.escape(s)}\w*\b", txt) for s in spoken):
                    continue
                if coco in there:
                    stat[m][0] += 1
                else:
                    stat[m][1] += 1
                    if len(ex[m]) < args.examples:
                        ex[m].append((coco, sorted(there) or ["nothing"], txt[:96]))

    models = sorted(stat)
    print("Objects a model named, checked against an independent detector on the")
    print("same frame. COCO classes only — actions, materials and weather cannot")
    print("be checked this way and are not counted.\n")
    print(f"{'model':<20}{'confirmed':>11}{'unconfirmed':>13}{'unconfirmed rate':>18}")
    print("-" * 62)
    for m in models:
        c, u, n = stat[m]
        print(f"{m:<20}{c:>11}{u:>13}{(100*u//max(1,c+u)):>17}%")
    print("\nA high rate is not proof of invention: the detector misses things too.")
    print("What it compares is how much each model says that cannot be checked.")
    if args.examples:
        print("\nExamples of unconfirmed mentions:")
        for m in models:
            for coco, there, txt in ex[m]:
                print(f"\n  {m} — said {coco!r}, detector found {there}")
                print(f"     “{txt}”")


if __name__ == "__main__":
    main()
