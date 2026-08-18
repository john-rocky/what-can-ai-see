#!/usr/bin/env python3
"""When does something first enter the frame, and does it stay?

Onsets in this corpus were eyeballed once and it went badly: a control clip with a
spill in it was scored for hours, and a `grounds` onset written by eye at 7.0s
survived only because the frames were checked when a measurement disagreed. Every
onset since has been measured. `spill_onset.py` does that for coffee on a pale
table by colour, which works in exactly one scene.

This is the general case for the class of clip that scene-search actually yields:
a FIXED camera on an empty-ish place, and a person, forklift or vehicle enters.
The signature is colour-blind — the fraction of the frame that differs from the
opening seconds rises and stays risen:

    background = median of the first WARMUP seconds
    onset      = first frame where the changed fraction exceeds the quiet level
                 by RISE, and holds for HOLD seconds

Reported per clip alongside the quiet baseline and the peak, so the number can be
argued with. A clip whose quiet level is already high has a moving camera or a
running machine and is not a member of this class — the tool says so rather than
returning a confident wrong second.

This does NOT decide what entered, or whether the clip is worth keeping. Those
need eyes (tools/review.py). It decides WHEN, which is the part eyes are bad at.

usage:
  enter_onset.py --clips office-11903981,warehouse-4477613
  enter_onset.py --unverified --scene office
"""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parent.parent

WARMUP_S = 1.2      # seconds of clip used as "the empty scene"
PIXEL_DELTA = 25    # per-pixel intensity change counted as different
QUIET_MAX = 0.06    # above this the scene is never quiet; not this tool's class
MOVE_PX = 0.35      # median per-frame global shift, in pixels at the 480px working
                    # width, above which the camera is not on a tripod


def camera_shift(grays: list, ) -> float:
    """Median global frame-to-frame translation, in pixels.

    Phase correlation returns the rigid shift between two frames, which is what a
    pan, a dolly or a drone produces and what a person walking through a fixed
    frame does not. This exists because the changed-pixel measure below CANNOT
    tell those apart: a drone gliding down a warehouse aisle and a person walking
    toward the lens both make the frame differ more and more from its opening, and
    the first version of this tool read the drone as "a forklift enters at 0.9s".
    Camera motion has to be measured, not inferred from the thing it contaminates."""
    # Blur first. Phase correlation is sensitive to high-frequency detail, and on
    # a 1956 film scan that detail is GRAIN — every frame's grain is independent,
    # so the correlation peak wanders even when the camera is bolted down. Measured
    # raw, 31 of 33 shots from an industrial documentary read as "camera moves" at
    # 0.30-0.51 px, tightly clustered, while the frame edges plainly do not move.
    # Grain is high-frequency and a pan is a global low-frequency shift, so a
    # Gaussian kills one and leaves the other.
    shifts = []
    for a, b in zip(grays, grays[1:]):
        fa = cv2.GaussianBlur(np.float32(a), (0, 0), 2.0)
        fb = cv2.GaussianBlur(np.float32(b), (0, 0), 2.0)
        (dx, dy), _ = cv2.phaseCorrelate(fa, fb)
        shifts.append(float(np.hypot(dx, dy)))
    return float(np.median(shifts)) if shifts else 0.0


def analyse(video: Path, fps: int) -> tuple[list[float], float]:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
                        "-vf", f"fps={fps},scale=480:-2", "-y", f"{td}/f%05d.png"],
                       check=True)
        paths = sorted(Path(td).glob("f*.png"))
        grays = [cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2GRAY) for p in paths]
    if len(grays) < 6:
        return [], 0.0
    move = camera_shift(grays)
    n_warm = max(3, int(WARMUP_S * fps))
    bg = np.median(np.stack(grays[:n_warm]), axis=0).astype(np.uint8)
    k = np.ones((3, 3), np.uint8)
    out = []
    for g in grays:
        d = (cv2.absdiff(g, bg) > PIXEL_DELTA).astype(np.uint8) * 255
        d = cv2.morphologyEx(d, cv2.MORPH_OPEN, k, iterations=1)
        out.append(float((d > 0).sum()) / d.size)
    return out, move


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default=None, help="comma-separated clip ids")
    ap.add_argument("--scene", default=None, help="every clip whose id starts with this")
    ap.add_argument("--unverified", action="store_true")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--rise", type=float, default=0.02,
                    help="fraction of frame that must change over the quiet level")
    ap.add_argument("--hold", type=float, default=1.0, help="seconds it must stay up")
    ap.add_argument("--all-edges", action="store_true",
                    help="report EVERY quiet->busy transition, not just the first. "
                         "Stock clips are cut to open on the action, so the first "
                         "edge usually has no lead-in; a later one often does, and "
                         "the trim window is ours to choose.")
    ap.add_argument("--lead", type=float, default=2.8,
                    help="seconds of quiet an edge needs before it to be usable "
                         "(three 1.6s windows at a 0.4s stride)")
    args = ap.parse_args()

    ids = [c.strip() for c in (args.clips or "").split(",") if c.strip()]
    if args.scene or args.unverified:
        for d in sorted((ROOT / "clips").iterdir()):
            if not (d / "meta.yaml").exists():
                continue
            if args.scene and not d.name.startswith(args.scene):
                continue
            y = yaml.safe_load("\n".join(
                l for l in (d / "meta.yaml").read_text().split("\n")
                if not l.startswith("#"))) or {}
            if args.unverified and str(y.get("label")) != "UNVERIFIED":
                continue
            ids.append(d.name)
    ids = list(dict.fromkeys(ids))
    if not ids:
        raise SystemExit("no clips matched")

    print(f"{'clip':<28}{'camera':>8}{'quiet':>8}{'peak':>8}{'onset':>8}  verdict")
    print("-" * 92)
    for cid in ids:
        v = ROOT / "clips" / cid / "clip.mp4"
        if not v.exists():
            print(f"{cid:<28}  missing")
            continue
        s, move = analyse(v, args.fps)
        if not s:
            print(f"{cid:<28}  too short")
            continue
        quiet = float(np.median(s[: max(3, int(WARMUP_S * args.fps))]))
        peak = max(s)
        if move > MOVE_PX:
            print(f"{cid:<28}{move:>8.2f}{quiet:>8.3f}{peak:>8.3f}{'—':>8}  "
                  f"CAMERA MOVES — no onset is measurable from a moving frame")
            continue
        if quiet > QUIET_MAX:
            print(f"{cid:<28}{move:>8.2f}{quiet:>8.3f}{peak:>8.3f}{'—':>8}  "
                  f"busy from the first second — a running machine, not an entry")
            continue
        need = int(args.hold * args.fps)
        hot = [x >= quiet + args.rise for x in s]
        edges = []
        for i in range(len(s) - need):
            if all(hot[i:i + need]) and (i == 0 or not hot[i - 1]):
                edges.append((i / args.fps, "in"))
        # Leaving is a FALLING edge and the first version of this tool could not see
        # one: on a clip where a woman stands in a doorway and then walks out, it
        # reported an onset of 1.7s (her moving) and missed the exit at 11s entirely.
        # "Did the object go away" is object-removed and entry-exit, both named in
        # the brief, so the mirror case is not optional.
        for i in range(need, len(s) - need):
            if all(hot[i - need:i]) and not any(hot[i:i + need]):
                edges.append((i / args.fps, "out"))
        edges.sort()
        if args.all_edges:
            usable = []
            for e, kind in edges:
                lead_from = max(0.0, e - args.lead)
                quiet_before = all(not h for h in hot[int(lead_from * args.fps):
                                                      max(0, int(e * args.fps) - 1)])
                # an exit needs a settled BEFORE too, but its before is the busy half
                ok = (e >= args.lead) and (quiet_before if kind == "in" else True)
                if ok:
                    usable.append(f"{e:.1f}s {kind}")
            tag = (f"{len(edges)} edge(s): " +
                   ", ".join(f"{e:.1f}s {k}" for e, k in edges[:6]) +
                   (f"  | USABLE: " + ", ".join(usable) if usable else
                    "  | none has enough settled time before it"))
            print(f"{cid:<28}{move:>8.2f}{quiet:>8.3f}{peak:>8.3f}{'':>8}  {tag}")
            continue
        onset = edges[0][0] if edges else None
        if onset is None:
            verdict = "nothing enters and stays — usable as QUIET footage"
        elif onset <= WARMUP_S:
            verdict = "occupied from the start — no clean before"
        else:
            verdict = f"something enters at {onset:.1f}s and holds"
        print(f"{cid:<28}{move:>8.2f}{quiet:>8.3f}{peak:>8.3f}"
              f"{(f'{onset:.1f}s' if onset is not None else '—'):>8}  {verdict}")


if __name__ == "__main__":
    main()
