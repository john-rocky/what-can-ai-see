#!/usr/bin/env python3
"""Draw a walk back: the recording, with each description over the frames it was computed from.

The point of the walk is the gap. The phone answers about a window that ended several
seconds ago, and at walking pace that is metres back down the street — a place already out
of shot. Drawing an answer at the moment it ARRIVED hides exactly that, because it lands
over scenery the model never saw and reads as a reasonable description of the wrong thing.

So each line is drawn from `windowStart` to the moment the next answer's window starts, and
the lag is printed beside it. A viewer watching the video sees the model describing a shop
front while the camera is already past the corner, which is the finding stated in the only
form that lands in one second.

Gaps in the recording are gaps in the file: the app writes frames at their real capture
times and skips the stretches the person-gate blocked, so a jump in the video IS a stretch
that was not recorded. Nothing is smoothed over here either.

usage:
  walk_card.py --walk runs/walk/walk-1755600000        # .mov + .jsonl share the stem
  walk_card.py --walk … --out cards/walk.mp4 --text-size 30
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from reel import ACCENT, font  # noqa: E402
from reel_fast import jfont  # noqa: E402
from said_card import paragraph  # noqa: E402

FPS = 24


def probe(video: Path) -> tuple[float, int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True).stdout.split()
    w, h, dur = int(out[0]), int(out[1]), float(out[2])
    return dur, w, h


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--walk", type=Path, required=True,
                    help="path without extension; <walk>.mov and <walk>.jsonl are read")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--text-size", type=int, default=28, dest="text_size")
    ap.add_argument("--lines", type=int, default=4)
    ap.add_argument("--label", default="Describe what is happening.")
    args = ap.parse_args()

    video = args.walk.with_suffix(".mov")
    sidecar = args.walk.with_suffix(".jsonl")
    if not video.exists() or not sidecar.exists():
        raise SystemExit(f"need both {video.name} and {sidecar.name}")

    rows = []
    for line in sidecar.read_text().splitlines():
        if line.strip():
            rows.append(json.loads(line))
    rows.sort(key=lambda r: r["windowStart"])
    if not rows:
        raise SystemExit("no descriptions in the sidecar")

    dur, vw, vh = probe(video)
    out = args.out or ROOT / "cards" / f"{args.walk.name}.mp4"
    out.parent.mkdir(parents=True, exist_ok=True)

    ts = args.text_size
    lh = round(ts * 1.20)
    f_said = font("reg", ts)
    f_kick = font("bold", 15)
    f_lag = font("bold", round(ts * 0.72))
    panel = round(ts * 2.4) + args.lines * lh
    W = 1080
    vid_h = round(W * vh / vw) // 2 * 2
    H = (vid_h + panel) // 2 * 2
    wrap = max(20, int((W - 88) / (ts * 0.56)))

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
             "-vf", f"fps={FPS},scale={W}:{vid_h}", "-y", str(td / "f%05d.png")], check=True)
        frames = sorted(td.glob("f*.png"))
        outd = td / "out"
        outd.mkdir()

        for k in range(len(frames)):
            t = k / FPS
            img = Image.new("RGB", (W, H), (10, 12, 16))
            img.paste(Image.open(frames[k]).convert("RGB"), (0, 0))
            d = ImageDraw.Draw(img, "RGBA")

            d.rectangle([0, vid_h, W, H], fill=(8, 10, 14, 255))
            d.text((44, vid_h + 14), "WALK", font=f_kick, fill=ACCENT)

            # The row whose WINDOW covers this moment, not the row that had arrived by now.
            cur = None
            for r in rows:
                if r["windowStart"] <= t:
                    cur = r
                else:
                    break
            if cur:
                # Lag and sampling together, because they are the two things about this
                # commentary that are not visible in the sentence itself: how far behind
                # the world it is, and whether a second walk down the same street would
                # produce it again.
                mode = cur.get("sampling", "?")
                d.text((W - 330, vid_h + 14),
                       f"{mode} · answer is {cur['lagSeconds']:.1f}s behind",
                       font=f_lag, fill=(226, 170, 90))
                txt = paragraph(cur["text"], args.lines * 100)
                for i, line in enumerate(textwrap.wrap(txt, wrap)[: args.lines]):
                    d.text((44, vid_h + round(ts * 1.9) + i * lh), line,
                           font=f_said, fill=(238, 242, 250))
            else:
                d.text((44, vid_h + round(ts * 1.9)), "— no answer yet",
                       font=f_said, fill=(118, 124, 136))

            img.save(outd / f"{k:05d}.png")

        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-framerate", str(FPS),
             "-i", str(outd / "%05d.png"), "-c:v", "libx264", "-crf", "20",
             "-pix_fmt", "yuv420p", "-y", str(out)], check=True)

    lags = [r["lagSeconds"] for r in rows]
    print(f"wrote {out}  {dur:.1f}s, {len(rows)} answer(s)")
    print(f"  lag  median {sorted(lags)[len(lags)//2]:.1f}s   min {min(lags):.1f}   max {max(lags):.1f}")
    modes = {r.get("sampling", "?") for r in rows}
    print(f"  sampling  {', '.join(sorted(modes))}"
          + ("   <- mixed, so run-to-run stability is not one number here"
             if len(modes) > 1 else ""))
    thermals = [r.get("thermal", "?") for r in rows]
    print(f"  thermal  {thermals[0]} -> {thermals[-1]}")
    batt = [r.get("batteryPct", -1) for r in rows if r.get("batteryPct", -1) >= 0]
    if len(batt) >= 2:
        print(f"  battery  {batt[0]:.0f}% -> {batt[-1]:.0f}%  ({batt[0]-batt[-1]:.0f} points)")


if __name__ == "__main__":
    main()
