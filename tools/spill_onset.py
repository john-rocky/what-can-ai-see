#!/usr/bin/env python3
"""Measure when a spill appears, instead of reading it off a contact sheet.

Onsets in this corpus were eyeballed from 12-panel sheets, which gives a
resolution of a few seconds and no way to check the answer. For a spill on a pale
table the event has an objective signature: the fraction of the table that is
brown. This finds the first frame where that fraction crosses a level and stays
above it, which is both more precise and auditable.

It also catches contamination. The negative for the first spill pair was built
from an episode the dataset labels "normal"; this measure scores its table at
0.024 brown at the end, against 0.003 for the other four normals. It had a spill
in it, and the pair was scored for hours before anyone looked.

An absolute level only works for one view. On the oblique camera the wooden table
itself falls inside the colour range, so every clip reads 0.04 and every clip looks
like a spill. `--mode relative` compares each clip against its OWN opening seconds
instead, which is view-independent: what matters is that the brown fraction rose,
not what it started at. Use relative for anything but the overhead camera.

Relative mode still needs eyes on the control. On `spill-neg-v2` it fires at 7.4s
at +0.004 — that is the cup of dark coffee and the jug entering the lower crop as
the arm sets them down, not a spill, and the frames say so. A measurement that
disagrees with the label is a reason to look, not a verdict.

usage:
  spill_onset.py --clips spill-pos,spill-neg --fps 10
  spill_onset.py --clips spill-pos-v2 --roi oblique --mode relative --rise 0.004
"""
from __future__ import annotations
import argparse, subprocess, tempfile
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent
# Amber/brown on a pale wooden table, in HSV. Deliberately narrow: a wide range
# also matches the wooden table itself and the robot's shadow.
LO, HI = (5, 80, 40), (30, 255, 190)


# Where the table is, as fractions of the frame (top, bottom, left, right). The
# overhead camera and the oblique one see the table in different places, and the
# oblique one has a large brown pinboard on the back wall that lands inside the
# colour range — measuring the whole frame there reports a spill in every clip.
ROIS = {
    "overhead": (0.45, 1.00, 0.15, 0.85),
    "oblique": (0.62, 1.00, 0.00, 1.00),
}


def brown_series(video: Path, fps: int, roi: str = "overhead") -> list[float]:
    top, bot, left, right = ROIS[roi]
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
                        "-vf", f"fps={fps},scale=480:-2", "-y", str(Path(td) / "f%05d.png")],
                       check=True)
        out = []
        for p in sorted(Path(td).glob("f*.png")):
            hsv = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2HSV)
            m = cv2.inRange(hsv, LO, HI)
            h, w = m.shape
            m = m[int(h * top):int(h * bot), int(w * left):int(w * right)]
            out.append(float((m > 0).sum()) / m.size)
        return out


ap = argparse.ArgumentParser()
ap.add_argument("--clips", required=True)
ap.add_argument("--fps", type=int, default=10)
ap.add_argument("--roi", default="overhead", choices=sorted(ROIS))
ap.add_argument("--mode", default="absolute", choices=["absolute", "relative"],
                help="relative scores each clip against its own opening seconds")
ap.add_argument("--rise", type=float, default=0.004,
                help="rise over baseline that counts, for --mode relative")
ap.add_argument("--level", type=float, default=0.012,
                help="brown fraction that counts as a spill being present")
ap.add_argument("--hold", type=float, default=1.0, help="seconds it must stay above")
a = ap.parse_args()

print(f"{'clip':<34} {'baseline':>9} {'end':>7} {'onset':>8}  verdict")
print("-" * 74)
for cid in [c.strip() for c in a.clips.split(",") if c.strip()]:
    v = ROOT / "clips" / cid / "clip.mp4"
    if not v.exists():
        print(f"  {cid}: missing"); continue
    s = brown_series(v, a.fps, a.roi)
    if a.mode == "relative":
        base = float(np.median(s[: max(3, int(1.5 * a.fps))]))
        s = [x - base for x in s]
    base = float(np.median(s[: a.fps]))
    end = float(np.median(s[-a.fps:]))
    # In relative mode the series is already baseline-subtracted, so the bar is the
    # RISE, not the absolute level the overhead camera was calibrated against.
    level = a.rise if a.mode == "relative" else a.level
    need = int(a.hold * a.fps)
    onset = None
    for i in range(len(s) - need):
        if all(x >= level for x in s[i:i + need]):
            onset = i / a.fps
            break
    verdict = "spill" if end >= level else "clean"
    print(f"{cid:<34} {base:>9.4f} {end:>7.4f} "
          f"{(f'{onset:.1f}s' if onset is not None else '—'):>8}  {verdict}")
