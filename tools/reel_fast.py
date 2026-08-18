#!/usr/bin/env python3
"""A fast cut: many scenes, each held only as long as the judgement takes.

`live.py` renders one clip at real speed under a status panel. It is honest and
it is the right artefact for reading a single case carefully — and as something to
scroll past it is dead. Sixteen seconds, most of it nothing happening, a small
panel of bars filling slowly. Twenty of those in a row is a boring account.

The feeling the footage can actually produce is *volume of judgement*: this thing
looks at a kitchen, a warehouse, a cat, a shop window, and decides, and decides,
and decides. That is a property of the corpus, not of any one clip, and it only
appears if the cutting is fast enough for the scenes to accumulate in the viewer's
head rather than in the timeline.

So: one beat per scene, roughly a second and a half, positioned at the moment the
answer lands. Full-bleed video, no panel — the verdict sits on the picture. A few
beats are marked to hold longer, because a reel with no rest is as flat as one
with no cuts; the ones worth holding are where a model says something specific
about something that is not there.

The verdicts are the real ones, taken from the real window that had closed at that
moment. Nothing is re-timed to make a cut land better. A beat that would need that
is a beat left out.

usage:
  reel_fast.py --beats beats.json --out cards/reel-fast.mp4
  reel_fast.py --auto --out cards/reel-fast.mp4      # pick beats from the corpus
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from card import verdict_of  # noqa: E402
from reel import W, H, FPS, ACCENT, font  # noqa: E402

# Colour means RIGHT or WRONG here, not yes or no.
#
# live.py uses the monitoring convention — red for alarm, green for clear — which
# is correct for someone reading a camera feed and actively misleading for someone
# scrolling past. "Is the cat on the bench?" YES is the right answer and it came
# out red, which every viewer reads as a failure. What a viewer wants to know is
# whether the model got it, so that is what the colour carries. The word YES or NO
# is still printed, so nothing is hidden by the recolouring.
RIGHT = (58, 190, 120)
WRONG = (240, 84, 76)
WAIT = (86, 92, 104)

F_Q = font("bold", 34)
F_CHIP = font("bold", 24)
F_NAME = font("bold", 18)
F_KICK = font("bold", 15)
F_SAID = font("reg", 21)


def meta(cid: str) -> dict:
    p = ROOT / "clips" / cid / "meta.yaml"
    return yaml.safe_load("\n".join(l for l in p.read_text().split("\n")
                                    if not l.startswith("#"))) or {}


def verdict_series(cid: str, model: str):
    d = ROOT / "runs" / "stream" / cid
    f = d / f"{model}.jsonl"
    if not f.exists():
        return None
    spec = json.loads((d / "windows.json").read_text())
    rows = {}
    for line in f.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "answer" not in r:
            continue
        i = int(r["id"].split("|")[1][1:])
        rows[i] = (verdict_of(r.get("answer", "")) if r.get("ok") else None,
                   " ".join((r.get("answer") or "").split()))
    return [(w["t_end"], *rows.get(w["i"], (None, ""))) for w in spec["windows"]
            if w["i"] in rows]


def state_at(series, t: float):
    seen = [s for s in series if s[0] <= t + 1e-6]
    return (seen[-1][1], seen[-1][2]) if seen else (None, "")


def scrim(img, y0, y1, a=170, fade=0):
    """Flat band, or a band that fades out over `fade` px.

    A flat 170-alpha band is invisible over a bright scene: the shattered jar sits
    on a near-white background and white text on it could not be read at all. The
    band is opaque where the text is and fades into the picture, so the overlay is
    legible on any footage without stamping a hard edge across the frame."""
    h = y1 - y0
    band = Image.new("RGBA", (W, h), (8, 10, 14, a))
    if fade:
        px = band.load()
        for y in range(max(0, h - fade), h):
            k = 1.0 - (y - (h - fade)) / fade
            for x in range(W):
                px[x, y] = (8, 10, 14, int(a * k))
    img.paste(band, (0, y0), band)


_CROP: dict[str, str] = {}


def content_crop(video: Path) -> str:
    """The picture inside the letterbox, as an ffmpeg crop expression.

    Several clips carry black pillarbox bars: the kantine recordings are 4:3
    content written into a 1280x720 file, so a third of the width is black. Under
    live.py the video was scaled down into its own band and nobody noticed; full
    bleed it is a black stripe down each side of the shot. cropdetect finds the
    real rectangle, and it is measured once per clip rather than guessed."""
    key = str(video)
    if key in _CROP:
        return _CROP[key]
    out = subprocess.run(
        ["ffmpeg", "-nostdin", "-ss", "1", "-i", str(video), "-vf",
         "cropdetect=limit=24:round=2", "-frames:v", "40", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    crops = [l.split("crop=")[-1].strip() for l in out.splitlines() if "crop=" in l]
    _CROP[key] = crops[-1] if crops else ""
    return _CROP[key]


def render_beat(beat: dict, workdir: Path, idx: int) -> list[Path]:
    cid = beat["clip"]
    mt = meta(cid)
    spec = json.loads((ROOT / "runs" / "stream" / cid / "windows.json").read_text())
    models = beat.get("models") or []
    series = {m: verdict_series(cid, m) for m in models}
    series = {m: s for m, s in series.items() if s}

    t0, t1 = float(beat["t0"]), float(beat["t1"])
    n = max(1, int((t1 - t0) * FPS))
    raw = workdir / f"raw{idx:03d}"
    raw.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t0:.2f}",
         "-i", str(ROOT / "clips" / cid / "clip.mp4"), "-t", f"{t1 - t0:.2f}",
         "-vf", (f"{'crop=' + content_crop(ROOT / 'clips' / cid / 'clip.mp4') + ',' if content_crop(ROOT / 'clips' / cid / 'clip.mp4') else ''}"
                 f"fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,"
                 f"crop={W}:{H}"),
         "-y", str(raw / "f%04d.png")], check=True)
    frames = sorted(raw.glob("f*.png"))
    out_dir = workdir / f"out{idx:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    question = spec.get("question", "")
    said_model = beat.get("say")

    # What the correct answer is at time t. For a stable clip it never changes; for
    # a transition it is No before the onset and Yes after.
    onset = mt.get("onset_s")
    expected = mt.get("expected")

    def truth_at(t: float):
        if mt.get("kind") == "stable" or expected in ("yes", "no"):
            return expected == "yes"
        if onset is None:
            return None
        return t >= float(onset)

    # When each model's answer changes inside this beat, so the chip can be lit at
    # the moment it moves. A chip that silently differs between two frames is a
    # change nobody sees; the flash is what makes it a moment.
    flip_at = {}
    for m, s in series.items():
        for (ta, va, _), (tb, vb, _) in zip(s, s[1:]):
            if va is not None and vb is not None and va != vb and t0 <= tb <= t1:
                flip_at.setdefault(m, tb)
    outs = []
    for k in range(n):
        t = t0 + k / FPS
        img = Image.open(frames[min(k, len(frames) - 1)]).convert("RGB")
        d = ImageDraw.Draw(img, "RGBA")

        scrim(img, 0, 128, 216, fade=40)
        d.text((44, 18), (beat.get("kicker") or mt.get("genre") or mt.get("event") or "").upper(),
               font=F_KICK, fill=ACCENT)
        d.text((44, 44), question, font=F_Q, fill=(246, 248, 252))

        # verdict chips, bottom-left, stacked
        n_rows = sum(1 for m in models if m in series)
        y = H - 40 - 38 * n_rows
        scrim(img, max(0, y - 16), H, 190)
        for m in models:
            if m not in series:
                continue
            v, _ = state_at(series[m], t)
            want = truth_at(t)
            lab = "YES" if v is True else "NO" if v is False else "—"
            col = (WAIT if v is None or want is None
                   else RIGHT if v is want else WRONG)
            name = m.replace("lfm2.5-vl-", "LFM ").replace("-vl-", " ").replace("-", " ")
            ft = flip_at.get(m)
            fresh = ft is not None and 0 <= t - ft <= 0.5
            d.rounded_rectangle([44, y, 44 + 76, y + 31], 7, fill=col)
            if fresh:
                d.rounded_rectangle([41, y - 3, 44 + 79, y + 34], 9,
                                    outline=(255, 255, 255), width=3)
            tw = d.textlength(lab, font=F_CHIP)
            d.text((44 + (76 - tw) / 2, y + 3), lab, font=F_CHIP, fill=(10, 12, 16))
            d.text((132, y + 6), name, font=F_NAME,
                   fill=(255, 255, 255) if fresh else (236, 240, 248))
            y += 38

        # The true moment, marked. Without it a viewer can see the chips move but
        # has no way to judge whether a model was early, late or right — which is
        # the whole question. Shown for half a second either side of the onset.
        if onset is not None and mt.get("kind") != "stable":
            on = float(onset)
            if t0 <= on <= t1 and -0.2 <= t - on <= 1.1:
                lab = (mt.get("moment") or "THE EVENT").upper()
                lw = d.textlength(lab, font=F_KICK)
                bx = W - 60 - lw - 26
                d.rounded_rectangle([bx, 150, bx + lw + 26, 182], 7,
                                    fill=(250, 250, 250))
                d.text((bx + 13, 158), lab, font=F_KICK, fill=(12, 14, 18))

        if said_model and said_model in series:
            _, txt = state_at(series[said_model], t)
            txt = txt.split("\n")[0]
            if txt:
                while d.textlength(txt, font=F_SAID) > W - 500 and len(txt) > 8:
                    txt = txt[:-2]
                d.text((450, H - 46), f"“{txt}”", font=F_SAID, fill=(220, 225, 235))

        p = out_dir / f"{k:04d}.png"
        img.save(p)
        outs.append(p)
    return outs


# ── choosing beats ────────────────────────────────────────────────────────────
# The first cut of this reel was hand-picked and it was dull for two reasons that
# are really one reason: almost every chip was green, and almost every chip was
# STILL. I had chosen moments after the models had settled, so each cut showed a
# steady verdict rather than a verdict being formed.
#
# The subject of this whole benchmark is the transition — the moment a scene stops
# being ordinary and a model has to notice. A cut that does not contain a chip
# changing is not showing that. So beats are no longer chosen by taste: every
# window where any model's answer changes is a candidate, and the ones that make
# the reel are the ones where the change is worth watching.
#
# Scored on three things, in this order:
#   flips      how many models change their answer inside the beat. Zero is
#              disqualifying, whatever else is true of the shot.
#   wrong      how many are wrong at the end of it. A wall of correct answers is
#              a wall of green and tells a viewer nothing they will remember.
#   split      whether the models disagree with each other when the beat ends.
def flip_beats(models, lead=2.5, tail=4.5, per_clip=1):
    """Every moment a chip changes, ranked. One beat per clip by default."""
    out = []
    for d in sorted((ROOT / "runs" / "stream").iterdir()):
        cid = d.name
        wj = d / "windows.json"
        mp = ROOT / "clips" / cid / "meta.yaml"
        if not wj.exists() or not mp.exists():
            continue
        mt = meta(cid)
        if mt.get("label") == "rejected":
            continue
        spec = json.loads(wj.read_text())
        have = {m: verdict_series(cid, m) for m in models}
        have = {m: s for m, s in have.items() if s}
        if len(have) < 3:
            continue
        onset = mt.get("onset_s")
        expected = mt.get("expected")

        def truth(t):
            if expected in ("yes", "no"):
                return expected == "yes"
            return None if onset is None else t >= float(onset)

        cand = []
        for m, s in have.items():
            for (t0, v0, _), (t1, v1, _) in zip(s, s[1:]):
                if v0 is None or v1 is None or v0 == v1:
                    continue
                cand.append(t1)
        for t in sorted(set(cand)):
            # Anchor on the EVENT, not on the model's reaction to it.
            #
            # Cutting around the moment a chip moved kept clipping the event
            # itself: a person takes two or three seconds to walk into a corridor,
            # a spill spreads for several more, and a model may flip near the end
            # of that or before it starts. Centring on the model put the thing
            # being judged half outside the frame. The onset is the real anchor and
            # the model's flip is then visible wherever it falls, early or late,
            # which is the comparison the reel exists to show.
            anchor = float(onset) if onset is not None else t
            a, b = max(0.0, anchor - lead), anchor + tail
            if not (a <= t <= b):
                continue
            if b > spec["duration_s"]:
                continue
            flips = sum(1 for m, s in have.items()
                        if state_at(s, a)[0] is not None
                        and state_at(s, a)[0] != state_at(s, b)[0])
            end = [state_at(s, b)[0] for s in have.values()]
            want = truth(b)
            wrong = sum(1 for v in end if v is not None and want is not None and v is not want)
            split = len({v for v in end if v is not None}) > 1
            if flips == 0:
                continue
            out.append(dict(clip=cid, t0=round(a, 2), t1=round(b, 2),
                            models=[m for m in models if m in have],
                            _score=(flips, wrong, int(split)), _t=t,
                            kicker=(mt.get("genre") or mt.get("event") or "")))
    # Ranking on flips alone hands the whole reel to one rig. Twelve of the first
    # eighteen beats came from the same coffee-pouring robot, plus its own mirror
    # and its own second camera — three views of one table, which is exactly the
    # monotony the fast cut was supposed to fix. So the sort is followed by a
    # round-robin over EVENTS: the best beat from each event, then the second best
    # from each, and so on. A reel of twelve different worlds beats a reel of the
    # twelve sharpest moments when eleven of them are the same table.
    out.sort(key=lambda b: (-b["_score"][0], -b["_score"][1], -b["_score"][2]))
    out = [b for b in out if not b["clip"].endswith(("-mir", "-v2"))]

    by_event: dict[str, list] = {}
    for b in out:
        by_event.setdefault(meta(b["clip"]).get("event") or "?", []).append(b)
    picked, seen_clip, round_i = [], {}, 0
    while any(len(v) > round_i for v in by_event.values()):
        for ev in sorted(by_event, key=lambda e: -len(by_event[e])):
            lst = by_event[ev]
            if len(lst) <= round_i:
                continue
            b = lst[round_i]
            if seen_clip.get(b["clip"], 0) >= per_clip:
                continue
            seen_clip[b["clip"]] = seen_clip.get(b["clip"], 0) + 1
            picked.append(b)
        round_i += 1
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--beats", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--auto", type=int, default=0, help="pick N beats automatically")
    ap.add_argument("--models", default="lfm2.5-vl-3b,holo2-4b,north-micro-vision,qwen3-vl-2b")
    ap.add_argument("--dump", type=Path, default=None, help="write the chosen beats here")
    args = ap.parse_args()
    if args.auto:
        ms = [m.strip() for m in args.models.split(",") if m.strip()]
        beats = flip_beats(ms)[: args.auto]
        for b in beats:
            print(f"  {b['clip']:<28} {b['t0']:>5}-{b['t1']:<5} "
                  f"flips={b['_score'][0]} wrong={b['_score'][1]} split={b['_score'][2]}")
        if args.dump:
            args.dump.write_text(json.dumps(beats, indent=1))
    else:
        beats = json.loads(args.beats.read_text())

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        allf = []
        for i, b in enumerate(beats):
            allf += render_beat(b, td, i)
            print(f"  beat {i+1}/{len(beats)}  {b['clip']}  {b['t0']}-{b['t1']}s")
        seq = td / "seq"
        seq.mkdir()
        for j, f in enumerate(allf):
            (seq / f"{j:05d}.png").symlink_to(f)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-framerate", str(FPS),
             "-i", str(seq / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "20", "-y", str(args.out)], check=True)
    dur = len(allf) / FPS
    print(f"wrote {args.out}  {dur:.1f}s, {len(beats)} beats")


if __name__ == "__main__":
    main()
