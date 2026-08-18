#!/usr/bin/env python3
"""One long film becomes many continuous shots, because a cut is not a camera.

The corpus was built one clip at a time and the arithmetic was brutal: 327
candidates fetched and measured, 6 kept. Almost all of the loss was camera motion
and missing lead-in, both properties of how stock footage is shot and sold.

A long film inverts it. One licence check, one download, and a 1956 industrial
documentary yields 33 continuous shots of eight seconds or more — a whole process,
in order, with the same camera holding still inside each shot.

The one thing that must not be skipped is the cut detection. A contact sheet that
spans an edit shows the model two different places and asks what changed; whatever
it answers measures the edit, not the scene. `warehouse-31751344` was rejected from
the stock corpus for exactly this. So shots are split on scene change first, and
only the interior of a shot is ever windowed.

What this does NOT do is decide whether a shot is worth keeping. Old documentaries
pan, zoom and dissolve constantly; `enter_onset.py` measures the camera and most
shots will fail that test. This just makes the units.

usage:
  split_shots.py --video film.mp4 --prefix alu --min-len 8 --out-dir clips
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def duration(v: Path) -> float:
    return float(subprocess.run(
        ["ffprobe", "-v", "0", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(v)], capture_output=True, text=True).stdout.strip() or 0)


def cuts(v: Path, threshold: float) -> list[float]:
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(v),
         "-vf", f"select='gt(scene,{threshold})',metadata=print:file=-",
         "-f", "null", "-"], capture_output=True, text=True).stdout
    return [float(l.split("pts_time:")[1].split()[0])
            for l in out.splitlines() if "pts_time:" in l]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", type=Path, required=True)
    ap.add_argument("--prefix", required=True, help="clip id prefix, e.g. alu")
    ap.add_argument("--min-len", type=float, default=8.0)
    ap.add_argument("--max-len", type=float, default=20.0,
                    help="a longer shot is cut down to this from its middle")
    ap.add_argument("--threshold", type=float, default=0.35)
    ap.add_argument("--source", default="", help="url or archive.org identifier")
    ap.add_argument("--licence", default="public domain")
    ap.add_argument("--out-dir", type=Path, default=ROOT / "clips")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dur = duration(args.video)
    bounds = [0.0] + cuts(args.video, args.threshold) + [dur]
    shots = [(a, b) for a, b in zip(bounds, bounds[1:]) if b - a >= args.min_len]
    print(f"{len(bounds)-1} shots, {len(shots)} at least {args.min_len}s "
          f"(film is {dur/60:.1f} min)")

    for n, (a, b) in enumerate(shots):
        # Trim a little off each end: scene detection lands on the first frame of
        # the new shot, and dissolves bleed across the boundary.
        a, b = a + 0.3, b - 0.3
        if b - a > args.max_len:
            mid = (a + b) / 2
            a, b = mid - args.max_len / 2, mid + args.max_len / 2
        cid = f"{args.prefix}-s{n:03d}"
        if args.dry_run:
            print(f"   {cid}  {a:.1f}-{b:.1f}s  ({b-a:.1f}s)")
            continue
        d = args.out_dir / cid
        d.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{a:.2f}", "-i", str(args.video),
             "-t", f"{b-a:.2f}", "-vf", "scale=1280:-2", "-an", "-y",
             str(d / "clip.mp4")], check=True)
        (d / "meta.yaml").write_text(f"""\
# Shot {n} of {args.video.name}, cut by tools/split_shots.py at scene threshold
# {args.threshold}. NOT YET SCOREABLE: measure the camera with enter_onset.py, then
# set event, label, onset_s and camera. A shot from a documentary is not a camera
# feed until it has been checked for pans and zooms.
id: {cid}
tier: field
event: UNVERIFIED
label: UNVERIFIED
pair: null
onset_s: null
duration_s: {round(b-a, 2)}
camera: UNVERIFIED
ground_truth: >-
  TODO — describe what is actually visible.
source:
  kind: archive
  provider: archive.org
  id: {args.source or args.video.stem}
  shot: {n}
  in_film_s: [{round(a, 2)}, {round(b, 2)}]
  license: {args.licence}
conditions:
  viewpoint: UNVERIFIED
  distance: UNVERIFIED
  light: UNVERIFIED
  occlusion: UNVERIFIED
  blur: UNVERIFIED
  clutter: UNVERIFIED
""")
        print(f"   {cid}  {a:.1f}-{b:.1f}s  ({b-a:.1f}s)")


if __name__ == "__main__":
    main()
