#!/usr/bin/env python3
"""What does a model bring up when nothing is asked of it?

`neutral.py` shows a scene and says only "describe what is happening". Nothing in
the reply is right or wrong; what matters is what it CONTAINS. This sorts the
descriptions into kinds of observation and reports, per model, how often each kind
appears at all.

The categories are the meaning axes from `events/genres.yaml` — the same cut used
to build the everyday corpus, so a coverage map here lines up with the accuracy
numbers there. A model that never mentions a surface being wet is a model whose
"is the ground wet?" score is measuring something it was not going to volunteer.

**The word lists are crude and that is deliberate.** A learned classifier would be
another model's opinion sitting under the headline number, and this project has
been burned by exactly that shape of hidden judgement. Crude and printable beats
accurate and opaque: `--examples` prints the sentences behind every count so the
classification can be argued with. Where a list is obviously wrong, fix the list —
it is nine lines of vocabulary, not a training run.

What this does NOT do is check whether the observation is true. A model that says
"a person is holding a cup" when there is no cup is counted under OBJECT and under
PEOPLE, the same as one that is right. Grounding is a separate pass against the
object detector; this pass is about attention, not accuracy.

usage:
  coverage.py
  coverage.py --examples 2
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEUTRAL = ROOT / "runs" / "neutral"

CATEGORIES = {
    "people":   r"\b(person|people|man|men|woman|women|worker|hand|arm|someone|"
                r"individual|figure|customer|child)\w*",
    "count":    r"\b(one|two|three|four|several|multiple|both|group|pair|number of|"
                r"a few|many)\b",
    "action":   r"\b(walk|writ|eat|drink|pour|hold|reach|move|carry|place|pick|"
                r"put|sit|stand|lift|push|climb|fall|open|close|clean|cook)\w*",
    # Suffix wildcards are dangerous here and two of them were wrong: `pan\w*`
    # matched "panel", which appears in the PROMPT, and `car\w*` matched "camera",
    # which also appears in the prompt. Any model echoing the instruction back
    # scored 100% on objects without naming a single one. Bounded plurals now, and
    # the prompt's own vocabulary is excluded below.
    "object":   r"\b(cups?|glass(es)?|bottles?|jars?|tables?|bowls?|machines?|"
                r"conveyors?|belts?|box(es)?|tools?|doors?|signs?|bench(es)?|"
                r"shel(f|ves)|robots?|arms?|pans?|laptops?|notebooks?|cars?|"
                r"forklifts?|skateboards?)\b",
    "spatial":  r"\b(on top of|on the|under|beside|next to|behind|in front|inside|"
                r"between|above|below|left|right|corner|edge|centre|center)\b",
    "material": r"\b(wet|dry|dirty|clean|spill|liquid|brown|dust|powder|stain|"
                r"puddle|shatter|broken|crack)\w*",
    "ambient":  r"\b(rain|snow|fog|dark|bright|night|daylight|lit|shadow|weather|"
                r"sunny|overcast)\w*",
    "text":     r"\b(sign|text|label|says|reads|word|letter|writing on|logo)\w*",
    "temporal": r"\b(then|after|before|begins|starts|stops|continues|remains|"
                r"throughout|no longer|still|now|change|same)\w*",
    "hedge":    r"\b(appears|seems|likely|possibly|may be|might|suggest|indicat|"
                r"unclear|difficult to)\w*",
}
COMPILED = {k: re.compile(v, re.I) for k, v in CATEGORIES.items()}
LEAD = re.compile(r"^\s*(yes|no)\b[\.,:;]?\s*", re.I)


# The prompt's own words, removed before categorising. A model that returns the
# instruction verbatim — Holo2 4B does this on most windows — otherwise scores as
# though it had described a camera, a panel and a sequence.
ECHO = re.compile(
    r"(the image is a contact sheet[^.]*\.|contact sheet of \d+ frames[^.]*\.|"
    r"covering the last [\d.]+s of a camera feed[^.]*\.|"
    r"in time order[^.]*\.|panel \d+ is the (earliest|latest)[^.]*\.)", re.I)


def body(answer: str) -> str:
    t = LEAD.sub("", (answer or "").strip(), count=1)
    return " ".join(ECHO.sub(" ", t).split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", type=int, default=0,
                    help="print N sentences per category so the rule can be checked")
    args = ap.parse_args()

    files = sorted(p for p in NEUTRAL.glob("*.jsonl") if p.stem != "tasks")
    if not files:
        raise SystemExit("no neutral runs yet")

    hits = defaultdict(lambda: defaultdict(int))
    total = defaultdict(int)
    words = defaultdict(list)
    ex = defaultdict(list)
    for f in files:
        m = f.stem
        for line in f.read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if not r.get("ok"):
                continue
            txt = body(r.get("answer", ""))
            if not txt:
                continue
            total[m] += 1
            words[m].append(len(txt.split()))
            for cat, rx in COMPILED.items():
                if rx.search(txt):
                    hits[m][cat] += 1
                    if len(ex[(m, cat)]) < args.examples:
                        ex[(m, cat)].append(txt[:120])

    models = [f.stem for f in files]
    print("Share of neutral descriptions that mention each kind of observation.")
    print("Not accuracy — what the model volunteers when nothing is asked.\n")
    print(f"{'category':<11}" + "".join(f"{m[:11]:>13}" for m in models))
    print("-" * (11 + 13 * len(models)))
    for cat in CATEGORIES:
        row = f"{cat:<11}"
        for m in models:
            t = total[m] or 1
            row += f"{100*hits[m][cat]//t:>12}%"
        print(row)
    print("-" * (11 + 13 * len(models)))
    print(f"{'windows':<11}" + "".join(f"{total[m]:>13}" for m in models))
    print(f"{'median len':<11}" + "".join(
        f"{(sorted(words[m])[len(words[m])//2] if words[m] else 0):>10} wd" for m in models))

    if args.examples:
        print("\nExamples, so the word lists can be checked:")
        for m in models:
            print(f"\n{m}")
            for cat in CATEGORIES:
                for s in ex[(m, cat)]:
                    print(f"   {cat:<10}“{s}”")


if __name__ == "__main__":
    main()
