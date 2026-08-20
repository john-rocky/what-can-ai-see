#!/usr/bin/env python3
"""Cut the fixtures the person-gate has to pass before a walk is allowed to start.

The gate is a promise made to a stranger on the street: nothing with you in it was
recorded. A promise that has never been tested is not a promise, and testing it by going
outside and hoping puts the person holding the phone in exactly the position the gate
exists to avoid.

So the app carries frames that are KNOWN to contain people, runs the detector over them at
launch, and refuses to enable Start unless every one of them fires. That turns three silent
failure modes into a visible refusal:

  - the detector did not load, or loaded and throws on every frame
  - the person class id is wrong for this detector family (yolox reports contiguous 0..79
    internally; if that ever reaches the gate un-mapped, `classID == 1` matches *bicycle*)
  - the score threshold is set above what this detector gives a real person

Frames are taken at several distances and framings on purpose. A fixture set of nothing but
big centred faces passes on a detector that would miss the person at the edge of the street,
which is the person most likely to object.

usage:
  gate_frames.py                       # default set, into walk/Resources/gate
  gate_frames.py --out walk/Resources/gate --per-clip 2
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Clip, timestamp, and what a person sees there. Chosen to span framings rather than to be
# easy: one hand only, people at a table mid-shot, a figure lying down (an odd pose for a
# person detector), a wide two-person room.
FIXTURES = [
    ("count-4035246", 1.0, "two women at a cafe table, mid shot"),
    ("count-6137848", 2.0, "three people at an outdoor table, wider"),
    ("handover-7424456", 1.5, "two people in a room, one seated on the floor"),
    ("fall-8526604", 0.5, "one man kneeling on a mat, close"),
    ("fall-7667144", 2.0, "a woman lying down, drawing — unusual pose"),
    ("action-6101146", 1.0, "one person seated at a table"),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "walk" / "Resources" / "gate")
    ap.add_argument("--size", default="960")
    args = ap.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    rows = []
    for clip, t, note in FIXTURES:
        src = ROOT / "clips" / clip / "clip.mp4"
        if not src.exists():
            print(f"  skip {clip} (no clip.mp4)")
            continue
        name = f"gate_{clip}.jpg"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(t), "-i", str(src),
             "-frames:v", "1", "-vf", f"scale={args.size}:-2", "-q:v", "3",
             "-y", str(args.out / name)], check=False)
        if (args.out / name).exists():
            rows.append({"image": name, "note": note, "expect": "person"})
            print(f"  {name}  {note}")

    if not rows:
        raise SystemExit("no fixtures cut — is clips/ populated?")
    (args.out / "gate_fixtures.json").write_text(json.dumps(rows, indent=1))
    print(f"\n{len(rows)} fixture(s) -> {args.out}")
    print("every one must detect a person or the app will not let a walk start")


if __name__ == "__main__":
    main()
