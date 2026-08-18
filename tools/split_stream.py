#!/usr/bin/env python3
"""Split a combined streaming run back into per-clip result files.

Models are run over one concatenated task file so each one loads exactly once —
driving wcas-run per (model, clip) meant 90 cold model loads, and with the Metal
shader cache purged that was 20+ minutes each. The task id already carries the
clip (`<clip>|w000|gate`), so the results split cleanly afterwards and every other
tool keeps reading the per-clip layout it expects.

usage: split_stream.py --combined runs/stream/_all18
"""
from __future__ import annotations
import argparse, collections, json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--combined", type=Path, required=True)
a = ap.parse_args()

for src in sorted(a.combined.glob("*.jsonl")):
    # Any tasks* file is INPUT, not results. This matched only the exact name
    # "tasks.jsonl" until a per-model input file called tasks-holo2-4b.jsonl was
    # split into every clip directory as though it were a model's verdicts —
    # where live.py would have drawn it as a row of unparseable answers.
    if src.name.startswith("tasks"):
        continue
    per: dict[str, list[str]] = collections.defaultdict(list)
    for line in src.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "id" not in r:
            continue
        per[r["id"].split("|")[0]].append(line)
    for clip, rows in per.items():
        out = a.combined.parent / clip / src.name
        if not out.parent.exists():
            continue
        # Merge rather than overwrite: a clip may already hold answers from an
        # earlier per-clip run, and the truncation bug taught the cost of assuming.
        existing = {}
        if out.exists():
            for l in out.read_text().splitlines():
                if l.strip():
                    existing[json.loads(l)["id"]] = l
        for l in rows:
            existing[json.loads(l)["id"]] = l
        out.write_text("\n".join(existing.values()) + "\n")
    print(f"{src.name}: {sum(len(v) for v in per.values())} rows -> {len(per)} clip(s)")
