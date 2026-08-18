#!/usr/bin/env python3
"""Ask nothing in particular, and see what the model brings up.

Every prompt in this benchmark so far names the event it is looking for — "has
anything been spilled", "did a person fall". That measures whether a model can
confirm a hypothesis someone else supplied. It cannot tell you what the model
would have noticed on its own, and that is the thing you need before you know what
a model is FOR.

So: the same contact sheet, the same runtime, and one neutral instruction —
describe what is happening. What comes back is not scored right or wrong. It is
scored for what it CONTAINS: people, objects, actions, materials, spatial
relations, counts, text, change over time. Aggregated over enough scenes that
becomes a map of what a model spontaneously attends to, and the map is what tells
you which products it could support. A model that reliably says "a person is
holding something" and never once says "the floor is wet" can do handover
detection and cannot do slip hazards, and no amount of asking it about floors
will change that.

Windows are sampled rather than exhausted: a coverage map does not need every
0.4s step, and the sampling is what makes this affordable across many scenes.

usage:
  neutral.py --clips count-4035246,spill-pos --every 3 --out runs/neutral/tasks.jsonl
  neutral.py --all --every 3 --out runs/neutral/tasks.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

PROMPT = ("The image is a contact sheet of {n} frames covering the last {w}s of a "
          "camera feed, in time order: panel 1 is the earliest, panel {n} is the "
          "latest. Describe what is happening.")


def meta(cid: str) -> dict:
    p = ROOT / "clips" / cid / "meta.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load("\n".join(l for l in p.read_text().split("\n")
                                    if not l.startswith("#"))) or {}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", default=None)
    ap.add_argument("--all", action="store_true",
                    help="every clip that already has a window spec")
    ap.add_argument("--every", type=int, default=3,
                    help="sample every Nth window")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    ids = [c.strip() for c in (args.clips or "").split(",") if c.strip()]
    if args.all:
        for d in sorted((ROOT / "runs" / "stream").iterdir()):
            if (d / "windows.json").exists() and not d.name.startswith("_"):
                m = meta(d.name)
                if m.get("label") == "rejected" or d.name.endswith(("-mir", "-v2")):
                    continue
                ids.append(d.name)
    ids = list(dict.fromkeys(ids))

    rows, seen = [], {}
    for cid in ids:
        spec_p = ROOT / "runs" / "stream" / cid / "windows.json"
        if not spec_p.exists():
            continue
        spec = json.loads(spec_p.read_text())
        n = 0
        for w in spec["windows"][:: args.every]:
            rows.append({
                "id": f"{cid}|w{w['i']:03d}|open",
                "image": w["sheet"],
                "prompt": PROMPT.format(n=spec["panels"], w=spec["window_s"]),
            })
            n += 1
        seen[cid] = n

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")
    print(f"{len(rows)} task(s) over {len(seen)} clip(s) -> {args.out}")
    for cid, n in list(seen.items())[:6]:
        print(f"   {cid:<28}{n}")
    if len(seen) > 6:
        print(f"   … and {len(seen)-6} more")


if __name__ == "__main__":
    main()
