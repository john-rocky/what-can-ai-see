#!/usr/bin/env python3
"""Cut a fetched clip down to the window the event actually happens in.

Stock footage is not shot for this. A 9-second skateboard clip can spend its
first five seconds on an empty wall, and a uniform 6-panel sheet then spends
three panels on nothing while the fall itself lands half out of frame in the
last one. That is not a model failing to see the event — it is the harness never
showing it, and it would be scored as a miss.

So every field clip is trimmed to a window before it becomes a benchmark item,
and the window is written into meta.yaml so the cut is reproducible and auditable.
The rule used here:

  positives   include ~2s of the pre-event state, the event, and ~2s after.
              The lead-in is not padding — for `change` and `dwell` events the
              before-state IS half the evidence, and a clip that opens mid-event
              cannot be answered by anything.
  negatives   the same duration as the positive it pairs with. A negative that
              is systematically shorter or longer than its positive gives the
              model a cue that has nothing to do with the event.

The original is kept as clip.full.mp4 so a window can be re-cut without re-fetching.

usage:
  trim.py --clip clips/fall-5155837 --start 6.5 --end 12.5
  trim.py --clip clips/fall-5155837 --start 6.5 --duration 6
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
         str(video)], capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True, type=Path, help="the clip directory")
    ap.add_argument("--start", type=float, required=True)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--duration", type=float, default=None)
    args = ap.parse_args()

    clip_dir = args.clip
    full = clip_dir / "clip.full.mp4"
    cut = clip_dir / "clip.mp4"
    if not full.exists():
        if not cut.exists():
            raise SystemExit(f"no clip.mp4 in {clip_dir}")
        cut.rename(full)  # first trim: preserve the fetched original

    source_len = probe_duration(full)
    if args.end is None and args.duration is None:
        raise SystemExit("give --end or --duration")
    end = args.end if args.end is not None else args.start + args.duration
    if not (0 <= args.start < end <= source_len + 0.05):
        raise SystemExit(
            f"window {args.start}-{end}s is outside the source (0-{source_len:.2f}s)")

    # Re-encode rather than stream-copy: a copy cuts at the nearest keyframe, which
    # on a long-GOP stock clip can move the boundary by seconds and silently
    # invalidate the onset_s recorded against it.
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
         "-ss", f"{args.start:.3f}", "-to", f"{end:.3f}", "-i", str(full),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-an",
         "-avoid_negative_ts", "make_zero", str(cut)], check=True)

    # Any sheet rendered from the old cut is now wrong; drop them so the next
    # build_tasks run regenerates against the new window.
    for stale in list(clip_dir.glob("*.jpg")) + list(clip_dir.glob("g*.json")) + \
            list(clip_dir.glob("f1.json")) + list(clip_dir.glob("diff.json")):
        stale.unlink()

    print(json.dumps({
        "clip": clip_dir.name, "source_duration": round(source_len, 2),
        "trim": [args.start, round(end, 3)],
        "duration": round(end - args.start, 3),
        "note": "record this window as `trim:` in meta.yaml",
    }))


if __name__ == "__main__":
    main()
