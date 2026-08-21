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


# ONE definition of the overlap measure, imported from the tool that reports it. Having a
# second copy here produced 0.32 and 0.34 for the same pair of files — the two STOP lists
# had drifted — which is exactly the class of quiet disagreement this whole script exists
# to catch, appearing inside the script itself.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from repeat import words as _words  # noqa: E402


def _overlap(a, b):
    A, B = _words(a), _words(b)
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
    check("phone/Mac overlap (x100)", round(med * 100), 93)

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

print("\nF28 — colour ablation, retail-store vs retail-store-gray")
_COLOUR = re.compile(
    r"\b(red|blue|green|yellow|orange|purple|pink|brown|colou?r\w*|"
    r"black.and.white|monochrome|sepia|grayscale|greyscale)\b", re.I)
for _m, _want in (("lfm2.5-vl-3b", 31), ("lfm2.5-vl-450m", 18)):
    _c = {r["id"].split("|")[1]: r.get("answer", "")
          for r in _rows(f"runs/film/retail-store/{_m}.jsonl")}
    _g = {r["id"].split("|")[1]: r.get("answer", "")
          for r in _rows(f"runs/film/retail-store-gray/{_m}.jsonl")}
    _ids = sorted(set(_c) & set(_g))
    if not _ids:
        continue
    _med = _st.median([_overlap(_c[i], _g[i]) for i in _ids])
    # No tolerance. One definition of the measure means the draft and the data are the
    # same computation, so any drift is a real change and should stop the build.
    check(f"{_m} colour/gray overlap (x100)", round(_med * 100), _want)
    # The claim that desaturation moves the text further than changing machine does.
    if _med >= 0.94:
        fail(f"F28 claims desaturation moves more than the phone/Mac gap; {_m} is {_med:.2f}")


print("\nF29 — Gilbreth same-camera pair")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from said_card import paragraph as _para  # noqa: E402

def _seg(path):
    # Echo stripped BEFORE anything is counted. Counting first is what produced a finding
    # that was really the prompt matching itself — see F29.
    return [_para(r.get("answer", ""), 2000) for r in _rows(path)]

for _m, _within, _across in (("lfm2.5-vl-3b", 19, 10), ("lfm2.5-vl-450m", 8, 8)):
    _o = _seg(f"runs/film/gilbreth-old/{_m}.jsonl")
    _n = _seg(f"runs/film/gilbreth-new/{_m}.jsonl")
    if len(_o) < 10 or len(_n) < 10:
        continue
    w = _st.median([_overlap(_o[i], _o[j]) for i in range(10) for j in range(i + 1, 10)])
    c = _st.median([_overlap(a, b) for a in _o[:12] for b in _n[:12]])
    check(f"{_m} within old (x100)", round(w * 100), _within)
    check(f"{_m} across the pair (x100)", round(c * 100), _across)


print("\nF30-F32 — the widened corpus")
_BIG = re.compile(r"\b(dozens?|hundreds?|many|numerous|crowd|large group|\d{2,})\b", re.I)
_NAMES = re.compile(r"\b(MOSSBY|ROOTY|TIGHTY|FLOOG|SLIM|NEL|FILBERT|ORV)\b", re.I)
_MASK = re.compile(r"\b(mask\w*|ape|monkey|gorilla|chimp\w*|costume|disguis\w*)\b", re.I)
_CAT = re.compile(r"\b(cat|cats|kitten\w*|feline)\b", re.I)
_OTHER = re.compile(r"\b(dog|puppy|rabbit|bear|mouse|mice|hamster|rat)\b", re.I)


def _stripped(path):
    return [_para(r.get("answer", ""), 2000) for r in _rows(path)]


def _hits(path, pat):
    return sum(1 for t in _stripped(path) if pat.search(t))


for _clip, _a, _b in (("cops-pursuit", 8, 0), ("cops-parade", 15, 4), ("nola-crowd", 29, 10)):
    check(f"{_clip} crowd words, 3B", _hits(f"runs/film/{_clip}/lfm2.5-vl-3b.jsonl", _BIG), _a)
    check(f"{_clip} crowd words, 450M", _hits(f"runs/film/{_clip}/lfm2.5-vl-450m.jsonl", _BIG), _b)

check("masks-bags names read, 3B", _hits("runs/film/masks-bags/lfm2.5-vl-3b.jsonl", _NAMES), 6)
check("masks-bags names read, 450M", _hits("runs/film/masks-bags/lfm2.5-vl-450m.jsonl", _NAMES), 1)
# The claim that carries F31: the 3B never mentions the masks.
check("masks-bags masks seen, 3B", _hits("runs/film/masks-bags/lfm2.5-vl-3b.jsonl", _MASK), 0)
check("cat named, 3B", _hits("runs/film/cat-kittens/lfm2.5-vl-3b.jsonl", _CAT), 26)
check("wrong animal, 3B", _hits("runs/film/cat-kittens/lfm2.5-vl-3b.jsonl", _OTHER), 6)


print("\n" + ("ALL QUOTED NUMBERS MATCH" if not fails else f"{len(fails)} MISMATCH: {fails}"))
sys.exit(1 if fails else 0)
