#!/usr/bin/env python3
"""Same events, same models, one thing changed — what happens to the ranking?

Built for the viewpoint ablation (kantine ships two synchronized cameras per
episode and this benchmark used only the first for its entire life), but it takes
any suffix, so it also answers the aspect-ratio question the same way: `-v2` is
the oblique view at a matched 16:9 centre crop, and `runs/stream/_v2-43` holds the
same view at native 4:3 before the framing was matched.

It reports balanced accuracy, not false alarms. A false-alarm column ranks a model
that answers No to everything first, and that is not a hypothetical — LFM2.5-VL
450M placed third of seven on it while sitting at exactly chance (F17). Detection
and false alarms are always printed beside the summary so the summary can be
checked rather than trusted.

Two rules this enforces, both learned by breaking them:

  * A method is only included where it ran on EVERY pair in both arms. A model
    that covers three pairs in one arm and four in the other produces a "change"
    that is a difference in sample, not in behaviour.
  * The onset comes from each clip's own meta, never from its counterpart. When a
    camera sees a spill two seconds earlier, that is a fact about the view, and
    copying the other view's onset would score it as a two-second false alarm.

usage:
  view_compare.py --a "" --b -v2 --label-a overhead --label-b oblique
  view_compare.py --a -v2 --b -v2 --dir-b runs/stream/_v2-43 --label-a "16:9" --label-b "4:3"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from card import verdict_of  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STREAM = ROOT / "runs" / "stream"

PAIRS = ["spill", "spill2", "spill3", "grounds"]
METHODS = [
    ("LFM2.5-VL 3B", "lfm2.5-vl-3b.jsonl"),
    ("Holo2 4B", "holo2-4b.jsonl"),
    ("Qwen3-VL 2B", "qwen3-vl-2b.jsonl"),
    ("North Micro Vision", "north-micro-vision.jsonl"),
    ("bg-diff (swept)", "baseline-bgdiff.jsonl"),
]


def verdicts(clip: str, fname: str, override: Path | None):
    """(window spec, {index: True/False/None}) or None if that method never ran."""
    d = STREAM / clip
    spec_path = d / "windows.json"
    if not spec_path.exists():
        return None
    src = (override / fname) if override else (d / fname)
    if not src.exists():
        return None
    spec = json.loads(spec_path.read_text())
    rows: dict[int, bool | None] = {}
    for line in src.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "answer" not in r:
            continue
        parts = r["id"].split("|")
        if len(parts) != 3 or parts[0] != clip:
            continue
        rows[int(parts[1][1:])] = verdict_of(r.get("answer", "")) if r.get("ok") else None
    return (spec, rows) if rows else None


def arm(suffix: str, override: Path | None) -> dict[str, dict]:
    """Per-clip result files are OVERWRITTEN by split_stream.py, so a directory can
    hold a mix of arms while a re-run is in flight. Reading that mix silently
    produced a table where every delta was exactly 0.00 — which looked like a
    finding and was stale data. Nothing here detects that; only finishing the run
    and re-splitting does. Check the run is complete before believing a small delta."""
    res: dict[str, dict] = {}
    for label, fname in METHODS:
        lats, hit, hitn, wrong, wrongn, fired, seen = [], 0, 0, 0, 0, 0, 0
        per_pair = {}
        for pid in PAIRS:
            a = verdicts(f"{pid}-pos{suffix}", fname, override)
            b = verdicts(f"{pid}-neg{suffix}", fname, override)
            if not a or not b:
                continue
            (ps, pr), (ns, nr) = a, b
            onset = ps.get("onset_s") or 0.0
            seen += 1
            after = [w for w in ps["windows"] if w["t_end"] >= onset]
            before = [w for w in ps["windows"] if w["t_end"] < onset]
            fl = [w["t_end"] for w in after if pr.get(w["i"]) is True]
            if fl:
                lats.append(fl[0] - onset)
                fired += 1
            h = sum(1 for w in after if pr.get(w["i"]) is True)
            wr = (sum(1 for w in before if pr.get(w["i"]) is True)
                  + sum(1 for w in ns["windows"] if nr.get(w["i"]) is True))
            hit += h; hitn += len(after)
            wrong += wr; wrongn += len(before) + len(ns["windows"])
            per_pair[pid] = {"hit": h, "n_after": len(after), "wrong": wr}
        # Only methods that covered every pair — see the docstring.
        if seen != len(PAIRS) or not hitn:
            continue
        tpr, fpr = hit / hitn, wrong / wrongn
        res[label] = {
            "lat": sorted(lats)[len(lats) // 2] if lats else None,
            "fired": fired, "tpr": tpr, "fpr": fpr, "bal": (tpr + 1 - fpr) / 2,
            "hit": hit, "hitn": hitn, "wrong": wrong, "wrongn": wrongn,
            "per_pair": per_pair,
        }
    return res


def show(title: str, d: dict[str, dict]) -> None:
    if not d:
        print(f"\n{title}: no method covered all {len(PAIRS)} pairs")
        return
    n = next(iter(d.values()))["wrongn"]
    print(f"\n{title} — {len(PAIRS)} pairs, {n} windows where No is correct")
    print("%-22s%8s%16s%16s%7s" % ("method", "lat", "detects", "wrong", "bal"))
    for k, v in sorted(d.items(), key=lambda kv: -kv[1]["bal"]):
        lat = "%+.1fs" % v["lat"] if v["lat"] is not None else "never"
        print("%-22s%8s%16s%16s%7.2f" % (
            k, lat,
            "%d/%d (%.0f%%)" % (v["hit"], v["hitn"], 100 * v["tpr"]),
            "%d/%d (%.0f%%)" % (v["wrong"], v["wrongn"], 100 * v["fpr"]),
            v["bal"]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", default="", help="clip-id suffix for arm A")
    ap.add_argument("--b", default="-v2", help="clip-id suffix for arm B")
    ap.add_argument("--dir-a", type=Path, default=None,
                    help="read arm A's result files from this directory instead")
    ap.add_argument("--dir-b", type=Path, default=None)
    ap.add_argument("--label-a", default="A")
    ap.add_argument("--label-b", default="B")
    args = ap.parse_args()

    a, b = arm(args.a, args.dir_a), arm(args.b, args.dir_b)
    show(args.label_a, a)
    show(args.label_b, b)

    both = [k for k in a if k in b]
    if not both:
        print("\nnothing ran on both arms")
        return
    print("\n%-22s%9s%9s%8s%11s%10s" % (
        "method", args.label_a[:8], args.label_b[:8], "delta", "detect d", "wrong d"))
    print("-" * 70)
    for k in sorted(both, key=lambda k: -a[k]["bal"]):
        print("%-22s%9.2f%9.2f%+8.2f%+10.0fpt%+9.0fpt" % (
            k, a[k]["bal"], b[k]["bal"], b[k]["bal"] - a[k]["bal"],
            100 * (b[k]["tpr"] - a[k]["tpr"]), 100 * (b[k]["fpr"] - a[k]["fpr"])))

    rank_a = sorted(both, key=lambda k: -a[k]["bal"])
    rank_b = sorted(both, key=lambda k: -b[k]["bal"])
    print(f"\nrank in {args.label_a}: {' > '.join(rank_a)}")
    print(f"rank in {args.label_b}: {' > '.join(rank_b)}")
    if rank_a[0] != rank_b[0]:
        print(f"\nTHE WINNER CHANGED: {rank_a[0]} -> {rank_b[0]}")
    steadiest = min(both, key=lambda k: abs(b[k]["bal"] - a[k]["bal"]))
    print(f"least affected: {steadiest} "
          f"({b[steadiest]['bal'] - a[steadiest]['bal']:+.2f})")

    print("\nper pair, detections after onset:")
    print("%-22s%s" % ("method", "".join("%14s" % p for p in PAIRS)))
    for k in sorted(both, key=lambda k: -a[k]["bal"]):
        cells = ""
        for p in PAIRS:
            pa, pb = a[k]["per_pair"].get(p), b[k]["per_pair"].get(p)
            cells += "%14s" % (f"{pa['hit']}/{pa['n_after']}->{pb['hit']}/{pb['n_after']}"
                               if pa and pb else "—")
        print("%-22s%s" % (k, cells))


if __name__ == "__main__":
    main()
