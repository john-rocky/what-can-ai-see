#!/usr/bin/env python3
"""One clean clip -> a controlled ladder of viewing conditions.

The corpus is licence-clean stock with no self-shot footage, so conditions cannot
be staged in front of a camera. Synthesising them from a clean source is not a
second-best substitute here — it is the better experiment. Two clips shot in
different places differ in a dozen ways at once, so a gap between them cannot be
attributed to darkness or to occlusion. A clip and its own degraded copy differ in
exactly one, so the curve that comes out is an ablation rather than a comparison.

Five axes, each with three levels, each a single ffmpeg filter chain:

  resolution   downscale then upscale — detail is destroyed, framing is kept
  darkness     exposure down, contrast down, sensor noise up
  occlusion    opaque bars over a fixed fraction of the frame
  blur         temporal frame averaging — real motion smear, not a gaussian
  compression  low bitrate and a long GOP — the artefact every real CCTV feed has

Deliberately NOT included: distance. Making a subject smaller in the frame needs
more scene around it than the source contains, and padding it with black would
measure the padding. Distance enters this benchmark two honest ways instead — the
panel-count ladder in sheet.py, which shrinks every panel for real, and sourcing
wide shots as their own clips.

usage:
  degrade.py --clip clips/fall-01/clip.mp4 --axis darkness --level 2 --out out.mp4
  degrade.py --clip clips/fall-01/clip.mp4 --all --out-dir clips/fall-01/degraded
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

# level -> filter chain. Level 0 is the untouched source and is never rendered.
# The numbers are chosen so level 3 is bad-but-not-hopeless: a human can still
# call the event on every level-3 clip, which is what makes a model failing there
# a finding rather than an unfair test.
AXES: dict[str, dict[int, str]] = {
    # Downscale to a target height, then back up. The upscale uses `neighbor` so
    # no interpolation invents detail the sensor never had.
    "resolution": {
        1: "scale=-2:240:flags=area,scale=-2:{h}:flags=neighbor",
        2: "scale=-2:120:flags=area,scale=-2:{h}:flags=neighbor",
        3: "scale=-2:60:flags=area,scale=-2:{h}:flags=neighbor",
    },
    # Exposure and contrast down together — underexposure alone just looks dim,
    # while real low light also crushes contrast and adds shot noise.
    "darkness": {
        1: "eq=brightness=-0.15:contrast=0.85,noise=alls=8:allf=t",
        2: "eq=brightness=-0.30:contrast=0.70,noise=alls=16:allf=t",
        3: "eq=brightness=-0.45:contrast=0.55,noise=alls=26:allf=t",
    },
    # Static opaque bars: a pillar, a rack upright, a parked vehicle. Fractions of
    # frame width covered: ~17%, ~33%, ~50%.
    "occlusion": {
        1: "drawbox=x=iw*0.40:y=0:w=iw*0.17:h=ih:color=black@1.0:t=fill",
        2: "drawbox=x=iw*0.30:y=0:w=iw*0.17:h=ih:color=black@1.0:t=fill,"
           "drawbox=x=iw*0.62:y=0:w=iw*0.16:h=ih:color=black@1.0:t=fill",
        3: "drawbox=x=iw*0.22:y=0:w=iw*0.17:h=ih:color=black@1.0:t=fill,"
           "drawbox=x=iw*0.50:y=0:w=iw*0.17:h=ih:color=black@1.0:t=fill,"
           "drawbox=x=iw*0.78:y=0:w=iw*0.16:h=ih:color=black@1.0:t=fill",
    },
    # Temporal averaging is what a slow shutter actually does: it smears along the
    # direction of motion and leaves static background sharp. A gaussian blurs both.
    "blur": {
        1: "tmix=frames=3:weights='1 1 1'",
        2: "tmix=frames=7:weights='1 1 1 1 1 1 1'",
        3: "tmix=frames=13:weights='1 1 1 1 1 1 1 1 1 1 1 1 1'",
    },
    # Bitrate is applied as an encoder setting, not a filter; the value is the
    # target bitrate and the chain is a no-op passthrough.
    "compression": {1: "null", 2: "null", 3: "null"},
}

COMPRESSION_BITRATE = {1: "400k", 2: "150k", 3: "60k"}


def probe_height(video: Path) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=height", "-of", "json", str(video)],
        capture_output=True, text=True, check=True).stdout
    return int(json.loads(out)["streams"][0]["height"])


def render(src: Path, axis: str, level: int, out: Path) -> None:
    if axis not in AXES:
        raise SystemExit(f"unknown axis {axis!r}; choose from {', '.join(AXES)}")
    if level not in AXES[axis]:
        raise SystemExit(f"level must be 1, 2 or 3 (0 is the untouched source)")

    chain = AXES[axis][level].format(h=probe_height(src))
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
           "-vf", chain, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an"]
    if axis == "compression":
        # A long GOP is half of what makes real CCTV ugly: motion between
        # keyframes turns into blocking exactly when the event happens.
        cmd += ["-b:v", COMPRESSION_BITRATE[level], "-maxrate", COMPRESSION_BITRATE[level],
                "-bufsize", "200k", "-g", "150"]
    else:
        cmd += ["-crf", "18"]
    cmd.append(str(out))
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True, type=Path)
    ap.add_argument("--axis", default=None, choices=sorted(AXES))
    ap.add_argument("--level", type=int, default=None)
    ap.add_argument("--all", action="store_true", help="every axis at every level")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe are required")

    if args.all:
        out_dir = args.out_dir or args.clip.parent / "degraded"
        for axis in AXES:
            for level in (1, 2, 3):
                out = out_dir / f"{axis}{level}.mp4"
                render(args.clip, axis, level, out)
                print(f"wrote {out}")
        return

    if args.axis is None or args.level is None or args.out is None:
        raise SystemExit("give --axis, --level and --out, or use --all")
    render(args.clip, args.axis, args.level, args.out)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
