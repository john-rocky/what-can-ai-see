#!/usr/bin/env python3
"""The compilation: clip, question, and every model's answer, overlaid.

Built for a muted autoplaying timeline, so each segment has to land without
sound and without the viewer reading a caption first. Three beats per clip:

  1. the clip plays at real speed, the question overlaid across the top
  2. it collapses into the contact sheet — the whole clip as one image, which is
     all the model is ever given. This beat is the argument: the viewer watches
     six seconds of motion become six small stills and understands the
     constraint without being told it.
  3. the answers come in over that sheet, one model per row, then ground truth

Nothing is sped up, no frame is cherry-picked, and the panels shown are the ones
sheet.py actually sampled. Each segment is rendered to its own file and the
segments are concatenated, so memory stays bounded no matter how long the reel is.

usage:
  reel.py --segments smoke-fire-8365988,fall-8526604,synth-stop-pos \\
          --results runs/field-v1/*.jsonl runs/floor/*.jsonl \\
          --out cards/reel.mp4
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from card import verdict_of  # noqa: E402 — one verdict-extraction rule, one place

W, H = 1280, 720
FPS = 25

BG = (11, 13, 17)
FG = (240, 242, 246)
DIM = (150, 156, 166)
GOOD = (76, 200, 130)
BAD = (242, 96, 88)
NEUTRAL = (150, 156, 166)
ACCENT = (87, 199, 209)

SHEET_BEAT = 1.4   # seconds on the bare contact sheet before answers start
ROW_IN = 0.72      # seconds between model rows arriving
TRUTH_PAUSE = 1.0  # seconds after the last row before ground truth
HOLD = 1.3         # seconds to read the finished segment

FONTS = {"bold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
         "reg": "/System/Library/Fonts/Supplemental/Arial.ttf"}


def font(kind: str, size: int) -> ImageFont.ImageFont:
    p = FONTS.get(kind)
    if p and Path(p).exists():
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


F_Q = font("bold", 41)
F_KICK = font("bold", 16)
F_MODEL = font("bold", 27)
F_QUOTE = font("reg", 20)
F_CHIP = font("bold", 24)
F_NOTE = font("reg", 21)
F_BIG = font("bold", 64)
F_LEDE = font("reg", 27)


def scrim(img: Image.Image, top: int, bottom: int, strength: int = 214) -> None:
    """A flat dark band, not a gradient: text over video needs a predictable
    contrast floor, and a gradient's midpoint is exactly where the type sits."""
    band = Image.new("RGBA", (W, bottom - top), (11, 13, 17, strength))
    img.paste(band, (0, top), band)


def probe_duration(v: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "json", str(v)], capture_output=True, text=True,
                         check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def first_clause(text: str, limit: int = 96) -> str:
    """The model's own words, trimmed to one readable clause."""
    t = " ".join((text or "").split())
    t = re.sub(r"^(yes|no)[\s,.:;-]*", "", t, flags=re.I)
    if not t:
        return ""
    head = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0]
    return textwrap.shorten(head, width=limit, placeholder=" …")


def fit(im: Image.Image, box_w: int, box_h: int) -> Image.Image:
    s = min(box_w / im.width, box_h / im.height)
    return im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))),
                     Image.LANCZOS)


def draw_question(d: ImageDraw.ImageDraw, question: str, truth: bool | None = None) -> None:
    """Question, plus which half of the pair this clip is.

    Without that label a viewer reads a green chip as "the model got it right",
    which is exactly the misreading the whole benchmark exists to prevent: the
    same three models answer Yes to the positive AND to its look-alike, and only
    seeing both halves makes that visible."""
    lines = textwrap.wrap(question, width=46)[:2]
    d.text((52, 30), "WHAT CAN AI SEE", font=F_KICK, fill=ACCENT)
    for i, line in enumerate(lines):
        d.text((52, 58 + i * 46), line, font=F_Q, fill=FG)
    if truth is None:
        return
    tag = "POSITIVE" if truth else "HARD NEGATIVE  ·  the look-alike"
    y = 58 + len(lines) * 46 - 2
    w_ = d.textlength(tag, font=F_KICK)
    d.rounded_rectangle([52, y, 52 + w_ + 26, y + 26], 6,
                        fill=(30, 62, 48) if truth else (58, 30, 30))
    d.text((65, y + 5), tag, font=F_KICK, fill=(120, 214, 160) if truth else (240, 140, 130))


def card_frame(title: str, lede: str, accent_line: str = "") -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((72, 232), "WHAT CAN AI SEE", font=F_KICK, fill=ACCENT)
    y = 268
    for line in textwrap.wrap(title, width=30)[:3]:
        d.text((72, y), line, font=F_BIG, fill=FG)
        y += 72
    y += 14
    for line in textwrap.wrap(lede, width=62)[:3]:
        d.text((72, y), line, font=F_LEDE, fill=DIM)
        y += 38
    if accent_line:
        d.text((72, y + 12), accent_line, font=F_NOTE, fill=ACCENT)
    return img


def render_segment(clip_id: str, encoding: str, rows: dict[str, dict],
                   model_meta: dict, events: dict, out: Path) -> float:
    clip_dir = ROOT / "clips" / clip_id
    meta = yaml.safe_load((clip_dir / "meta.yaml").read_text())
    event = events[meta["event"]]
    sheet_meta = json.loads((clip_dir / f"{encoding}.json").read_text())
    truth = meta["label"] == "positive"
    question = event["question"]

    # Wrong answers first: the eye should land on the failure.
    ordered = sorted(rows.items(),
                     key=lambda kv: (verdict_of(kv[1].get("gate", "")) == truth,
                                     model_meta.get(kv[0], {}).get("size_mb", 0)))

    duration = probe_duration(clip_dir / "clip.mp4")

    onset = meta.get("onset_s")
    times = sheet_meta["times"]
    if meta.get("shows_transition") and onset is not None:
        after = next((k for k, tt in enumerate(times, 1) if tt >= onset), len(times))
        change_note = f"the change falls between panel {max(1, after - 1)} and panel {after}"
    elif meta.get("shows_transition"):
        change_note = "the scene changes during the clip"
    else:
        change_note = "no change: the scene is the same in every panel"

    answers_len = SHEET_BEAT + len(ordered) * ROW_IN + TRUTH_PAUSE + HOLD
    total = duration + answers_len
    n_frames = int(total * FPS)

    sheet = Image.open(clip_dir / f"{encoding}.jpg").convert("RGB")

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(clip_dir / "clip.mp4"),
             "-vf", f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=decrease,"
                    f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0b0d11",
             "-y", str(td / "c%04d.png")], check=True)
        clip_frames = sorted(td.glob("c*.png"))
        if not clip_frames:
            raise SystemExit(f"{clip_id}: ffmpeg produced no frames")

        # Beat 2/3 layout: the sheet on the left, answers on the right. The
        # contact sheet is nearly square (a 2x3 tiling of 16:9 panels) and the
        # frame is 16:9, so centring it leaves two dead bars; putting the answers
        # in the space instead means nothing is shrunk to make room.
        col_x, col_w = 762, W - 762 - 46
        sheet_box_h = H - 190 - 58
        sheet_im = fit(sheet, 660, sheet_box_h)
        sheet_x, sheet_y = 52, 190

        out_dir = td / "out"
        out_dir.mkdir()
        for i in range(n_frames):
            t_ = i / FPS

            if t_ < duration:                                 # ── beat 1: the clip
                idx = min(len(clip_frames) - 1, i)
                img = Image.open(clip_frames[idx]).convert("RGB")
                scrim(img, 0, 178)
                scrim(img, H - 52, H, 190)
                d = ImageDraw.Draw(img, "RGBA")
                draw_question(d, question, truth)
                d.text((52, H - 40), f"{clip_id}   ·   {duration:.0f}s   ·   real speed",
                       font=F_KICK, fill=DIM)
            else:                                  # ── beats 2 and 3: sheet + answers
                a = t_ - duration
                img = Image.new("RGB", (W, H), BG)
                d = ImageDraw.Draw(img, "RGBA")
                draw_question(d, question, truth)
                img.paste(sheet_im, (sheet_x, sheet_y))
                d.text((sheet_x, sheet_y + sheet_im.height + 12),
                       f"the whole clip · {sheet_meta['panels']} panels · "
                       f"~{sheet_meta['tokens_per_panel_at_196']:g} visual tokens each",
                       font=F_KICK, fill=ACCENT)
                d.text((sheet_x, sheet_y + sheet_im.height + 34), change_note,
                       font=F_KICK, fill=(168, 174, 186))

                showing = 0 if a < SHEET_BEAT else min(
                    len(ordered), int((a - SHEET_BEAT) / ROW_IN) + 1)

                y = sheet_y
                if showing:
                    d.text((col_x, y), "THE ANSWERS", font=F_KICK, fill=ACCENT)
                    y += 34
                for model_id, ans in ordered[:showing]:
                    v = verdict_of(ans.get("gate", ""))
                    label = "YES" if v is True else "NO" if v is False else "—"
                    colour = NEUTRAL if v is None else (GOOD if v == truth else BAD)
                    mm = model_meta.get(model_id, {})
                    d.text((col_x, y), mm.get("name", model_id), font=F_MODEL, fill=FG)
                    chip_w = 92
                    d.rounded_rectangle([col_x + col_w - chip_w, y - 2,
                                         col_x + col_w, y + 33], 8, fill=colour)
                    tw = d.textlength(label, font=F_CHIP)
                    d.text((col_x + col_w - chip_w + (chip_w - tw) / 2, y + 4), label,
                           font=F_CHIP, fill=BG)
                    y += 38
                    said = first_clause(ans.get("open") or ans.get("gate") or "", 150)
                    for line in textwrap.wrap(f"“{said}”", width=44)[:3]:
                        d.text((col_x, y), line, font=F_QUOTE, fill=(168, 174, 186))
                        y += 26
                    y += 18

                if a >= SHEET_BEAT + len(ordered) * ROW_IN + TRUTH_PAUSE:
                    y = max(y, sheet_y + 300)
                    d.line([(col_x, y), (col_x + col_w, y)], fill=(44, 48, 56), width=1)
                    d.text((col_x, y + 16), "GROUND TRUTH", font=F_KICK, fill=ACCENT)
                    d.text((col_x + 190, y + 8), "YES" if truth else "NO",
                           font=F_MODEL, fill=FG)
                    gt = " ".join(str(meta["ground_truth"]).split())
                    yy = y + 48
                    for line in textwrap.wrap(gt, width=44)[:4]:
                        d.text((col_x, yy), line, font=F_QUOTE, fill=DIM)
                        yy += 26

            img.save(out_dir / f"{i:05d}.png")

        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-framerate", str(FPS),
             "-i", str(out_dir / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "20", str(out)], check=True)
    return total


def render_card(img: Image.Image, seconds: float, out: Path) -> None:
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "f.png"
        img.save(p)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-loop", "1", "-i", str(p),
             "-t", f"{seconds}", "-r", str(FPS), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "20", str(out)], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--segments", required=True,
                    help="comma-separated clip ids, in order")
    ap.add_argument("--encoding", default="g6")
    ap.add_argument("--results", type=Path, nargs="+", required=True)
    ap.add_argument("--models", type=Path, default=ROOT / "events" / "models.yaml")
    ap.add_argument("--events", type=Path, default=ROOT / "events" / "events.yaml")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--closing", default=None,
                    help="headline stat for the closing card")
    args = ap.parse_args()

    model_meta = {m["id"]: m for m in yaml.safe_load(args.models.read_text())["models"]}
    events = {e["id"]: e for e in yaml.safe_load(args.events.read_text())["events"]}

    by_clip: dict[str, dict[str, dict]] = {}
    for path in args.results:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if "model" not in r or "id" not in r:
                continue
            clip, enc, q = r["id"].split("|")
            if enc != args.encoding:
                continue
            by_clip.setdefault(clip, {}).setdefault(r["model"], {})[q] = (
                r.get("answer", "") if r.get("ok") else "")

    segments = [s.strip() for s in args.segments.split(",") if s.strip()]
    missing = [s for s in segments if s not in by_clip]
    if missing:
        raise SystemExit(f"no {args.encoding} results for: {', '.join(missing)}")

    work = args.out.parent / f".{args.out.stem}-parts"
    work.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []

    intro = work / "00-intro.mp4"
    render_card(card_frame(
        "What can a phone-sized AI actually see?",
        "Vision-language models small enough to run on an iPhone, shown real "
        "camera footage and asked one yes/no question.",
        "measured on device · no cloud"), 4.0, intro)
    parts.append(intro)

    total = 4.0
    for n, clip_id in enumerate(segments, 1):
        part = work / f"{n:02d}-{clip_id}.mp4"
        secs = render_segment(clip_id, args.encoding, by_clip[clip_id],
                              model_meta, events, part)
        parts.append(part)
        total += secs
        print(f"  {n}/{len(segments)}  {clip_id}  {secs:.1f}s")

    if args.closing:
        outro = work / "99-outro.mp4"
        render_card(card_frame("The scores look great.",
                               "Recall is 1.00 in most cells. So is the false-alarm "
                               "rate. They are not detecting events — they are "
                               "answering Yes.",
                               args.closing), 5.0, outro)
        parts.append(outro)
        total += 5.0

    listing = work / "parts.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(args.out)],
        check=True)
    print(f"wrote {args.out}  ({W}x{H}, {total:.0f}s, {len(segments)} segment(s))")


if __name__ == "__main__":
    main()
