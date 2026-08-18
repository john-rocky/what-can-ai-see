#!/usr/bin/env python3
"""One clip, every model's verdict, the ground truth — as a single postable image.

The card leads with the CONTACT SHEET rather than the video still, because that is
the part nobody expects: this is not a frame the model looked at, it is the whole
clip, and it is all the model ever gets. Six panels at 33 tokens each. Putting
that on screen next to the verdicts is what makes a wrong answer legible instead
of just embarrassing — quite often the model is not being stupid, it is being
shown ten tokens of a person.

Rows are sorted with the correct answers at the bottom, so the eye lands on the
failures first. Nothing is hidden: a model that refused shows as `—`, not as a miss.

usage:
  card.py --clip synth-fall-pos --encoding g6 --results runs/floor/*.jsonl --out cards/x.png
"""

from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

W = 1200  # X renders a 1200px-wide image without recompressing it to mush
PAD = 40
BG = (13, 14, 17)
FG = (238, 239, 242)
DIM = (139, 143, 152)
RULE = (38, 40, 46)
GOOD = (61, 200, 125)
BAD = (240, 92, 84)
NEUTRAL = (150, 152, 160)
ACCENT = (108, 168, 255)

FONTS = {
    "bold": "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "reg": "/System/Library/Fonts/Supplemental/Arial.ttf",
    "mono": "/System/Library/Fonts/Menlo.ttc",
}


def font(kind: str, size: int) -> ImageFont.ImageFont:
    path = FONTS.get(kind)
    if path and Path(path).exists():
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default(size)


def verdict_of(answer: str):
    """Same extraction as score.py, kept deliberately simple and identical in spirit:
    read the first line, else the first sentence, else give up."""
    import re
    text = (answer or "").strip()
    if not text:
        return None
    # See the note in score.py: MiniCPM-V puts its verdict in \boxed{} after a
    # chain of reasoning, so the box wins over any first-line heuristic.
    if (m := re.search(r"\\boxed\s*\{\s*(yes|no)", text, re.I)):
        return m.group(1).lower() == "yes"
    first = text.splitlines()[0].strip()
    if re.match(r"^\W*(yes|yeah|true)\b", first, re.I):
        return True
    if re.match(r"^\W*(no|nope|false|none)\b", first, re.I):
        return False
    head = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
    if re.search(r"\byes\b", head, re.I):
        return True
    if re.search(r"\b(no|not|never)\b", head, re.I):
        return False
    return None


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
    events = {e["id"]: e for e in yaml.safe_load(args.events.read_text())["events"]}
    event = events[meta["event"]]
    model_meta = {m["id"]: m for m in yaml.safe_load(args.models.read_text())["models"]}
    sheet_meta = json.loads((clip_dir / f"{args.encoding}.json").read_text())
    truth = meta["label"] == "positive"

    # Collect this clip's gate + open answers per model.
    rows: dict[str, dict] = {}
    for path in args.results:
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            # A runs/<batch>/*.jsonl glob also matches the batch's own tasks.jsonl,
            # whose lines carry no `model`; skip them rather than crashing.
            if "model" not in r or "id" not in r:
                continue
            clip, enc, q = r["id"].split("|")
            if clip != args.clip or enc != args.encoding:
                continue
            rows.setdefault(r["model"], {})[q] = r.get("answer", "") if r.get("ok") else ""
    if not rows:
        raise SystemExit(f"no results for {args.clip} / {args.encoding}")

    # Wrong answers first — the eye should land on the failure, not scroll to it.
    ordered = sorted(
        rows.items(),
        key=lambda kv: (verdict_of(kv[1].get("gate", "")) == truth,
                        model_meta.get(kv[0], {}).get("size_mb", 0)))

    sheet = Image.open(clip_dir / f"{args.encoding}.jpg").convert("RGB")
    sheet_w = W - 2 * PAD
    sheet_h = round(sheet.height * sheet_w / sheet.width)
    sheet = sheet.resize((sheet_w, sheet_h), Image.LANCZOS)

    f_title = font("bold", 44)
    f_sub = font("reg", 21)
    f_kicker = font("bold", 17)
    f_model = font("bold", 25)
    f_note = font("reg", 18)
    f_verdict = font("bold", 27)
    f_mono = font("mono", 17)

    row_h = 92
    head_h = 150
    band_h = 62
    foot_h = 146   # header + two wrapped ground-truth lines + the credit line
    H = head_h + sheet_h + band_h + len(ordered) * row_h + foot_h + PAD

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # ── header ────────────────────────────────────────────────────────────────
    d.text((PAD, 34), "WHAT CAN AI SEE", font=f_kicker, fill=ACCENT)
    d.text((PAD, 62), event["question"], font=f_title, fill=FG)
    d.text((PAD, 116), f"{meta['event']}  ·  {event['evidence']}  ·  "
                       f"{'POSITIVE' if truth else 'HARD NEGATIVE'}  ·  {args.clip}",
           font=f_sub, fill=DIM)

    y = head_h
    img.paste(sheet, (PAD, y))
    y += sheet_h

    # ── the budget band: the line that explains most of the failures below ────
    d.rectangle([PAD, y + 12, W - PAD, y + band_h - 4], fill=(21, 23, 28))
    tpp = sheet_meta["tokens_per_panel_at_196"]
    px = sheet_meta["panel_px_at_448"]
    d.text((PAD + 16, y + 26),
           f"This is the whole clip. {sheet_meta['panels']} panels, "
           f"~{tpp:g} visual tokens each ({px[0]}×{px[1]} px at the model's canvas).",
           font=f_note, fill=(196, 200, 210))
    y += band_h

    # ── model rows ────────────────────────────────────────────────────────────
    for model_id, answers in ordered:
        v = verdict_of(answers.get("gate", ""))
        label = "YES" if v is True else "NO" if v is False else "—"
        correct = v is not None and v == truth
        colour = NEUTRAL if v is None else (GOOD if correct else BAD)

        d.line([(PAD, y), (W - PAD, y)], fill=RULE, width=1)
        mm = model_meta.get(model_id, {})
        d.text((PAD, y + 18), mm.get("name", model_id), font=f_model, fill=FG)
        detail = f"{mm.get('params', '?')}  ·  {mm.get('size_mb', '?')} MB"
        if mm.get("visual_tokens"):
            detail += f"  ·  {mm['visual_tokens']} visual tokens"
        d.text((PAD, y + 50), detail, font=f_note, fill=DIM)

        # Verdict chip, right-aligned.
        chip_w, chip_h = 112, 46
        cx = W - PAD - chip_w
        d.rounded_rectangle([cx, y + 22, cx + chip_w, y + 22 + chip_h], 9,
                            fill=colour if v is not None else (34, 36, 42))
        tw = d.textlength(label, font=f_verdict)
        d.text((cx + (chip_w - tw) / 2, y + 32), label, font=f_verdict,
               fill=BG if v is not None else NEUTRAL)

        # The model's own words, so the verdict is not just a colour. The open
        # description is preferred over the gate's: a model that answers the gate
        # right while describing a different scene is the failure worth showing.
        said = " ".join((answers.get("open") or answers.get("gate") or "").split())
        if said:
            quote_x = PAD + 330
            avail = (cx - 24) - quote_x  # stop short of the verdict chip
            said = textwrap.shorten(said, width=int(avail / 10.1), placeholder=" …")
            d.text((quote_x, y + 52), f"“{said}”", font=f_mono, fill=(126, 130, 140))
        y += row_h

    # ── footer ────────────────────────────────────────────────────────────────
    d.line([(PAD, y), (W - PAD, y)], fill=RULE, width=1)
    d.text((PAD, y + 20), "GROUND TRUTH", font=f_kicker, fill=ACCENT)
    truth_text = f"{'YES' if truth else 'NO'} — {' '.join(str(meta['ground_truth']).split())}"
    # Wrap to the card width rather than running off the right edge. Two lines is
    # the budget; the full text lives in the clip's meta.yaml.
    lines = textwrap.wrap(truth_text, width=int((W - 2 * PAD) / 9.6))[:2]
    for n, line in enumerate(lines):
        d.text((PAD, y + 46 + n * 26), line, font=f_sub, fill=FG)
    d.text((PAD, y + 52 + len(lines) * 26),
           "on-device VLMs via CoreAIKit  ·  measured on Apple silicon, no cloud",
           font=f_note, fill=DIM)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.out)
    print(f"wrote {args.out}  ({W}x{H})")


if __name__ == "__main__":
    main()
