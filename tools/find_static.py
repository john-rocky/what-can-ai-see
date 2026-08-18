#!/usr/bin/env python3
"""Find locked-off camera footage — the only kind a staged transition can use.

tools/stage.py composites a change into a fixed position. If the camera drifts,
the patch slides against the scene and the seam becomes the thing a model detects.
So a staged clip needs a genuinely static camera.

Whole-frame difference cannot answer that: a conveyor clip scores high because the
conveyor is *supposed* to move. This measures the frame BORDER instead — the outer
strip, which on a fixed industrial camera is wall, floor, framework and machine
housing, and moves only if the camera does. A high border score means the camera
moved; a low one with a high centre score is exactly what is wanted: a still camera
watching a running process.

That is also why this matters beyond staging. Real factory, retail and security
cameras are bolted to something. A benchmark sourced from handheld and drone stock
is measuring a viewpoint the deployment will never have.

usage:
  find_static.py --queries "bottling line,conveyor factory" --limit 8
  find_static.py --rank clips/part-missing-6754824 clips/line-stopped-10416701
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import time
import urllib.parse
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.pexels.com/videos/search"
BORDER = 0.12          # fraction of each edge treated as "should not move"
STATIC_BORDER = 4.0    # mean abs border difference below this reads as locked off
SAMPLES = 5            # frame pairs sampled across the clip


def probe_duration(v: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(v)], capture_output=True, text=True,
                         check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def _grab(v: Path, t: float, dst: Path) -> Image.Image:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", str(v),
                    "-frames:v", "1", "-vf", "scale=480:-2", "-y", str(dst)], check=True)
    return Image.open(dst).convert("L")


def border_and_centre(a: Image.Image, b: Image.Image) -> tuple[float, float]:
    diff = ImageChops.difference(a, b)
    w, h = diff.size
    bx, by = int(w * BORDER), int(h * BORDER)
    centre = diff.crop((bx, by, w - bx, h - by))
    # Border = whole frame minus centre. Blanking the centre and correcting for the
    # zeroed area is cheaper than compositing four strips and gives the same mean.
    blanked = diff.copy()
    blanked.paste(0, (bx, by, w - bx, h - by))
    total_px, centre_px = w * h, centre.width * centre.height
    border_px = total_px - centre_px
    border_mean = ImageStat.Stat(blanked).mean[0] * total_px / max(1, border_px)
    return border_mean, ImageStat.Stat(centre).mean[0]


def score(video: Path) -> dict:
    """Border motion (camera) and centre motion (process), averaged over the clip."""
    dur = probe_duration(video)
    borders, centres = [], []
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        for i in range(SAMPLES):
            t = dur * (0.1 + 0.75 * i / max(1, SAMPLES - 1))
            a = _grab(video, t, td / "a.png")
            b = _grab(video, min(dur - 0.05, t + 0.8), td / "b.png")
            bm, cm = border_and_centre(a, b)
            borders.append(bm)
            centres.append(cm)
    border = sum(borders) / len(borders)
    centre = sum(centres) / len(centres)
    return {"border": round(border, 2), "centre": round(centre, 2),
            "duration": round(dur, 1),
            "static": border < STATIC_BORDER,
            # A still camera watching a running process is the ideal base clip:
            # low border, high centre.
            "usable_for_freeze": border < STATIC_BORDER and centre > 6.0}


def api_search(query: str, key: str, per_page: int) -> list[dict]:
    url = f"{API}?{urllib.parse.urlencode({'query': query, 'per_page': per_page, 'orientation': 'landscape'})}"
    for attempt in range(3):
        p = subprocess.run(["curl", "-s", "--max-time", "25",
                            "-H", f"Authorization: {key}", url],
                           capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            try:
                return json.loads(p.stdout).get("videos", [])
            except json.JSONDecodeError:
                pass
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default=None, help="comma-separated Pexels queries")
    ap.add_argument("--limit", type=int, default=6, help="candidates per query")
    ap.add_argument("--rank", type=Path, nargs="*", default=None,
                    help="score clip directories already on disk")
    args = ap.parse_args()

    if args.rank:
        print(f"{'clip':<32} {'border':>7} {'centre':>7} {'dur':>6}  verdict")
        rows = []
        for d in args.rank:
            v = d / "clip.mp4" if d.is_dir() else d
            s = score(v)
            rows.append((s["border"], d.name if d.is_dir() else d.stem, s))
        for _, name, s in sorted(rows):
            verdict = ("LOCKED OFF, process moving" if s["usable_for_freeze"]
                       else "locked off, little motion" if s["static"]
                       else "camera moves")
            print(f"{name:<32} {s['border']:>7.2f} {s['centre']:>7.2f} "
                  f"{s['duration']:>6.1f}  {verdict}")
        return

    if not args.queries:
        raise SystemExit("give --queries or --rank")
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise SystemExit("PEXELS_API_KEY is not set")

    print(f"{'id':>10} {'border':>7} {'centre':>7} {'dur':>6}  title")
    with tempfile.TemporaryDirectory() as td:
        for q in [x.strip() for x in args.queries.split(",") if x.strip()]:
            print(f"\n— {q}")
            for v in api_search(q, key, args.limit):
                files = [f for f in v["video_files"] if (f.get("height") or 0) <= 720]
                if not files:
                    continue
                small = sorted(files, key=lambda f: -(f.get("height") or 0))[0]
                tmp = Path(td) / f"{v['id']}.mp4"
                # A 720p copy is plenty to measure camera motion and keeps the
                # screening pass cheap; the winner is re-fetched at full size.
                if subprocess.run(["curl", "-sL", "--max-time", "120", "-o", str(tmp),
                                   small["link"]]).returncode != 0 or not tmp.exists():
                    continue
                try:
                    s = score(tmp)
                except Exception:
                    continue
                slug = v["url"].rstrip("/").rsplit("/", 1)[-1]
                title = " ".join(slug.split("-")[:-1])[:52]
                mark = "  <<< LOCKED OFF" if s["usable_for_freeze"] else (
                    "  < static" if s["static"] else "")
                print(f"{v['id']:>10} {s['border']:>7.2f} {s['centre']:>7.2f} "
                      f"{s['duration']:>6.1f}  {title}{mark}")
                tmp.unlink(missing_ok=True)
                time.sleep(0.2)


if __name__ == "__main__":
    main()
