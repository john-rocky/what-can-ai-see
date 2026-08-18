#!/usr/bin/env python3
"""Fetch by SCENE, not by event name — because event-name search does not work.

`sources.yaml` searches for the event: "person climbing fence", "vehicle arrival".
Reviewed, that yields indoor bouldering gyms and drone shots of full car parks.
The Pexels API ignores negation and matches the title, and nobody uploads footage
titled after an industrial incident.

What does exist, in quantity, is b-roll of PLACES: warehouses, production lines,
loading docks, workshops. That footage is shot on a tripod because it is meant to
be cut into a corporate video, and things enter and leave the frame while the
camera holds still. A fixed camera plus a thing entering the frame is exactly the
transition this benchmark measures — it just is not what the clip is called.

Concretely, of the three events reviewed by event-name search:

    entry-exit        12 of 19 usable   (doors: a transition people compose)
    intrusion          5 of 22          (all parkour, all moving cameras)
    vehicle-arrival    3 of 15          (all three are warehouse forklift b-roll,
                                         found on page 2 under a query that was
                                         looking for arriving cars)

So the yield came from the scene, not the query. This searches scenes and applies
no title filter at all: every result is downloaded and sent to review.py, where a
person decides. The filtering that matters cannot be done on metadata.

usage:
  fetch_scene.py --scene warehouse --limit 12
  fetch_scene.py --all --limit 8 --min-duration 8
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
SEARCH_API = "https://api.pexels.com/videos/search"

# Places where a fixed camera watches a process. The slug becomes the clip id
# prefix, so keep them short and filename-safe.
SCENES = {
    "warehouse": ["warehouse interior", "warehouse forklift", "warehouse aisle shelves"],
    "loading-dock": ["loading dock truck", "warehouse loading bay", "delivery dock"],
    "production": ["factory production line", "assembly line factory", "manufacturing line"],
    "conveyor": ["conveyor belt factory", "parcel conveyor sorting", "bottling line"],
    "workshop": ["workshop bench tools", "mechanic workshop", "welding workshop"],
    "construction": ["construction site workers", "building site crane"],
    "retail": ["supermarket aisle", "grocery store shelves", "retail store interior"],
    "kitchen": ["commercial kitchen", "restaurant kitchen staff"],
    "office": ["office corridor", "office reception desk"],
}


def api(url: str, key: str) -> dict:
    out = subprocess.run(
        ["curl", "-s", "--max-time", "25", "-H", f"Authorization: {key}", url],
        capture_output=True, text=True)
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError:
        return {}


def best_file(video: dict) -> dict | None:
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and (f.get("height") or 0) <= 1440]
    if not files:
        return None
    return sorted(files, key=lambda f: -(f.get("height") or 0))[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene", default=None)
    ap.add_argument("--all", action="store_true", help="every scene")
    ap.add_argument("--genres", action="store_true",
                    help="use events/genres.yaml instead of the industrial scene list — "
                         "one search set per GENRE OF MEANING (counting, spatial relation, "
                         "material, text) rather than per place")
    ap.add_argument("--limit", type=int, default=8, help="clips per scene")
    ap.add_argument("--min-duration", type=int, default=6,
                    help="seconds; a clip shorter than a couple of windows is unusable")
    ap.add_argument("--max-duration", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        raise SystemExit("PEXELS_API_KEY is not set")

    global SCENES
    if args.genres:
        import yaml
        doc = yaml.safe_load((ROOT / "events" / "genres.yaml").read_text())
        SCENES = {g["id"]: g["search"] for g in doc["genres"]}
    scenes = sorted(SCENES) if args.all else [args.scene]
    if not scenes or scenes == [None]:
        raise SystemExit("give --scene or --all")

    have = {d.name for d in (ROOT / "clips").iterdir() if d.is_dir()}
    total = 0
    for scene in scenes:
        seen: dict[int, dict] = {}
        for q in SCENES[scene]:
            url = f"{SEARCH_API}?query={q.replace(' ', '+')}&per_page=20&orientation=landscape"
            for v in api(url, key).get("videos", []):
                d = v.get("duration") or 0
                if args.min_duration <= d <= args.max_duration:
                    seen.setdefault(v["id"], v)
        picked = list(seen.values())[: args.limit]
        print(f"\n{scene}: {len(seen)} candidate(s), taking {len(picked)}")
        for v in picked:
            cid = f"{scene}-{v['id']}"
            if cid in have:
                print(f"  {cid}: already present")
                continue
            f = best_file(v)
            if not f:
                print(f"  {cid}: no usable mp4")
                continue
            title = (v.get("url", "").rstrip("/").split("/")[-1]
                     .rsplit("-", 1)[0].replace("-", " "))
            if args.dry_run:
                print(f"  {cid}: {v['duration']}s  {title[:70]}")
                continue
            d = ROOT / "clips" / cid
            d.mkdir(parents=True, exist_ok=True)
            subprocess.run(["curl", "-sSL", "-o", str(d / "clip.mp4"), f["link"]], check=True)
            if (d / "clip.mp4").stat().st_size < 50_000:
                print(f"  {cid}: download failed")
                continue
            (d / "meta.yaml").write_text(f"""\
# Fetched by tools/fetch_scene.py — searched by PLACE, not by event.
# NOT YET SCOREABLE. Watch it (tools/review.py), then set:
#   label      positive | negative   (and delete this UNVERIFIED marker)
#   event      which event it shows, from events/events.yaml
#   onset_s    the second the event becomes visible, or null for a negative
#   camera     fixed | handheld | moving   — needed to read the transition score
# Rejected clips go to clips/REJECTED.md with the reason, never deleted silently.
id: {cid}
tier: field
event: UNVERIFIED
label: UNVERIFIED
pair: null
onset_s: null
duration_s: {v.get('duration')}
camera: UNVERIFIED
ground_truth: >-
  TODO — describe what is actually visible, in the terms events.yaml uses.
source:
  kind: stock
  provider: pexels
  id: {v['id']}
  url: {v.get('url')}
  title: {title}
  scene_query: {scene}
  license: pexels
  license_note: free to use, no attribution required, redistribution of the file
    itself is not permitted — the benchmark ships ids and urls, not the mp4s.
conditions:
  viewpoint: UNVERIFIED
  distance: UNVERIFIED
  light: UNVERIFIED
  occlusion: UNVERIFIED
  blur: UNVERIFIED
  clutter: UNVERIFIED
""")
            total += 1
            print(f"  {cid}: ok — {v['duration']}s — {title[:64]}")
            time.sleep(0.25)
    print(f"\n{total} clip(s) fetched")


if __name__ == "__main__":
    sys.exit(main())
