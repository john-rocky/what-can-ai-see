#!/usr/bin/env python3
"""The footage, and what each model says about it. No verdicts.

`live.py` draws a chip per model because it renders the judgement runs, where the
answer is yes or no. The neutral pass has no verdict to draw — the reply is a
sentence, and the sentence is the whole point. A card that forced it into a chip
would show a row of amber "no answer" boxes over the most interesting output in
the project.

So: full-bleed video, the neutral instruction at the top, and each model's current
sentence underneath, replaced as each window closes. The viewer reads what the
model claims while watching whether it is there.

The case this was built for is one shot of a wooded hillside from a 1956 film,
eight identical frames, foreground change 0.022 — and LFM2.5-VL 3B reporting a
helicopter, then a helicopter, then a small vehicle, then nothing, then a fire.
Nothing moves. Nothing is there. A chip cannot show that.

usage:
  said_card.py --stream runs/stream/alu-s011 --run runs/alu --out cards/heli.mp4
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
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from reel import W, H, FPS, ACCENT, font  # noqa: E402
from reel_fast import jfont  # noqa: E402

F_KICK = font("bold", 15)
F_Q = font("bold", 30)
F_NAME = font("bold", 17)
F_SAID = font("reg", 20)

LEAD = re.compile(r"^\s*(yes|no)\b[\.,:;]?\s*", re.I)
ECHO = re.compile(r"(the image is a contact sheet[^.]*\.|contact sheet of \d+ frames[^.]*\.|"
                  r"covering the last [\d.]+s of a camera feed[^.]*\.|in time order[^.]*\.|"
                  r"panel \d+ is the (earliest|latest)[^.]*\.|based on the provided contact "
                  r"sheet[^:]*:|here is a description[^:]*:)", re.I)


def sentence(a: str, limit: int) -> str:
    t = ECHO.sub(" ", LEAD.sub("", (a or "").strip()))
    t = " ".join(t.replace("**", "").split())
    # the first clause carries the claim; the rest is padding
    parts = re.split(r"(?<=[.;])\s+", t)
    out = parts[0] if parts else t
    return out[:limit] + ("…" if len(out) > limit else "")


def scrim(img, y0, y1, a=200, fade=0):
    h = y1 - y0
    band = Image.new("RGBA", (W, h), (8, 10, 14, a))
    if fade:
        px = band.load()
        for y in range(max(0, h - fade), h):
            k = 1.0 - (y - (h - fade)) / fade
            for x in range(W):
                px[x, y] = (8, 10, 14, int(a * k))
    img.paste(band, (0, y0), band)


def render_one(stream: Path, run: Path, models_arg, note, label, t0, t1,
               tail: float, work: Path, idx: int, translate=None) -> Path:
    class A: pass
    args = A()
    args.stream, args.run, args.models = stream, run, models_arg
    args.note, args.label, args.t0, args.t1, args.tail = note, label, t0, t1, tail
    args.translate = translate
    args.out = work / f"{idx:02d}.mp4"
    _render(args)
    return args.out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", type=Path, default=None)
    ap.add_argument("--run", type=Path, default=None, help="dir with <model>.jsonl")
    ap.add_argument("--models", default=None, help="comma-separated, default all")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tail", type=float, default=1.5)
    ap.add_argument("--note", default=None, help="line drawn under the question")
    ap.add_argument("--label", default=None, help="question text to draw, e.g. in Japanese")
    ap.add_argument("--translate", type=Path, default=None,
                    help="json map of the models' English sentences to Japanese, for a "
                         "CHECK cut. A translated quote is a quote you wrote, so the card "
                         "is stamped as a translation and this must never be used on "
                         "anything published.")
    ap.add_argument("--t0", type=float, default=None)
    ap.add_argument("--t1", type=float, default=None)
    ap.add_argument("--segments", type=Path, default=None,
                    help="json list of {stream, run, label, note, t0, t1} — a reel of "
                         "description cards rather than a single one")
    args = ap.parse_args()

    if args.segments:
        segs = json.loads(args.segments.read_text())
        work = args.out.parent / f".{args.out.stem}-parts"
        work.mkdir(parents=True, exist_ok=True)
        parts = []
        for i, s in enumerate(segs):
            parts.append(render_one(Path(s["stream"]), Path(s["run"]),
                                    s.get("models"), s.get("note"), s.get("label"),
                                    s.get("t0"), s.get("t1"), args.tail, work, i,
                                    args.translate))
            print(f"  {i+1}/{len(segs)}  {Path(s['stream']).name}")
        listing = work / "parts.txt"
        listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-c", "copy", "-y", str(args.out)], check=True)
        print(f"wrote {args.out}  {len(parts)} card(s)")
        return
    _render(args)


def _render(args) -> None:
    spec = json.loads((args.stream / "windows.json").read_text())
    cid = spec["clip"]
    mt = yaml.safe_load("\n".join(
        l for l in (ROOT / "clips" / cid / "meta.yaml").read_text().split("\n")
        if not l.startswith("#"))) or {}

    names = ([m.strip() for m in args.models.split(",")] if args.models else
             sorted(p.stem for p in args.run.glob("*.jsonl")
                    if p.stem not in ("tasks", "frames") and not p.stem.startswith("detect-")))
    said: dict[str, list[tuple[float, str]]] = {}
    for m in names:
        f = args.run / f"{m}.jsonl"
        if not f.exists():
            continue
        rows = {}
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            c, wid, _ = r["id"].split("|")
            if c != cid or not r.get("ok"):
                continue
            rows[int(wid[1:])] = r.get("answer", "")
        seq = [(w["t_end"], rows[w["i"]]) for w in spec["windows"] if w["i"] in rows]
        if seq:
            said[m] = seq
    if not said:
        raise SystemExit(f"no neutral answers for {cid} in {args.run}")

    ja = {}
    if getattr(args, "translate", None):
        ja = {k: v for k, v in json.loads(Path(args.translate).read_text()).items()
              if not k.startswith("_")}

    rows_n = len(said)
    panel = 58 + rows_n * 74
    vid_h = (H - panel) // 2 * 2
    t0 = float(getattr(args, "t0", None) or 0.0)
    t1 = float(getattr(args, "t1", None) or spec["duration_s"])
    duration = t1 - t0
    n = int((duration + args.tail) * FPS)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t0:.2f}",
             "-i", str(ROOT / "clips" / cid / "clip.mp4"), "-t", f"{duration:.2f}",
             "-vf", f"fps={FPS},scale={W}:{vid_h}:force_original_aspect_ratio=increase,"
                    f"crop={W}:{vid_h}", "-y", str(td / "f%04d.png")], check=True)
        frames = sorted(td.glob("f*.png"))
        out_dir = td / "out"
        out_dir.mkdir()
        for k in range(n):
            t = t0 + k / FPS
            img = Image.new("RGB", (W, H), (10, 12, 16))
            img.paste(Image.open(frames[min(k, len(frames) - 1)]).convert("RGB"), (0, 0))
            d = ImageDraw.Draw(img, "RGBA")
            scrim(img, 0, 118, 210, fade=34)
            d.text((44, 16), (mt.get("event") or cid).upper(), font=F_KICK, fill=ACCENT)
            qtext = getattr(args, "label", None) or spec.get(
                "question", "Describe what is happening.")
            d.text((44, 40), qtext, font=jfont(30) if any(
                "\u3040" <= c <= "\u9fff" for c in qtext) else F_Q,
                   fill=(246, 248, 252))
            if ja:
                stamp = "日本語はチェック用の翻訳 — モデルの出力は英語"
                sw = d.textlength(stamp, font=jfont(15))
                d.text((W - 44 - sw, 20), stamp, font=jfont(15), fill=(226, 170, 90))
            if args.note:
                # Arial has no CJK glyphs and Pillow draws every kanji as a hollow
                # box instead of failing, so a Japanese note rendered with the
                # English font looks like a corrupted frame rather than a missing
                # font. Pick the face from the text, not from a flag.
                nf = (jfont(16) if any("\u3040" <= c <= "\u9fff" for c in args.note)
                      else F_KICK)
                d.text((44, 84), args.note, font=nf, fill=(150, 210, 220))

            y = H - panel + 18
            scrim(img, H - panel, H, 205)
            for m in names:
                if m not in said:
                    continue
                # Before the first window closes there is genuinely no answer yet —
                # but two seconds of "…" at the head of a nine-second card is dead
                # air. Say what is true instead: nothing has been asked yet.
                seen = [s for s in said[m] if s[0] <= t + 1e-6]
                txt = (sentence(seen[-1][1], 200) if seen
                       else "— the first window has not closed yet")
                if ja and txt in ja:
                    txt = ja[txt]
                elif ja and seen:
                    txt = txt + "  [未訳]"
                d.text((44, y), m, font=F_NAME, fill=(150, 156, 168))
                cjk = any("\u3040" <= c <= "\u9fff" for c in txt)
                fs = jfont(19, "W3") if cjk else F_SAID
                width = 54 if cjk else 96
                for i, line in enumerate(textwrap.wrap(txt, width)[:2]):
                    d.text((44, y + 22 + i * 24), line, font=fs,
                           fill=(238, 242, 250) if seen else (118, 124, 136))
                y += 74
            img.save(out_dir / f"{k:05d}.png")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-framerate", str(FPS),
             "-i", str(out_dir / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "20", "-y", str(args.out)], check=True)
    print(f"wrote {args.out}  {(n/FPS):.1f}s, {rows_n} model(s)")


if __name__ == "__main__":
    main()
