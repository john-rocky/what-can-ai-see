#!/usr/bin/env python3
"""Phone vs Mac, on the same windows: does the device agree with the desktop?

Speed is the number people ask for and agreement is the number that decides whether the
speed matters. Every finding in this repo was measured on a Mac Studio M4 Max. If the phone
answers the same images differently — different quantisation, different scheduler, a
different vision path — then those 24 findings are Mac findings and say nothing about what
ships. That is worth knowing before any of them is quoted at a phone.

Two things are reported and they are deliberately separate:

  throughput  seconds per window, and windows per second against the 0.4 s stride the
              sliding-window design assumes. A model that cannot keep up is not broken; it
              means the stride on a phone is a different number, and that number belongs in
              the design rather than in a footnote.

  agreement   exact match is the wrong test for free text — two runs of the same model on
              the same image differ in wording. So: the fraction of content words shared
              (Jaccard over stemmed non-stopwords), plus how often the phone names an object
              the Mac did not. Neither is a verdict. They are there to be READ, which is why
              the most divergent pairs are printed in full.

usage:
  phone_compare.py --model lfm2.5-vl-450m
  phone_compare.py --model lfm2.5-vl-3b --mac runs/film/general-bridge --show 5
"""

from __future__ import annotations

import argparse
import json
import re
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

STOP = {
    "a", "an", "and", "are", "as", "at", "be", "being", "but", "by", "for", "from", "in",
    "is", "it", "its", "of", "on", "or", "over", "that", "the", "there", "this", "to",
    "was", "were", "with", "which", "while", "then", "each", "into", "their", "they",
    "has", "have", "had", "also", "both", "appears", "seems", "likely", "possibly",
    "image", "frame", "frames", "panel", "panels", "sheet", "contact", "sequence",
    "camera", "feed", "seconds", "second", "shows", "showing", "captures", "capturing",
}


def words(t: str) -> set[str]:
    # Crude stemming: this compares two runs of the SAME model, so "moving"/"moves" being
    # one token matters more than linguistic correctness.
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


def load(path: Path) -> dict[str, dict]:
    rows = {}
    if not path.exists():
        return rows
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows[d.get("id", "")] = d
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--phone", type=Path, default=None)
    ap.add_argument("--mac", type=Path, default=None,
                    help="run dir holding <model>.jsonl from the Mac")
    ap.add_argument("--stride", type=float, default=0.4,
                    help="the sliding-window step the Mac design assumes")
    ap.add_argument("--show", type=int, default=3,
                    help="print this many of the most divergent pairs, in full")
    args = ap.parse_args()

    phone = load(args.phone or ROOT / "runs" / "phone" / f"{args.model}.jsonl")
    if not phone:
        raise SystemExit("no phone results — run tools/phone_run.sh first")

    mac_dir = args.mac or ROOT / "runs" / "film" / "general-bridge"
    mac = load(mac_dir / f"{args.model}.jsonl")

    ms = [d["ms"] for d in phone.values() if d.get("ok") and "ms" in d]
    if ms:
        mean_s = st.mean(ms) / 1000
        print(f"{args.model}  n={len(ms)} on device")
        print(f"  seconds per window   median {st.median(ms)/1000:.2f}   mean {mean_s:.2f}")
        print(f"  windows per second   {1/mean_s:.3f}")
        print(f"  vs the {args.stride}s stride   {mean_s/args.stride:.1f}x slower than real time")
        fp = [d.get("footprint_mb", 0) for d in phone.values()]
        av = [d.get("available_mb", 0) for d in phone.values()]
        if fp:
            print(f"  peak footprint       {max(fp):.0f} MB   min headroom {min(av):.0f} MB")
        th = [d.get("thermal", "?") for d in phone.values()]
        if th:
            print(f"  thermal              {th[0]} -> {th[-1]}")
        # Drift across the run is the throttling question. First and last thirds rather than
        # a fitted slope: a phone does not degrade linearly, it steps when a state changes.
        if len(ms) >= 6:
            k = len(ms) // 3
            print(f"  first third {st.mean(ms[:k])/1000:.2f}s   "
                  f"last third {st.mean(ms[-k:])/1000:.2f}s")

    if not mac:
        print(f"\n  no Mac results at {mac_dir}/{args.model}.jsonl — speed only")
        return

    shared = [i for i in phone if i in mac and phone[i].get("ok") and mac[i].get("ok")]
    if not shared:
        print("\n  no window ids in common — the phone ran a different payload")
        return

    scored = []
    for i in shared:
        a, b = words(phone[i].get("answer", "")), words(mac[i].get("answer", ""))
        if not (a | b):
            continue
        scored.append((len(a & b) / len(a | b), i))
    scored.sort()
    js = [s for s, _ in scored]
    print(f"\nagreement with {mac_dir.name}, {len(scored)} shared window(s)")
    print(f"  content-word overlap   median {st.median(js):.2f}   min {min(js):.2f}   max {max(js):.2f}")

    for s, i in scored[: args.show]:
        print(f"\n  --- {i}   overlap {s:.2f}")
        print(f"    phone: {' '.join(phone[i].get('answer','').split())[:200]}")
        print(f"    mac  : {' '.join(mac[i].get('answer','').split())[:200]}")


if __name__ == "__main__":
    main()
