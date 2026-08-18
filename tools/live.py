#!/usr/bin/env python3
"""The clip, playing normally, with the models' verdicts changing live underneath.

This is the view that answers "what does the AI see, and when does it decide?".
The footage runs at real speed and full size; below it each model has a status
chip and a timeline that fills in as the playhead moves. Nothing is decomposed
into panels on screen — the panels are what the model gets, not what the viewer
needs.

The honest mechanic, and the reason this measures something the rest of the repo
does not: a window ending at time t is all the model has at time t. It cannot see
the future. So the chip at time t shows the verdict of the most recent window that
had already ended, which means the delay between the true onset marker and the
moment the strip turns red **is the detection latency**, on screen, in seconds.

Colour is monitoring-panel convention, not correctness: green is "clear", red is
"alarm". Whether an alarm was right is judged against the onset marker and the
ground-truth line — which is the judgement a person watching should be making.

usage:
  live.py --stream runs/stream/fall-7644974 --out cards/live-fall.mp4
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import textwrap
from collections import defaultdict
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from card import verdict_of  # noqa: E402
from reel import W, H, FPS, BG, FG, DIM, ACCENT, font  # noqa: E402

# Three states, three colours. WAIT and NOANSWER were the same grey in the first
# version, which made "the model has not been asked yet" indistinguishable from
# "the model failed to answer" — a viewer cannot read the panel without that split.
CLEAR = (58, 190, 120)      # the model answered No
ALARM = (240, 84, 76)       # the model answered Yes
WAIT = (74, 80, 92)         # no window has closed yet, so nothing has been asked
NOANSWER = (198, 158, 70)   # asked, but the reply had no extractable yes/no

F_KICK = font("bold", 15)
F_Q = font("bold", 33)
F_MODEL = font("bold", 18)
F_CHIP = font("bold", 16)
F_SMALL = font("reg", 14)
F_NOTE = font("reg", 17)

# The status panel grows with the number of model rows. It was a constant sized for
# five, and a six-model card silently drew the last row on top of the ground-truth
# line — the two-camera comparison is the first card with six, and the collision is
# only visible if you look at a frame rather than trusting that it rendered.
ROW_H = 35
ROW_H_SAID = 58        # with the model's own sentence drawn under its row
PANEL_CHROME = 258 - 5 * ROW_H   # header, legend, timeline margins, ground-truth line


def panel_height(n_models: int, said: bool = False) -> int:
    return PANEL_CHROME + max(4, n_models) * (ROW_H_SAID if said else ROW_H)


TL_X0, TL_X1 = 430, W - 196  # timeline extent; latency sits to its right


_LEAD = re.compile(r"^\s*(yes|no)\b[\.,:;]?\s*", re.I)
_LABEL = re.compile(r"^(evidence|reason)\s*[:\-]\s*", re.I)


def evidence(answer: str) -> str:
    """The sentence after the verdict token, whitespace-normalised."""
    a = _LEAD.sub("", (answer or "").strip(), count=1)
    return " ".join(_LABEL.sub("", a).strip().split())


def scrim(img: Image.Image, top: int, bottom: int, a: int = 220) -> None:
    band = Image.new("RGBA", (W, bottom - top), (10, 12, 16, a))
    img.paste(band, (0, top), band)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", type=Path, required=True, help="runs/stream/<clip>")
    ap.add_argument("--models", type=Path, default=ROOT / "events" / "models.yaml")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--tail", type=float, default=1.6, help="seconds held on the last frame")
    ap.add_argument("--said", action="store_true",
                    help="draw each model's own sentence of evidence under its row")
    ap.add_argument("--tag", default=None,
                    help="segment label for a continuous reel, e.g. '3/12 · fall'")
    args = ap.parse_args()

    spec = json.loads((args.stream / "windows.json").read_text())
    model_meta = {m["id"]: m for m in yaml.safe_load(args.models.read_text())["models"]}
    clip_dir = ROOT / "clips" / spec["clip"]
    duration = spec["duration_s"]
    onset = spec.get("onset_s")
    truth = spec["label"] == "positive"

    # verdicts[model] = list of (t_end, verdict)
    verdicts: dict[str, list[tuple[float, bool | None]]] = {}
    # The prompt asks for a verdict AND a sentence of evidence. The sentence was on
    # disk from the first run and unread for weeks; it is what a viewer can actually
    # check, so it belongs on screen next to the bar it explains.
    said: dict[str, dict[int, str]] = defaultdict(dict)
    for p in sorted(args.stream.glob("*.jsonl")):
        # A stream directory holds more than verdicts: `tasks.jsonl` is the input,
        # `frames.jsonl` is the detector's input, and `detect-*.jsonl` is raw boxes
        # keyed per FRAME, not per window. Those rows carry no "answer" and their
        # ids have two fields rather than three, so they are skipped by shape
        # below — but naming them here keeps the failure legible if that changes.
        if p.name in {"tasks.jsonl", "frames.jsonl"} or p.name.startswith("detect-"):
            continue
        rows = {}
        model = None
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if "model" not in r or "answer" not in r:
                continue
            parts = r["id"].split("|")
            if len(parts) != 3:
                continue
            model = r["model"]
            wid = int(parts[1][1:])
            rows[wid] = verdict_of(r.get("answer", "") if r.get("ok") else "")
            said[model][wid] = evidence(r.get("answer", "")) if r.get("ok") else ""
        if model:
            verdicts[model] = [(w["t_end"], rows.get(w["i"]), said[model].get(w["i"], ""))
                               for w in spec["windows"] if w["i"] in rows]
    if not verdicts:
        raise SystemExit(f"no results in {args.stream}")
    models = sorted(verdicts, key=lambda m: model_meta.get(m, {}).get("size_mb", 0))

    # Latency is only readable if several windows fall ENTIRELY before the event.
    # fall-5916779 has 3.3s of lead-in against a 1.6s window, so one window closes
    # before the fall and a "-1.3s" reading says nothing about the model. Where the
    # cut cannot supply more lead-in (handover-4440917's source is 4.0s in total,
    # parcel-pass is continuous from frame one) the honest fix is to put the caveat
    # on screen rather than let the number be read as a measurement.
    pre_windows = (sum(1 for w in spec["windows"] if w["t_end"] <= (onset or 0))
                   if onset is not None else None)
    short_lead = onset is not None and pre_windows < 3

    # First alarm per model, for the latency readout.
    first_alarm = {m: next((t for t, v, _ in verdicts[m] if v is True), None)
                   for m in models}

    def state_at(m: str, t: float):
        """The most recent window that had already ENDED at time t. Before the
        first one there is not enough history and the panel says so."""
        seen = [r for r in verdicts[m] if r[0] <= t + 1e-6]
        return (seen[-1][1], seen[-1][2]) if seen else ("wait", "")

    total = duration + args.tail
    n = int(total * FPS)
    vid_top = 0

    # The video gets whatever the panel does not take, so it is never covered.
    # Even height, or ffmpeg's scale/pad chain fails outright: a 6-model card with
    # sentences leaves 289 rows and dies with exit 234 rather than anything legible.
    vid_h = (H - panel_height(len(models), args.said)) // 2 * 2

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-i", str(clip_dir / "clip.mp4"),
             "-vf", f"fps={FPS},scale={W}:{vid_h}:force_original_aspect_ratio=decrease,"
                    f"pad={W}:{vid_h}:(ow-iw)/2:(oh-ih)/2:color=0x0a0c10",
             "-y", str(td / "f%04d.png")], check=True)
        frames = sorted(td.glob("f*.png"))
        if not frames:
            raise SystemExit("ffmpeg produced no frames")

        out_dir = td / "out"
        out_dir.mkdir()
        panel_top = H - panel_height(len(models), args.said)

        for i in range(n):
            t = i / FPS
            img = Image.new("RGB", (W, H), (10, 12, 16))
            img.paste(Image.open(frames[min(i, len(frames) - 1)]).convert("RGB"), (0, 0))
            scrim(img, 0, 88)
            d = ImageDraw.Draw(img, "RGBA")

            kicker = "WHAT CAN AI SEE"
            if args.tag:
                kicker += f"   ·   {args.tag}"
            d.text((44, 12), kicker, font=F_KICK, fill=ACCENT)
            half = "POSITIVE" if truth else "HARD NEGATIVE  ·  the look-alike"
            hw = d.textlength(half, font=F_KICK)
            d.rounded_rectangle([W - 60 - hw - 24, 14, W - 60, 40], 5,
                                fill=(28, 58, 44) if truth else (58, 28, 28))
            d.text((W - 60 - hw - 12, 20), half, font=F_KICK,
                   fill=(120, 214, 160) if truth else (240, 140, 130))
            d.text((44, 36), spec["question"], font=F_Q, fill=FG)

            # A clock, so the viewer can read the delay off the screen.
            clk = f"{min(t, duration):4.1f}s"
            d.text((W - 60 - d.textlength(clk, font=F_Q), 44), clk,
                   font=F_Q, fill=DIM)

            y = panel_top + 12
            d.text((44, y), "LIVE VERDICT", font=F_KICK, fill=ACCENT)
            lx = TL_X0
            for col, lab in ((CLEAR, 'CLEAR = model said No'),
                             (ALARM, 'ALARM = model said Yes'),
                             (WAIT, 'not asked yet')):
                d.rounded_rectangle([lx, y - 1, lx + 13, y + 12], 3, fill=col)
                d.text((lx + 20, y - 2), lab, font=F_KICK, fill=DIM)
                lx += 20 + d.textlength(lab, font=F_KICK) + 22
            d.text((lx + 6, y - 2), f"{spec['window_s']:.1f}s window, every "
                                    f"{spec['stride_s']:.1f}s", font=F_KICK, fill=(104, 110, 122))
            y += 26

            for m in models:
                st, evid = state_at(m, t)
                if st == "wait":
                    label, col = "NOT ASKED", WAIT
                elif st is True:
                    label, col = "ALARM", ALARM
                elif st is False:
                    label, col = "CLEAR", CLEAR
                else:
                    label, col = "NO ANSWER", NOANSWER

                name = model_meta.get(m, {}).get("name", m)
                d.text((44, y + 8), name, font=F_MODEL, fill=FG)
                d.rounded_rectangle([286, y + 5, 286 + 104, y + 29], 6, fill=col)
                tw = d.textlength(label, font=F_CHIP)
                d.text((286 + (104 - tw) / 2, y + 9), label, font=F_CHIP, fill=(10, 12, 16))

                # timeline
                span = TL_X1 - TL_X0
                d.rounded_rectangle([TL_X0, y + 9, TL_X1, y + 27], 4, fill=(24, 27, 33))
                # The clip only becomes answerable once a full window has elapsed.
                span0 = (TL_X1 - TL_X0) * spec["window_s"] / duration
                d.rounded_rectangle([TL_X0, y + 9, TL_X0 + span0, y + 27], 4, fill=WAIT)
                for k, (te, v, _) in enumerate(verdicts[m]):
                    nxt = verdicts[m][k + 1][0] if k + 1 < len(verdicts[m]) else duration
                    if te > t:
                        break
                    x0 = TL_X0 + span * te / duration
                    x1 = TL_X0 + span * min(nxt, t) / duration
                    if x1 <= x0:
                        continue
                    c = ALARM if v is True else CLEAR if v is False else NOANSWER
                    d.rectangle([x0, y + 9, x1, y + 27], fill=c)

                fa = first_alarm[m]
                if fa is not None and t >= fa:
                    txt = ("(lead-in too short)" if short_lead else
                           f"{fa - onset:+.1f}s vs onset" if onset is not None
                           else f"false alarm {fa:.1f}s")
                    d.text((TL_X1 + 12, y + 10), txt, font=F_SMALL, fill=(236, 150, 144))
                if args.said:
                    # The sentence sits under its own row, full width, dim: the bar
                    # says WHAT the model answered, this says what it claims to see.
                    # Truncated rather than wrapped — two lines per model would push
                    # the video off the frame, and the first clause carries the claim.
                    txt = evid or ("\u2014 no evidence sentence; the model answered "
                                   "the verdict only" if st != "wait" else "")
                    col = (150, 156, 168) if evid else (128, 100, 60)
                    while txt and d.textlength(txt, font=F_SMALL) > W - 108:
                        txt = txt[:-2]
                        if d.textlength(txt + "\u2026", font=F_SMALL) <= W - 108:
                            txt += "\u2026"
                    d.text((60, y + ROW_H + 1), txt, font=F_SMALL, fill=col)
                y += ROW_H_SAID if args.said else ROW_H

            # onset marker + playhead, drawn over every row
            span = TL_X1 - TL_X0
            rows_top, rows_bot = panel_top + 38 + 9, y - ROW_H + 27
            if onset is not None:
                ox = TL_X0 + span * onset / duration
                d.line([(ox, rows_top - 8), (ox, rows_bot + 8)], fill=(250, 250, 250), width=2)
                d.text((ox + 6, rows_top - 24), "EVENT", font=F_KICK, fill=(250, 250, 250))
            px = TL_X0 + span * min(t, duration) / duration
            d.line([(px, rows_top - 8), (px, rows_bot + 8)], fill=ACCENT, width=2)

            if short_lead:
                warn = (f"only {pre_windows} window(s) close before the event — "
                        f"detection delay is not measurable on this cut")
                d.rounded_rectangle([44, H - 52, 44 + d.textlength(warn, font=F_SMALL) + 26,
                                     H - 30], 5, fill=(62, 46, 16))
                d.text((57, H - 48), warn, font=F_SMALL, fill=(232, 194, 108))
            gt = textwrap.shorten(" ".join(str(spec["ground_truth"]).split()), 96,
                                  placeholder=" …")
            d.text((44, H - 24), f"GROUND TRUTH  {'YES' if truth else 'NO'} — {gt}",
                   font=F_NOTE, fill=DIM)
            img.save(out_dir / f"{i:05d}.png")

        args.out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-y", "-framerate", str(FPS),
             "-i", str(out_dir / "%05d.png"), "-c:v", "libx264", "-pix_fmt", "yuv420p",
             "-crf", "19", "-movflags", "+faststart", str(args.out)], check=True)

    fired = {m: first_alarm[m] for m in models}
    print(f"wrote {args.out}  ({W}x{H}, {total:.1f}s, {len(models)} model(s))")
    for m in models:
        f = fired[m]
        if f is None:
            print(f"  {m}: never fired")
        elif onset is not None:
            print(f"  {m}: first alarm {f:.1f}s (onset {onset:.1f}s -> {f - onset:+.1f}s)")
        else:
            print(f"  {m}: first alarm {f:.1f}s (clip is a negative — false alarm)")


if __name__ == "__main__":
    main()
