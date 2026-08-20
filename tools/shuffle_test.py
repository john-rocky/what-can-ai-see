#!/usr/bin/env python3
"""Does the ORDER of the per-window descriptions carry anything?

The long-span bet is that a memoryless perception layer still leaves a usable
account of ten minutes, assembled outside the model. That bet has a cheap way to
fail: if a shuffled transcript reads the same as an ordered one, the sequence adds
nothing and this was a detection problem all along.

Testing it with a summariser would put another model's opinion under the result.
Instead, the structure is measured directly: **how similar are two descriptions as
a function of how far apart in time they are?**

  decays with distance   nearby windows describe more of the same thing than
                         distant ones. The transcript has a shape, and shuffling
                         destroys it.
  flat                   every window says roughly the same thing regardless of
                         when. Order is decoration.

Similarity is lexical overlap on content words — no embedding, no model. It is
crude, and crude is the point: anything cleverer would be unauditable, and the
question here is coarse enough that Jaccard answers it.

One confound is handled explicitly. Consecutive windows share 3 of their 4 panels,
so of course they are similar; that says nothing about the span. The gap curve is
therefore reported separately for pairs inside one shot and pairs across different
shots, and only the second is evidence about long-range structure.

usage:
  shuffle_test.py --run runs/alu
  shuffle_test.py --run runs/neutral --model lfm2.5-vl-3b
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

STOP = {"the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "is", "it",
        "for", "with", "that", "this", "its", "be", "are", "was", "not", "no",
        "from", "by", "has", "have", "into", "over", "than", "then", "there",
        "their", "them", "they", "which", "while", "as", "image", "images",
        "frame", "frames", "panel", "panels", "contact", "sheet", "sequence",
        "camera", "feed", "shows", "showing", "shown", "seconds", "second",
        "time", "order", "earliest", "latest", "appears", "appear", "scene",
        "captures", "capturing", "captured", "depicts", "depicting", "video"}
ECHO = re.compile(r"(the image is a contact sheet[^.]*\.|contact sheet of \d+ frames[^.]*\.|"
                  r"covering the last [\d.]+s of a camera feed[^.]*\.|in time order[^.]*\.|"
                  r"panel \d+ is the (earliest|latest)[^.]*\.)", re.I)


def words(t: str) -> set[str]:
    t = ECHO.sub(" ", t or "")
    return {w for w in re.findall(r"[a-z]{4,}", t.lower()) if w not in STOP}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    files = [p for p in sorted(args.run.glob("*.jsonl"))
             if p.stem not in ("tasks", "frames", "detect-rf-detr")]
    if args.model:
        files = [p for p in files if p.stem == args.model]
    if not files:
        raise SystemExit("no runs found")

    # position of each clip within its source, so "across shots" has a real distance
    order = {}
    for d in (ROOT / "clips").iterdir():
        m = d / "meta.yaml"
        if not m.exists():
            continue
        y = yaml.safe_load("\n".join(l for l in m.read_text().split("\n")
                                     if not l.startswith("#"))) or {}
        s = y.get("source") or {}
        order[d.name] = (s.get("in_film_s") or [0])[0]

    print(f"{'model':<20}{'pairs':>8}{'same shot':>12}{'across shots':>14}{'shuffled':>11}")
    print("-" * 66)
    for f in files:
        rows = []
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("ok"):
                continue
            cid, wid, _ = r["id"].split("|")
            spec_p = ROOT / "runs" / "stream" / cid / "windows.json"
            if not spec_p.exists():
                continue
            spec = json.loads(spec_p.read_text())
            w = next((x for x in spec["windows"] if x["i"] == int(wid[1:])), None)
            if w is None:
                continue
            t = order.get(cid, 0) + w["t_end"]
            rows.append((cid, t, words(r.get("answer", ""))))
        if len(rows) < 8:
            continue
        rows.sort(key=lambda r: r[1])

        same, across = [], []
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                s = jaccard(rows[i][2], rows[j][2])
                (same if rows[i][0] == rows[j][0] else across).append(s)
        # a shuffled transcript: pair descriptions with random partners
        rnd = random.Random(7)
        idx = list(range(len(rows)))
        shuf = []
        for _ in range(len(across) or 1):
            a, b = rnd.sample(idx, 2)
            shuf.append(jaccard(rows[a][2], rows[b][2]))

        def m(v):
            return statistics.mean(v) if v else float("nan")
        print(f"{f.stem:<20}{len(same)+len(across):>8}{m(same):>12.3f}"
              f"{m(across):>14.3f}{m(shuf):>11.3f}")

    print("\n'across shots' vs 'shuffled' is the test. If they match, the transcript")
    print("has no long-range structure and the span adds nothing.")


if __name__ == "__main__":
    main()
