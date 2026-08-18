#!/usr/bin/env python3
"""Classical baselines on the same windows the VLMs answered.

The point of this file is to make one claim falsifiable: that the four events a
small VLM can actually do — glass shattering, a hand entering a machine, a liquid
spill, a spill of grounds — are all large appearance changes that a 1995
frame-differencer would also catch. That claim has been repeated in the findings
without ever being tested. If a background subtractor with one threshold matches
the 3B, the VLM added nothing and the headline changes.

Object detection alone cannot do this and that is part of the answer. COCO has no
class for "spill", "broken glass" or "heap of coffee grounds", so a detector can
only be turned into an anomaly detector by bolting a hand-written rule onto it
(a danger polygon, a class filter). The classical side therefore needs a
DIFFERENT pipeline per event and per-scene configuration, while the VLM took the
same one-sentence question across all four. That configuration cost is a result,
so every knob this file exposes is written into the output.

Two baselines, deliberately in order of how little they assume:

  bgdiff   MOG2 background subtraction. Alarm when the persistently-changed area
           exceeds a fraction of frame. Knobs: one area threshold. No labels, no
           training, no geometry.
  zone     Same, restricted to a hand-drawn polygon — the standard industrial
           intrusion rule, minus the detector. Knobs: threshold + polygon.

The negatives here are NOT static: the robot arm moves throughout every one of
them. So this is not a test of "did pixels change" — it is a test of whether
pixel change can separate "the arm moved" from "coffee is on the table". That is
exactly the distinction the VLM is claimed to add.

Verdicts are emitted in the same JSONL shape wcas-run produces, so score.py and
live.py read them with no special-casing and a baseline appears as one more row
on the timeline.

usage:
  baseline.py --stream runs/stream/spill-pos --method bgdiff --area 0.02
  baseline.py --stream runs/stream/hazard-hand-pos --method zone \
              --polygon 300,80,950,80,950,430,300,430
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent

# A fixed camera does not need an adaptive background model — it needs a picture
# of the empty scene. The median of the opening frames is exactly that, and it is
# what a 1995 system would have used. The first attempt here used MOG2 and scored
# windows before it had converged, which reported the whole frame as foreground
# and made the baseline look absurd. A strawman baseline would flatter the VLM,
# so this is the stronger method, given its best threshold by sweep.
WARMUP_S = 1.5      # seconds of clip used to build the background
PIXEL_DELTA = 25    # per-pixel intensity change counted as "different"


def frames_of(video: Path, fps: int, workdir: Path) -> list[Path]:
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
         "-vf", f"fps={fps},scale=480:-2", "-y", str(workdir / "f%05d.png")], check=True)
    return sorted(workdir.glob("f*.png"))


def polygon_mask(shape, poly, src_w: int) -> np.ndarray:
    """Polygon in ORIGINAL 1280x720 coordinates, scaled to the working size."""
    h, w = shape
    scale = w / src_w
    pts = np.array([[int(x * scale), int(y * scale)] for x, y in poly], np.int32)
    m = np.zeros((h, w), np.uint8)
    cv2.fillPoly(m, [pts], 255)
    return m


def foreground_series(video: Path, fps: int, poly, method: str) -> list[float]:
    """Fraction of the (masked) frame differing from the background, per frame."""
    with tempfile.TemporaryDirectory() as td:
        paths = frames_of(video, fps, Path(td))
        grays = [cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2GRAY) for p in paths]
        h, w = grays[0].shape
        n_warm = max(3, int(WARMUP_S * fps))
        bg = np.median(np.stack(grays[:n_warm]), axis=0).astype(np.uint8)
        mask = polygon_mask((h, w), poly, 1280) if (method == "zone" and poly) else None
        denom = (int(mask.sum() // 255) if mask is not None else h * w) or 1

        k = np.ones((3, 3), np.uint8)
        out = []
        for g in grays:
            d = cv2.absdiff(g, bg)
            fg = (d > PIXEL_DELTA).astype(np.uint8) * 255
            fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, k, iterations=1)
            fg = cv2.morphologyEx(fg, cv2.MORPH_CLOSE, k, iterations=2)
            if mask is not None:
                fg = cv2.bitwise_and(fg, fg, mask=mask)
            out.append(float((fg > 0).sum()) / denom)
        return out


def window_peaks(spec: dict, frac: list[float], fps: int) -> list[float]:
    """One number per window: the largest foreground fraction inside it.

    Max, not mean, because the VLM only has to notice the event in one of the four
    panels it is shown — taking the mean would handicap the baseline."""
    peaks = []
    for wdw in spec["windows"]:
        i0, i1 = int(wdw["t_start"] * fps), min(len(frac), int(wdw["t_end"] * fps))
        peaks.append(max(frac[i0:i1]) if i1 > i0 else 0.0)
    return peaks


def verdict_rows(spec: dict, peaks: list[float], area: float, method: str) -> list[dict]:
    return [{
        "id": f"{spec['clip']}|w{w['i']:03d}|gate",
        "model": f"baseline-{method}",
        "ok": True,
        "answer": "Yes" if p >= area else "No",
        "peak_foreground": round(p, 5),
        "area_threshold": area,
        "ms": 0,
    } for w, p in zip(spec["windows"], peaks)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", type=Path, required=True)
    ap.add_argument("--method", default="bgdiff", choices=["bgdiff", "zone"])
    ap.add_argument("--area", type=float, default=0.02,
                    help="fraction of (masked) frame that must change to fire")
    ap.add_argument("--polygon", default=None,
                    help="x,y,x,y,... in the 1280x720 frame, for --method zone")
    ap.add_argument("--fps", type=int, default=10, help="analysis fps")
    ap.add_argument("--self", dest="self_sweep", action="store_true",
                    help="sweep the threshold against THIS clip's own pre-onset windows "
                         "instead of a separate negative. For the transition tier, where a "
                         "clip is scored on its own before/after and there is no paired "
                         "control, this is the matching operating point: fire after the "
                         "onset, stay silent before it. Cross-pairing two unrelated clips "
                         "measures how different they are, which is F19's whole point.")
    ap.add_argument("--pair", type=Path, default=None,
                    help="the matched stream dir; with it, sweep the threshold and "
                         "report the BEST operating point instead of a fixed one")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    spec = json.loads((args.stream / "windows.json").read_text())
    video = ROOT / "clips" / spec["clip"] / "clip.mp4"
    poly = None
    if args.polygon:
        v = [int(x) for x in args.polygon.split(",")]
        poly = list(zip(v[0::2], v[1::2]))

    peaks = window_peaks(spec, foreground_series(video, args.fps, poly, args.method),
                         args.fps)

    area = args.area
    swept = None
    if args.self_sweep:
        onset = spec.get("onset_s")
        if onset is None:
            raise SystemExit("--self needs a measured onset_s")
        before = [(w, p) for w, p in zip(spec["windows"], peaks) if w["t_end"] < onset]
        after = [(w, p) for w, p in zip(spec["windows"], peaks) if w["t_end"] >= onset]
        best = None
        for a in [x / 1000 for x in range(1, 601)]:
            fired = [w["t_end"] for w, p in after if p >= a]
            if not fired:
                continue
            pre = sum(1 for _, p in before if p >= a)
            hits = len(fired)
            score = (-pre, hits, -(fired[0] - onset))
            if best is None or score > best[0]:
                best = (score, a, fired[0] - onset, pre, hits)
        if best:
            _, area, lat, pre, hits = best
            swept = {"best_area": area, "latency_s": round(lat, 2),
                     "pre_onset_fires": pre, "pre_onset_windows": len(before),
                     "detected_windows": hits, "post_onset_windows": len(after),
                     "mode": "self"}
    elif args.pair:
        # Give the baseline its best shot: sweep the one knob it has and keep the
        # threshold that maximises (fires after onset on the positive) while
        # (staying silent on the negative). Anything less would be a strawman.
        nspec = json.loads((args.pair / "windows.json").read_text())
        npeaks = window_peaks(spec_n := nspec,
                              foreground_series(ROOT / "clips" / nspec["clip"] / "clip.mp4",
                                                args.fps, poly, args.method), args.fps)
        onset = spec.get("onset_s") or 0.0
        best = None
        for a in [x / 1000 for x in range(1, 601)]:
            pos_fire = [w["t_end"] for w, p in zip(spec["windows"], peaks) if p >= a]
            neg_fire = sum(1 for p in npeaks if p >= a)
            detected = [t for t in pos_fire if t >= onset]
            if not detected:
                continue
            pre = sum(1 for t in pos_fire if t < onset)
            score = (-neg_fire - pre, -(detected[0] - onset))
            if best is None or score > best[0]:
                best = (score, a, detected[0] - onset, neg_fire, pre)
        if best:
            _, area, lat, neg_fire, pre = best
            swept = {"best_area": area, "latency_s": round(lat, 2),
                     "negative_fires": neg_fire, "pre_onset_fires": pre,
                     "negative_windows": len(npeaks)}

    rows = verdict_rows(spec, peaks, area, args.method)
    out = args.out or (args.stream / f"baseline-{args.method}.jsonl")
    out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")

    fired = [r for r in rows if r["answer"] == "Yes"]
    print(json.dumps({
        "clip": spec["clip"], "method": args.method, "area_threshold": area,
        "windows": len(rows), "fired": len(fired),
        "first_fire_s": next((w["t_end"] for w, r in zip(spec["windows"], rows)
                              if r["answer"] == "Yes"), None),
        "onset_s": spec.get("onset_s"),
        "peak_range": [round(min(peaks), 4), round(max(peaks), 4)],
        "swept": swept, "out": str(out),
    }))


if __name__ == "__main__":
    main()
