#!/usr/bin/env python3
"""Contact sheets for many clips at once, so curation is a look instead of a chore.

Selection is the bottleneck in this project — not compute, not tooling. A title
match is a shortlist and nothing more: the Pexels API ignores negation, so
"intrusion" returns rock climbing and "vehicle arrival" returns a parked lot seen
from a drone. Every candidate has to be watched before it can be labelled, and
watching them one at a time is what kept the corpus at 56 clips.

This lays out N clips per page, each as a strip of frames across its full
duration, captioned with its id and title. One page answers, for a dozen clips at
once, the only three questions that matter for the stream tier:

  1. can a person tell what happens?          (if not, no model failure is legible)
  2. is there a BEFORE and an AFTER?          (a clip that opens on the event
                                               cannot show a transition, which is
                                               the whole subject)
  3. roughly when does it start?              (the onset, to a second)

Clips that pass get their meta.yaml filled in; the rest go to clips/REJECTED.md
with the reason, because a corpus that only shows what survived curation cannot
be audited.

usage:
  review.py --clips clips/intrusion-*  --out /tmp/review
  review.py --event intrusion --unverified --per-page 8 --out /tmp/review
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
STRIP_W, STRIP_H = 208, 117      # per frame in a clip's strip
PAD, CAPTION = 10, 34


def font(size: int):
    from PIL import ImageFont
    for p in ("/System/Library/Fonts/SFNSDisplay.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_ID, F_SUB = font(15), font(12)


def meta_of(d: Path) -> dict:
    p = d / "meta.yaml"
    if not p.exists():
        return {}
    body = "\n".join(l for l in p.read_text().split("\n") if not l.startswith("#"))
    return yaml.safe_load(body) or {}


def strip(video: Path, n: int, workdir: Path) -> list[Path]:
    """n frames spread across the whole clip — the point is the arc, not detail."""
    dur = float(subprocess.run(
        ["ffprobe", "-v", "0", "-show_entries", "format=duration", "-of", "csv=p=0",
         str(video)], capture_output=True, text=True).stdout.strip() or 0)
    if dur <= 0:
        return []
    out = []
    for i in range(n):
        t = dur * (i + 0.5) / n
        f = workdir / f"{video.parent.name}_{i}.png"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.2f}",
                        "-i", str(video), "-frames:v", "1",
                        "-vf", f"scale={STRIP_W}:{STRIP_H}:force_original_aspect_ratio=increase,"
                               f"crop={STRIP_W}:{STRIP_H}",
                        "-y", str(f)], check=False)
        if f.exists():
            out.append(f)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", nargs="*", type=Path, default=None)
    ap.add_argument("--event", default=None, help="every clip dir for this event")
    ap.add_argument("--unverified", action="store_true",
                    help="only clips still labelled UNVERIFIED")
    ap.add_argument("--frames", type=int, default=6, help="frames per clip")
    ap.add_argument("--per-page", type=int, default=8)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    dirs = [Path(c) for c in (args.clips or [])]
    if args.event:
        dirs += sorted(d for d in (ROOT / "clips").iterdir()
                       if d.is_dir() and meta_of(d).get("event") == args.event)
    if args.unverified:
        dirs = [d for d in dirs if str(meta_of(d).get("label")) == "UNVERIFIED"]
    dirs = [d for d in dict.fromkeys(dirs) if (d / "clip.mp4").exists()]
    if not dirs:
        raise SystemExit("no clips matched")

    args.out.mkdir(parents=True, exist_ok=True)
    page_w = PAD + args.frames * (STRIP_W + PAD)
    row_h = CAPTION + STRIP_H + PAD

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        pages = []
        for start in range(0, len(dirs), args.per_page):
            chunk = dirs[start:start + args.per_page]
            img = Image.new("RGB", (page_w, PAD + len(chunk) * row_h), (14, 16, 20))
            d = ImageDraw.Draw(img)
            for r, cd in enumerate(chunk):
                y = PAD + r * row_h
                m = meta_of(cd)
                gt = " ".join(str(m.get("ground_truth", "")).split())
                d.text((PAD, y), cd.name, font=F_ID, fill=(235, 238, 245))
                d.text((PAD + 250, y + 2),
                       f"{m.get('duration_s', '?')}s   {gt[:96]}", font=F_SUB,
                       fill=(150, 156, 168))
                for i, f in enumerate(strip(cd / "clip.mp4", args.frames, td)):
                    img.paste(Image.open(f), (PAD + i * (STRIP_W + PAD), y + CAPTION))
                    d.text((PAD + i * (STRIP_W + PAD) + 4, y + CAPTION + 2),
                           f"{i + 1}", font=F_SUB, fill=(255, 230, 120))
            p = args.out / f"page{start // args.per_page + 1:02d}.png"
            img.save(p)
            pages.append(p)
            print(f"{p}   {len(chunk)} clip(s)")
    print(f"\n{len(dirs)} clip(s) over {len(pages)} page(s)")


if __name__ == "__main__":
    main()
