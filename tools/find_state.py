#!/usr/bin/env python3
"""Find pairs of frames that show the same place in two different states.

The 2026-08 conclusion in SCENARIOS.md was that stock footage does not carry states — a wet
floor and a dry floor look like the same shop, so the cases where a VLM might earn its place
are the cases nobody films. That was a conclusion about STOCK footage. Process films are
different: Gilbreth filmed a bench being emptied, and a 1954 supermarket film shows shelves
being stocked. The state is in there because documenting the process was the point.

The hard part is not finding it, it is not fooling myself. Picking frames by eye is how five
findings went wrong in one session. So the pair has to be chosen by two mechanical criteria
that pull in opposite directions:

  same place   phase correlation says the camera did not move between them. A pair from two
               camera positions confounds the state change with a viewpoint change, which is
               F18 — the finding that moving the camera swaps first and third place.

  different    the frames differ substantially in content anyway. Two identical frames from a
               static shot are trivially "same place", and they are not a state pair.

Both together mean: the camera held still and the contents changed. That is the shape of
"the shelf was full and now it is empty" and it can be found without an opinion about what
is in the frame.

What it does NOT do is say what the state IS. That is the human step, and it belongs in
`meta.yaml` as ground truth, written after looking at the pair that came out of here.

usage:
  find_state.py --video sources/film/OutofThi1954.mp4 --from 600 --to 1300 --every 4
  find_state.py --video sources/film/OriginalFilm.mp4 --from 330 --to 620 --top 8
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent


def frames(video: Path, t0: float, t1: float, every: float, work: Path) -> list[tuple[float, np.ndarray]]:
    out = []
    t = t0
    while t <= t1:
        f = work / f"f{int(t*10):07d}.png"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.1f}", "-i", str(video),
             "-frames:v", "1", "-vf", "scale=320:240", "-y", str(f)], check=False)
        if f.exists():
            img = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                out.append((t, img.astype(np.float32)))
        t += every
    return out


def camera_shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Returns (shift in px, response). **Both**, and the caller must use both.

    Discarding the response is what retracted F29. `cv2.phaseCorrelate` on two images with
    no correspondence returns a near-zero shift with a response near zero — it defaults to
    the origin rather than failing — so an intertitle card scored 0.54 px against a
    workbench and I read that as "the camera held still". Calibration on this material:
    a frame against itself gives response 1.000, two frames of the same shot 5 s apart give
    0.333, and a title card against a bench gives 0.040. Anything under ~0.15 means the
    shift is not a measurement of anything.

    Blur first for a separate reason: phase correlation keys on high-frequency detail, and
    on a film scan that detail is GRAIN — the mistake that once made 31 of 33 static shots
    read as moving.
    """
    fa = cv2.GaussianBlur(a, (0, 0), 2.0)
    fb = cv2.GaussianBlur(b, (0, 0), 2.0)
    (dx, dy), response = cv2.phaseCorrelate(fa, fb)
    return float((dx * dx + dy * dy) ** 0.5), float(response)


def content_change(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference after equalising exposure — film brightness drifts between
    shots and would otherwise read as content."""
    na = (a - a.mean()) / (a.std() + 1e-6)
    nb = (b - b.mean()) / (b.std() + 1e-6)
    return float(np.abs(na - nb).mean())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--from", dest="t0", type=float, required=True)
    ap.add_argument("--to", dest="t1", type=float, required=True)
    ap.add_argument("--every", type=float, default=4.0)
    ap.add_argument("--max-shift", type=float, default=2.5,
                    help="pixels of camera motion allowed between the two frames")
    ap.add_argument("--min-response", type=float, default=0.15,
                    help="phase-correlation response below which the shift is meaningless. "
                         "See camera_shift(): an unrelated pair scores 0.04 and still "
                         "reports a sub-pixel shift.")
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()

    with tempfile.TemporaryDirectory() as td:
        fs = frames(args.video, args.t0, args.t1, args.every, Path(td))
        if len(fs) < 2:
            raise SystemExit("not enough frames")
        print(f"{len(fs)} frames sampled from {args.video.name}\n")
        cands = []
        for i in range(len(fs)):
            for j in range(i + 1, len(fs)):
                ta, a = fs[i]
                tb, b = fs[j]
                s, resp = camera_shift(a, b)
                # Response first: a low-response pair has no correspondence at all, and its
                # shift is an artefact of the transform, not a measurement.
                if resp < args.min_response or s > args.max_shift:
                    continue
                cands.append((content_change(a, b), s, resp, ta, tb))
        cands.sort(reverse=True)
        if not cands:
            print("no pair held the camera still — this stretch is all moving shots")
            return
        print(f"{'change':>8}{'shift px':>10}{'resp':>7}{'A':>9}{'B':>9}   gap")
        for c, s, resp, ta, tb in cands[: args.top]:
            print(f"{c:>8.3f}{s:>10.2f}{resp:>7.2f}{ta:>8.0f}s{tb:>8.0f}s{tb-ta:>7.0f}s")
        print("\nLook at the top pairs before believing any of them: this says the camera "
              "held and the pixels changed, not that the CHANGE IS A STATE.")


if __name__ == "__main__":
    main()
