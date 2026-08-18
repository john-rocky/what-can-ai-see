#!/usr/bin/env python3
"""Explainer segments for the two findings a clip-and-verdict reel cannot show.

reel.py answers "did the model get this clip right". These two findings are about
something else, and each needs its own shape:

  scaffold   F10. The model was told to describe each of six panels before
             answering. Both halves of a pair get the SAME description. The thing
             to see is the two texts side by side being identical — a verdict chip
             cannot carry that.

  curve      F11. One pair, degraded one variable at a time. The thing to see is
             the picture getting worse while the answer stays right, and then the
             one axis where it stops. That is four states at once, not a sequence.

Both reuse reel.py's palette and card frames so the output cuts together with it.

usage:
  reel_finding.py --out cards/reel-findings.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from reel import (W, H, FPS, BG, FG, DIM, GOOD, BAD, ACCENT, font, card_frame,  # noqa: E402
                  render_card, fit, verdict_of)

F_KICK = font("bold", 16)
F_H = font("bold", 34)
F_SUB = font("reg", 21)
F_MONO = font("reg", 19)
F_CHIP = font("bold", 20)
F_TAG = font("bold", 15)
F_PUNCH = font("bold", 27)


def answers_for(run_dir: Path, model: str) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    p = run_dir / f"{model}.jsonl"
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "model" not in r:
            continue
        clip, enc, q = r["id"].split("|")
        out.setdefault(clip, {})[q] = r.get("answer", "") if r.get("ok") else ""
    return out


def encode(frames_dir: Path, out: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-framerate", str(FPS),
         "-i", str(frames_dir / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-crf", "20", str(out)], check=True)


def seg_scaffold(model: str, model_name: str, pos: str, neg: str,
                 run_dir: Path, out: Path) -> float:
    """Two sheets, and the same words underneath both."""
    ans = answers_for(run_dir, model)
    texts = {c: " ".join((ans.get(c, {}).get("panels") or "").split()) for c in (pos, neg)}
    verdicts = {c: (texts[c].split()[-1] if texts[c] else "") for c in (pos, neg)}
    identical = texts[pos] == texts[neg]

    sheets = {c: fit(Image.open(ROOT / "clips" / c / "g6.jpg").convert("RGB"), 520, 300)
              for c in (pos, neg)}
    total = 13.0
    n = int(total * FPS)
    with tempfile.TemporaryDirectory() as td:
        fd = Path(td)
        for i in range(n):
            t = i / FPS
            img = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(img, "RGBA")
            d.text((52, 30), "WHAT CAN AI SEE", font=F_KICK, fill=ACCENT)
            for k, line in enumerate(textwrap.wrap(
                    "Told to describe each of the six panels, then answer", 52)[:2]):
                d.text((52, 58 + k * 40), line, font=F_H, fill=FG)
            d.text((52, 142), f"{model_name}  ·  the same clip pair as before",
                   font=F_SUB, fill=DIM)

            for col, (clip, tag, tagcol) in enumerate((
                    (pos, "CONVEYOR STOPPED", (120, 214, 160)),
                    (neg, "CONVEYOR MOVING", (240, 140, 130)))):
                x = 52 + col * 600
                img.paste(sheets[clip], (x, 190))
                d.rounded_rectangle([x, 500, x + d.textlength(tag, font=F_TAG) + 24, 526], 5,
                                    fill=(30, 62, 48) if col == 0 else (58, 30, 30))
                d.text((x + 12, 505), tag, font=F_TAG, fill=tagcol)
                if t > 2.2:
                    d.text((x, 542), "it wrote:", font=F_KICK, fill=ACCENT)
                    body = textwrap.wrap(texts[clip] or "(nothing)", 40)[:4]
                    for k, line in enumerate(body):
                        d.text((x, 566 + k * 26), line, font=F_MONO, fill=(196, 202, 214))
            if t > 6.4:
                d.rectangle([0, H - 74, W, H], fill=(58, 30, 30))
                punch = ("IDENTICAL — byte for byte, for both clips" if identical
                         else "Six panels. One template, repeated. No per-panel content.")
                d.text((52, H - 56), punch, font=F_PUNCH, fill=(250, 190, 184))
            img.save(fd / f"{i:05d}.png")
        encode(fd, out)
    return total


def seg_curve(model: str, model_name: str, base: str, run_dir: Path,
              axes: list[str], out: Path) -> float:
    """One pair, degraded; the answer holds until it does not."""
    ans = answers_for(run_dir, model)

    def cell(clip: str):
        v = verdict_of(ans.get(clip, {}).get("gate", ""))
        return v

    steps = [("clean", base)] + [(f"{ax} L3", f"{base}__{ax}3") for ax in axes]
    tiles = {c: fit(Image.open(ROOT / "clips" / c / "g6.jpg").convert("RGB"), 288, 250)
             for _, c in steps}
    total = 13.0
    n = int(total * FPS)
    with tempfile.TemporaryDirectory() as td:
        fd = Path(td)
        for i in range(n):
            t = i / FPS
            img = Image.new("RGB", (W, H), BG)
            d = ImageDraw.Draw(img, "RGBA")
            d.text((52, 30), "WHAT CAN AI SEE", font=F_KICK, fill=ACCENT)
            d.text((52, 58), "How far can you degrade it before it breaks?",
                   font=F_H, fill=FG)
            d.text((52, 108), f"{model_name}  ·  “Was an object taken away?”  ·  "
                              f"both halves of the pair degraded together",
                   font=F_SUB, fill=DIM)

            shown = min(len(steps), max(1, int((t - 0.6) / 1.5) + 1))
            for k, (label, clip) in enumerate(steps[:shown]):
                x = 52 + k * 300
                img.paste(tiles[clip], (x, 176))
                d.text((x, 438), label.upper(), font=F_TAG, fill=DIM)
                v = cell(clip)
                ok = v is True                       # the positive: yes is correct
                txt = "DETECTED" if ok else "MISSED"
                col = GOOD if ok else BAD
                d.rounded_rectangle([x, 462, x + 150, 496], 7, fill=col)
                d.text((x + 14, 468), txt, font=F_CHIP, fill=BG)
                # The 60p tile looks untouched at this size, and that is the
                # result rather than an oversight: the contact sheet has already
                # thrown away more detail than the round trip does. Say it, so a
                # viewer does not read it as a missing degradation.
                if label.startswith("resolution"):
                    for j, ln in enumerate([
                            "it IS degraded — 60p round trip.",
                            "at panel scale you cannot see it:",
                            "the sheet threw that detail away first."]):
                        d.text((x, 506 + j * 22), ln, font=F_TAG, fill=(126, 132, 144))

            if t > 7.2:
                d.text((52, 546), "60p-equivalent and near-dark: still detected.",
                       font=F_PUNCH, fill=(150, 224, 186))
            if t > 9.0:
                d.text((52, 592), "Half the view blocked: gone.",
                       font=F_PUNCH, fill=(250, 160, 152))
            if t > 10.2:
                d.text((52, 646),
                       "Camera placement matters more than camera spec.",
                       font=F_SUB, fill=DIM)
            img.save(fd / f"{i:05d}.png")
        encode(fd, out)
    return total


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    work = args.out.parent / f".{args.out.stem}-parts"
    work.mkdir(parents=True, exist_ok=True)
    parts, total = [], 0.0

    intro = work / "00.mp4"
    render_card(card_frame(
        "Two things a scoreboard cannot show.",
        "What happens when you tell the model to look panel by panel — and how "
        "far the picture can degrade before it stops working.",
        "measured on device · no cloud"), 4.5, intro)
    parts.append(intro); total += 4.5

    a = work / "01-scaffold.mp4"
    total += seg_scaffold("lfm2.5-vl-3b", "LFM2.5-VL 3B",
                          "synth-stop-pos", "synth-stop-neg", ROOT / "runs/panels", a)
    parts.append(a)

    a2 = work / "01b-scaffold.mp4"
    total += seg_scaffold("north-micro-vision", "North Micro Vision (Cohere, 2.4B)",
                          "synth-stop-pos", "synth-stop-neg", ROOT / "runs/panels", a2)
    parts.append(a2)

    b = work / "02-curve.mp4"
    total += seg_curve("lfm2.5-vl-3b", "LFM2.5-VL 3B", "object-removed-5241131",
                       ROOT / "runs/ladder", ["darkness", "resolution", "occlusion"], b)
    parts.append(b)

    outro = work / "99.mp4"
    render_card(card_frame("A format is not a thought.",
                           "All three models produced a correctly-formatted six-item "
                           "list and filled every slot with one template. The JSON "
                           "would have validated.",
                           "what-can-ai-see"), 5.0, outro)
    parts.append(outro); total += 5.0

    listing = work / "parts.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat",
                    "-safe", "0", "-i", str(listing), "-c", "copy",
                    "-movflags", "+faststart", str(args.out)], check=True)
    print(f"wrote {args.out}  ({W}x{H}, {total:.0f}s)")


if __name__ == "__main__":
    main()
