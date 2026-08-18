#!/usr/bin/env python3
"""Real footage + one controlled change at a known time = a transition clip.

The events a monitoring system is actually bought for are **transitions**: the
scene was normal, then it was not. A clip of a building already alight in frame
one does not test that at all — it tests "is there fire in this image", which is
a single-frame state question wearing a video costume. Half this benchmark's
first corpus had that flaw, and F6 explains why: nobody films the moment a line
jams or a part goes missing, so those clips cannot be sourced.

So they are staged. A static-camera stock clip supplies the *before* state, and
one change is composited in at a known frame. What that buys is a pair that no
amount of sourcing could:

    the negative is the same clip, unmodified.

Background, lighting, camera, grain, compression and duration are byte-identical
between the two halves. The only difference is the event. Nothing else can be the
cue — which is exactly the ablation a matched pair is supposed to be and never
quite is with two separately-shot clips.

Transitions, each mapping to an event the corpus could not otherwise cover:

  freeze   the scene runs, then holds still      -> line-stopped  (the dwell case)
  vanish   a region is patched with clean background from time T
                                                 -> part-missing, object-removed
  appear   a patch cropped from the scene is placed somewhere new
                                                 -> object-abandoned, foreign object
  drift    a region darkens or discolours over a ramp
                                                 -> damage, stain, scorch

These are labelled `tier: staged` and are never called field footage. The honest
caveat is on every clip: a composite can leave an edge a real event would not
have, so a model that beats these may be reading the seam. `--check` renders a
difference map so that seam can at least be looked at.

usage:
  stage.py --probe clips/line-stopped-31818733     # grid overlay to pick coordinates
  stage.py --base clips/line-stopped-31818733 --event line-stopped \\
           --transition freeze --at 3.0 --duration 6
  stage.py --base clips/X --event part-missing --transition vanish \\
           --at 3.0 --rect 520,300,120,90 --from 300,300 --duration 6
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml
from PIL import Image, ImageChops, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent

# What a staged transition means for each event, written onto the clip so the
# ground truth is never reconstructed from the transition name later.
EVENT_TEXT = {
    "freeze": ("The machinery runs normally for the first part of the clip and then "
               "holds completely still for the rest. A running line that stops."),
    "vanish": ("An item present in the earlier panels is gone from its position in the "
               "later ones, with nothing else in the scene changing."),
    "appear": ("An item that is not in the earlier panels is present in the later ones, "
               "sitting where it does not belong."),
    "drift": ("A region of the scene darkens and discolours progressively across the "
              "clip, as a scorch, stain or spreading defect would."),
}
CONTROL_TEXT = ("The same clip, unmodified: the scene continues normally throughout. "
                "Background, lighting, camera, grain and duration are identical to the "
                "positive it pairs with — the composited change is the only difference.")


def probe(v: Path) -> tuple[float, int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
         "stream=width,height:format=duration", "-of", "json", str(v)],
        capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    return float(j["format"]["duration"]), int(j["streams"][0]["width"]), \
        int(j["streams"][0]["height"])


def grab(v: Path, t: float, out: Path) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{t:.3f}", "-i", str(v),
                    "-frames:v", "1", "-y", str(out)], check=True)


def do_probe(base: Path) -> None:
    """A frame with a coordinate grid, so rects can be picked by eye."""
    v = base / "clip.mp4"
    dur, w, h = probe(v)
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "f.png"
        grab(v, dur * 0.2, f)
        im = Image.open(f).convert("RGB")
        d = ImageDraw.Draw(im, "RGBA")
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 20)
        except OSError:
            font = ImageFont.load_default(20)
        step = 100
        for x in range(0, w, step):
            d.line([(x, 0), (x, h)], fill=(0, 255, 255, 110), width=1)
            d.text((x + 4, 4), str(x), font=font, fill=(0, 255, 255))
        for y in range(0, h, step):
            d.line([(0, y), (w, y)], fill=(0, 255, 255, 110), width=1)
            d.text((4, y + 4), str(y), font=font, fill=(0, 255, 255))
        out = base / "probe.png"
        im.save(out)
    print(f"wrote {out}  ({w}x{h}, {dur:.2f}s)")


def render_freeze(src: Path, at: float, dur: float, out: Path, work: Path) -> None:
    """Cut at `at`, then hold the frame for the remainder.

    Two passes rather than one filter_complex: a concat of two encoded segments is
    trivially verifiable, and the still half is re-encoded at the same settings so
    its grain and blocking match the moving half."""
    head, still, tail = work / "head.mp4", work / "still.png", work / "tail.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
                    "-t", f"{at:.3f}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-crf", "18", "-an", str(head)], check=True)
    grab(src, at, still)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-loop", "1",
                    "-i", str(still), "-t", f"{dur - at:.3f}", "-r", "25",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", str(tail)],
                   check=True)
    listing = work / "parts.txt"
    listing.write_text(f"file '{head.resolve()}'\nfile '{tail.resolve()}'\n")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(listing), "-c", "copy", str(out)], check=True)


def render_overlay(src: Path, patch: Path, x: int, y: int, at: float, ramp: float,
                   dur: float, out: Path) -> None:
    """Composite a still patch in from time `at`, optionally fading over `ramp`."""
    if ramp > 0:
        chain = (f"[1:v]format=rgba,fade=t=in:st={at:.3f}:d={ramp:.3f}:alpha=1[p];"
                 f"[0:v][p]overlay={x}:{y}:shortest=1[v]")
    else:
        chain = f"[0:v][1:v]overlay={x}:{y}:enable='gte(t,{at:.3f})'[v]"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
                    "-loop", "1", "-i", str(patch), "-filter_complex", chain,
                    "-map", "[v]", "-t", f"{dur:.3f}", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "18", "-an", str(out)], check=True)


def feather(im: Image.Image, px: int = 6) -> Image.Image:
    """Soften the patch edge. A hard rectangle is a seam any model could learn;
    it does not make the event easier to see, only easier to cheat."""
    from PIL import ImageFilter
    rgba = im.convert("RGBA")
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rectangle([px, px, im.width - px, im.height - px], fill=255)
    rgba.putalpha(mask.filter(ImageFilter.GaussianBlur(px * 0.8)))
    return rgba


def blot(size: tuple[int, int], tint: tuple[int, int, int],
         peak: float = 0.62) -> Image.Image:
    """A soft, irregular, radially-falling-off stain.

    The first version of `drift` composited an opaque rectangle and produced a
    black box — which a model could detect trivially and a human would never call
    a defect. A real scorch or stain has no edge: it is densest at its centre and
    fades to nothing, and its outline is not a shape anyone would draw. This
    builds that: an elliptical radial gradient, its radius modulated per-angle so
    the boundary is ragged, capped well below full opacity so the surface texture
    underneath still shows through."""
    import math
    from PIL import ImageFilter
    w, h = size
    alpha = Image.new("L", size, 0)
    px = alpha.load()
    cx, cy = w / 2, h / 2
    # A few harmonics give a lobed outline without looking like a flower.
    phases = [(2, 0.13, 0.7), (3, 0.09, 2.1), (5, 0.05, 4.0)]
    for y in range(h):
        for x in range(w):
            dx, dy = (x - cx) / max(1e-6, cx), (y - cy) / max(1e-6, cy)
            r = math.hypot(dx, dy)
            if r >= 1.35:
                continue
            ang = math.atan2(dy, dx)
            wobble = 1.0 + sum(a * math.sin(k * ang + ph) for k, a, ph in phases)
            rr = r / max(0.4, wobble)
            if rr >= 1.0:
                continue
            px[x, y] = int(255 * peak * (1.0 - rr) ** 1.6)
    alpha = alpha.filter(ImageFilter.GaussianBlur(max(3, min(w, h) * 0.05)))
    out = Image.new("RGBA", size, tint + (0,))
    out.putalpha(alpha)
    return out


def write_meta(out_dir: Path, clip_id: str, event: str, label: str, pair: str,
               dur: float, onset: float | None, base_id: str, transition: str,
               base_meta: dict, note: str) -> None:
    meta = {
        "id": clip_id, "tier": "staged", "event": event, "label": label,
        "pair": pair, "onset_s": onset, "duration_s": round(dur, 2),
        "ground_truth": note,
        "staged": {"base_clip": base_id, "transition": transition,
                   "at_s": onset,
                   "caveat": ("Composited, not filmed. A model that scores here may be "
                              "reading a compositing seam rather than the event; the "
                              "patch edge is feathered and tools/stage.py --check "
                              "renders a difference map for inspection.")},
        "source": base_meta.get("source", {}),
        "conditions": base_meta.get("conditions", {}),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "meta.yaml").write_text(
        f"# STAGED from {base_id} by tools/stage.py ({transition}).\n"
        f"# Its pair is the same footage unmodified, so the composited change is the\n"
        f"# only difference between the two halves.\n"
        + yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=88))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", type=Path, default=None)
    ap.add_argument("--check", type=Path, default=None,
                    help="staged clip dir; renders a difference map vs its control")
    ap.add_argument("--base", type=Path, default=None)
    ap.add_argument("--event", default=None)
    ap.add_argument("--transition", default=None,
                    choices=["freeze", "vanish", "appear", "drift"])
    ap.add_argument("--at", type=float, default=3.0, help="seconds; when it changes")
    ap.add_argument("--duration", type=float, default=6.0)
    ap.add_argument("--start", type=float, default=0.0, help="trim the base from here")
    ap.add_argument("--rect", default=None, help="X,Y,W,H — the region that changes")
    ap.add_argument("--from", dest="from_xy", default=None,
                    help="X,Y — clean background to sample (vanish)")
    ap.add_argument("--to", dest="to_xy", default=None,
                    help="X,Y — where to place it (appear)")
    ap.add_argument("--ramp", type=float, default=0.0, help="seconds to fade in")
    ap.add_argument("--tint", default="18,14,10", help="R,G,B for drift")
    ap.add_argument("--suffix", default="", help="disambiguate multiple stagings")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")

    if args.probe:
        return do_probe(args.probe)

    if args.check:
        d = args.check
        meta = yaml.safe_load((d / "meta.yaml").read_text())
        ctrl = ROOT / "clips" / meta["pair"]
        with tempfile.TemporaryDirectory() as td:
            a, b = Path(td) / "a.png", Path(td) / "b.png"
            dur = probe(d / "clip.mp4")[0]
            grab(d / "clip.mp4", dur * 0.9, a)
            grab(ctrl / "clip.mp4", dur * 0.9, b)
            diff = ImageChops.difference(Image.open(a).convert("RGB"),
                                         Image.open(b).convert("RGB"))
            out = d / "diff.png"
            diff.point(lambda v: min(255, v * 4)).save(out)
        print(f"wrote {out} — anything bright is what the staging changed")
        return

    if not (args.base and args.event and args.transition):
        raise SystemExit("give --base, --event and --transition (or --probe / --check)")

    base_meta = yaml.safe_load((args.base / "meta.yaml").read_text())
    base_id = args.base.name
    src_full = args.base / "clip.mp4"
    dur_full, w, h = probe(src_full)
    if args.start + args.duration > dur_full + 0.05:
        raise SystemExit(f"{args.start}+{args.duration}s exceeds the {dur_full:.2f}s source")

    stem = f"{args.event}-staged-{base_id.split('-')[-1]}{args.suffix}"
    pos_dir = ROOT / "clips" / stem
    neg_dir = ROOT / "clips" / f"{stem}-control"

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        # The control is cut first and everything is staged from it, so both halves
        # share one encode of the source rather than two.
        control = work / "control.mp4"
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y",
                        "-ss", f"{args.start:.3f}", "-i", str(src_full),
                        "-t", f"{args.duration:.3f}", "-c:v", "libx264",
                        "-pix_fmt", "yuv420p", "-crf", "18", "-an", str(control)],
                       check=True)
        staged = work / "staged.mp4"

        if args.transition == "freeze":
            render_freeze(control, args.at, args.duration, staged, work)
        else:
            if not args.rect:
                raise SystemExit(f"--rect is required for {args.transition}")
            rx, ry, rw, rh = (int(v) for v in args.rect.split(","))
            frame = work / "f.png"
            grab(control, max(0.0, args.at - 0.2), frame)
            im = Image.open(frame).convert("RGB")

            if args.transition == "vanish":
                if not args.from_xy:
                    raise SystemExit("--from X,Y is required for vanish")
                fx, fy = (int(v) for v in args.from_xy.split(","))
                patch = im.crop((fx, fy, fx + rw, fy + rh))
                px, py = rx, ry
            elif args.transition == "appear":
                if not args.to_xy:
                    raise SystemExit("--to X,Y is required for appear")
                patch = im.crop((rx, ry, rx + rw, ry + rh))
                px, py = (int(v) for v in args.to_xy.split(","))
            else:  # drift
                tint = tuple(int(v) for v in args.tint.split(","))
                patch = blot((rw, rh), tint)
                px, py = rx, ry

            patch_path = work / "patch.png"
            (patch if args.transition == "drift" else feather(patch)).save(patch_path)
            ramp = args.ramp if args.ramp else (1.6 if args.transition == "drift" else 0.0)
            render_overlay(control, patch_path, px, py, args.at, ramp,
                           args.duration, staged)

        pos_dir.mkdir(parents=True, exist_ok=True)
        neg_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(staged, pos_dir / "clip.mp4")
        shutil.copy(control, neg_dir / "clip.mp4")

    write_meta(pos_dir, stem, args.event, "positive", neg_dir.name, args.duration,
               args.at, base_id, args.transition, base_meta,
               EVENT_TEXT[args.transition])
    write_meta(neg_dir, neg_dir.name, args.event, "negative", stem, args.duration,
               None, base_id, f"{args.transition}-control", base_meta, CONTROL_TEXT)
    # `negative_hardness` is not a judgement call here: identical background makes
    # this the hardest negative the corpus can contain.
    m = yaml.safe_load((neg_dir / "meta.yaml").read_text())
    m["negative_hardness"] = "hard"
    (neg_dir / "meta.yaml").write_text(
        f"# STAGED control for {stem}: the same footage, unmodified.\n"
        + yaml.safe_dump(m, sort_keys=False, allow_unicode=True, width=88))

    print(f"{stem}  (+{neg_dir.name})  {args.transition} at {args.at}s, "
          f"{args.duration}s from {base_id}")


if __name__ == "__main__":
    main()
