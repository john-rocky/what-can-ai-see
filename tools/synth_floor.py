#!/usr/bin/env python3
"""The floor test: synthetic clips where the event is unmissable.

Before spending on real footage it is worth knowing whether a model reads panel
order as time AT ALL. These clips remove every confound real footage has —
distance, lighting, occlusion, clutter, motion blur, camera angle — and leave
only the temporal structure. A model that cannot call the synthetic fall cannot
call a real one, and a model that CAN still tells us nothing about real footage.
So this is a gate, not a score.

Pairs generated:
  synth-fall-pos      upright figure tips over and stays down
  synth-fall-neg      upright figure crouches and stands back up   (the hard negative)
  synth-remove-pos    box present, person passes, box gone
  synth-remove-neg    box present, person passes in front, box still there
  synth-stop-pos      conveyor items frozen for the whole clip
  synth-stop-neg      conveyor items advancing normally

usage: synth_floor.py --out-dir clips
"""

from __future__ import annotations

import argparse
import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

W, H = 640, 360
FPS = 15
SECONDS = 6
GROUND = int(H * 0.82)

BG = (196, 198, 202)
FLOOR = (150, 152, 158)
BODY = (44, 92, 176)
HEAD = (222, 184, 148)
BOX = (198, 96, 48)
BELT = (92, 94, 100)


def base(draw: ImageDraw.ImageDraw) -> None:
    draw.rectangle([0, 0, W, H], fill=BG)
    draw.rectangle([0, GROUND, W, H], fill=FLOOR)


def figure(draw: ImageDraw.ImageDraw, cx: float, angle_deg: float,
           height: float = 130.0) -> None:
    """A person pinned at the feet, rotated by `angle_deg` about that pivot.

    angle 0 = upright, 90 = flat on the ground. `height` shortens the body
    without rotating it, which is what a crouch looks like from a fixed camera —
    the distinction the negative clip is built around.
    """
    a = math.radians(angle_deg)
    fx, fy = cx, GROUND
    tx = fx + math.sin(a) * height
    ty = fy - math.cos(a) * height
    draw.line([(fx, fy), (tx, ty)], fill=BODY, width=18)
    hr = 15
    draw.ellipse([tx - hr, ty - hr, tx + hr, ty + hr], fill=HEAD)


def walker(draw: ImageDraw.ImageDraw, cx: float) -> None:
    figure(draw, cx, 0.0, height=120.0)


def render(frames_fn, out: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        n = FPS * SECONDS
        for i in range(n):
            im = Image.new("RGB", (W, H))
            d = ImageDraw.Draw(im)
            base(d)
            frames_fn(d, i / (n - 1))
            im.save(td / f"{i:04d}.png")
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
             "-framerate", str(FPS), "-i", str(td / "%04d.png"),
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", str(out)],
            check=True,
        )


# ── fall ──────────────────────────────────────────────────────────────────────
def fall_pos(d, t):
    # upright until 40%, tips over between 40-60%, stays down after
    if t < 0.40:
        angle = 0.0
    elif t < 0.60:
        angle = 90.0 * (t - 0.40) / 0.20
    else:
        angle = 90.0
    figure(d, W * 0.5, angle)


def fall_neg(d, t):
    # crouches down and stands back up — never leaves vertical
    depth = math.sin(math.pi * t) if 0.2 < t < 0.8 else 0.0
    figure(d, W * 0.5, 0.0, height=130.0 - 62.0 * depth)


# ── removal ───────────────────────────────────────────────────────────────────
def _box(d, present: bool):
    if present:
        d.rectangle([W * 0.68, GROUND - 62, W * 0.68 + 74, GROUND], fill=BOX)


def remove_pos(d, t):
    _box(d, t < 0.5)
    walker(d, W * 0.10 + W * 0.75 * t)


def remove_neg(d, t):
    _box(d, True)
    walker(d, W * 0.10 + W * 0.75 * t)


# ── line stopped ──────────────────────────────────────────────────────────────
def _belt(d):
    d.rectangle([0, GROUND - 40, W, GROUND - 10], fill=BELT)


def stop_pos(d, t):
    _belt(d)
    for k in range(4):  # frozen: positions do not depend on t
        x = 70 + k * 140
        d.rectangle([x, GROUND - 82, x + 60, GROUND - 40], fill=BOX)


def stop_neg(d, t):
    _belt(d)
    for k in range(4):
        x = (70 + k * 140 + t * 420) % (W + 120) - 60
        d.rectangle([x, GROUND - 82, x + 60, GROUND - 40], fill=BOX)


CLIPS = {
    "synth-fall-pos": fall_pos,
    "synth-fall-neg": fall_neg,
    "synth-remove-pos": remove_pos,
    "synth-remove-neg": remove_neg,
    "synth-stop-pos": stop_pos,
    "synth-stop-neg": stop_neg,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=Path("clips"))
    args = ap.parse_args()
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")
    for name, fn in CLIPS.items():
        out = args.out_dir / name / "clip.mp4"
        render(fn, out)
        print(f"wrote {out}")


if __name__ == "__main__":
    main()
