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

  # the settings a film cut wants, arrived at by looking at the output on a phone:
  said_card.py --stream runs/stream/general-bridge --run runs/film/general-bridge \
      --size 1080x1460 --fit pad --lines 6 --text-size 28 \
      --label "Describe what is happening." --out cards/bridge.mp4

  4:3 footage needs --fit pad; the default crop throws away the edges, and on this
  material the edges are where the answer is. 20px text is legible at a desk and
  not on a phone, which is where these get watched.
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
import reel  # noqa: E402
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


# Openers, not content. Every model prefaces the claim with a restatement of the
# task — "This contact sheet captures a sequence of a man firing a rifle" — and on
# a card that preface eats the line. ECHO cannot handle these: it deletes whole
# sentences, and here the sentence is the answer. Trim the opener, keep the rest.
OPENER = re.compile(
    r"^(this|the)\s+(contact\s+sheet|image|sequence|series\s+of\s+(images|frames))\s+"
    r"(captures?|shows?|depicts?|displays?|presents?|appears\s+to\s+show)\s+"
    r"(a\s+(sequence|series|dramatic|dynamic|tense|time-lapse)[\w\s-]*?\s+of\s+)?", re.I)


# Sentences that say nothing about the picture. Qwen in particular opens with one
# or two sentences of the task read back — "The sequence is in chronological order,
# with Panel 1 being the earliest and Panel 4 the latest" — and taking the first
# sentence therefore put the PROMPT on the card, twice, under a model's name. A
# sentence is meta if it talks about panels, sequences or the sheet and mentions
# nothing else; one that says "in panel 3 the barrel drops" is not meta.
# A sentence is worthless here if, once the task read-back is stripped off, nothing
# about the picture is left. Order matters and getting it wrong is what this cost:
# checking META first threw away "This contact sheet captures a sequence of a man
# firing a rifle at a cannon" — the single best line in the run — because the
# sentence contains the words "contact sheet". Strip, THEN judge what remains.
# "Is this sentence only about the sheet?" cannot be a full-match regex, because
# the boilerplate contains "3.0 seconds" and a character class that excludes the
# period stops dead at it. So: delete every known boilerplate phrase and see what
# is left. Fewer than three real words means the sentence said nothing.
BOILER = re.compile(
    r"\b(here is (a|the)( detailed)? description( of)?|a detailed description|"
    r"the events (occurring|shown|captured)|what is happening|"
    r"(over|in|during|covering) the last [\d.]+ seconds?|of (a|the) camera feed|"
    r"in chronological order|in time order|chronological|"
    r"from panel \d+|panel \d+|\(?(earliest|latest)\)?|"
    r"a \d+[- ](frame|panel) contact sheet|(a|the) contact sheet|"
    r"a (continuous |single, continuous )?sequence of( (four|\d+))? (frames|images|panels)|"
    r"the (sequence|frames|images|panels)( is| are)?|presented|provided|shown|"
    r"progress(es|ing|ion)?|(from )?left to right|unfolding|unfolds|"
    r"in the order|arranged)\b", re.I)


# Function words survive the boilerplate deletion and pad the count back up:
# "With Panel 1 being the earliest and Panel 4 the latest" leaves "with being and
# the", four words, and was kept. Only content words count.
STOP = {"a", "an", "and", "are", "as", "at", "be", "being", "but", "by", "for",
        "from", "in", "is", "it", "its", "of", "on", "or", "over", "that", "the",
        "there", "this", "to", "was", "were", "with", "which", "while", "then",
        "each", "into", "their", "they", "has", "have", "had", "also", "both"}


def _is_meta(q: str) -> bool:
    rest = re.sub(r"[^A-Za-z]+", " ", BOILER.sub(" ", q)).lower().split()
    return len([w for w in rest if w not in STOP]) < 3


# Leading clauses that restate the task. Stripped rather than dropped, because the
# claim usually follows the comma: "Based on the sequence of four frames from a
# contact sheet, the image captures a person in a field."
# The budget before the comma is deliberately small. At 140 characters this ate
# "…a person swinging a baseball bat in front of a large cylindrical object," and
# left only the trailing "likely a cannon" — it had swallowed the claim to reach a
# comma. Real boilerplate is under 70 characters; anything longer is content.
PREFIX = re.compile(
    r"^(based on|looking at|from|in|here is|the image is|this is)?[^,:;.]{0,50}?"
    r"\b(contact sheet|chronological order|time order|panel \d|\d+[- ](frame|panel)|"
    r"sequence of (four|the|\\d+)? ?frames?|"
    r"detailed description of (what|the))\b[^,:;.]{0,50}[,:]\s*", re.I)

COUNT = re.compile(r"^(four|4|\d+)\s+(frames?|panels?|images?)\s+"
                   r"(capturing|showing|depicting|of)\s+", re.I)


def _strip(q: str) -> str:
    q = q.strip()
    for _ in range(3):
        nxt = PREFIX.sub("", q, count=1)
        if nxt == q:
            break
        q = nxt
    q = COUNT.sub("", OPENER.sub("", q).strip()).strip()
    return q


def sentence(a: str, limit: int) -> str:
    t = ECHO.sub(" ", LEAD.sub("", (a or "").strip()))
    t = " ".join(t.replace("**", "").split())
    for raw in re.split(r"(?<=[.;:])\s+", t):
        q = _strip(raw)
        if len(q) < 14 or _is_meta(q):
            continue
        if q[:1].islower():
            q = q[0].upper() + q[1:]
        return q[:limit] + ("…" if len(q) > limit else "")
    return " ".join(t.split())[:limit]


def paragraph(a: str, limit: int) -> str:
    """Everything the model said, minus the task read back.

    `sentence` answers "what did it claim"; this answers "what did it write". The
    two differ by a lot — the median reply here is 456 characters and its first
    clause is 63, so a card built on `sentence` shows 14% of the output. Which one
    belongs on screen is a judgement about the viewer, not about the model, so it
    is a flag rather than a default.
    """
    t = ECHO.sub(" ", LEAD.sub("", (a or "").strip()))
    t = " ".join(t.replace("**", "").split())
    out = []
    for raw in re.split(r"(?<=[.;:])\s+", t):
        q = _strip(raw)
        if len(q) < 10 or _is_meta(q):
            continue
        # Every retained sentence starts one, because stripping a leading "In panel
        # 3," leaves the rest mid-sentence: "the man is preparing to fire".
        if q[:1].islower():
            q = q[0].upper() + q[1:]
        out.append(q)
    txt = " ".join(out) or " ".join(t.split())
    return txt[:limit] + ("…" if len(txt) > limit else "")


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
               tail: float, work: Path, idx: int, translate=None, tally=None,
               size=None, fit="crop", lines=2, text_size=28, overlap=0) -> Path:
    class A: pass
    args = A()
    args.stream, args.run, args.models = stream, run, models_arg
    args.size, args.fit = size, fit
    args.lines, args.text_size = lines, text_size
    args.overlap = overlap
    args.note, args.label, args.t0, args.t1, args.tail = note, label, t0, t1, tail
    args.translate = translate
    args.tally = tally
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
    ap.add_argument("--size", default=None, metavar="WxH",
                    help="canvas, default 1280x720. A 4:3 film needs a taller one.")
    ap.add_argument("--overlap", type=int, default=0,
                    help="pixels the text band rides up over the picture, under a "
                         "gradient. The film is the content; a band that starts "
                         "hard at the frame edge turns the card into a dashboard. "
                         "Overlapping buys the picture that many pixels back "
                         "without cropping it, which is not an option here — the "
                         "composition IS what is being measured.")
    ap.add_argument("--text-size", type=int, default=28, dest="text_size",
                    help="model-sentence size in px. Was fixed at 20, which is "
                         "legible on a 1280px card at desk distance and not on a "
                         "phone, where these are actually watched.")
    ap.add_argument("--lines", type=int, default=2,
                    help="text lines per model. 2 shows the opening claim; 4-6 shows "
                         "most of what was actually written.")
    ap.add_argument("--fit", choices=("crop", "pad"), default="crop",
                    help="crop fills the frame and throws away the edges. On this "
                         "footage that is not cosmetic: the thing being measured is "
                         "WHERE the muzzle points relative to the man, and a crop "
                         "that trims the frame can remove exactly that. Use pad for "
                         "anything whose composition is the subject.")
    ap.add_argument("--note", default=None, help="line drawn under the question")
    ap.add_argument("--label", default=None, help="question text to draw, e.g. in Japanese")
    ap.add_argument("--tally", default=None,
                    help="regex; counts the windows whose description matches, running, "
                         "in the corner. On five minutes of an empty stairwell the count "
                         "of windows claiming a person is the entire finding, and a viewer "
                         "cannot hold it in their head across 300 seconds.")
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
                                    args.translate, s.get("tally") or args.tally,
                                    args.size, args.fit, args.lines,
                                    args.text_size, args.overlap))
            print(f"  {i+1}/{len(segs)}  {Path(s['stream']).name}")
        listing = work / "parts.txt"
        listing.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-c", "copy", "-y", str(args.out)], check=True)
        print(f"wrote {args.out}  {len(parts)} card(s)")
        return
    _render(args)


def _render(args) -> None:
    global W, H
    if getattr(args, "size", None):
        W, H = (int(v) for v in args.size.lower().split("x"))
        reel.W, reel.H = W, H
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

    tally_rx = None
    if getattr(args, "tally", None):
        tally_rx = re.compile(args.tally, re.I)

    ja = {}
    if getattr(args, "translate", None):
        ja = {k: v for k, v in json.loads(Path(args.translate).read_text()).items()
              if not k.startswith("_")}

    rows_n = len(said)
    nlines = max(1, int(getattr(args, "lines", 2) or 2))
    # Every metric that used to be a literal is derived from the text size, so one
    # flag moves the whole block coherently. The old constants were 20px text on a
    # 24px line at 96 characters wide; those ratios are kept.
    ts = max(12, int(getattr(args, "text_size", 28) or 28))
    lh = round(ts * 1.20)
    f_said, f_name = font("reg", ts), font("bold", round(ts * 0.72))
    wrap_lat = max(20, int((W - 88) / (ts * 0.56)))
    wrap_cjk = max(12, int((W - 88) / (ts * 1.00)))
    # Name line, the text block, and a gap. Without the last term the next model's
    # name lands 5px under the previous model's final line and the two rows read as
    # one paragraph.
    row_h = round(ts * 1.1) + nlines * lh + round(ts * 0.75)
    panel = 58 + rows_n * row_h
    # The picture gets the panel's height back, up to `overlap`, and the band is
    # drawn over it with a fade so nothing is cut — only covered, at the bottom,
    # where this footage carries water and ground rather than the subject.
    over = max(0, int(getattr(args, "overlap", 0) or 0))
    vid_h = (H - panel + over) // 2 * 2
    t0 = float(getattr(args, "t0", None) or 0.0)
    t1 = float(getattr(args, "t1", None) or spec["duration_s"])
    duration = t1 - t0
    n = int((duration + args.tail) * FPS)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t0:.2f}",
             "-i", str(ROOT / "clips" / cid / "clip.mp4"), "-t", f"{duration:.2f}",
             "-vf", (f"fps={FPS},scale={W}:{vid_h}:force_original_aspect_ratio=increase,"
                     f"crop={W}:{vid_h}") if getattr(args, "fit", "crop") == "crop" else
                    (f"fps={FPS},scale={W}:{vid_h}:force_original_aspect_ratio=decrease,"
                     f"pad={W}:{vid_h}:(ow-iw)/2:(oh-ih)/2:color=0x0a0c10"),
             "-y", str(td / "f%04d.png")], check=True)
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

            if tally_rx:
                hits = {m: sum(1 for te, a in said[m]
                               if te <= t + 1e-6 and tally_rx.search(sentence(a, 400)))
                        for m in said}
                asked = {m: sum(1 for te, _ in said[m] if te <= t + 1e-6) for m in said}
                lines = [f"{m}  {hits[m]}/{asked[m]}" for m in names if m in said]
                bw = max(d.textlength(l, font=F_NAME) for l in lines) + 34
                bh = 30 + 26 * len(lines)
                d.rounded_rectangle([W - 44 - bw, 132, W - 44, 132 + bh], 8,
                                    fill=(12, 14, 18, 225))
                d.text((W - 44 - bw + 17, 142), "windows claiming a person",
                       font=F_KICK, fill=ACCENT)
                # NOT `k` — that is the frame-loop variable, and rebinding it here
                # made every frame save as the same filename. Three thousand frames
                # collapsed into one and the card came out 0.04 seconds long while
                # the tool cheerfully reported 61.5.
                for row_i, l in enumerate(lines):
                    d.text((W - 44 - bw + 17, 166 + row_i * 26), l, font=F_NAME,
                           fill=(238, 242, 250))

            y = H - panel + 18
            # The band starts where the text starts, and the picture runs `over`
            # pixels PAST that point behind a scrim that fades in. Drawing the
            # solid part `over` pixels early instead — the first attempt — put the
            # hard edge in the middle of the frame and blacked out 340px of image
            # to buy back 170.
            scrim(img, H - panel + over, H, 214)
            for yy in range(over):
                a = int(214 * (yy / max(1, over)) ** 1.5)
                band = Image.new("RGBA", (W, 1), (8, 10, 14, a))
                img.paste(band, (0, H - panel + yy), band)
            for m in names:
                if m not in said:
                    continue
                # Before the first window closes there is genuinely no answer yet —
                # but two seconds of "…" at the head of a nine-second card is dead
                # air. Say what is true instead: nothing has been asked yet.
                seen = [s for s in said[m] if s[0] <= t + 1e-6]
                pick = sentence if nlines <= 2 else paragraph
                txt = (pick(seen[-1][1], nlines * 100) if seen
                       else "— the first window has not closed yet")
                if ja and txt in ja:
                    txt = ja[txt]
                elif ja and seen:
                    txt = txt + "  [未訳]"
                d.text((44, y), m, font=f_name, fill=(150, 156, 168))
                cjk = any("\u3040" <= c <= "\u9fff" for c in txt)
                fs = jfont(round(ts * 0.95), "W3") if cjk else f_said
                width = wrap_cjk if cjk else wrap_lat
                # A sentence that runs past the last line has to SAY it was cut.
                # Silently ending on "with no significant smoke or fire" reads as
                # the model's own words stopping there, which is a misquote.
                wrapped = textwrap.wrap(txt, width)
                if len(wrapped) > nlines:
                    wrapped = wrapped[:nlines]
                    wrapped[-1] = wrapped[-1].rstrip(" .,;") + " …"
                for i, line in enumerate(wrapped):
                    d.text((44, y + round(ts * 1.1) + i * lh), line, font=fs,
                           fill=(238, 242, 250) if seen else (118, 124, 136))
                y += row_h
            img.save(out_dir / f"{k:05d}.png")
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-framerate", str(FPS),
             "-i", str(out_dir / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "20", "-y", str(args.out)], check=True)
    print(f"wrote {args.out}  {(n/FPS):.1f}s, {rows_n} model(s)")


if __name__ == "__main__":
    main()
