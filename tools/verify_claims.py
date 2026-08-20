#!/usr/bin/env python3
"""Recompute every number quoted in the post drafts, from the run files.

A draft is a copy of the data, and copies drift — especially after a correction.
The spill numbers in this repo were quoted, then invalidated by a contaminated
control, then recomputed; anything written down in between is wrong. This
recomputes each quoted figure from `runs/` so a mismatch is caught before the
post goes out rather than after.

usage: verify_claims.py
"""
from __future__ import annotations
import json, pathlib, re, sys
from pathlib import Path
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from card import verdict_of

ROOT = pathlib.Path(__file__).resolve().parent.parent

A2_PAIRS = [("spill-pos","spill-neg"),("spill2-pos","spill2-neg"),
            ("spill3-pos","spill3-neg"),("grounds-pos","grounds-neg"),
            ("hazard-hand-pos","hazard-hand-neg")]
MODELS = {"LFM2.5-VL 3B":"lfm2.5-vl-3b.jsonl",
          "LFM2.5-VL 450M":"lfm2.5-vl-450m.jsonl",
          "MiniCPM-V 4.6":"minicpm-v-4.6.jsonl","North Micro Vision":"north-micro-vision.jsonl",
          "Qwen3-VL 2B":"qwen3-vl-2b.jsonl","Holo2 4B":"holo2-4b.jsonl",
          "bg-diff":"baseline-bgdiff.jsonl","RF-DETR+person":"baseline-detect-presence.jsonl"}

def read(clip, fn):
    p = ROOT/"runs/stream"/clip/fn
    if not p.exists(): return None
    spec = json.loads((ROOT/"runs/stream"/clip/"windows.json").read_text())
    rows = {}
    for l in p.read_text().splitlines():
        if l.strip():
            r = json.loads(l)
            rows[int(r["id"].split("|")[1][1:])] = verdict_of(r.get("answer","")) if r.get("ok") else None
    return spec, rows

fails = []
def check(name, got, want, tol=0):
    ok = abs(got - want) <= tol
    print(f"  {'OK ' if ok else 'FAIL'} {name}: draft says {want}, data says {got}")
    if not ok: fails.append(name)

print("A2 — five pairs. Every window whose correct answer is No counts, on BOTH")
print("     halves: the control, and the positive before the event starts. Counting")
print("     only the control understates the VLMs, because the baseline's threshold")
print("     sweep penalises pre-onset fires and so has none by construction.")
agg = {}
for label, fn in MODELS.items():
    lats, fa, tot, pre, pretot, n = [], 0, 0, 0, 0, 0
    for pos, neg in A2_PAIRS:
        a, b = read(pos, fn), read(neg, fn)
        if not a or not b: continue
        (ps, pr), (ns, nr) = a, b
        on = ps.get("onset_s") or 0.0; n += 1
        after = [w["t_end"] for w in ps["windows"]
                 if pr.get(w["i"]) is True and w["t_end"] >= on]
        if after: lats.append(after[0]-on)
        fa += sum(1 for w in ns["windows"] if nr.get(w["i"]) is True)
        tot += len(ns["windows"])
        before = [w for w in ps["windows"] if w["t_end"] < on]
        pre += sum(1 for w in before if pr.get(w["i"]) is True)
        pretot += len(before)
    if n: agg[label] = (n, sorted(lats)[len(lats)//2] if lats else None,
                        fa, tot, pre, pretot)
for label,(n,med,fa,tot,pre,pretot) in agg.items():
    print(f"    {label:<18} n={n} lat={med:+.1f}s  ctrl={fa}/{tot}  pre={pre}/{pretot}"
          f"  wrong={fa+pre}/{tot+pretot} ({100*(fa+pre)/(tot+pretot):.0f}%)")

# Detection, not just silence. A method that answers No to everything scores a
# perfect false-alarm rate; ranking on that column alone put LFM2.5-VL 450M third
# of seven when it is at chance. Balanced accuracy is checked here so that cannot
# recur silently.
print("\n     detection sustain and balanced accuracy")
bal = {}
for label, fn in MODELS.items():
    hit = hitn = 0
    for pos, neg in A2_PAIRS:
        a = read(pos, fn)
        if not a: continue
        ps, pr = a
        on = ps.get("onset_s") or 0.0
        after = [w for w in ps["windows"] if w["t_end"] >= on]
        hit += sum(1 for w in after if pr.get(w["i"]) is True); hitn += len(after)
    if not hitn or label not in agg: continue
    _, _, fa, tot, pre, pretot = agg[label]
    tpr, fpr = hit/hitn, (fa+pre)/(tot+pretot)
    bal[label] = (tpr+1-fpr)/2
    print(f"    {label:<18} detects {hit}/{hitn} ({100*tpr:.0f}%)  "
          f"wrong {100*fpr:.0f}%  balanced {bal[label]:.2f}")
for name, want in [("LFM2.5-VL 3B", 0.90), ("Holo2 4B", 0.78),
                   ("bg-diff", 0.73), ("Qwen3-VL 2B", 0.65)]:
    if name in bal: check(f"balanced acc {name} (x100)", round(100*bal[name]), round(100*want))
if "LFM2.5-VL 450M" in bal:
    b = bal["LFM2.5-VL 450M"]
    check("LFM2.5-VL 450M is at chance (x100)", round(100*b), 50)
    if b > 0.55:
        print("  NOTE 450M is no longer at chance — the A2 post says it is")

_, _, fa3, tot3, pre3, pt3 = agg["LFM2.5-VL 3B"]
_, _, fab, totb, preb, ptb = agg["bg-diff"]
check("no-answer windows", tot3 + pt3, 236)
check("3B wrong", fa3 + pre3, 20)
check("bg-diff wrong", fab + preb, 23)
check("bg-diff pre-onset (0 by construction)", preb, 0)
check("Qwen3-VL 2B wrong", agg["Qwen3-VL 2B"][2] + agg["Qwen3-VL 2B"][4], 165)
check("median latency 3B (x10)", round(agg["LFM2.5-VL 3B"][1]*10), 3)
# The false-alarm column alone must never be reported as a ranking: on it the 3B
# and the subtractor are 8% vs 10%, which A2 called a tie for one draft. The
# separation is in detection sustain, so both are asserted here.
if abs((fab + preb) - (fa3 + pre3)) < 0.02 * (tot3 + pt3):
    print("  OK   3B and bg-diff are within 2 points on false alarms — A2 must NOT")
    print("       claim a false-alarm win; the claim rests on detection sustain")
else:
    print("  NOTE the false-alarm gap moved past 2 points — A2 says they tie there")
if bal.get("LFM2.5-VL 3B", 0) - bal.get("bg-diff", 0) < 0.05:
    print("  NOTE the 3B no longer leads bg-diff on balanced accuracy — rewrite A2")

print("\nA1 — stock corpus, one inference per clip")
# field-v2, NOT field-v1. field-v1 is 2 models and 32 cells; the draft and the
# site both quote the full run. Checking the smaller file was itself a live drift
# for a while — the tool passed while the numbers it guarded had moved.
sc = json.loads((ROOT/"runs/field-v2/scores.json").read_text())
check("cells", len(sc), 136)
check("models", len({s["model"] for s in sc}), 6)
check("recall==1.00 cells", sum(1 for s in sc if s["recall"] == 1.0), 98)
check("FA==1.00 cells", sum(1 for s in sc if s["false_alarm_rate"] == 1.0), 78)
at_chance = sum(1 for s in sc if s["pair_discrimination"] is not None
                and s["pair_discrimination"] <= 0.25)
check("cells at chance or worse", at_chance, 86)
oc = {}
for s in sc:
    for k, v in s["pair_outcomes"].items():
        oc[k] = oc.get(k, 0) + v
print(f"    pair outcomes: {oc}  total {sum(oc.values())}")
check("matched pairs", sum(oc.values()), 134)
check("discriminated", oc["discriminated"], 23)
check("trigger-happy", oc["trigger_happy"], 99)
check("blind", oc["blind"], 9)
check("inverted", oc["inverted"], 3)

print("\nA3 — hand in danger zone")
for label in ("LFM2.5-VL 3B","bg-diff","RF-DETR+person"):
    a, b = read("hazard-hand-pos", MODELS[label]), read("hazard-hand-neg", MODELS[label])
    if not a or not b: continue
    (ps,pr),(ns,nr) = a, b
    on = ps["onset_s"]
    after = [w["t_end"] for w in ps["windows"] if pr.get(w["i"]) is True and w["t_end"]>=on]
    fa = sum(1 for w in ns["windows"] if nr.get(w["i"]) is True)
    print(f"    {label:<18} lat={after[0]-on:+.1f}s  FA={fa}/{len(ns['windows'])}")

print("\nA4 — kite")
import collections
for c in ("damage-jar-pos","damage-bottle-pos"):
    n = 0
    for l in (ROOT/"runs/stream"/c/"detect-rf-detr.jsonl").read_text().splitlines():
        if l.strip():
            n += sum(1 for b in json.loads(l).get("boxes",[]) if b["label"]=="kite")
    print(f"    {c:<20} kite detections = {n}")


# ---------------------------------------------------------------- F25-F27, on-device
# The phone numbers were measured once each on one device. Re-deriving them here is what
# keeps a quoted figure honest after the run directory has moved on: every other section
# in this file exists because a number in a draft had drifted from the data behind it.

import statistics as _st


def _rows(p):
    out = []
    for line in Path(p).read_text().splitlines() if Path(p).exists() else []:
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def _overlap(a, b):
    STOP = {"the", "and", "with", "that", "this", "from", "for", "are", "was", "were",
            "image", "frame", "frames", "panel", "panels", "sheet", "contact", "sequence",
            "camera", "feed", "seconds", "second", "shows", "showing", "captures", "time",
            "order", "earliest", "latest", "scene", "first", "final", "last"}
    def w(t):
        out = set()
        for x in re.findall(r"[a-z]+", (t or "").lower()):
            if len(x) < 3 or x in STOP:
                continue
            for suf in ("ing", "ed", "es", "s"):
                if len(x) > 5 and x.endswith(suf):
                    x = x[: -len(suf)]
                    break
            out.add(x)
        return out
    A, B = w(a), w(b)
    return len(A & B) / len(A | B) if (A | B) else 1.0


print("\nF25 — run-to-run stability")
_det = sorted(Path("runs/determinism").glob("sweep-*-r1.jsonl")) if Path("runs/determinism").exists() else []
for r1 in _det:
    model = r1.name[len("sweep-"):-len("-r1.jsonl")]
    r2 = r1.with_name(r1.name.replace("-r1.jsonl", "-r2.jsonl"))
    a, b = {x["id"]: x.get("answer", "") for x in _rows(r1)}, {x["id"]: x.get("answer", "") for x in _rows(r2)}
    ids = sorted(set(a) & set(b))
    if not ids:
        continue
    med = _st.median([_overlap(a[i], b[i]) for i in ids])
    check(f"{model} is deterministic on the Mac (x100)", round(med * 100), 100)

_g = sorted(Path("runs/phone/determinism").glob("greedy-r*.jsonl"))
if len(_g) >= 2:
    runs = [{x["id"]: x.get("answer", "") for x in _rows(p)} for p in _g]
    ids = sorted(set.intersection(*(set(r) for r in runs)))
    med = _st.median([_overlap(runs[0][i], runs[1][i]) for i in ids])
    check("system model with --greedy is deterministic (x100)", round(med * 100), 100)

print("\nF26 — phone vs Mac, LFM2.5-VL 450M, 27 windows")
_ph = {x["id"]: x for x in _rows("runs/phone/lfm2.5-vl-450m.jsonl")}
_mc = {x["id"]: x for x in _rows("runs/macmirror/lfm2.5-vl-450m.jsonl")}
_ids = sorted(set(_ph) & set(_mc))
if _ids:
    med = _st.median([_overlap(_ph[i].get("answer", ""), _mc[i].get("answer", "")) for i in _ids])
    check("windows compared", len(_ids), 27)
    # Stated as 0.94 in F26; allow the last digit to move, not the claim.
    if abs(med - 0.94) > 0.02:
        fail(f"F26 phone/Mac overlap: draft says 0.94, data says {med:.2f}")
    else:
        print(f"  OK  phone/Mac overlap: draft says 0.94, data says {med:.2f}")

print("\nF27 — on-device speed")
if _ph:
    ms = [r["ms"] for r in _ph.values() if r.get("ok")]
    med_s = _st.median(ms) / 1000
    if abs(med_s - 4.68) > 0.15:
        fail(f"450M median per window: draft says 4.68s, data says {med_s:.2f}s")
    else:
        print(f"  OK  450M median per window: draft says 4.68s, data says {med_s:.2f}s")
    check("450M answered / refused on the phone",
          sum(1 for r in _ph.values() if r.get("ok")), 27)
    k = len(ms) // 3
    first, last = _st.mean(ms[:k]) / 1000, _st.mean(ms[-k:]) / 1000
    if last <= first:
        fail(f"F27 claims it slows down; first third {first:.2f}s, last {last:.2f}s")
    else:
        print(f"  OK  slows within the run: {first:.2f}s -> {last:.2f}s")

_sys = _rows("runs/phone/determinism/greedy-r1.jsonl")
if _sys:
    check("system model refusals on the phone (greedy)",
          sum(1 for r in _sys if not r.get("ok")), 1)

print("\n" + ("ALL QUOTED NUMBERS MATCH" if not fails else f"{len(fails)} MISMATCH: {fails}"))
sys.exit(1 if fails else 0)
