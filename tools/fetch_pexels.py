#!/usr/bin/env python3
"""Pull a candidate clip into clips/ with its provenance attached.

Every clip carries where it came from, under what licence, and who shot it — not
as courtesy but because the whole corpus exists to be posted publicly, and a clip
whose provenance is not written down at fetch time is a clip that can never
safely be used. `meta.yaml` is written with `label: UNVERIFIED`; nothing is
scoreable until a human has watched the contact sheet and replaced that.

Normalisation: every clip becomes 1280x720, 16:9, no audio. Source aspect is
letterboxed rather than cropped — a crop can remove the event, and an event
outside the frame is a labelling error that looks like a model failure.

usage:
  fetch_pexels.py --event fall --ids 5155837,2791953 --label positive
  fetch_pexels.py --event smoke-fire --from-survey positive --limit 6
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIDEO_API = "https://api.pexels.com/videos/videos"


def api(url: str, key: str) -> dict:
    for attempt in range(3):
        proc = subprocess.run(
            ["curl", "-s", "--max-time", "25", "-H", f"Authorization: {key}", url],
            capture_output=True, text=True)
        if proc.returncode == 0 and proc.stdout.strip():
            try:
                return json.loads(proc.stdout)
            except json.JSONDecodeError:
                pass
        if attempt < 2:
            time.sleep(2 * (attempt + 1))
    raise SystemExit(f"failed to fetch {url}")


def pick_file(video: dict) -> dict:
    """Prefer the largest file at or under 1080p.

    Bigger than that is wasted: every model resizes to a 448 or 512 square, so a
    4K source and a 1080p source reach the model as identical pixels. Downloading
    4K would only slow the fetch and fill the disk.
    """
    files = [f for f in video["video_files"] if (f.get("height") or 0) <= 1080]
    if not files:
        files = video["video_files"]
    return sorted(files, key=lambda f: -(f.get("height") or 0))[0]


def normalise(src: Path, dst: Path) -> None:
    # Letterbox into 1280x720. `force_original_aspect_ratio=decrease` + pad keeps
    # the whole frame; cropping could cut the event out of shot.
    subprocess.run(
        ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
         "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,fps=25",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-an",
         str(dst)], check=True)


def fetch(video_id: int, event: str, label: str, key: str, force: bool) -> Path | None:
    clip_id = f"{event}-{video_id}"
    clip_dir = ROOT / "clips" / clip_id
    if (clip_dir / "clip.mp4").exists() and not force:
        print(f"  {clip_id}: already present")
        return clip_dir

    video = api(f"{VIDEO_API}/{video_id}", key)
    if "id" not in video:
        print(f"  {video_id}: not available ({video.get('error', 'unknown')})")
        return None
    chosen = pick_file(video)

    clip_dir.mkdir(parents=True, exist_ok=True)
    raw = clip_dir / "source.mp4"
    proc = subprocess.run(["curl", "-sL", "--max-time", "300", "-o", str(raw),
                           chosen["link"]])
    if proc.returncode != 0 or not raw.exists() or raw.stat().st_size < 10_000:
        print(f"  {video_id}: download failed")
        raw.unlink(missing_ok=True)
        return None

    normalise(raw, clip_dir / "clip.mp4")
    raw.unlink()

    slug = video["url"].rstrip("/").rsplit("/", 1)[-1]
    title = " ".join(slug.split("-")[:-1])
    (clip_dir / "meta.yaml").write_text(f"""# Fetched by tools/fetch_pexels.py. NOT YET SCOREABLE.
# Watch the contact sheet, then replace `label: UNVERIFIED` with positive or
# negative, set `onset_s` for positives, write `ground_truth`, and pair it with
# its opposite clip. An unverified clip is excluded by build_tasks.py.
id: {clip_id}
tier: field
event: {event}
label: UNVERIFIED          # intended: {label}
pair: null
onset_s: null
duration_s: {video.get('duration')}
ground_truth: >-
  TODO — describe what is actually visible, in the terms events.yaml uses.
source:
  kind: stock
  provider: pexels
  video_id: {video_id}
  url: {video['url']}
  title: "{title}"
  author: "{video.get('user', {}).get('name', 'unknown')}"
  author_url: {video.get('user', {}).get('url', '')}
  license: Pexels License (free to use, no attribution required, not for resale as-is)
  fetched_resolution: {chosen.get('width')}x{chosen.get('height')}
conditions:
  distance: unknown
  target_size: unknown
  light: unknown
  occlusion: unknown
  blur: unknown
  viewpoint: unknown
  clutter: unknown
  duration_class: unknown
""")
    print(f"  {clip_id}: ok — {title}")
    return clip_dir


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", required=True)
    ap.add_argument("--ids", default=None, help="comma-separated Pexels video ids")
    ap.add_argument("--from-survey", default=None, choices=["positive", "negative"],
                    help="take title-matched candidates from events/survey.json")
    ap.add_argument("--label", default=None, choices=["positive", "negative"])
    ap.add_argument("--limit", type=int, default=6)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise SystemExit("PEXELS_API_KEY is not set")

    if args.ids:
        ids = [int(x) for x in args.ids.split(",") if x.strip()]
        label = args.label or "positive"
    elif args.from_survey:
        survey = json.loads((ROOT / "events" / "survey.json").read_text())
        if args.event not in survey:
            raise SystemExit(f"{args.event} is not in the survey")
        rows = survey[args.event][args.from_survey]["matched"][: args.limit]
        ids = [r["id"] for r in rows]
        label = args.from_survey
    else:
        raise SystemExit("give --ids or --from-survey")

    print(f"{args.event} / {label}: {len(ids)} clip(s)")
    for vid in ids:
        fetch(vid, args.event, label, key, args.force)
        time.sleep(0.3)


if __name__ == "__main__":
    sys.exit(main())
