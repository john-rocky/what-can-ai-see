#!/usr/bin/env python3
"""Did anyone say the one thing the scene is about?

Every other measure here counts what a description CONTAINS — objects, motion,
counts, materials. That rewards a model for naming the furniture. A person
watching a scene does not narrate furniture; they extract the single fact the
shot exists to convey, and in a well-made shot that fact is a RELATION between
things rather than a thing: the muzzle is pointing at him, the ladder is under
him, the car is behind the child.

Both objects in such a shot are ordinary detector classes. A 2015 detector finds
a person and a cannon in every frame of Keaton's flatcar sequence and is no
closer to the point of it. So this scores the relation only:

  key_fact:                       # in the clip's meta.yaml
    window_s: [75, 125]           # while the relation actually holds
    says:  "cannon .* (at|toward) (him|the man)"
    plain: "the cannon is pointing at the man"

A window inside `window_s` scores a hit if any of `says` matches. Everything
outside is ignored — a model that says it before it is true has not read the
scene, it has guessed a genre, and giving it credit would be the same error as
counting a pre-onset fire as a detection.

Every match is PRINTED, not just tallied. Three earlier regexes in this repo
were wrong in ways only reading the matched text revealed: `pan\\w*` matched
"panel" (which is in the prompt), `car\\w*` matched "camera", and a motion
pattern matched "the progression of the frames". A count with no visible
evidence behind it is not a measurement.

usage:
  relation.py --stream runs/stream/general-cannon --run runs/film/general-cannon
  relation.py --stream ... --run ... --show-misses 6
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from said_card import sentence  # noqa: E402


def load(run: Path) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    for f in sorted(run.glob("*.jsonl")):
        if f.name in ("tasks.jsonl", "frames.jsonl"):
            continue
        rows: dict[int, str] = {}
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                # A run still in flight leaves a half-written last line. Scoring a
                # partial file is normal here — the alternative is waiting an hour
                # to find out a regex is wrong.
                continue
            parts = d.get("id", "").split("|")
            if len(parts) < 2 or not parts[1].startswith("w"):
                continue
            rows[int(parts[1][1:])] = d.get("answer", "") or ""
        if rows:
            out[f.stem] = rows
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", type=Path, required=True)
    ap.add_argument("--run", type=Path, required=True)
    ap.add_argument("--clip", type=Path, default=None)
    ap.add_argument("--show-misses", type=int, default=0,
                    help="print N sentences from inside the window that did NOT hit")
    args = ap.parse_args()

    win = json.loads((args.stream / "windows.json").read_text())
    clip = args.clip or (ROOT / "clips" / win["clip"])
    meta = yaml.safe_load((clip / "meta.yaml").read_text())
    kf = meta.get("key_fact")
    if not kf:
        raise SystemExit(f"{clip.name}: no key_fact: block in meta.yaml")

    t0, t1 = kf["window_s"]
    pats = [re.compile(p, re.I) for p in ([kf["says"]] if isinstance(kf["says"], str)
                                          else kf["says"])]
    inside = {w["i"] for w in win["windows"] if t0 <= w["t_end"] <= t1}
    runs = load(args.run)

    print(f"{win['clip']}   {kf['plain']}")
    print(f"true over {t0:.0f}-{t1:.0f}s  =  {len(inside)} of {len(win['windows'])} windows\n")

    for model, rows in sorted(runs.items()):
        # Scored against the windows this model ACTUALLY answered. Counting an
        # unrun window as a miss is how a half-finished run reads as a perfect
        # failure, which is a different and much more flattering claim than the
        # true one.
        scored = sorted(inside & set(rows))
        hits = [w for w in scored if any(p.search(rows[w]) for p in pats)]
        early = [w for w in sorted(set(rows) - inside)
                 if any(p.search(rows[w]) for p in pats)]
        gap = "" if len(scored) == len(inside) else f"  [{len(inside) - len(scored)} not run yet]"
        print(f"  {model:<20} {len(hits):>3}/{len(scored)} inside"
              f"   {len(early):>3} outside (not credited){gap}")
        for w in hits:
            for p in pats:
                m = p.search(rows[w])
                if m:
                    a = " ".join(rows[w].split())
                    lo, hi = max(0, m.start() - 60), min(len(a), m.end() + 60)
                    print(f"        w{w:03d}  …{a[lo:hi]}…")
                    break
        if args.show_misses:
            miss = [w for w in scored if w not in hits]
            for w in miss[:args.show_misses]:
                print(f"        w{w:03d}  MISS  {sentence(rows.get(w, ''), 96)}")
    print()


if __name__ == "__main__":
    main()
