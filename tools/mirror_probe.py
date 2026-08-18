#!/usr/bin/env python3
"""Does the answer survive a horizontal flip?

Every clip in this corpus is public — Pexels stock, kantine's HuggingFace
recordings — so the models may well have seen them in training. That is not a
caveat to note and move past: if a model is retrieving a memorised caption rather
than reading the picture, every number here measures the wrong thing.

A mirror is the cheapest probe available. Flipping left-right changes nothing
semantic — a cat on a bench is still on the bench, two people are still two — but
the pixels no longer match anything in a training set.

The test is ASYMMETRIC and saying so is the point:

  answers hold   evidence the model is reading the picture. Strong-ish.
  answers move   inconclusive. Could be lost retrieval; could be ordinary
                 sensitivity to layout, which vision models genuinely have.
                 A mirror does not distinguish those, and nothing here pretends
                 it does.

There is already one piece of evidence from the main run that does not need this
probe at all: if these clips had been memorised with their stock captions ("two
women talking at a cafe"), the counting question would be easy. It is the one
question every model fails.

usage: mirror_probe.py
"""
from __future__ import annotations
import json, pathlib, sys
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from card import verdict_of

ROOT = pathlib.Path(__file__).resolve().parent.parent
STREAM = ROOT / "runs" / "stream"


def seq(cid, model):
    d = STREAM / cid
    f = d / f"{model}.jsonl"
    if not f.exists() or not (d / "windows.json").exists():
        return None
    spec = json.loads((d / "windows.json").read_text())
    rows = {}
    for line in f.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if "answer" in r:
                rows[int(r["id"].split("|")[1][1:])] = (
                    verdict_of(r.get("answer", "")) if r.get("ok") else None)
    return [rows.get(w["i"]) for w in spec["windows"]]


def meta(cid):
    p = ROOT / "clips" / cid / "meta.yaml"
    return yaml.safe_load("\n".join(l for l in p.read_text().split("\n")
                                    if not l.startswith("#"))) or {}


def main():
    pairs = []
    for d in sorted((ROOT / "clips").iterdir()):
        if d.name.endswith("-mir") and (d / "meta.yaml").exists():
            base = d.name[:-4]
            if (ROOT / "clips" / base).exists():
                pairs.append((base, d.name))
    models = sorted({p.stem for b, m in pairs for p in (STREAM / m).glob("*.jsonl")
                     if not p.stem.startswith(("tasks", "frames", "detect-"))})
    if not models:
        raise SystemExit("no mirrored results yet")

    print("Per-window agreement between a clip and its mirror image.\n")
    print(f"{'clip':<24}{'genre':<13}" + "".join(f"{m[:11]:>13}" for m in models))
    tot = {m: [0, 0] for m in models}
    for base, mir in pairs:
        mt = meta(base)
        row = f"{base:<24}{str(mt.get('genre'))[:12]:<13}"
        for m in models:
            a, b = seq(base, m), seq(mir, m)
            if not a or not b:
                row += f"{'-':>13}"; continue
            n = min(len(a), len(b))
            both = [(x, y) for x, y in zip(a[:n], b[:n]) if x is not None and y is not None]
            same = sum(1 for x, y in both if x == y)
            tot[m][0] += same; tot[m][1] += len(both)
            row += f"{f'{100*same//max(1,len(both))}% of {len(both)}':>13}"
        print(row)
    print(f"\n{'AGREEMENT':<24}{'':<13}" +
          "".join(f"{f'{100*tot[m][0]//max(1,tot[m][1])}%':>13}" for m in models))

    print("\nAccuracy on the stable clips, original vs mirror "
          "(the answer should not care which way round the scene is):")
    print(f"{'clip':<24}{'want':>5}" + "".join(f"{m[:11]:>13}" for m in models))
    for base, mir in pairs:
        mt = meta(base)
        if mt.get("kind") != "stable":
            continue
        want = mt.get("expected") == "yes"
        row = f"{base:<24}{('yes' if want else 'no'):>5}"
        for m in models:
            a, b = seq(base, m), seq(mir, m)
            if not a or not b:
                row += f"{'-':>13}"; continue
            def acc(s):
                d = [v for v in s if v is not None]
                return 100 * sum(1 for v in d if v is want) // max(1, len(d))
            row += f"{f'{acc(a)}%->{acc(b)}%':>13}"
        print(row)


if __name__ == "__main__":
    main()
