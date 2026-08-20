#!/usr/bin/env python3
"""Assemble the phone app's payload: the same windows the Mac ran, as bundle resources.

The device bench answers one question the whole repo has been assuming: everything here
was measured on a Mac Studio M4 Max, and the project is about ON-DEVICE models. Comparing
the two only means something if the phone is shown the exact same images with the exact
same prompts, so this copies windows straight out of `runs/stream/<clip>/windows/` rather
than re-cutting them.

Images go INTO the app bundle rather than to Documents. A task file pushed separately can
drift from the images it names — the ids still resolve, the answers still come back, and
nothing anywhere says the phone answered about a different frame than the Mac did. Bundled,
the payload is one signed unit: it either matches or the build fails.

Flat filenames, because a bundle resource is looked up by name and not by path: two files
both called `w012.jpg` from different clips would collide silently and one clip would
quietly answer about the other's frames.

usage:
  stage_phone.py --clip general-bridge --every 4
  stage_phone.py --clip general-bridge --clip general-cannon --every 6 --max 40
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "phone" / "Resources"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip", action="append", required=True,
                    help="clip name under runs/stream/ (repeatable)")
    ap.add_argument("--every", type=int, default=4,
                    help="take every Nth window. A phone run is minutes per dozen windows, "
                         "so the full sweep is not the starting point.")
    ap.add_argument("--key", action="store_true",
                    help="include EVERY window inside the clip's key_fact range, whatever "
                         "--every says. Without this a sparse sample can contain one of the "
                         "four windows where the event is actually true, and relation.py "
                         "then reports a score out of one — a number that looks like a "
                         "measurement and is a sampling artefact.")
    ap.add_argument("--max", type=int, default=40,
                    help="cap on total tasks. 40 at ~3 s each is a 2-minute run, which is "
                         "long enough for the thermal curve to start showing.")
    ap.add_argument("--out", type=Path, default=RES)
    args = ap.parse_args()

    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)

    lines, copied = [], 0
    for clip in args.clip:
        stream = ROOT / "runs" / "stream" / clip
        spec_path = stream / "windows.json"
        if not spec_path.exists():
            raise SystemExit(f"no windows.json for {clip} — run tools/stream.py first")
        spec = json.loads(spec_path.read_text())
        prompt = None
        # The prompt the Mac actually sent, recovered from the task file rather than
        # rebuilt from the question: stream.py composes a preamble around it, and a
        # hand-rebuilt prompt would differ by a clause and make the comparison invalid.
        tasks_path = stream / "tasks.jsonl"
        if tasks_path.exists():
            first = tasks_path.read_text().splitlines()[0]
            prompt = json.loads(first).get("prompt")
        if not prompt:
            raise SystemExit(f"no tasks.jsonl for {clip} — cannot recover the exact prompt")

        # Which windows to take. `--key` unions the sampled ones with the whole judgment
        # range, so the sample is cheap AND the score is over the full range.
        chosen = list(range(0, len(spec["windows"]), args.every))
        if args.key:
            meta_path = ROOT / "clips" / clip / "meta.yaml"
            body = "\n".join(
                l for l in meta_path.read_text().split("\n") if not l.startswith("#"))
            kf = (yaml.safe_load(body) or {}).get("key_fact")
            if kf:
                t0, t1 = kf["window_s"]
                chosen += [w["i"] for w in spec["windows"] if t0 <= w["t_end"] <= t1]
        chosen = sorted(set(chosen))

        for w in [spec["windows"][i] for i in chosen if i < len(spec["windows"])]:
            if len(lines) >= args.max:
                break
            src = Path(w["sheet"])
            if not src.exists():
                continue
            name = f"{clip}_w{w['i']:03d}.jpg"
            shutil.copy2(src, args.out / name)
            copied += 1
            lines.append(json.dumps({
                "id": f"{clip}|w{w['i']:03d}|open",
                "image": name,
                "prompt": prompt,
            }))

    if not lines:
        raise SystemExit("no windows matched")
    (args.out / "tasks.jsonl").write_text("\n".join(lines) + "\n")

    mb = sum(f.stat().st_size for f in args.out.iterdir()) / 1e6
    print(f"{len(lines)} task(s), {copied} image(s), {mb:.1f} MB -> {args.out}")
    print("next: xcodegen generate --spec phone/project.yml --project phone")


if __name__ == "__main__":
    main()
