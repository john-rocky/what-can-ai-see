#!/usr/bin/env python3
"""The same event from the rig's other camera — a viewpoint ablation for free.

Every kantine recording ships two synchronized cameras, `observation.images.logitech_1`
and `logitech_2`. This benchmark has only ever used the first. The second is the
same episode, the same event, the same ground truth, from a completely different
angle — overhead against low-and-oblique — which makes it the one ablation here
that changes exactly one variable and nothing else.

It matters because of what the comparison against background subtraction found: the
VLM's advantage shows up when the changed area is SMALL. From the oblique camera a
spreading pool is foreshortened, so it covers fewer pixels, and there is far more
background in frame. If that finding is about the mechanism rather than about this
one camera, the pixel baseline should degrade more than the VLM does here. If both
degrade equally, the finding was about the viewpoint.

What this does NOT do is copy the onset across. The two cameras are synchronized so
in principle the time transfers, but "in principle" is what put a spill inside a
control clip: an onset defined as *when the change becomes visible* is a property of
the view, not of the world, and from a shallow angle a pool becomes visible later.
Each clip is written with `onset_s: null` and a TODO, and must be measured before it
can be scored.

usage:
  second_view.py --clips spill-pos,spill-neg --out-suffix -v2
  second_view.py --clips spill-pos --trim 0,15        # override a missing trim
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import urllib.parse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://huggingface.co/datasets"
CAM_A, CAM_B = "observation.images.logitech_1", "observation.images.logitech_2"


def load_meta(cid: str) -> dict:
    p = ROOT / "clips" / cid / "meta.yaml"
    body = "\n".join(l for l in p.read_text().split("\n") if not l.startswith("#"))
    return yaml.safe_load(body)


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["curl", "-sSL", "-o", str(dest), url], check=True)
    if dest.stat().st_size < 10_000:
        raise SystemExit(f"download looks empty: {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True, help="comma-separated clip ids")
    ap.add_argument("--out-suffix", default="-v2")
    ap.add_argument("--trim", default=None,
                    help="start,end in seconds, for a clip whose meta has no trim")
    ap.add_argument("--cache", type=Path,
                    default=Path("/private/tmp/claude-501/-Users-majimadaisuke-code-"
                                 "what-can-ai-see/cfee046d-f750-4d3f-b516-108ca1608b58/"
                                 "scratchpad/cam2"))
    args = ap.parse_args()

    for cid in [c.strip() for c in args.clips.split(",") if c.strip()]:
        meta = load_meta(cid)
        src = meta["source"]
        if src.get("camera") != CAM_A:
            print(f"{cid}: source camera is {src.get('camera')}, skipping")
            continue

        trim = meta.get("trim")
        if trim is None:
            if not args.trim:
                print(f"{cid}: no trim in meta and no --trim given, skipping")
                continue
            trim = [float(x) for x in args.trim.split(",")]
        start, end = float(trim[0]), float(trim[1])

        rel = src["file"].replace(CAM_A, CAM_B)
        url = f"{BASE}/{src['repo']}/resolve/main/{urllib.parse.quote(rel)}"
        cached = args.cache / src["repo"].replace("/", "__") / Path(rel).name
        if not cached.exists():
            print(f"{cid}: fetching {rel}")
            fetch(url, cached)

        out_id = cid + args.out_suffix
        out_dir = ROOT / "clips" / out_id
        out_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-ss", str(start), "-i", str(cached),
             "-t", str(end - start), "-vf", "scale=1280:-2", "-an",
             "-y", str(out_dir / "clip.mp4")], check=True)

        new = dict(meta)
        new["id"] = out_id
        new["onset_s"] = None            # deliberately dropped — see the docstring
        new["pair"] = (meta.get("pair") or "") + args.out_suffix
        new["derived_from"] = cid
        new["view"] = "oblique-low (logitech_2); the paired clip is overhead (logitech_1)"
        new["source"] = dict(src, file=rel, camera=CAM_B)
        new["conditions"] = dict(meta.get("conditions") or {}, viewpoint="fixed-rig-oblique")
        new.pop("verified_clean", None)
        new.pop("onset_method", None)
        new["todo"] = ("MEASURE the onset from THIS view before scoring, and re-verify the "
                       "control from this view. Both were established on the overhead "
                       "camera and neither transfers by assumption.")
        header = (f"# The {CAM_B} view of {cid}: same episode, same trim, same event,\n"
                  f"# different angle. Onset and control cleanliness are NOT inherited.\n")
        (out_dir / "meta.yaml").write_text(
            header + yaml.safe_dump(new, sort_keys=False, allow_unicode=True, width=96))
        dur = subprocess.run(
            ["ffprobe", "-v", "0", "-show_entries", "format=duration", "-of", "csv=p=0",
             str(out_dir / "clip.mp4")], capture_output=True, text=True).stdout.strip()
        print(f"{cid} -> {out_id}  ({float(dur):.1f}s, trim {start}-{end})")


if __name__ == "__main__":
    main()
