#!/usr/bin/env python3
"""Which clips have already gone out, so a series never repeats itself.

Posting is not a one-off here — the point is a run of them — and the second reel
cut for this project reused five of its ten clips from the first. Nothing caught
it because nothing was tracking it: every beat selector optimises for the most
interesting moment, and the most interesting moments do not change between
Tuesday and Thursday.

So a ledger. `docs/posted.json` records what each published cut contained, and
`--fresh` filters a candidate list down to what an audience has not seen.

Registering is deliberately manual: a rendered file is not a published one, and
the difference matters. Nothing is marked used until it actually goes out.

usage:
  used.py --register reel-post.mp4 --beats /tmp/beats8.json --note "first X post"
  used.py --list
  used.py --fresh spill-pos,count-3970144,alu-s013
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "posted.json"


def load() -> dict:
    if LEDGER.exists():
        return json.loads(LEDGER.read_text())
    return {"posts": []}


def used_clips(d: dict) -> set[str]:
    return {c for p in d["posts"] for c in p["clips"]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", default=None, help="the cut's filename")
    ap.add_argument("--beats", type=Path, default=None, help="the beats json it was cut from")
    ap.add_argument("--clips", default=None, help="or the clip ids directly")
    ap.add_argument("--note", default="")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--fresh", default=None,
                    help="comma-separated candidates; prints the ones not yet posted")
    args = ap.parse_args()

    d = load()

    if args.register:
        clips = []
        if args.beats:
            clips = [b["clip"] for b in json.loads(args.beats.read_text())]
        elif args.clips:
            clips = [c.strip() for c in args.clips.split(",") if c.strip()]
        if not clips:
            raise SystemExit("give --beats or --clips")
        d["posts"].append({"cut": args.register, "note": args.note,
                           "clips": sorted(dict.fromkeys(clips))})
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(d, indent=1) + "\n")
        print(f"registered {args.register}: {len(set(clips))} clip(s)")

    if args.list:
        for p in d["posts"]:
            print(f"\n{p['cut']}  — {p['note']}")
            for c in p["clips"]:
                print(f"   {c}")
        print(f"\n{len(used_clips(d))} clip(s) used across {len(d['posts'])} post(s)")

    if args.fresh:
        seen = used_clips(d)
        cands = [c.strip() for c in args.fresh.split(",") if c.strip()]
        fresh = [c for c in cands if c not in seen]
        stale = [c for c in cands if c in seen]
        print(f"fresh ({len(fresh)}): {', '.join(fresh) or '-'}")
        if stale:
            print(f"already posted ({len(stale)}): {', '.join(stale)}")


if __name__ == "__main__":
    main()
