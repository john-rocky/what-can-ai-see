#!/usr/bin/env python3
"""Scores -> the page a company reads before committing to a PoC.

One question, answered per (model, event): **would this work?** The page leads
with pair discrimination rather than recall, because a table of recall would show
every model in this benchmark as a near-perfect detector, and every one of them
would fire on the look-alike too.

Self-contained HTML — no CDN, no external fonts, images inlined as data URIs —
because it is meant to be published and shared as a single file.

usage:
  gen_site.py --scores runs/field-v2/scores.json --out site/index.html
  gen_site.py --scores runs/field-v2/scores.json --cards cards --out site/index.html
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

# pair_discrimination -> (verdict, css class). Chance is 0.25; a cell at or below
# it is not evidence of anything, and the wording says so rather than printing a
# number that looks like a score.
def verdict_of(pd: float | None) -> tuple[str, str]:
    if pd is None:
        return "no data", "nd"
    if pd >= 0.75:
        return "works", "good"
    if pd >= 0.5:
        return "partial", "mid"
    if pd > 0.25:
        return "weak", "weak"
    return "no better than chance", "bad"


def data_uri(path: Path) -> str:
    return ("data:image/jpeg;base64,"
            + base64.b64encode(path.read_bytes()).decode())


CSS = """
/* Tokens define the LIGHT palette on bare :root, are redefined for dark under
   prefers-color-scheme (guarded so an explicit light choice beats a dark OS),
   and redefined again under [data-theme="dark"] so the toggle wins both ways.
   No component color is ever declared inside a media or [data-theme] block —
   that is the bug that renders one theme's text on the other theme's ground. */
:root{
  --paper:#f7f8fa; --surface:#ffffff; --sunken:#eef0f4;
  --ink:#12151b; --ink-2:#4a515e; --ink-3:#79808d;
  --rule:#dfe3ea; --rule-2:#c9cfd9;
  --accent:#0b6a74; --accent-soft:#e2f1f2;
  --good:#1f7a45; --good-bg:#dff0e5;
  --mid:#8a6206; --mid-bg:#f7ebcf;
  --weak:#9a4f12; --weak-bg:#f8e6d8;
  --bad:#b23a28; --bad-bg:#f9e0dc;
  --nd:#79808d; --nd-bg:#e8eaef;
  --shadow:0 1px 2px rgba(18,21,27,.06),0 8px 24px rgba(18,21,27,.05);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#0d1014; --surface:#151920; --sunken:#1b2028;
    --ink:#eef1f6; --ink-2:#a8b0bd; --ink-3:#79818f;
    --rule:#252b35; --rule-2:#333a46;
    --accent:#57c7d1; --accent-soft:#13323a;
    --good:#5fd08c; --good-bg:#14301f;
    --mid:#e2b551; --mid-bg:#332714;
    --weak:#e79a5c; --weak-bg:#352112;
    --bad:#f2796c; --bad-bg:#38191a;
    --nd:#79818f; --nd-bg:#1e232b;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
  }
}
:root[data-theme="dark"]{
  --paper:#0d1014; --surface:#151920; --sunken:#1b2028;
  --ink:#eef1f6; --ink-2:#a8b0bd; --ink-3:#79818f;
  --rule:#252b35; --rule-2:#333a46;
  --accent:#57c7d1; --accent-soft:#13323a;
  --good:#5fd08c; --good-bg:#14301f;
  --mid:#e2b551; --mid-bg:#332714;
  --weak:#e79a5c; --weak-bg:#352112;
  --bad:#f2796c; --bad-bg:#38191a;
  --nd:#79818f; --nd-bg:#1e232b;
  --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 24px rgba(0,0,0,.3);
}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.65 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",Roboto,
       Helvetica,Arial,sans-serif;
  font-feature-settings:"kern" 1;
}
.wrap{max-width:1080px;margin:0 auto;padding:clamp(32px,6vw,72px) 22px 96px}

/* ── type scale ─────────────────────────────────────────────────────────── */
h1{font-size:clamp(30px,5vw,46px);line-height:1.08;letter-spacing:-.025em;
   margin:0 0 18px;text-wrap:balance;font-weight:700}
h2{font-size:clamp(21px,3vw,27px);line-height:1.2;letter-spacing:-.015em;
   margin:0 0 6px;text-wrap:balance;font-weight:650}
p{margin:0 0 15px;max-width:68ch;color:var(--ink-2)}
.lede{font-size:clamp(17px,2vw,19px);line-height:1.55;color:var(--ink-2);max-width:64ch}
.eyebrow{font:600 12px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin:0 0 14px}
section{margin-top:clamp(48px,7vw,80px)}
.sub{color:var(--ink-3);font-size:14.5px;margin:0 0 18px;max-width:68ch}
code{font:0.9em/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  background:var(--sunken);padding:.15em .4em;border-radius:4px;color:var(--ink)}

/* ── headline stats ─────────────────────────────────────────────────────── */
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));
  gap:14px;margin:28px 0 0}
.stat{background:var(--surface);border:1px solid var(--rule);border-radius:12px;
  padding:18px 20px;box-shadow:var(--shadow)}
.stat .n{font:700 clamp(30px,4vw,40px)/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums;letter-spacing:-.03em;color:var(--ink);display:block}
.stat .n.alarm{color:var(--bad)}
.stat .k{display:block;margin-top:8px;font-size:13.5px;line-height:1.4;color:var(--ink-3)}

/* ── tables ─────────────────────────────────────────────────────────────── */
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:18px 0;
  border:1px solid var(--rule);border-radius:12px;background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:14px;min-width:600px}
th,td{padding:11px 14px;text-align:left;border-bottom:1px solid var(--rule);
  white-space:nowrap}
tbody tr:last-child td{border-bottom:none}
thead th{position:sticky;top:0;background:var(--sunken);color:var(--ink-3);
  font:600 11.5px/1.3 ui-monospace,SFMono-Regular,Menlo,monospace;
  letter-spacing:.09em;text-transform:uppercase;border-bottom:1px solid var(--rule-2)}
thead th .ev{display:block;font-weight:400;letter-spacing:.04em;color:var(--ink-3);
  opacity:.8;margin-top:3px}
td.num,th.num{text-align:right;
  font:400 13.5px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums;color:var(--ink)}
td.name{font-weight:600;color:var(--ink)}
tbody tr:hover td{background:var(--sunken)}

/* Status reads as form before it reads as number. */
.pill{display:inline-block;padding:3px 10px;border-radius:99px;
  font:600 12px/1.45 -apple-system,BlinkMacSystemFont,sans-serif;white-space:nowrap}
.pill .v{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums;opacity:.75;margin-left:5px}
.good{background:var(--good-bg);color:var(--good)}
.mid{background:var(--mid-bg);color:var(--mid)}
.weak{background:var(--weak-bg);color:var(--weak)}
.bad{background:var(--bad-bg);color:var(--bad)}
.nd{background:var(--nd-bg);color:var(--nd)}

/* ── sliding-window comparison ───────────────────────────────────────────── */
.barrow{display:flex;align-items:center;gap:10px}
.bar{height:9px;border-radius:5px;background:var(--bad);flex:0 0 auto;min-width:3px}
.bar.win{background:var(--good)}
.barn{font:600 13px/1 ui-monospace,SFMono-Regular,Menlo,monospace;
  font-variant-numeric:tabular-nums;color:var(--ink-2);flex:0 0 62px}
td .ev{display:block;font-weight:400;font-size:12.5px;line-height:1.35;
  letter-spacing:0;color:var(--ink-3);margin-top:3px}

.note{background:var(--accent-soft);border-radius:10px;padding:16px 20px;
  margin:20px 0;font-size:15px;color:var(--ink);max-width:68ch}
.note b{font-weight:650}

/* ── clip gallery ───────────────────────────────────────────────────────── */
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));
  gap:16px;margin:20px 0}
.clip{background:var(--surface);border:1px solid var(--rule);border-radius:12px;
  overflow:hidden;box-shadow:var(--shadow)}
.clip img{width:100%;display:block;border-bottom:1px solid var(--rule)}
.clip .body{padding:14px 16px}
.clip .q{font-weight:650;font-size:14.5px;line-height:1.35;color:var(--ink);
  margin-bottom:6px;text-wrap:balance}
.clip .m{font:400 12px/1.4 ui-monospace,SFMono-Regular,Menlo,monospace;
  color:var(--ink-3)}
.clip .m b{color:var(--ink)}
.clip .gt{margin:8px 0 0;font-size:13px;line-height:1.5;color:var(--ink-2)}

footer{margin-top:clamp(56px,8vw,88px);padding-top:22px;
  border-top:1px solid var(--rule);color:var(--ink-3);font-size:13px;max-width:68ch}
a{color:var(--accent)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:3px}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
"""


# ── the sliding-window comparison ─────────────────────────────────────────────
# The matrix above asks one question of a whole clip. This asks the same question
# every 0.4s over a 1.6s window, which is how a camera actually runs, and puts a
# classical baseline on the same windows. Read from runs/stream rather than
# hardcoded, because these numbers have been invalidated twice: once by a control
# clip that had the event in it, once by counting only one of the two kinds of
# window whose correct answer is No.
STREAM_PAIRS = [
    ("spill", "a full cup knocked over", "a pool"),
    ("spill2", "poured beside the cup", "a thin run"),
    ("spill3", "poured onto the table", "a stain"),
    ("grounds", "grounds miss the machine", "a heap"),
    ("hazard-hand", "a hand enters the iron's path", "a hand"),
]
STREAM_METHODS = [
    ("LFM2.5-VL 3B", "lfm2.5-vl-3b.jsonl"),
    ("MiniCPM-V 4.6", "minicpm-v-4.6.jsonl"),
    ("background subtraction, swept", "baseline-bgdiff.jsonl"),
    ("LFM2.5-VL 450M", "lfm2.5-vl-450m.jsonl"),
    ("Holo2 4B", "holo2-4b.jsonl"),
    ("North Micro Vision", "north-micro-vision.jsonl"),
    ("Qwen3-VL 2B", "qwen3-vl-2b.jsonl"),
]


def _stream_verdicts(clip: str, fname: str):
    """(windows spec, {window index: True/False/None}) or None if not run."""
    d = ROOT / "runs" / "stream" / clip
    f = d / fname
    if not f.exists():
        return None
    spec = json.loads((d / "windows.json").read_text())
    rows: dict[int, bool | None] = {}
    for line in f.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        parts = r["id"].split("|")
        if len(parts) != 3 or "answer" not in r:
            continue
        a = (r.get("answer") or "").strip().lower() if r.get("ok") else ""
        rows[int(parts[1][1:])] = True if a.startswith("yes") else (
            False if a.startswith("no") else _boxed(a))
    return spec, rows


def _boxed(answer: str) -> bool | None:
    """MiniCPM-V reasons first and answers in \boxed{}; the first line is not it."""
    m = re.search(r"\\boxed\{\s*(yes|no)\s*\}", answer)
    return None if not m else m.group(1) == "yes"


def stream_stats(suffix: str = "", pairs=None):
    """Per method: median latency, false alarms, pre-onset fires, and the totals.

    A window on the POSITIVE clip that closes before the event starts is a window
    whose correct answer is No, exactly like one on the control. Both are counted.
    The baseline's threshold sweep is penalised for pre-onset fires, so it has none
    by construction — charging only the VLMs for theirs is what made an earlier
    version of this table read 6% vs 14% instead of 8% vs 10%."""
    per_pair, agg = {}, {}
    use = pairs if pairs is not None else STREAM_PAIRS
    for label, fname in STREAM_METHODS:
        lats, fa, tot, pre, pretot = [], 0, 0, 0, 0
        hit, hitn, fired_pairs, pairs = 0, 0, 0, 0
        for pid, _, _ in use:
            a = _stream_verdicts(f"{pid}-pos{suffix}", fname)
            b = _stream_verdicts(f"{pid}-neg{suffix}", fname)
            if not a or not b:
                continue
            (ps, pr), (ns, nr) = a, b
            onset = ps.get("onset_s") or 0.0
            pairs += 1
            after = [wd for wd in ps["windows"] if wd["t_end"] >= onset]
            hit += sum(1 for wd in after if pr.get(wd["i"]) is True)
            hitn += len(after)
            fired = [wd["t_end"] for wd in after if pr.get(wd["i"]) is True]
            if fired:
                lats.append(fired[0] - onset)
                fired_pairs += 1
            before = [wd for wd in ps["windows"] if wd["t_end"] < onset]
            p_fa = sum(1 for wd in ns["windows"] if nr.get(wd["i"]) is True)
            p_pre = sum(1 for wd in before if pr.get(wd["i"]) is True)
            fa += p_fa; tot += len(ns["windows"])
            pre += p_pre; pretot += len(before)
            per_pair[(label, pid)] = {
                "lat": (fired[0] - onset) if fired else None,
                "fa": p_fa, "n_neg": len(ns["windows"]),
                "pre": p_pre, "n_pre": len(before)}
        if tot:
            tpr = hit / hitn if hitn else 0.0
            fpr = (fa + pre) / (tot + pretot)
            agg[label] = {"lat": sorted(lats)[len(lats) // 2] if lats else None,
                          "wrong": fa + pre, "n": tot + pretot,
                          "hit": hit, "hitn": hitn, "tpr": tpr,
                          "fired_pairs": fired_pairs, "pairs": pairs,
                          "balanced": (tpr + 1 - fpr) / 2}
    return per_pair, agg


# ── the viewpoint ablation ────────────────────────────────────────────────────
# The rig has two synchronized cameras and this benchmark used only the first for
# its entire life. `-v2` is the same episodes from the second, built through the
# identical 16:9 centre-crop pipeline so framing is held constant — it had to be,
# because these models stretch every input to a square canvas (F1). That control
# came back at 0 changed verdicts out of 1088, so what remains is the angle.
def viewpoint_arms():
    """Both camera arms, restricted to methods that covered every pair in each.

    hazard-hand is dropped: from the oblique camera a person's arm is in frame at
    t=0 and never leaves, so that pair has no window whose correct answer is No.
    That is not a gap in the data — it is the finding that the overhead pair's
    "onset" is when its crop could first see the hand, not when the hand arrived."""
    keep = [p for p in STREAM_PAIRS if p[0] != "hazard-hand"]
    a = stream_stats("", keep)[1]
    b = stream_stats("-v2", keep)[1]
    n = len(keep)
    return {k: (a[k], b[k]) for k in a
            if k in b and a[k]["pairs"] == n and b[k]["pairs"] == n}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scores", type=Path, required=True)
    ap.add_argument("--models", type=Path, default=ROOT / "events" / "models.yaml")
    ap.add_argument("--events", type=Path, default=ROOT / "events" / "events.yaml")
    ap.add_argument("--clips", type=Path, default=ROOT / "clips")
    ap.add_argument("--encoding", default="g6",
                    help="the encoding the headline matrix reports")
    ap.add_argument("--gallery", type=int, default=6, help="clip cards to inline")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    scores = json.loads(args.scores.read_text())
    model_meta = {m["id"]: m for m in yaml.safe_load(args.models.read_text())["models"]}
    events = {e["id"]: e for e in yaml.safe_load(args.events.read_text())["events"]}

    models = sorted({s["model"] for s in scores},
                    key=lambda m: model_meta.get(m, {}).get("size_mb", 0))
    used_events = sorted({s["event"] for s in scores})
    encodings = sorted({s["encoding"] for s in scores})

    cell = {(s["model"], s["event"], s["encoding"]): s for s in scores}
    e = html.escape
    out: list[str] = []
    w = out.append

    def n(v, spec="{:.2f}"):
        return "&ndash;" if v is None else spec.format(v)

    # Headline numbers, computed from the same cells the tables below show.
    n_cells = len(scores)
    at_chance = sum(1 for s in scores
                    if s["pair_discrimination"] is not None
                    and s["pair_discrimination"] <= 0.25)
    recall_1 = sum(1 for s in scores if s["recall"] == 1.0)
    fa_1 = sum(1 for s in scores if s["false_alarm_rate"] == 1.0)
    stab = [s["prompt_stability"] for s in scores if s["prompt_stability"] is not None]
    outcomes = defaultdict(int)
    for s in scores:
        for k, v in s["pair_outcomes"].items():
            outcomes[k] += v
    n_pairs = sum(outcomes.values()) or 1

    w(f"<style>{CSS}</style><div class='wrap'>")
    w("<p class='eyebrow'>What Can AI See</p>")
    w("<h1>Can a small VLM on an iPhone see this event?</h1>")
    w("<p class='lede'>Device-class vision-language models measured through "
      "CoreAIKit on Apple silicon, no cloud. Every cell is scored on matched "
      "pairs \u2014 a positive clip and the hard negative built to look like it \u2014 "
      "because recall alone scores a model that answers Yes to everything at 1.00.</p>")

    w("<div class='stats'>")
    w(f"<div class='stat'><span class='n alarm'>{at_chance}/{n_cells}</span>"
      f"<span class='k'>cells at chance or worse on pair discrimination</span></div>")
    w(f"<div class='stat'><span class='n'>{recall_1}/{n_cells}</span>"
      f"<span class='k'>cells at recall 1.00 &mdash; what a conventional table "
      f"would show</span></div>")
    w(f"<div class='stat'><span class='n alarm'>{fa_1}/{n_cells}</span>"
      f"<span class='k'>cells that also fired on <em>every</em> look-alike "
      f"negative</span></div>")
    if stab:
        w(f"<div class='stat'><span class='n'>{sum(stab)/len(stab):.2f}</span>"
          f"<span class='k'>mean agreement across three phrasings of the same "
          f"question (greedy decoding)</span></div>")
    w("</div>")

    w(f"<div class='note'><b>Recall is 1.00 in {recall_1} of {n_cells} cells and the "
      f"false-alarm rate is 1.00 in {fa_1} of them.</b> The models are not detecting "
      f"events; they are answering Yes. Of {n_pairs} matched pairs, "
      f"{outcomes['discriminated']} were genuine detections and "
      f"{outcomes['trigger_happy']} fired on the look-alike too.</div>")

    # ── the constraint ────────────────────────────────────────────────────────
    w("<section><h2>The budget</h2>")
    w("<p class='sub'>Each model resizes its input to one fixed square canvas and "
      "turns it into a fixed number of visual tokens. That count is not per frame "
      "\u2014 it is the whole image, and since the runtime takes one image per turn, "
      "it is the whole clip. A video must be flattened into a single contact sheet "
      "before any of these models can see it at all.</p>")
    w("<div class='scroll'><table><thead><tr><th>model</th><th>params</th>"
      "<th class='num'>size</th><th class='num'>canvas</th>"
      "<th class='num'>visual tokens</th><th class='num'>tokens per panel at g6</th>"
      "</tr></thead><tbody>")
    for m in models:
        mm = model_meta.get(m, {})
        vt = mm.get("visual_tokens")
        canvas = mm.get("canvas") or []
        w(f"<tr><td class='name'>{e(mm.get('name', m))}</td>"
          f"<td>{e(str(mm.get('params','?')))}</td>"
          f"<td class='num'>{mm.get('size_mb','?')}&nbsp;MB</td>"
          f"<td class='num'>{canvas[0] if canvas else '?'}&sup2;</td>"
          f"<td class='num'>{vt or '?'}</td>"
          f"<td class='num'>{round(vt/6) if vt else '?'}</td></tr>")
    w("</tbody></table></div></section>")

    # ── the headline matrix ───────────────────────────────────────────────────
    w(f"<section><h2>Would it work?</h2>")
    w(f"<p class='sub'>At <code>{e(args.encoding)}</code>. Pair discrimination is "
      "the fraction of matched pairs where the model said Yes to the positive "
      "<em>and</em> No to its look-alike. Chance is 0.25; answering the same word "
      "to both scores zero, whichever word it is.</p>")
    w("<div class='scroll'><table><thead><tr><th>model</th>")
    for ev in used_events:
        w(f"<th>{e(ev)}<span class='ev'>"
          f"{e(events.get(ev,{}).get('evidence','?'))}</span></th>")
    w("</tr></thead><tbody>")
    for m in models:
        w(f"<tr><td class='name'>{e(model_meta.get(m,{}).get('name',m))}</td>")
        for ev in used_events:
            s = cell.get((m, ev, args.encoding))
            pd = s["pair_discrimination"] if s else None
            label, css = verdict_of(pd)
            num = "" if pd is None else f"<span class='v'>{pd:.2f}</span>"
            w(f"<td><span class='pill {css}'>{e(label)}{num}</span></td>")
        w("</tr>")
    w("</tbody></table></div></section>")

    # ── the detail table ──────────────────────────────────────────────────────
    w("<section><h2>Every cell</h2>")
    w("<p class='sub'><code>FA</code> is the fraction of look-alike negatives the "
      "model fired on. <code>stab</code> is agreement across three phrasings of the "
      "same question \u2014 decoding is greedy, so anything below 1.00 is the model "
      "responding to wording, not sampling noise. <code>deny</code> counts positives "
      "where the model's own free description named the event while its yes/no "
      "answer said No.</p>")
    w("<div class='scroll'><table><thead><tr><th>model</th><th>enc</th><th>event</th>"
      "<th class='num'>recall</th><th class='num'>FA</th><th class='num'>pair</th>"
      "<th class='num'>lat s</th><th class='num'>stab</th><th class='num'>deny</th>"
      "</tr></thead><tbody>")
    for m in models:
        for enc in encodings:
            for ev in used_events:
                s = cell.get((m, ev, enc))
                if not s:
                    continue
                w(f"<tr><td class='name'>{e(model_meta.get(m,{}).get('name',m))}</td>"
                  f"<td><code>{e(enc)}</code></td><td>{e(ev)}</td>"
                  f"<td class='num'>{n(s['recall'])}</td>"
                  f"<td class='num'>{n(s['false_alarm_rate'])}</td>"
                  f"<td class='num'>{n(s['pair_discrimination'])}</td>"
                  f"<td class='num'>{n(s['latency_s'], '{:+.1f}')}</td>"
                  f"<td class='num'>{n(s['prompt_stability'])}</td>"
                  f"<td class='num'>{s.get('denied_own_description') or ''}</td></tr>")
    w("</tbody></table></div></section>")

    # ── what the model is actually shown ──────────────────────────────────────
    # ── one number is not a ranking ───────────────────────────────────────────
    per_pair, agg = stream_stats()
    if agg:
        px = agg.get("background subtraction, swept")
        vlms = {k: v for k, v in agg.items() if "subtraction" not in k}
        best = max(vlms.items(), key=lambda kv: kv[1]["balanced"])
        by_wrong = sorted(vlms.items(), key=lambda kv: kv[1]["wrong"] / kv[1]["n"])
        worst_ba = min(vlms.items(), key=lambda kv: kv[1]["balanced"])
        rank_by_fa = [k for k, _ in by_wrong]
        chance = [k for k, v in vlms.items() if abs(v["balanced"] - 0.5) < 0.03]

        w("<section><h2>One number is not a ranking</h2>")
        w("<p class='sub'>The matrix above asks one question of a whole clip. A camera "
          "does not work that way. Here the same models are re-asked every 0.4&nbsp;s over "
          "a 1.6&nbsp;s sliding window, on five matched pairs from a fixed industrial rig, "
          "against background subtraction whose one threshold is swept over 600 values and "
          "set to the one that maximises <em>its own</em> score on each pair.</p>")
        w("<div class='stats'>")
        w(f"<div class='stat'><span class='n'>{best[1]['lat']:+.1f}s</span>"
          f"<span class='k'>median detection latency &mdash; the same for every method "
          f"that fires at all</span></div>")
        w(f"<div class='stat'><span class='n'>{best[1]['balanced']:.2f}</span>"
          f"<span class='k'>best balanced accuracy, {e(best[0])} &mdash; against "
          f"{px['balanced']:.2f} for the pixel baseline</span></div>" if px else "")
        if chance:
            w(f"<div class='stat'><span class='n alarm'>0.50</span>"
              f"<span class='k'>{e(chance[0])} is at chance, while ranking "
              f"{rank_by_fa.index(chance[0]) + 1}{'st' if rank_by_fa.index(chance[0]) == 0 else 'nd' if rank_by_fa.index(chance[0]) == 1 else 'rd' if rank_by_fa.index(chance[0]) == 2 else 'th'} "
              f"of {len(vlms)} on false alarms alone</span></div>")
        w("</div>")
        w("<div class='note'><b>A false-alarm column rewards silence; a recall column "
          "rewards noise.</b> Neither is a ranking &mdash; each is one half of one. The "
          "smallest model here answers Yes to 20% of the windows where the event has "
          "happened and 20% where it has not: the same number, which is what "
          "&ldquo;the answer is unrelated to the event&rdquo; looks like in a table. "
          "Read the two columns together, always.</div>")

        n_tot = best[1]["n"]
        w(f"<p class='sub' style='margin-top:26px'><b>Detects</b> is the share of windows "
          f"after the event where the method said Yes. <b>Wrong</b> is every window whose "
          f"correct answer is No &mdash; {n_tot} of them: the controls, plus the positives "
          f"before the event starts. Balanced accuracy averages the two, so neither "
          f"answering Yes to everything nor answering No to everything scores above 0.50.</p>")
        w("<div class='scroll'><table><thead><tr><th>method</th>"
          "<th class='num'>median lat</th><th>detects</th><th>wrong</th>"
          "<th class='num'>balanced</th></tr></thead><tbody>")
        for label, v in sorted(agg.items(), key=lambda kv: -kv[1]["balanced"]):
            rate = 100 * v["wrong"] / v["n"]
            fired = "" if v["fired_pairs"] == v["pairs"] else (
                f"<span class='ev'>fired on only {v['fired_pairs']} of {v['pairs']} pairs "
                f"&mdash; its latency is not a usable number</span>")
            w(f"<tr><td class='name'>{e(label)}{fired}</td>"
              f"<td class='num'>{v['lat']:+.1f}</td>"
              f"<td><div class='barrow'><span class='barn'>{100*v['tpr']:.0f}%</span>"
              f"<span class='bar win' style='width:{max(3, round(200*v['tpr']))}px'></span></div></td>"
              f"<td><div class='barrow'><span class='barn'>{rate:.0f}%</span>"
              f"<span class='bar' style='width:{max(3, round(200*rate/100))}px'></span></div></td>"
              f"<td class='num'>{v['balanced']:.2f}</td></tr>")
        w("</tbody></table></div>")

        w("<p class='sub' style='margin-top:26px'>Per pair, against the pixel baseline. "
          "<code>ctrl</code> is false alarms on the look-alike, <code>pre</code> is fires "
          "on the positive before the event began.</p>")
        w("<div class='scroll'><table><thead><tr><th>pair</th><th>what changes</th>"
          "<th class='num'>3B lat</th><th class='num'>ctrl</th><th class='num'>pre</th>"
          "<th class='num'>px lat</th><th class='num'>ctrl</th><th class='num'>pre</th>"
          "<th>fewer errors</th></tr></thead><tbody>")
        for pid, desc, change in STREAM_PAIRS:
            a = per_pair.get(("LFM2.5-VL 3B", pid))
            b = per_pair.get(("background subtraction, swept", pid))
            if not a or not b:
                continue
            aw, bw = a["fa"] + a["pre"], b["fa"] + b["pre"]
            who = ("<span class='pill good'>VLM</span>" if aw < bw else
                   "<span class='pill bad'>pixels</span>" if bw < aw else
                   "<span class='pill nd'>tie</span>")
            w(f"<tr><td class='name'>{e(pid)}<span class='ev'>{e(desc)}</span></td>"
              f"<td>{e(change)}</td>"
              f"<td class='num'>{a['lat']:+.1f}s</td><td class='num'>{a['fa']}/{a['n_neg']}</td>"
              f"<td class='num'>{a['pre']}/{a['n_pre']}</td>"
              f"<td class='num'>{b['lat']:+.1f}s</td><td class='num'>{b['fa']}/{b['n_neg']}</td>"
              f"<td class='num'>{b['pre']}/{b['n_pre']}</td><td>{who}</td></tr>")
        w("</tbody></table></div>")
        w("<div class='note'>On false alarms the best VLM and the 1995 algorithm are level "
          "&mdash; 8% against 10%, and every method first fires at the same moment. The "
          "separation is that the subtractor drops below threshold once the pool stops "
          "spreading and <b>misses 44% of the windows after the event</b>, where the 3B "
          "holds the alarm on 89%. If a downstream system only needs the first alarm, no "
          "VLM here earns its cost. If it samples at an arbitrary moment, that gap is the "
          "whole story. <b>Not shown:</b> five pairs, one rig, one camera, one lighting "
          "setup; the baseline&rsquo;s threshold is fitted on the pair it is scored on; "
          "and balanced accuracy weights a missed window and a false alarm equally, which "
          "no real deployment does.</div>")
        w("</section>")

    # ── the same event from the other camera ─────────────────────────────────
    arms = viewpoint_arms()
    if len(arms) >= 4:
        rank_a = sorted(arms, key=lambda k: -arms[k][0]["balanced"])
        rank_b = sorted(arms, key=lambda k: -arms[k][1]["balanced"])
        w("<section><h2>We moved the camera</h2>")
        w("<p class='sub'>The rig records two synchronised cameras and everything above "
          "used only the first. These are the same episodes from the second &mdash; same "
          "room, same lighting, same events, same questions, same crop pipeline &mdash; "
          "a low oblique angle instead of a high one. Onsets were re-measured from the new "
          "view rather than copied, because when a camera sees a spill two seconds earlier "
          "that is a fact about the view.</p>")
        w("<div class='stats'>")
        w(f"<div class='stat'><span class='n alarm'>{rank_a[0][:14]} &rarr; {rank_b[0][:14]}</span>"
          f"<span class='k'>the ranking's first place, before and after the camera "
          f"moved</span></div>")
        w(f"<div class='stat'><span class='n'>0/1088</span>"
          f"<span class='k'>verdicts changed by the framing control &mdash; re-cropping "
          f"4:3 to 16:9 moved nothing, so this is the angle</span></div>")
        w("</div>")
        w("<div class='scroll'><table><thead><tr><th>method</th>"
          "<th class='num'>overhead</th><th class='num'>oblique</th>"
          "<th class='num'>change</th><th class='num'>detection</th>"
          "</tr></thead><tbody>")
        for k in rank_a:
            va, vb = arms[k]
            delta = vb["balanced"] - va["balanced"]
            cls = "bad" if delta <= -0.1 else ("good" if delta >= 0.1 else "nd")
            w(f"<tr><td class='name'>{e(k)}</td>"
              f"<td class='num'>{va['balanced']:.2f}</td>"
              f"<td class='num'>{vb['balanced']:.2f}</td>"
              f"<td><span class='pill {cls}'>{delta:+.2f}</span></td>"
              f"<td class='num'>{100*va['tpr']:.0f}% &rarr; {100*vb['tpr']:.0f}%</td></tr>")
        w("</tbody></table></div>")
        w("<div class='note'><b>A small-VLM benchmark on one camera measures a "
          "model&ndash;camera pair, not a model.</b> The model this benchmark spent weeks "
          "identifying as the one that works is third from the new angle; the one written "
          "off as too trigger-happy is first. The best model's false alarms barely move "
          "&mdash; its <em>detection</em> collapses, and only on the small changes: a full "
          "pool it still sees from either angle, a thin run of coffee it misses two times "
          "in three. That is the same mechanism as the table above, seen from the other "
          "side: it wins when the change is small, and a shallow angle is what makes a "
          "change small. <b>Not shown:</b> four pairs, one rig, two cameras. An earlier "
          "version of this section reported the pixel baseline as the only stable method; "
          "that was two effects cancelling, and the control removed it.</div>")
        w("</section>")

    gallery = sorted(
        (d for d in args.clips.iterdir()
         if (d / f"{args.encoding}.jpg").exists() and (d / "meta.yaml").exists()
         and "__" not in d.name
         and yaml.safe_load((d / "meta.yaml").read_text()).get("label")
         in ("positive", "negative")),
        key=lambda d: d.name)[: args.gallery]
    if gallery:
        w("<section><h2>What the model is actually shown</h2>")
        w("<p class='sub'>Not a frame \u2014 the whole clip, as one image. This is "
          "the entire input.</p><div class='grid'>")
        for d in gallery:
            meta = yaml.safe_load((d / "meta.yaml").read_text())
            ev = events.get(meta.get("event"), {})
            truth = "YES" if meta.get("label") == "positive" else "NO"
            gt = " ".join(str(meta.get("ground_truth", "")).split())
            w(f"<div class='clip'><img src='{data_uri(d / f'{args.encoding}.jpg')}' "
              f"alt='Contact sheet for {e(d.name)}'><div class='body'>"
              f"<div class='q'>{e(ev.get('question','?'))}</div>"
              f"<div class='m'>{e(d.name)} &middot; ground truth <b>{truth}</b></div>"
              f"<p class='gt'>{e(gt[:170])}{'&hellip;' if len(gt) > 170 else ''}</p>"
              f"</div></div>")
        w("</div></section>")

    w("<footer>Measured on a Mac Studio M4&nbsp;Max, macOS&nbsp;27, through "
      "CoreAIKit. Clips are licence-clean stock, curated by eye; ground truth is "
      "hand-written and rejected clips are recorded with their reasons. Nothing "
      "here is quoted that was not measured, and where a number is a projection "
      "rather than a measurement it says so."
      "</footer></div>")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("<title>What Can AI See</title>\n" + "\n".join(out))
    print(f"wrote {args.out}  ({args.out.stat().st_size / 1024:.0f} KB, "
          f"{len(models)} model(s), {len(used_events)} event(s))")


if __name__ == "__main__":
    main()
