#!/usr/bin/env python3
"""The condition curve: where a working cell stops working.

Only meaningful on a pair the model gets RIGHT when clean. The first attempt ran
the ladder on `smoke-fire`, where all three models scored 0/1 on the clean pair —
degrading something that already fails produces a flat line and measures nothing.
This refuses to plot a model whose level-0 cell is not a detection, and says so.

usage: ladder.py --run runs/ladder --pair object-removed-5241131
"""
from __future__ import annotations
import argparse, collections, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import verdict

ap = argparse.ArgumentParser()
ap.add_argument("--run", type=Path, required=True)
ap.add_argument("--out", type=Path, default=None)
a = ap.parse_args()

idx = {r["task_id"]: r for r in json.loads((a.run / "tasks.index.json").read_text())}
res = {}
for p in a.run.glob("*.jsonl"):
    if p.name == "tasks.jsonl":
        continue
    for line in p.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if "model" in r:
                res[(r["model"], r["id"])] = r

def split(clip):
    return (clip.split("__")[1][:-1], int(clip.split("__")[1][-1])) if "__" in clip else ("clean", 0)

cells = collections.defaultdict(dict)     # (model, axis, level) -> clip -> (is_pos, verdict)
for m in sorted({m for m, _ in res}):
    for row in idx.values():
        if row["question"] != "gate":
            continue
        r = res.get((m, row["task_id"]))
        if not r:
            continue
        ax, lv = split(row["clip"])
        v = verdict(r.get("answer", "") if r.get("ok") else "")
        cells[(m, ax, lv)][row["clip"]] = (row["label"] == "positive", v)

def discriminated(d):
    """1 if the model said yes to the positive and no to its look-alike."""
    pos = [(c, v) for c, (t, v) in d.items() if t]
    neg = [(c, v) for c, (t, v) in d.items() if not t]
    if not pos or not neg:
        return None
    return int(pos[0][1] is True and neg[0][1] is False)

models = sorted({m for m, _, _ in cells})
axes = [x for x in sorted({ax for _, ax, _ in cells}) if x != "clean"]
print("Condition curve — both halves of the pair degraded together, one variable at a time.")
print("A cell that does not work clean cannot show a curve; it is skipped and named.\n")
print(f"{'model':<20} {'axis':<12} {'clean':>6} {'L1':>5} {'L2':>5} {'L3':>5}")
print("-" * 60)
skipped = []
rows_out = []
for m in models:
    base = discriminated(cells.get((m, "clean", 0), {}))
    if base != 1:
        skipped.append(m)
        continue
    for ax in axes:
        vals = [discriminated(cells.get((m, ax, lv), {})) for lv in (1, 2, 3)]
        fmt = lambda v: "  -" if v is None else ("ok" if v else "..")
        print(f"{m:<20} {ax:<12} {'ok':>6} " + " ".join(f"{fmt(v):>5}" for v in vals))
        rows_out.append({"model": m, "axis": ax, "clean": 1,
                         "levels": vals})
for m in skipped:
    print(f"{m:<20} — skipped: does not discriminate the clean pair, so no curve exists")
print("\nok = discriminated (yes to the positive, no to its look-alike);  .. = lost it")
if a.out:
    a.out.write_text(json.dumps({"curves": rows_out, "skipped": skipped}, indent=2))
    print(f"\nwrote {a.out}")
