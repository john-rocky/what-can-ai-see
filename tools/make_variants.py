#!/usr/bin/env python3
"""Turn a curated pair into a condition ladder, both halves degraded together.

`degrade.py` renders one variable at one level. This registers the results as
first-class clips so the existing harness — build_tasks, score, card — picks them
up with no special-casing, and it enforces the one rule that makes the ladder
mean anything:

    **a pair is always degraded together.**

Darken the positive and leave the negative clean and the model can score above
chance on brightness alone. Every variant of a positive is paired with the
identically-processed variant of its negative, so the only thing that changes
across a rung is the condition under test.

Variant clips are named `<clip>__<axis><level>` and carry `derived_from`, so
they can never be mistaken for field footage, and their `conditions` block has
the degraded axis overwritten with the level actually applied.

usage:
  make_variants.py --pair fall-5916779           # that clip and its mate, all axes
  make_variants.py --pair smoke-fire-8365988 --axes darkness,occlusion --levels 1,2
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DEGRADE = ROOT / "tools" / "degrade.py"

# How a degraded axis reads back in the clip's `conditions` block, per level.
CONDITION_LABEL = {
    "resolution": {1: "240p-equivalent", 2: "120p-equivalent", 3: "60p-equivalent"},
    "darkness": {1: "dim", 2: "dark", 3: "very-dark"},
    "occlusion": {1: "17%-occluded", 2: "33%-occluded", 3: "50%-occluded"},
    "blur": {1: "light-motion-blur", 2: "motion-blur", 3: "heavy-motion-blur"},
    "compression": {1: "400kbps", 2: "150kbps", 3: "60kbps"},
}
# Which `conditions` key each axis overwrites.
CONDITION_KEY = {"resolution": "target_size", "darkness": "light",
                 "occlusion": "occlusion", "blur": "blur", "compression": "compression"}


def load_meta(clip_id: str) -> dict:
    p = ROOT / "clips" / clip_id / "meta.yaml"
    if not p.exists():
        raise SystemExit(f"no such clip: {clip_id}")
    return yaml.safe_load(p.read_text())


def make_variant(clip_id: str, meta: dict, axis: str, level: int) -> str:
    variant_id = f"{clip_id}__{axis}{level}"
    out_dir = ROOT / "clips" / variant_id
    out_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [sys.executable, str(DEGRADE), "--clip", str(ROOT / "clips" / clip_id / "clip.mp4"),
         "--axis", axis, "--level", str(level), "--out", str(out_dir / "clip.mp4")],
        check=True, capture_output=True)

    child = dict(meta)
    child["id"] = variant_id
    child["derived_from"] = clip_id
    child["tier"] = "variant"
    child["degradation"] = {"axis": axis, "level": level}
    child["pair"] = f"{meta['pair']}__{axis}{level}" if meta.get("pair") else None
    conditions = dict(meta.get("conditions") or {})
    conditions[CONDITION_KEY[axis]] = CONDITION_LABEL[axis][level]
    child["conditions"] = conditions
    # Drop provenance fields that describe the fetched original, not this render.
    child.pop("trim", None)

    (out_dir / "meta.yaml").write_text(
        f"# DERIVED from {clip_id} by tools/make_variants.py — {axis} level {level}.\n"
        f"# Not field footage. Its pair is the identically-degraded mate, so the only\n"
        f"# difference across this rung is the condition under test.\n"
        + yaml.safe_dump(child, sort_keys=False, allow_unicode=True, width=88))
    return variant_id


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pair", required=True,
                    help="either clip of a curated pair; both are degraded")
    ap.add_argument("--axes", default="resolution,darkness,occlusion,blur,compression")
    ap.add_argument("--levels", default="1,2,3")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg is required")

    meta = load_meta(args.pair)
    mate_id = meta.get("pair")
    if not mate_id:
        raise SystemExit(f"{args.pair} has no pair — degrading it alone would be "
                         f"unscoreable")
    mate = load_meta(mate_id)
    if meta.get("label") == mate.get("label"):
        raise SystemExit(f"{args.pair} and {mate_id} are both {meta.get('label')}")

    axes = [a.strip() for a in args.axes.split(",") if a.strip()]
    levels = [int(x) for x in args.levels.split(",") if x.strip()]

    made = 0
    for axis in axes:
        for level in levels:
            for clip_id, m in ((args.pair, meta), (mate_id, mate)):
                variant = make_variant(clip_id, m, axis, level)
                made += 1
            print(f"  {axis}{level}: {args.pair}__{axis}{level} + {mate_id}__{axis}{level}")
    print(f"{made} variant clip(s) from the pair {args.pair} / {mate_id}")


if __name__ == "__main__":
    main()
