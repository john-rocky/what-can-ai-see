#!/usr/bin/env python3
"""Same model, same image, same prompt, N times — how much does the answer move?

Every score in this repo treats one run as the model's answer. That is only sound if a
second run would say the same thing. It came up because a window that named the event on
one pass ("the train is falling from the bridge") did not name it on the next, from the
same file with the same prompt — which means a 0/13 and a 3/13 could be the same model on
two afternoons, and the whole table would be noise wearing a number.

Three things are measured and they are different questions:

  content drift   Jaccard over content words between runs. Wording always moves; what
                  matters is whether the CLAIM moves with it.
  event flips     for a clip with a key_fact, how many runs matched the pattern. 3/3 or
                  0/3 is a model; 1/3 is a coin, and a single-run score of that window is
                  meaningless in either direction.
  refusal flips   the system model refuses some windows. If the SAME window is refused on
                  one run and answered on the next, "refusal rate" is not a property of
                  the footage and cannot be quoted as one.

usage:
  repeat.py --runs runs/phone/determinism/system-r*.jsonl
  repeat.py --runs … --clip general-bridge --show 4
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

STOP = {
    "a", "an", "and", "are", "as", "at", "be", "being", "but", "by", "for", "from", "in",
    "is", "it", "its", "of", "on", "or", "over", "that", "the", "there", "this", "to",
    "was", "were", "with", "which", "while", "then", "each", "into", "their", "they",
    "has", "have", "had", "also", "both", "appears", "seems", "likely", "possibly",
    "image", "frame", "frames", "panel", "panels", "sheet", "contact", "sequence",
    "camera", "feed", "seconds", "second", "shows", "showing", "captures", "capturing",
    "first", "next", "final", "last", "earliest", "latest", "time", "order", "scene",
}


def words(t: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z]+", (t or "").lower()):
        if len(w) < 3 or w in STOP:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > 5 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def load(p: Path) -> dict[str, dict]:
    rows = {}
    for line in p.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            rows[d.get("id", "")] = d
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", nargs="+", type=Path, required=True)
    ap.add_argument("--clip", default=None,
                    help="score the key_fact of this clip across runs")
    ap.add_argument("--show", type=int, default=3,
                    help="print this many of the least stable windows, in full")
    args = ap.parse_args()

    runs = [load(p) for p in args.runs]
    if len(runs) < 2:
        raise SystemExit("need at least two runs")
    ids = sorted(set(runs[0]) & set.intersection(*(set(r) for r in runs[1:])))
    print(f"{len(runs)} runs, {len(ids)} windows in common\n")

    # content drift
    scored = []
    for i in ids:
        sets = [words(r[i].get("answer", "")) for r in runs]
        pairs = [
            len(a & b) / len(a | b)
            for k, a in enumerate(sets) for b in sets[k + 1:] if (a | b)
        ]
        if pairs:
            scored.append((st.mean(pairs), i))
    scored.sort()
    js = [s for s, _ in scored]
    print("content-word overlap between runs, same image and prompt")
    print(f"  median {st.median(js):.2f}   min {min(js):.2f}   max {max(js):.2f}")
    print(f"  windows under 0.40 overlap: {sum(1 for s in js if s < 0.40)}/{len(js)}")

    # refusal flips
    ref = {i: [not r[i].get("ok", True) for r in runs] for i in ids}
    flips = [i for i, v in ref.items() if any(v) and not all(v)]
    always = [i for i, v in ref.items() if all(v)]
    print(f"\nrefusals: always {len(always)}   sometimes {len(flips)}")
    for i in flips:
        print(f"  FLIP {i}  refused in {sum(ref[i])}/{len(runs)} runs")
    for i in always:
        print(f"  always {i}")

    # event flips
    if args.clip:
        meta = ROOT / "clips" / args.clip / "meta.yaml"
        body = "\n".join(l for l in meta.read_text().split("\n") if not l.startswith("#"))
        kf = (yaml.safe_load(body) or {}).get("key_fact")
        spec = json.loads((ROOT / "runs" / "stream" / args.clip / "windows.json").read_text())
        if kf:
            t0, t1 = kf["window_s"]
            inside = {w["i"] for w in spec["windows"] if t0 <= w["t_end"] <= t1}
            pats = [re.compile(p, re.I) for p in kf["says"]]
            print(f"\n{args.clip}: {kf['plain']}")
            hits = []
            for i in ids:
                if args.clip not in i:
                    continue
                w = int(i.split("|")[1][1:])
                if w not in inside:
                    continue
                n = sum(
                    1 for r in runs if any(p.search(r[i].get("answer", "")) for p in pats))
                hits.append((w, n))
            for w, n in sorted(hits):
                mark = "  " if n in (0, len(runs)) else "  <- coin"
                print(f"  w{w:03d}  named it in {n}/{len(runs)} runs{mark}")
            if not hits:
                print("  (no judgment windows in this payload)")

    print("\nleast stable windows")
    for s, i in scored[: args.show]:
        print(f"\n  --- {i}   overlap {s:.2f}")
        for k, r in enumerate(runs):
            t = " ".join((r[i].get("answer") or r[i].get("error") or "").split())
            print(f"    run{k + 1}: {t[:170]}")


if __name__ == "__main__":
    main()
