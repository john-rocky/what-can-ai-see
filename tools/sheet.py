#!/usr/bin/env python3
"""Video -> the single image a VLM actually gets.

CoreAIKit's VL path takes one image per turn (KitVisionExecutor: "Multi-image and
KV reuse are follow-ups"), so a clip must be flattened into one image before any
model in the catalog can see it. How you flatten it is the biggest lever in the
whole benchmark, so it is a named, versioned encoding here rather than a hidden step.

Two facts from VLArchitecture.swift set every constant below:

1. Every VLM resizes the input to a FIXED SQUARE canvas — 448x448 (Qwen3-VL,
   MiniCPM-V, Holo2) or 512x512 (LFM2.5-VL, North Micro) — with `.stretch`.
   So the composed sheet should already be near-square, or the stretch distorts
   the scene. A 4-panel horizontal strip is 16:3; stretched to square it is
   squashed 5x and the benchmark measures the squash, not the model.

2. The canvas becomes 64-256 visual tokens for the WHOLE image. Not per frame —
   total. Panels therefore compete for a fixed token budget, and `tokens_per_panel`
   (reported below) is the number that predicts whether a model can resolve
   anything inside a panel at all.

Encodings — a ladder in panel count, each shaped to stay near-square for a
16:9 source, with the Qwen3-VL 196-token budget shown per panel:

    f1      1 panel    1x1   196 tok/panel   max detail, zero time
    g2      2 panels   1x2    98             before / after
    g6      6 panels   2x3    32
    g12    12 panels   3x4    16
    g20    20 panels   4x5     9             time-rich, detail-starved
    diff    2 panels   1x2    98             first vs last, for `change` events

usage:
  sheet.py --video clip.mp4 --encoding g6 --out sheet.jpg
  sheet.py --video clip.mp4 --encoding g12 --out sheet.jpg --labels none
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# (cols, rows). Shapes chosen so a 16:9 source tiles to a near-square canvas:
# canvas aspect = (cols*16)/(rows*9), kept inside [0.75, 1.35] so the model's
# `.stretch` to square is a mild correction rather than a distortion.
GRIDS = {
    "f1": (1, 1),
    "g2": (1, 2),
    "g6": (2, 3),
    "g12": (3, 4),
    "g20": (4, 5),
    "diff": (1, 2),
}

# Compose at 2x the largest model canvas (512) so the downsample into the model's
# own CoreGraphics `.high` resize is well antialiased. Composing at 448 directly
# would resample twice at the target rate and lose detail the model could have had.
COMPOSE_SIDE = 1024

# Reference budget for the reported tokens_per_panel, so one number is comparable
# across encodings. Qwen3-VL / Holo2 = 196; LFM2.5 / North Micro = 256; MiniCPM = 64.
REFERENCE_TOKENS = 196

GUTTER = 6  # px between panels at COMPOSE_SIDE, so panel boundaries survive the downsample
BADGE = 0.13  # badge box height as a fraction of panel height


def probe(video: Path) -> tuple[float, int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(video)],
        capture_output=True, text=True, check=True,
    ).stdout
    j = json.loads(out)
    s = j["streams"][0]
    return float(j["format"]["duration"]), int(s["width"]), int(s["height"])


def sample_times(duration: float, n: int, encoding: str, peak: float | None) -> list[float]:
    """Timestamps to grab, in seconds.

    Panels sit at the centres of n equal slices rather than at 0 and `duration`.
    The first and last frames of a clip are the two most likely to be a fade, a
    cut, or a compression artefact, and an event that starts at t=0 means the
    clip was trimmed wrong.
    """
    if encoding == "f1":
        return [peak if peak is not None else duration * 0.5]
    if encoding == "diff":
        return [duration * 0.05, duration * 0.95]
    return [duration * (i + 0.5) / n for i in range(n)]


def extract(video: Path, times: list[float], workdir: Path) -> list[Path]:
    paths = []
    for i, t in enumerate(times):
        out = workdir / f"f{i:02d}.png"
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-ss", f"{t:.3f}",
             "-i", str(video), "-frames:v", "1", "-y", str(out)],
            check=True,
        )
        if not out.exists():
            raise SystemExit(f"ffmpeg produced no frame at t={t:.3f}s")
        paths.append(out)
    return paths


def _font(size: int) -> ImageFont.ImageFont:
    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ):
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def compose(frames: list[Path], cols: int, rows: int, labels: str) -> Image.Image:
    """Tile panels at their native aspect. Panel order is reading order: left to
    right, top to bottom, which is the only time axis the model gets."""
    ims = [Image.open(p).convert("RGB") for p in frames]
    src_w, src_h = ims[0].size

    panel_w = (COMPOSE_SIDE - GUTTER * (cols - 1)) // cols
    panel_h = max(1, round(panel_w * src_h / src_w))
    sheet_w = panel_w * cols + GUTTER * (cols - 1)
    sheet_h = panel_h * rows + GUTTER * (rows - 1)

    sheet = Image.new("RGB", (sheet_w, sheet_h), (10, 10, 12))
    draw = ImageDraw.Draw(sheet, "RGBA")
    single = cols * rows == 1
    box = max(14, int(panel_h * BADGE))
    font = _font(int(box * 0.74))

    for i, im in enumerate(ims):
        c, r = i % cols, i // cols
        x, y = c * (panel_w + GUTTER), r * (panel_h + GUTTER)
        sheet.paste(im.resize((panel_w, panel_h), Image.LANCZOS), (x, y))
        if labels == "badge" and not single:
            # A corner badge, not a caption band: a band would spend 10%+ of the
            # already-tiny token budget on text, and at g12 that is more tokens
            # than a whole panel gets.
            draw.rectangle([x, y, x + box * 1.5, y + box], fill=(10, 10, 12, 215))
            draw.text((x + box * 0.34, y + box * 0.12), str(i + 1),
                      fill=(255, 255, 255), font=font)
    return sheet


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True, type=Path)
    ap.add_argument("--encoding", default="g6", choices=sorted(GRIDS))
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--labels", default="badge", choices=["badge", "none"])
    ap.add_argument("--peak", type=float, default=None,
                    help="seconds; the frame --encoding f1 grabs (default: midpoint)")
    args = ap.parse_args()

    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise SystemExit("ffmpeg and ffprobe are required")

    cols, rows = GRIDS[args.encoding]
    n = cols * rows
    duration, _, _ = probe(args.video)
    times = sample_times(duration, n, args.encoding, args.peak)

    with tempfile.TemporaryDirectory() as td:
        frames = extract(args.video, times, Path(td))
        sheet = compose(frames, cols, rows, args.labels)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(args.out, quality=93)

    w, h = sheet.size
    # What the model actually resolves. The sheet is a uniform tiling, so once it
    # is stretched onto the 448 square each panel occupies 448/cols x 448/rows —
    # regardless of the source resolution. That is the whole point: source
    # resolution stops mattering the moment the clip becomes a sheet.
    print(json.dumps({
        "encoding": args.encoding, "grid": [cols, rows], "panels": n,
        "times": [round(t, 3) for t in times],
        "sheet_px": [w, h], "canvas_aspect": round(w / h, 3),
        "panel_px_at_448": [round(448 / cols), round(448 / rows)],
        "tokens_per_panel_at_196": round(REFERENCE_TOKENS / n, 1),
        "out": str(args.out),
    }))


if __name__ == "__main__":
    sys.exit(main())
