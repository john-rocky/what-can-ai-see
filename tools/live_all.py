#!/usr/bin/env python3
"""Run the live sliding-window view over every curated pair and cut them together.

One clip at a time is a demo. The point of doing it across a corpus is that a
person watching twenty of these in a row builds an intuition for where the edge
is — which is the thing a leaderboard number cannot give anyone, and the reason
this project exists.

Each stage is resumable and skipped if its output already exists, so this can be
interrupted and restarted without repaying for the inference.

Order is deliberate: pairs stay adjacent, positive first. A viewer who sees the
alarm fire correctly on the positive and then fire again on its look-alike has
learned the whole finding in twenty seconds, and no caption has to say it.

usage:
  live_all.py --plan                       # what it would do, and the cost
  live_all.py --models lfm2.5-vl-3b,north-micro-vision
  live_all.py --concat-only --out cards/live-reel.mp4
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "runner/.build/release/wcas-run"
STREAM = ROOT / "runs" / "stream"
SEGMENTS = ROOT / "cards" / ".live-segments"

# Event order for the finished reel: the industrial transitions first (they are
# what the corpus is for), then people, then the state events last — those have no
# before-state, so the bar cannot change and they are the least interesting to
# watch even when the model is right.
SUPERSEDED = {"fall-7644974"}

EVENT_ORDER = ["line-stopped", "object-removed", "parcel-pass", "handover",
               "fall", "ppe-missing", "smoke-fire"]


def curated_pairs() -> list[tuple[str, str, str]]:
    """(event, positive, negative), one per pair, variants excluded."""
    metas = {}
    for p in sorted((ROOT / "clips").glob("*/meta.yaml")):
        if not (p.parent / "clip.mp4").exists():
            continue
        m = yaml.safe_load(p.read_text())
        if m.get("label") not in ("positive", "negative"):
            continue
        if m.get("tier") == "variant":      # degraded copies are not watchable demos
            continue
        metas[p.parent.name] = m
    seen, out = set(), []
    for cid, m in metas.items():
        if m["label"] != "positive":
            continue
        mate = m.get("pair")
        if not mate or mate not in metas or cid in seen:
            continue
        seen.update({cid, mate})
        out.append((m["event"], cid, mate))
    # Synthetic floor clips are diagrams, not footage; they do not belong in a reel
    # whose purpose is to build intuition about real cameras.
    out = [t for t in out if not t[1].startswith("synth-")]
    # fall-live-pos was re-cut from fall-7644974 precisely because that cut had no
    # pre-event windows, which makes its latency unmeasurable. Keeping both would
    # put the superseded version in the reel next to its own fix.
    out = [t for t in out if t[1] not in SUPERSEDED]
    out.sort(key=lambda t: (EVENT_ORDER.index(t[0]) if t[0] in EVENT_ORDER else 99, t[1]))
    return out


def sh(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="lfm2.5-vl-3b,north-micro-vision")
    ap.add_argument("--window", type=float, default=1.6)
    ap.add_argument("--stride", type=float, default=0.4)
    ap.add_argument("--panels", type=int, default=4)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--concat-only", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "cards" / "live-reel.mp4")
    args = ap.parse_args()

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    pairs = curated_pairs()
    clips = [c for _, pos, neg in pairs for c in (pos, neg)]

    if args.plan:
        total_windows = 0
        print(f"{len(pairs)} pair(s), {len(clips)} clip(s), {len(models)} model(s)\n")
        for ev, pos, neg in pairs:
            spec = json.loads((STREAM / pos / "windows.json").read_text()) \
                if (STREAM / pos / "windows.json").exists() else None
            n = spec and len(spec["windows"])
            print(f"  {ev:<16} {pos:<34} / {neg}")
        for c in clips:
            d = yaml.safe_load((ROOT / "clips" / c / "meta.yaml").read_text())
            dur = float(d.get("duration_s") or 6.0)
            total_windows += max(0, int((dur - args.window) / args.stride) + 1)
        calls = total_windows * len(models)
        print(f"\n~{total_windows} window(s) x {len(models)} model(s) = ~{calls} inferences")
        print(f"at ~4.5 s each that is roughly {calls * 4.5 / 60:.0f} minutes")
        return

    SEGMENTS.mkdir(parents=True, exist_ok=True)

    if not args.concat_only:
        for n, clip in enumerate(clips, 1):
            sd = STREAM / clip
            if not (sd / "tasks.jsonl").exists():
                sh([sys.executable, str(ROOT / "tools/stream.py"), "--clip",
                    str(ROOT / "clips" / clip), "--window", str(args.window),
                    "--stride", str(args.stride), "--panels", str(args.panels)])
            n_tasks = len((sd / "tasks.jsonl").read_text().strip().splitlines())
            for m in models:
                done = 0
                f = sd / f"{m}.jsonl"
                if f.exists():
                    done = len([l for l in f.read_text().splitlines() if l.strip()])
                if done >= n_tasks:
                    continue
                print(f"[{n}/{len(clips)}] {clip} / {m}  ({done}/{n_tasks} done)", flush=True)
                sh([str(RUNNER), "--model", m, "--tasks", str(sd / "tasks.jsonl"),
                    "--out", str(f), "--resume", "--max-tokens", "70"])

    # Render one segment per clip, tagged with its position so a long reel stays
    # navigable.
    order: list[Path] = []
    idx = 0
    for ev, pos, neg in pairs:
        idx += 1
        for clip in (pos, neg):
            seg = SEGMENTS / f"{clip}.mp4"
            if not seg.exists():
                tag = f"{idx}/{len(pairs)}  ·  {ev}"
                sh([sys.executable, str(ROOT / "tools/live.py"), "--stream",
                    str(STREAM / clip), "--out", str(seg), "--tag", tag])
            order.append(seg)

    listing = SEGMENTS / "list.txt"
    listing.write_text("".join(f"file '{p.resolve()}'\n" for p in order))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sh(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
        "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(args.out)])
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(args.out)],
                         capture_output=True, text=True).stdout.strip()
    print(f"\nwrote {args.out}  ({len(order)} segments, {float(dur):.0f}s)")


if __name__ == "__main__":
    main()
