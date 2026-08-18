#!/usr/bin/env python3
"""Score the genre corpus: does the answer hold when it should, change when it should.

Two kinds of clip, and they need different questions asked of them.

  stable      The scene holds and the correct answer never changes. What is
              measured is whether the MODEL holds. Accuracy alone hides the
              interesting half: a model can be right on average while changing
              its mind eleven times across a still cafe shot, and a person
              watching that bar flicker learns something no accuracy column
              carries. So `flips` is reported beside `correct`.

  transition  The answer changes once, at a measured second. Scored as before:
              did it fire, when, and did it fire early.

The point of the split is that the four metrics this benchmark set out to report
include judgement stability, and until now nothing measured it on video.

usage: genre_score.py            # every labelled genre clip
       genre_score.py --model lfm2.5-vl-3b
"""
from __future__ import annotations
import argparse, json, pathlib, sys
import yaml
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from card import verdict_of

ROOT = pathlib.Path(__file__).resolve().parent.parent
STREAM = ROOT / "runs" / "stream"


def meta(cid):
    p = ROOT / "clips" / cid / "meta.yaml"
    return yaml.safe_load("\n".join(l for l in p.read_text().split("\n")
                                    if not l.startswith("#"))) or {}


def verdicts(cid, model):
    d = STREAM / cid
    f = d / f"{model}.jsonl"
    if not f.exists() or not (d / "windows.json").exists():
        return None
    spec = json.loads((d / "windows.json").read_text())
    rows = {}
    for line in f.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "answer" not in r:
            continue
        rows[int(r["id"].split("|")[1][1:])] = (
            verdict_of(r.get("answer", "")) if r.get("ok") else None)
    seq = [rows.get(w["i"]) for w in spec["windows"]]
    return spec, seq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    clips = []
    for d in sorted((ROOT / "clips").iterdir()):
        if not (d / "meta.yaml").exists():
            continue
        m = meta(d.name)
        if m.get("genre") and m.get("label") != "rejected":
            clips.append((d.name, m))
    models = ([args.model] if args.model else
              sorted({p.stem for c, _ in clips for p in (STREAM / c).glob("*.jsonl")
                      if not p.stem.startswith(("tasks", "frames", "detect-"))}))

    print("STABLE clips — the correct answer never changes; does the model's?")
    print(f"{'clip':<24}{'genre':<13}{'want':>5}" + "".join(f"{m[:11]:>13}" for m in models))
    stab = {m: [0, 0, 0] for m in models}      # correct, answered, flips
    cov = {m: [0, 0] for m in models}          # answered, asked
    for cid, mt in clips:
        if mt.get("kind") != "stable":
            continue
        want = mt.get("expected") == "yes"
        row = f"{cid:<24}{str(mt['genre'])[:12]:<13}{('yes' if want else 'no'):>5}"
        for m in models:
            got = verdicts(cid, m)
            if not got:
                row += f"{'-':>13}"; continue
            _, seq = got
            ok = sum(1 for v in seq if v is want)
            n = sum(1 for v in seq if v is not None)
            # A window the model never answered is excluded from the denominator,
            # which quietly flatters a flaky model: MiniCPM-V 4.6 returns "session
            # ended without producing a response" on ~10% of windows and its 99%
            # is therefore 99% OF THE ONES IT ANSWERED. Coverage is printed in the
            # totals so the two are never confused.
            cov[m][0] += n; cov[m][1] += len(seq)
            fl = sum(1 for a, b in zip(seq, seq[1:])
                     if a is not None and b is not None and a != b)
            stab[m][0] += ok; stab[m][1] += n; stab[m][2] += fl
            row += f"{f'{100*ok//max(1,n)}% /{fl}f':>13}"
        print(row)
    print(f"\n{'TOTAL':<24}{'':<13}{'':>5}" +
          "".join(f"{f'{100*stab[m][0]//max(1,stab[m][1])}% /{stab[m][2]}f':>13}" for m in models))
    print(f"{'answered':<24}{'':<13}{'':>5}" +
          "".join(f"{f'{100*cov[m][0]//max(1,cov[m][1])}%':>13}" for m in models))
    print("  '82% /11f' = right on 82% of the windows it ANSWERED, changed its mind 11 times.")
    print("  'answered' is how many it replied to at all — a model that declines is not right.")

    print("\n\nTRANSITION clips — the answer should change once, at the onset.")
    print(f"{'clip':<24}{'genre':<13}{'onset':>6}" + "".join(f"{m[:11]:>13}" for m in models))
    for cid, mt in clips:
        if mt.get("kind") != "transition":
            continue
        row = f"{cid:<24}{str(mt['genre'])[:12]:<13}{mt.get('onset_s'):>6}"
        for m in models:
            got = verdicts(cid, m)
            if not got:
                row += f"{'-':>13}"; continue
            spec, seq = got
            on = mt.get("onset_s") or 0
            pre = [v for w, v in zip(spec["windows"], seq) if w["t_end"] < on]
            post = [(w, v) for w, v in zip(spec["windows"], seq) if w["t_end"] >= on]
            early = sum(1 for v in pre if v is True)
            fired = next((w["t_end"] - on for w, v in post if v is True), None)
            hit = sum(1 for _, v in post if v is True)
            row += f"{(f'{fired:+.1f}s' if fired is not None else 'never') + f' e{early}':>13}"
        print(row)
    print("  '+0.4s e0' = first fired 0.4s after the onset, with 0 early fires before it.")


if __name__ == "__main__":
    main()
