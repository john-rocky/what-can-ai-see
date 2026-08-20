#!/usr/bin/env python3
"""List the strings a check-translation map is still missing.

Every card ships in two cuts: the model's English and a Japanese translation for
checking. The translation is keyed by the exact string that gets drawn, so a new
run, a new `--lines` setting, or a change to the sentence extractor all produce
keys the map has never seen — and the card silently renders them with a `[未訳]`
tag rather than failing.

Doing the whole map again each time is wasteful and error-prone: the first pass
here was 236 strings written out by hand in list order, and two of them went
missing, which put every later translation off by one until the mismatch was
caught by counting. So: print only what is NOT already translated, translate that,
and merge. The map grows and nothing is retyped.

  ja_todo.py --run runs/film/general-cannon runs/film/general-bridge --map runs/film/ja.json
  ja_todo.py --run … --lines 5            # paragraph form rather than first clause
  ja_todo.py --merge new.txt --map runs/film/ja.json     # new.txt = one line per TODO, in order

usage note: --merge asserts the line count matches the TODO list it would have
printed, because a silent off-by-one here mistranslates every later card.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from said_card import paragraph, sentence  # noqa: E402


def strings(runs: list[Path], lines: int) -> list[str]:
    pick, limit = ((sentence, 200) if lines <= 2 else (paragraph, lines * 100))
    seen: dict[str, None] = {}
    for run in runs:
        for f in sorted(run.glob("*.jsonl")):
            if f.stem in ("tasks", "frames") or f.stem.startswith("detect-"):
                continue
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not d.get("ok"):
                    continue
                s = pick(d.get("answer", ""), limit)
                if s:
                    seen.setdefault(s, None)
    return sorted(seen)


# Terms that cannot legitimately vanish in translation. This exists because an
# off-by-one in a hand-written list is invisible: every line is a plausible
# Japanese sentence, and the card renders happily with the wrong caption under
# every clip. Two separate insertions were needed to realign a 236-line list, the
# second one landed seven rows late, and only a spot check on the word "cannon"
# revealed it. A missing marker is not proof of an error — a translator may render
# "horseback" without the character for horse — so this prints suspects to read,
# not a verdict.
MARKERS = [("cannon", "大砲"), ("rifle", "ライフル"), ("locomotive", "機関車"),
           ("bridge", "橋"), ("river", "川"), ("wildfire", "山火事"),
           ("forest fire", "森林火災"), ("derail", "脱線"), ("soldier", "兵"),
           ("baseball", "野球"), ("W.B.A.R.R.", "W.B.A.R.R."), ("panel", "パネル"),
           ("smoke", "煙"), ("explosion", "爆発"), ("horse", "馬")]


def verify(have: dict) -> int:
    # Word boundaries, not substrings. Without them "river" matched "driver's seat"
    # and the checker reported a mistranslation in a line that had no river in it —
    # the same substring bug that made "pan\\w*" match "panel" and "car\\w*" match
    # "camera" in the coverage tool.
    pats = [(re.compile(r"(?<![a-z])" + re.escape(e) + r"(?![a-z])", re.I), e, j)
            for e, j in MARKERS]
    pairs = {k: v for k, v in have.items() if not k.startswith("_")}
    bad = []
    for k, v in pairs.items():
        missing = [e for pat, e, j in pats if pat.search(k) and j not in v]
        if missing:
            bad.append((missing, k, v))
    print(f"{len(pairs)} pairs checked, {len(bad)} with a marker that did not survive")
    for missing, k, v in bad[:25]:
        print(f"\n  missing {missing}\n  EN {k[:110]}\n  JA {v[:90]}")
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", nargs="+", type=Path, required=True)
    ap.add_argument("--map", type=Path, required=True)
    ap.add_argument("--lines", type=int, default=2)
    ap.add_argument("--verify", action="store_true",
                    help="check every pair for markers that must survive translation")
    ap.add_argument("--merge", type=Path, default=None,
                    help="file of translations, one per line, in the printed order")
    args = ap.parse_args()

    have = json.loads(args.map.read_text()) if args.map.exists() else {}

    if args.verify:
        raise SystemExit(verify(have))
    todo = [s for s in strings(args.run, args.lines) if s not in have]

    if not args.merge:
        for i, s in enumerate(todo):
            print(f"{i:03d}|{s}")
        print(f"\n{len(todo)} untranslated of {len(strings(args.run, args.lines))} "
              f"({len(have) - sum(1 for k in have if k.startswith('_'))} already in the map)",
              file=sys.stderr)
        return

    new = [l.rstrip("\n") for l in args.merge.read_text().splitlines() if l.strip()]
    if len(new) != len(todo):
        raise SystemExit(f"{len(new)} translations for {len(todo)} strings — refusing to "
                         f"merge, the pairing would be off by {len(todo) - len(new)}")
    have.update(dict(zip(todo, new)))
    args.map.write_text(json.dumps(have, ensure_ascii=False, indent=1))
    print(f"merged {len(new)}; map now holds "
          f"{sum(1 for k in have if not k.startswith('_'))}")


if __name__ == "__main__":
    main()
