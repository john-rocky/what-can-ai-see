#!/usr/bin/env python3
"""Many clips as one contact-sheet-of-contact-sheets, for bulk curation.

Curation is the bottleneck: nothing enters the corpus until a human has watched
it, and looking at clips one at a time does not scale past a few dozen. This puts
N clips on one page — each as a 3-frame strip with its id — so a whole fetch batch
can be triaged in a single look. Anything that survives triage still gets opened
on its own before it is labelled; this only decides what is worth opening.

usage: montage.py --clips a,b,c --out /tmp/m.jpg
"""
from __future__ import annotations
import argparse, json, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
COLS, TW, TH = 3, 400, 76      # strips per row; each strip is 3 thumbs wide

ap = argparse.ArgumentParser()
ap.add_argument("--clips", required=True)
ap.add_argument("--out", type=Path, required=True)
a = ap.parse_args()

def font(sz):
    for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",):
        if Path(p).exists():
            return ImageFont.truetype(p, sz)
    return ImageFont.load_default(sz)

ids = [c.strip() for c in a.clips.split(",") if c.strip()]
rows = (len(ids) + COLS - 1) // COLS
CELL_H = TH + 26
sheet = Image.new("RGB", (COLS * (TW + 10) + 10, rows * (CELL_H + 10) + 10), (14, 16, 20))
d = ImageDraw.Draw(sheet)
f = font(15)

for i, cid in enumerate(ids):
    v = ROOT / "clips" / cid / "clip.mp4"
    if not v.exists():
        continue
    dur = float(json.loads(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(v)],
        capture_output=True, text=True).stdout)["format"]["duration"])
    x0 = 10 + (i % COLS) * (TW + 10)
    y0 = 10 + (i // COLS) * (CELL_H + 10)
    with tempfile.TemporaryDirectory() as td:
        for k, frac in enumerate((0.12, 0.5, 0.88)):
            p = Path(td) / f"{k}.png"
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{dur*frac:.2f}",
                            "-i", str(v), "-frames:v", "1", "-y", str(p)], check=True)
            im = Image.open(p).convert("RGB").resize((TW // 3 - 2, TH), Image.LANCZOS)
            sheet.paste(im, (x0 + k * (TW // 3), y0))
    d.text((x0 + 2, y0 + TH + 4), f"{cid}  ·  {dur:.0f}s", font=f, fill=(210, 214, 222))

sheet.save(a.out, quality=90)
print(f"wrote {a.out}  ({len(ids)} clips, {sheet.size[0]}x{sheet.size[1]})")
