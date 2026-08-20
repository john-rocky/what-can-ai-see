#!/usr/bin/env python3
"""Slice a clip into overlapping windows and ask the model about each one.

Everything else in this repo runs ONE inference over a whole clip, which answers
"can this model classify this clip". That is not what a monitoring system does and
it is not what a person watching wants to see. A deployed camera runs the model
again and again on the last few seconds, and the question is: **at what moment
does it change its mind?**

So a window ending at time t is the only thing the model gets. It cannot see the
future, which means:

  - the verdict for window t applies from t onward, and detection latency is
    (first window that fires) minus (true onset) — a real number in seconds
  - every window on a negative clip that fires is a false alarm, and the count
    over the clip's duration is a false-alarm rate per camera-hour that was
    measured rather than projected
  - a person can watch the verdict flip in sync with the footage

usage:
  stream.py --clip clips/fall-7644974 --window 2.4 --stride 0.4 --panels 4
  # then: wcas-run --tasks runs/stream/<clip>/tasks.jsonl --out .../<model>.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from sheet import compose, extract, probe  # noqa: E402

# Panel grids for a short window. A window is a couple of seconds, so it needs far
# fewer panels than a whole clip — and fewer panels means more tokens each.
WINDOW_GRIDS = {1: (1, 1), 2: (1, 2), 4: (2, 2), 6: (2, 3)}

PREAMBLE = ("The image is a contact sheet of {n} frames covering the last {w:.1f} seconds "
            "of a camera feed, in time order: panel 1 is the earliest, panel {n} is the "
            "latest. ")
GATE = ("{question} Answer with the single word Yes or No on the first line, then one "
        "short sentence of evidence.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", type=Path, required=True)
    ap.add_argument("--events", type=Path, default=ROOT / "events" / "events.yaml")
    ap.add_argument("--window", type=float, default=2.4, help="seconds of history")
    ap.add_argument("--stride", type=float, default=0.4, help="seconds between calls")
    ap.add_argument("--panels", type=int, default=4, choices=sorted(WINDOW_GRIDS))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--neutral", action="store_true",
                    help="window a clip that has no event assigned yet. Requiring a "
                         "label before windowing has the discovery workflow backwards: "
                         "the neutral pass exists to find out what a clip shows, so it "
                         "cannot be gated on already knowing.")
    args = ap.parse_args()

    meta = yaml.safe_load((args.clip / "meta.yaml").read_text())
    events = {e["id"]: e for e in yaml.safe_load(args.events.read_text())["events"]}
    if args.neutral or meta.get("event") not in events:
        if not args.neutral:
            raise SystemExit(
                f"{args.clip.name}: event {meta.get('event')!r} is not in events.yaml. "
                f"Label it, or pass --neutral to window it without a question.")
        event = {"id": meta.get("event", "UNVERIFIED"),
                 "question": "Describe what is happening.",
                 "evidence": "unassigned"}
    else:
        event = events[meta["event"]]
    video = args.clip / "clip.mp4"
    duration, _, _ = probe(video)

    out_dir = args.out or (ROOT / "runs" / "stream" / args.clip.name)
    frames_dir = out_dir / "windows"
    frames_dir.mkdir(parents=True, exist_ok=True)

    cols, rows = WINDOW_GRIDS[args.panels]
    lines, index = [], []
    i = 0
    t_end = args.window
    while t_end <= duration + 1e-6:
        t0 = t_end - args.window
        # Panels at the centres of equal slices inside the window, same rule the
        # whole-clip sheets use, so a window sheet and a clip sheet are comparable.
        times = [t0 + args.window * (k + 0.5) / args.panels for k in range(args.panels)]
        sheet_path = frames_dir / f"w{i:03d}.jpg"
        if not sheet_path.exists():
            with tempfile.TemporaryDirectory() as td:
                frames = extract(video, times, Path(td))
                compose(frames, cols, rows, "badge").save(sheet_path, quality=93)
        # A neutral pass asks for a description, so it must NOT also demand a
        # Yes/No first line. Wrapping it in GATE anyway produced the prompt
        # "Describe what is happening. Answer with the single word Yes or No",
        # which is two contradictory instructions and measures neither.
        kind = "open" if args.neutral else "gate"
        body = (event["question"] if args.neutral
                else GATE.format(question=event["question"]))
        task_id = f"{args.clip.name}|w{i:03d}|{kind}"
        lines.append(json.dumps({
            "id": task_id, "image": str(sheet_path.resolve()),
            "prompt": PREAMBLE.format(n=args.panels, w=args.window) + body,
        }))
        index.append({"i": i, "t_start": round(t0, 3), "t_end": round(t_end, 3),
                      "times": [round(x, 3) for x in times], "sheet": str(sheet_path)})
        i += 1
        t_end += args.stride

    (out_dir / "tasks.jsonl").write_text("\n".join(lines) + "\n")
    (out_dir / "windows.json").write_text(json.dumps({
        "clip": args.clip.name, "event": meta["event"], "label": meta["label"],
        "question": event["question"], "onset_s": meta.get("onset_s"),
        "duration_s": round(duration, 3), "window_s": args.window,
        "stride_s": args.stride, "panels": args.panels,
        "ground_truth": meta.get("ground_truth", ""),
        "windows": index,
    }, indent=2))
    print(f"{len(lines)} window(s) over {duration:.1f}s "
          f"({args.window}s window, {args.stride}s stride, {args.panels} panels) "
          f"-> {out_dir}/tasks.jsonl")


if __name__ == "__main__":
    main()
