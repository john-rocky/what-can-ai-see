#!/usr/bin/env python3
"""Is it reliable about the CLIP even when it is unreliable about the WINDOW?

Every measurement in this repo so far scores one window at a time, and by that measure the
models look poor: the cat is named in 26 of 30 windows and a different animal in 6, the
crowd is never counted, the relation is missed. All of that is true and all of it assumes
the unit of the answer is the window.

Most of what people actually want from footage is not a per-frame verdict. "Which of these
recordings has a cat in it", "when was someone at the counter", "find the clip with the
bicycles" — these are questions about a stretch, and a stretch is thirty windows. A model
that is 87% right per window and never wrong the same way twice can be far better than 87%
right per stretch, because the errors do not agree with each other while the truth does.

That is the thing this measures, and it is a claim that can fail: if the false answers
cluster the same way the true ones do, aggregating changes nothing.

Two numbers per term:

  per-window   the fraction of windows containing the term. What the repo has measured.
  per-clip     whether the term wins a plain majority of windows. What an index would use.

A term list is supplied per clip in `--terms`, split into what is genuinely present and
what is not. Both halves are needed: a rule that says yes to everything scores perfectly on
the present half.

usage:
  aggregate.py --run runs/film --model lfm2.5-vl-3b
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from said_card import paragraph  # noqa: E402

# What is in each clip, and what is plausibly-but-definitely NOT. The absent terms are
# chosen to be things the footage could be mistaken for rather than random words, because a
# false-positive rate against implausible terms is not worth reporting.
TRUTH: dict[str, tuple[list[str], list[str]]] = {
    "cat-kittens": (
        ["cat|kitten|feline"],
        ["dog|puppy", "bird", "car|vehicle", "kitchen"],
    ),
    "cops-pursuit": (
        ["man|person|figure", "street|road|building", "run|running|chase|chasing"],
        ["cat|dog|animal", "kitchen|indoor room", "boat|ship", "forest|trees"],
    ),
    "cops-parade": (
        ["crowd|people|group|men", "street|road|building", "horse|carriage|cart"],
        ["cat|dog", "kitchen", "beach|ocean", "snow"],
    ),
    "nola-crowd": (
        ["crowd|people|group", "street|road|city|building"],
        ["cat|dog", "forest|woods", "kitchen", "snow"],
    ),
    "masks-bags": (
        ["bag|sack|paper", "bicycle|bike|cycling", "child|children|boy|kid|young"],
        ["cat|dog", "kitchen", "boat|ship", "snow"],
    ),
    "retail-store": (
        ["shelf|shelves|store|shop|market|grocery|aisle", "product|goods|package|can|box"],
        ["forest|woods", "beach|ocean", "cat|dog", "train|locomotive"],
    ),
    "gilbreth-old": (
        ["table|bench|desk|workbench", "box|carton|package|bar", "person|woman|worker|hand"],
        ["cat|dog", "street|road", "train|locomotive", "outdoor|forest"],
    ),
    "general-bridge": (
        ["train|locomotive|engine", "bridge|trestle", "river|water"],
        ["cat|dog", "kitchen", "shop|store", "crowd of people"],
    ),
    "general-cannon": (
        ["cannon|gun|artillery", "man|person", "track|rail|railway|flatcar"],
        ["cat|dog", "kitchen", "boat|ship", "shop|store"],
    ),
}


def load(path: Path) -> list[str]:
    # Echo stripped first, always. The prompt contains "camera feed", "panel", "frames" and
    # counting those as content is the error this repo has now made five times.
    out = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        if d.get("ok"):
            out.append(paragraph(d.get("answer", ""), 4000))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", type=Path, default=ROOT / "runs" / "film")
    ap.add_argument("--model", default="lfm2.5-vl-3b")
    ap.add_argument("--majority", type=float, default=0.5)
    args = ap.parse_args()

    rows_present, rows_absent = [], []
    print(f"{args.model}\n")
    print(f"{'clip':<16}{'term':<38}{'per-window':>12}{'per-clip':>10}")
    for clip, (present, absent) in sorted(TRUTH.items()):
        f = args.run / clip / f"{args.model}.jsonl"
        if not f.exists():
            continue
        texts = load(f)
        if not texts:
            continue
        for term, truth in [(t, True) for t in present] + [(t, False) for t in absent]:
            pat = re.compile(rf"\b({term})\b", re.I)
            hits = sum(1 for t in texts if pat.search(t))
            frac = hits / len(texts)
            says = frac > args.majority
            ok = says == truth
            (rows_present if truth else rows_absent).append(ok)
            mark = "" if ok else "   <- wrong"
            label = term if len(term) < 36 else term[:35] + "…"
            print(f"{clip:<16}{label:<38}{frac:>11.0%}{('yes' if says else 'no'):>10}{mark}")

    def rate(rows):
        return f"{sum(rows)}/{len(rows)}" if rows else "—"

    print(f"\nper-clip majority vote")
    print(f"  present terms called present   {rate(rows_present)}")
    print(f"  absent terms called absent     {rate(rows_absent)}")
    both = rows_present + rows_absent
    if both:
        print(f"  overall                        {sum(both)}/{len(both)}"
              f"  ({sum(both)/len(both):.0%})")


if __name__ == "__main__":
    main()
