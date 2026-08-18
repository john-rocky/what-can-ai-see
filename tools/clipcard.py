#!/usr/bin/env python3
"""The comparison video: the clip, what the model actually got, and every verdict.

Three beats, because the whole argument needs to land in about fifteen seconds on
a muted autoplaying timeline:

  1. the clip plays at real speed, left
  2. the contact sheet builds panel by panel, right, in sync with the playhead —
     this is the beat that does the work. A viewer watches six seconds of smooth
     motion collapse into six small stills and understands the constraint without
     being told it.
  3. the verdicts drop in, one model per row, ground truth last

Nothing is sped up and no frame is cherry-picked: the panels appear at the exact
timestamps sheet.py sampled, so the right-hand side is literally the model's input
assembling itself.

usage:
  clipcard.py --clip synth-fall-pos --encoding g6 --results runs/floor/*.jsonl \
              --out cards/synth-fall-pos.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import textwrap
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT / "tools"))
from card import verdict_of  # noqa: E402  — one extraction rule, one place

W, H = 1280, 720
FPS = 25
BG = (13, 14, 17)
FG = (238, 239, 242)
DIM = (139, 143, 152)
RULE = (38, 40, 46)
GOOD = (61, 200, 125)
BAD = (240, 92, 84)
NEUTRAL = (150, 152, 160)
ACCENT = (108, 168, 255)
HOLD_S = 4.0  # seconds of verdict beat after the clip ends

FONTS = {
    "bold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "reg": "/System/Library/Fonts/Supplemental/Arial.ttf",
}


def font(kind: str, size: int) -> ImageFont.ImageFont:
    path = FONTS.get(kind)
    if path and Path(path).exists():
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def probe_duration(video: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
         str(video)], capture_output=True, text=True, check=True).stdout
    return float(json.loads(out)["format"]["duration"])


def clip_frames(video: Path, n: int, duration: float, size, workdir: Path) -> list[Image.Image]:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(video),
         "-vf", f"fps={FPS},scale={size[0]}:{size[1]}:flags=lanczos",
         "-y", str(workdir / "c%04d.png")], check=True)
    got = sorted(workdir.glob("c*.png"))
    if not got:
        raise SystemExit("ffmpeg extracted no frames")
    # Pad by repeating the last frame so the clip track covers the verdict beat.
    ims = [Image.open(p).convert("RGB") for p in got]
    while len(ims) < n:
        ims.append(ims[-1])
    return ims[:n]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", required=True)
    ap.add_argument("--encoding", default="g6")
    ap.add_argument("--results", type=Path, nargs="+", required=True)
    ap.add_argument("--models", type=Path, default=ROOT / "events" / "models.yaml")
    ap.add_argument("--events", type=Path, default=ROOT / "events" / "events.yaml")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    clip_dir = ROOT / "clips" / args.clip
    meta = yaml.safe_load((clip_dir / "meta.yaml").read_text())
    event = {e["id"]: e for e in yaml.safe_load(args.events.read_text())["events"]}[meta["event"]]
    model_meta = {m["id"]: m for m in yaml.safe_load(args.models.read_text())["models"]}
    sheet_meta = json.loads((clip_dir / f"{args.encoding}.json").read_text())
    truth = meta["label"] == "positive"
    cols, rows_n = sheet_meta["grid"]
    times = sheet_meta["times"]

    results: dict[str, dict] = {}
    for path in args.results:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if "model" not in r or "id" not in r:   # skip the batch's tasks.jsonl
                continue
            clip, enc, q = r["id"].split("|")
            if clip == args.clip and enc == args.encoding:
                results.setdefault(r["model"], {})[q] = r.get("answer", "") if r.get("ok") else ""
    if not results:
        raise SystemExit(f"no results for {args.clip} / {args.encoding}")
    ordered = sorted(results.items(),
                     key=lambda kv: (verdict_of(kv[1].get("gate", "")) == truth,
                                     model_meta.get(kv[0], {}).get("size_mb", 0)))

    duration = probe_duration(clip_dir / "clip.mp4")
    total_frames = int((duration + HOLD_S) * FPS)

    # ── layout ────────────────────────────────────────────────────────────────
    pad = 34
    head_h = 104
    left_w = 560
    clip_h = round(left_w * 9 / 16)
    right_x = pad + left_w + 30
    right_w = W - right_x - pad

    panel_w = (right_w - 6 * (cols - 1)) // cols
    panel_h = round(panel_w * 9 / 16)

    f_kicker = font("bold", 15)
    f_title = font("bold", 30)
    f_sub = font("reg", 16)
    f_small = font("reg", 15)
    f_model = font("bold", 19)
    f_verdict = font("bold", 19)
    f_label = font("bold", 13)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        clip_ims = clip_frames(clip_dir / "clip.mp4", total_frames, duration,
                               (left_w, clip_h), td)
        # Panel stills come from the clip track itself, at the sampled timestamps,
        # so the sheet the viewer watches assemble is the sheet the model was given.
        panels = []
        for t in times:
            idx = min(len(clip_ims) - 1, int(t * FPS))
            panels.append(clip_ims[idx].resize((panel_w, panel_h), Image.LANCZOS))

        out_dir = td / "out"
        out_dir.mkdir()
        sheet_y = head_h + 26

        for i in range(total_frames):
            t = i / FPS
            img = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(img)

            d.text((pad, 26), "WHAT CAN AI SEE", font=f_kicker, fill=ACCENT)
            d.text((pad, 48), event["question"], font=f_title, fill=FG)

            # left: the clip
            img.paste(clip_ims[i], (pad, head_h + 26))
            d.text((pad, head_h + 26 + clip_h + 12),
                   f"{args.clip}   ·   {duration:.0f}s   ·   real speed",
                   font=f_small, fill=DIM)

            # right: the sheet, filling in at the sampled timestamps
            d.text((right_x, head_h), "WHAT THE MODEL GETS", font=f_kicker, fill=ACCENT)
            for k in range(cols * rows_n):
                c, r = k % cols, k // cols
                x = right_x + c * (panel_w + 6)
                y = sheet_y + r * (panel_h + 6)
                if t >= times[k]:
                    img.paste(panels[k], (x, y))
                    d.rectangle([x, y, x + 22, y + 16], fill=(10, 10, 12))
                    d.text((x + 7, y + 2), str(k + 1), font=f_label, fill=FG)
                else:
                    d.rectangle([x, y, x + panel_w, y + panel_h], fill=(23, 25, 30))

            sheet_bottom = sheet_y + rows_n * (panel_h + 6)
            if t >= times[-1]:
                d.text((right_x, sheet_bottom + 6),
                       f"the whole clip · {sheet_meta['panels']} panels · "
                       f"~{sheet_meta['tokens_per_panel_at_196']:g} tokens each",
                       font=f_small, fill=(196, 200, 210))

            # verdict beat
            reveal = t - duration
            if reveal > 0:
                vy = head_h + 26 + clip_h + 48
                d.text((pad, vy), "VERDICTS", font=f_kicker, fill=ACCENT)
                vy += 26
                for n, (model_id, answers) in enumerate(ordered):
                    if reveal < 0.35 + n * 0.45:
                        break
                    v = verdict_of(answers.get("gate", ""))
                    label = "YES" if v is True else "NO" if v is False else "—"
                    colour = NEUTRAL if v is None else (GOOD if v == truth else BAD)
                    mm = model_meta.get(model_id, {})
                    d.text((pad, vy + 4), mm.get("name", model_id), font=f_model, fill=FG)
                    cw = 62
                    d.rounded_rectangle([pad + left_w - cw, vy, pad + left_w, vy + 28], 6,
                                        fill=colour if v is not None else (34, 36, 42))
                    tw = d.textlength(label, font=f_verdict)
                    d.text((pad + left_w - cw + (cw - tw) / 2, vy + 4), label,
                           font=f_verdict, fill=BG if v is not None else NEUTRAL)
                    vy += 38
                if reveal > 0.35 + len(ordered) * 0.45:
                    d.line([(pad, vy + 4), (pad + left_w, vy + 4)], fill=RULE, width=1)
                    d.text((pad, vy + 14),
                           f"GROUND TRUTH   {'YES' if truth else 'NO'}",
                           font=f_kicker, fill=ACCENT)
                    gt = textwrap.shorten(" ".join(str(meta["ground_truth"]).split()),
                                          width=66, placeholder=" …")
                    d.text((pad, vy + 34), gt, font=f_sub, fill=DIM)

            img.save(out_dir / f"{i:05d}.png")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-framerate", str(FPS),
             "-i", str(out_dir / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "19", "-movflags", "+faststart", str(args.out)], check=True)

    print(f"wrote {args.out}  ({W}x{H}, {total_frames / FPS:.1f}s)")


if __name__ == "__main__":
    main()
