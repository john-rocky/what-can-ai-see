#!/usr/bin/env python3
"""Rank candidate clips by whether anything visibly changes and stays changed.

Curating by eye does not scale and it kept producing the same verdict for the
same reason: every kantine anomaly that worked (hand entering, coffee spilling,
grounds heaping) leaves a large persistent change in the frame, and every one
that failed (a plate dropped vs placed, a probe in the wrong hole, an item in the
wrong box) does not. That property is measurable, so measure it first and only
open the clips worth opening.

The measure reuses the classical baseline: median-of-opening-frames background,
per-frame changed-area fraction. Two numbers come out —

  peak      the largest changed area at any moment. High for any motion.
  settled   the changed area in the LAST second. High only if something changed
            and STAYED changed, which is what an anomaly leaves behind and what a
            passing robot arm does not.

`settled` is the one that predicts. A clip where the arm sweeps through scores a
big peak and a near-zero settled value; a spill scores both.

DOES NOT WORK — kept as a record of what was tried.

Run over the known-good and known-bad clips it ranked an EXPERT episode highest
(`assembly-wrong-grocery-ok`, 0.378) and the best working case lowest
(`damage-jar-pos`, 0.007). The reason is plain in hindsight: measured against its
own opening frames, a robot arm that finishes somewhere else is itself a large
persistent change, while a jar shattering into thin fragments covers very little
area. So the number tracks "did the arm end up elsewhere", not "was something
left behind".

The right formulation for a paired dataset is to compare the anomaly episode's
END STATE against its EXPERT counterpart's end state — what is different about
how this run finished. That is not implemented here. Until it is, curation stays
by eye, which is slow and is the real bottleneck on corpus size.

usage: screen_visible.py --clips a,b,c
"""
from __future__ import annotations
import argparse, subprocess, sys, tempfile
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent
FPS, WARMUP_S, PIXEL_DELTA = 6, 1.5, 25

def series(video: Path) -> list[float]:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
                        "-vf", f"fps={FPS},scale=320:-2", "-y", str(Path(td) / "f%05d.png")],
                       check=True)
        gs = [cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2GRAY)
              for p in sorted(Path(td).glob("f*.png"))]
    if not gs:
        return []
    n = max(3, int(WARMUP_S * FPS))
    bg = np.median(np.stack(gs[:n]), axis=0).astype(np.uint8)
    k = np.ones((3, 3), np.uint8)
    out = []
    for g in gs:
        fg = (cv2.absdiff(g, bg) > PIXEL_DELTA).astype(np.uint8) * 255
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k, iterations=1)
        out.append(float((fg > 0).sum()) / (g.shape[0] * g.shape[1]))
    return out

ap = argparse.ArgumentParser()
ap.add_argument("--clips", required=True)
a = ap.parse_args()

rows = []
for cid in [c.strip() for c in a.clips.split(",") if c.strip()]:
    v = ROOT / "clips" / cid / "clip.mp4"
    if not v.exists():
        print(f"  {cid}: missing"); continue
    s = series(v)
    if not s:
        continue
    settled = float(np.median(s[-FPS:]))
    rows.append((settled, max(s), cid))

print(f"{'clip':<40} {'peak':>7} {'settled':>8}   read as")
print("-" * 78)
for settled, peak, cid in sorted(rows, reverse=True):
    verdict = ("persistent change — worth watching" if settled >= 0.02
               else "transient motion only — likely nothing left behind")
    print(f"{cid:<40} {peak:>7.3f} {settled:>8.3f}   {verdict}")
