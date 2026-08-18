#!/usr/bin/env python3
"""Which events can actually be sourced under a clean licence?

The corpus is licence-clean stock only — no self-shot footage — so the taxonomy in
events/events.yaml is a wish list until this says otherwise. And the binding
constraint is not the positive. Anyone can find "person falling"; the benchmark
needs the LOOK-ALIKE that is not a fall — a crouch, a sit, a stretch, in a similar
setting. An event with plentiful positives and no credible negative cannot be
scored here at all, so both columns are surveyed and the negative column is the
one that decides.

Reports per event: result counts for the positive and negative queries, and how
many hits are in the usable duration band (a clip much under ~3s cannot carry a
6-panel sheet; much over ~30s and the event is a needle in the trim).

usage:
  survey_pexels.py                       # all events
  survey_pexels.py --event fall --show   # candidate URLs for one event
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.pexels.com/videos/search"
MIN_S, MAX_S = 3, 40


def search(query: str, key: str, per_page: int = 15) -> dict:
    """Fetch via curl rather than urllib.

    urllib hung indefinitely against this endpoint here — 6 KB transferred in
    twelve minutes at 0% CPU, with its own 25s timeout never firing. curl with an
    explicit --max-time returns in under a second for the same request, so the
    harness uses the thing that demonstrably works instead of the thing that
    should.
    """
    url = f"{API}?{urllib.parse.urlencode({'query': query, 'per_page': per_page, 'orientation': 'landscape'})}"
    for attempt in range(3):
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "20", "-H", f"Authorization: {key}", url],
            capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                pass
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    return {"error": "fetch failed", "videos": [], "total_results": 0}


def usable(videos: list[dict]) -> list[dict]:
    return [v for v in videos if MIN_S <= v.get("duration", 0) <= MAX_S]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", type=Path, default=ROOT / "events" / "sources.yaml")
    ap.add_argument("--event", default=None, help="survey one event only")
    ap.add_argument("--show", action="store_true", help="print candidate URLs")
    ap.add_argument("--out", type=Path, default=ROOT / "events" / "survey.json")
    args = ap.parse_args()

    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise SystemExit("PEXELS_API_KEY is not set")

    plan = yaml.safe_load(args.sources.read_text())["queries"]
    if args.event:
        plan = {k: v for k, v in plan.items() if k == args.event}
        if not plan:
            raise SystemExit(f"no query plan for event {args.event!r}")

    report = {}
    print(f"{'event':<18} {'pos seen':>9} {'pos hit':>8} {'neg seen':>9} {'neg hit':>8}  verdict")
    print("-" * 80)
    for event, spec in plan.items():
        counts = {}
        for side in ("positive", "negative"):
            side_spec = spec.get(side, {})
            pattern = re.compile(side_spec.get("title", ".")) if side_spec.get("title") else None
            seen, matched = {}, {}
            for q in side_spec.get("search", []):
                for v in usable(search(q, key).get("videos", [])):
                    # The Pexels title lives at the end of the URL slug.
                    slug = v["url"].rstrip("/").rsplit("/", 1)[-1]
                    title = " ".join(slug.split("-")[:-1])
                    row = {"id": v["id"], "url": v["url"], "title": title,
                           "duration": v["duration"], "query": q}
                    seen[v["id"]] = row
                    if pattern is None or pattern.search(title):
                        matched[v["id"]] = row
                time.sleep(0.3)  # be polite to the API
            counts[side] = {"seen": len(seen), "matched": list(matched.values())}

        p, n = len(counts["positive"]["matched"]), len(counts["negative"]["matched"])
        # A pair needs both sides. The negative is usually the scarce half.
        verdict = ("strong" if p >= 6 and n >= 6 else
                   "workable" if p >= 3 and n >= 3 else
                   "negative-starved" if p >= 3 else
                   "positive-starved" if n >= 3 else "thin")
        report[event] = {**counts, "verdict": verdict}
        print(f"{event:<18} {counts['positive']['seen']:>9} {p:>8} "
              f"{counts['negative']['seen']:>9} {n:>8}  {verdict}")
        sys.stdout.flush()

        if args.show:
            for side in ("positive", "negative"):
                print(f"  {side}:")
                for v in counts[side]["matched"][:12]:
                    print(f"    {v['id']:>9} {v['duration']:>3}s  {v['title']}")

    args.out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    sys.exit(main())
