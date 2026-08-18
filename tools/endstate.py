#!/usr/bin/env python3
"""A pair screen that DOES NOT WORK. Kept because its failure is the result.

Read this before reaching for it. Measured on the five pairs in F16:

    pair        positive  negative  ratio
    spill         0.0773    0.0591    1.3
    spill2        0.1098    0.0957    1.1
    spill3        0.0509    0.0873    0.6   <- backwards
    grounds       0.0161    0.0594    0.3   <- backwards
    hazard        0.2184    0.0583    3.7   <- the only one it gets right

Four of five fail, two of them inverted, and the four it fails are pairs verified
correct by other means (brown fraction for the spills, and by eye for grounds —
its positive ends with a visible heap of grounds on the table, its negative with
a clean table and the spoon back in the tin).

The premise below is what is wrong: it assumes the robot arm averages out between
the first and last second, so what survives is what the event left behind. It does
not. The arm's final resting position differs from episode to episode, and that
difference is LARGER than the trace the anomaly leaves. The screen is measuring
where the arm parked.

That is not a quirk of this implementation. It is the same fact that gives the
swept background subtractor 10/34 false alarms on `spill2` while the VLM holds at
2/34: on a real rig, normal task variation moves more pixels than the anomaly
does. Any screen built on "count the changed pixels" inherits it. This one is left
here, failing, rather than tuned per scene, because a per-scene threshold would
turn the finding into a configuration and hide it.

Controls are still verified — by `spill_onset.py` where its colour model applies,
and by looking at the last frame where it does not.

---- original premise, retained so the failure is legible ----

Does the positive END differently from the negative? A pair screen for fixed cameras.

spill_onset.py verifies a control by colour, which only works in the one scene it
was calibrated for — on the coffee-machine rig the machine itself is brown, so it
scores the clean control at 0.166 and calls it a spill. A control that cannot be
checked is a control that gets trusted, and trusting the dataset label is exactly
what put a spill inside the first `spill-neg`.

This screen is colour-blind and scene-agnostic. On a fixed camera, an event that
leaves a trace changes the scene PERSISTENTLY: the last second does not look like
the first. A robot arm moving through does not, because it leaves. So:

    median(last HOLD seconds) vs median(first HOLD seconds), fraction changed

The median across a second of frames is what removes the arm — it is in a
different place in each frame, so it loses to the static background. What survives
is what stayed put: a pool, a heap, broken glass.

A valid pair separates. `pos` should be several times `neg`. When they are close,
either the control has the event in it or the positive leaves no visible trace —
both disqualify the pair, and which one it is takes eyes, not this tool.

This does NOT verify the onset time and does NOT work on a moving camera. It is a
screen, not a label.

usage: endstate.py --pairs spill:spill-pos,spill-neg grounds:grounds-pos,grounds-neg
"""
from __future__ import annotations
import argparse, subprocess, tempfile
from pathlib import Path
import cv2, numpy as np

ROOT = Path(__file__).resolve().parent.parent
DELTA = 25   # per-pixel intensity change counted as different


def changed_fraction(video: Path, fps: int, hold: float) -> tuple[float, int]:
    with tempfile.TemporaryDirectory() as td:
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
                        "-vf", f"fps={fps},scale=480:-2", "-y", f"{td}/f%05d.png"], check=True)
        paths = sorted(Path(td).glob("f*.png"))
        grays = [cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2GRAY) for p in paths]
    n = max(3, int(hold * fps))
    if len(grays) < 2 * n:
        return float("nan"), len(grays)
    start = np.median(np.stack(grays[:n]), axis=0).astype(np.uint8)
    end = np.median(np.stack(grays[-n:]), axis=0).astype(np.uint8)
    d = (cv2.absdiff(end, start) > DELTA).astype(np.uint8) * 255
    k = np.ones((3, 3), np.uint8)
    d = cv2.morphologyEx(d, cv2.MORPH_OPEN, k, iterations=1)
    return float((d > 0).sum()) / d.size, len(grays)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", required=True, help="name:pos-clip,neg-clip")
    ap.add_argument("--fps", type=int, default=10)
    ap.add_argument("--hold", type=float, default=1.5, help="seconds averaged at each end")
    ap.add_argument("--ratio", type=float, default=3.0, help="pos/neg needed to pass")
    args = ap.parse_args()

    print(f"{'pair':<14}{'positive':>10}{'negative':>10}{'ratio':>8}  verdict")
    print("-" * 60)
    bad = 0
    for spec in args.pairs:
        name, clips = spec.split(":", 1)
        pos_id, neg_id = [c.strip() for c in clips.split(",")]
        pos, _ = changed_fraction(ROOT / "clips" / pos_id / "clip.mp4", args.fps, args.hold)
        neg, _ = changed_fraction(ROOT / "clips" / neg_id / "clip.mp4", args.fps, args.hold)
        ratio = pos / neg if neg > 1e-6 else float("inf")
        ok = ratio >= args.ratio
        bad += not ok
        print(f"{name:<14}{pos:>10.4f}{neg:>10.4f}{ratio:>8.1f}  "
              f"{'separates' if ok else 'TOO CLOSE — check both halves by eye'}")
    print(f"\n{len(args.pairs) - bad}/{len(args.pairs)} pairs separate at {args.ratio}x")


if __name__ == "__main__":
    main()
