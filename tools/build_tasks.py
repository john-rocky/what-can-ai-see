#!/usr/bin/env python3
"""Cross clips x encodings x questions into the task file wcas-run consumes.

Three questions per (clip, encoding). They are not variations on one measurement —
they answer three different business questions and they fail independently:

  gate   the event's yes/no question. The only one that scores. Asked of the
         positive AND its matched negative, because recall without the paired
         false-alarm number is the oldest way to make a detector look good.
  open   "what is happening" with no hint of the event. This is the one a human
         reads to form an impression, so it is the demo content — and it also
         catches the model that answers the gate correctly while describing a
         completely different scene.
  when   "which panel does it first happen in". Detection delay, in panels,
         convertible to seconds because the panel timestamps are known.

Every prompt states the panel count and that reading order is time order. Leaving
that implicit measures whether the model guesses the convention, which is not what
anyone is buying.

usage:
  build_tasks.py --clips clips --models lfm2.5-vl-450m,north-micro-vision \
                 --encodings g6 --out runs/tasks.jsonl
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "tools" / "sheet.py"

# The panel-order preamble, stated for every multi-panel encoding. `f1` gets none —
# it is one frame and there is no order to explain.
PREAMBLE = ("The image is a contact sheet of {n} frames taken from a single video clip. "
            "They are in time order: panel 1 is the earliest, panel {n} is the latest.")

OPEN_Q = ("Describe what happens in this clip. Two sentences at most. "
          "Say what changes between the earliest and latest frames.")

GATE_Q = ("{question} Answer with the single word Yes or No on the first line, "
          "then one short sentence naming the panel and the visual evidence.")

WHEN_Q = ("{question} If yes, reply with the number of the earliest panel in which it is "
          "visible, as a bare number. If it never happens, reply None.")

# Stability variants. Same clip, same sheet, same question — three ways of asking.
# A model whose verdict flips between these is not detecting the event, it is
# responding to the phrasing, and no amount of averaging over clips will reveal
# that. Decoding is greedy, so any disagreement here is prompt sensitivity alone
# and not sampling noise.
#
# v1 is GATE_Q above (the strict-format ask). The other two vary one thing each:
# v2 removes the format scaffolding entirely, v3 inverts the framing so that "No"
# is the affirmative answer — which catches a model that has simply learned that
# the agreeable reply to a yes/no question about an image is "Yes".
GATE_VARIANTS = {
    "gate": GATE_Q,
    "gate2": "{question}",
    "gate3": ("Look at the clip and decide: {question} "
              "Reply Yes only if you can point to the evidence. "
              "If you cannot see it, reply No."),
}

# The F9 follow-up. On the synthetic conveyor pair every model asserted a
# cross-panel relationship that was not in the pixels — one described stationary
# boxes as travelling left to right and offered that as its evidence. The models
# read a panel and generalise rather than comparing panels.
#
# This variant forces the comparison to happen in the output before the verdict
# does: enumerate the panels first, then judge. If the failure is representational
# the scaffold changes nothing; if it is a reasoning shortcut, this recovers it.
# Either answer is worth having, which is why it is a separate scored question
# rather than a replacement for `gate`.
PANEL_Q = ("First, for each of the {n} panels in order, write one short line: the panel "
           "number, then where the main subject or objects are within that panel. "
           "Do not skip a panel and do not summarise. "
           "Then, on a new line, answer this question with the single word Yes or No: "
           "{question}")


def load_events(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text())
    return {e["id"]: e for e in doc["events"]}


def render_sheet(clip_dir: Path, encoding: str) -> tuple[Path, dict]:
    """Build the sheet if it is not already there; return its path and metadata."""
    out = clip_dir / f"{encoding}.jpg"
    meta_path = clip_dir / f"{encoding}.json"
    if out.exists() and meta_path.exists():
        return out, json.loads(meta_path.read_text())
    proc = subprocess.run(
        [sys.executable, str(SHEET), "--video", str(clip_dir / "clip.mp4"),
         "--encoding", encoding, "--out", str(out)],
        capture_output=True, text=True, check=True,
    )
    meta = json.loads(proc.stdout)
    meta_path.write_text(json.dumps(meta, indent=2))
    return out, meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", type=Path, default=ROOT / "clips")
    ap.add_argument("--events", type=Path, default=ROOT / "events" / "events.yaml")
    ap.add_argument("--encodings", default="g6",
                    help="comma-separated: f1,g2,g6,g12,g20,diff")
    ap.add_argument("--questions", default="gate,open,when",
                    help="comma-separated subset of gate,gate2,gate3,panels,open,when "
                         "(gate2/gate3 are the stability variants; panels forces a "
                         "per-panel enumeration before the verdict)")
    ap.add_argument("--only", default=None, help="comma-separated clip ids")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    events = load_events(args.events)
    encodings = [e.strip() for e in args.encodings.split(",") if e.strip()]
    questions = [q.strip() for q in args.questions.split(",") if q.strip()]
    only = {c.strip() for c in args.only.split(",")} if args.only else None

    clip_dirs = sorted(d for d in args.clips.iterdir()
                       if (d / "meta.yaml").exists() and (d / "clip.mp4").exists())
    if only:
        clip_dirs = [d for d in clip_dirs if d.name in only]
    if not clip_dirs:
        raise SystemExit(f"no clips with meta.yaml + clip.mp4 under {args.clips}")

    # A freshly fetched clip is labelled UNVERIFIED until a human has watched its
    # contact sheet. Scoring one would invent ground truth, so they are skipped
    # loudly rather than silently: an unnoticed skip is how a batch quietly
    # becomes half the size it was meant to be.
    unverified = [d.name for d in clip_dirs
                  if yaml.safe_load((d / "meta.yaml").read_text()).get("label")
                  not in ("positive", "negative")]
    if unverified:
        print(f"skipping {len(unverified)} unverified clip(s): "
              f"{', '.join(sorted(unverified)[:6])}"
              f"{' …' if len(unverified) > 6 else ''}")
        clip_dirs = [d for d in clip_dirs if d.name not in set(unverified)]
    if not clip_dirs:
        raise SystemExit("no verified clips — curate meta.yaml labels first")

    lines, index = [], []
    for clip_dir in clip_dirs:
        meta = yaml.safe_load((clip_dir / "meta.yaml").read_text())
        event = events.get(meta["event"])
        if event is None:
            raise SystemExit(f"{clip_dir.name}: unknown event {meta['event']!r}")
        for encoding in encodings:
            sheet_path, sheet_meta = render_sheet(clip_dir, encoding)
            n = sheet_meta["panels"]
            preamble = "" if n == 1 else PREAMBLE.format(n=n) + " "
            bodies = {"open": OPEN_Q,
                      "when": WHEN_Q.format(question=event["question"])}
            for name, template in GATE_VARIANTS.items():
                bodies[name] = template.format(question=event["question"])
            # `panels` needs the panel count, so it is built here rather than in
            # the GATE_VARIANTS table. Meaningless on f1 — one panel is not a
            # comparison — so it is only offered for multi-panel encodings.
            if n > 1:
                bodies["panels"] = PANEL_Q.format(n=n, question=event["question"])
            for q in questions:
                task_id = f"{meta['id']}|{encoding}|{q}"
                lines.append(json.dumps({
                    "id": task_id,
                    "image": str(sheet_path.resolve()),
                    "prompt": preamble + bodies[q],
                }))
                index.append({
                    "task_id": task_id, "clip": meta["id"], "encoding": encoding,
                    "question": q, "event": meta["event"], "label": meta["label"],
                    "pair": meta.get("pair"), "onset_s": meta.get("onset_s"),
                    "tier": meta.get("tier", "field"),
                    "shows_transition": meta.get("shows_transition"),
                    "panels": n, "panel_times": sheet_meta["times"],
                    "tokens_per_panel_at_196": sheet_meta["tokens_per_panel_at_196"],
                    "conditions": meta.get("conditions", {}),
                })

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    index_path = args.out.with_suffix(".index.json")
    index_path.write_text(json.dumps(index, indent=2))
    print(f"{len(lines)} tasks -> {args.out}")
    print(f"index      -> {index_path}")
    print(f"clips {len(clip_dirs)} x encodings {len(encodings)} x questions {len(questions)}")


if __name__ == "__main__":
    main()
