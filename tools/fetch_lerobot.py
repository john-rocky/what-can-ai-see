#!/usr/bin/env python3
"""Pull episodes from a LeRobot-format HF dataset into the corpus.

Why these matter: kantine's industrial sets ship every task in TWO versions —
`_anomaly` and `_expert` — recorded on the same rig, the same fixed cameras and
the same task. That is the matched pair this benchmark has been hand-building all
along: identical scene, one execution goes wrong, one does not. Apache-2.0, so
unlike the research anomaly datasets there is no redistribution problem.

Fixed cameras, too. LeRobot rigs bolt the camera down, which is what a real
inspection station looks like and what find_static.py exists to hunt for in stock.

usage:
  fetch_lerobot.py --repo kantine/industrial_screws_sorting_anomaly --episodes 3
"""
from __future__ import annotations
import argparse, json, subprocess, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://huggingface.co/datasets"


def tree(repo: str, path: str):
    url = f"https://huggingface.co/api/datasets/{repo}/tree/main/{path}?recursive=true"
    p = subprocess.run(["curl", "-s", "--max-time", "40", url], capture_output=True, text=True)
    try:
        return json.loads(p.stdout)
    except Exception:
        return []


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--episodes", type=int, default=3)
    ap.add_argument("--eps", default=None,
                    help="explicit episode indices, e.g. 10,11,12 — REQUIRED for the "
                         "anomaly sets, whose meta/tasks.jsonl assigns a different "
                         "anomaly (or none at all) to each index range")
    ap.add_argument("--camera", default=None, help="default: the first camera found")
    ap.add_argument("--event", default="assembly-wrong")
    ap.add_argument("--label", default=None, help="positive|negative; default from repo name")
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--anomaly", default=None,
                    help="what the anomaly IS, from meta/tasks.jsonl")
    args = ap.parse_args()

    rows = [r for r in tree(args.repo, "videos") if r.get("path", "").endswith(".mp4")]
    if not rows:
        raise SystemExit(f"no videos in {args.repo}")
    cams = sorted({r["path"].split("/")[2] for r in rows})
    cam = args.camera or cams[0]
    cam_rows = sorted((r for r in rows if r["path"].split("/")[2] == cam),
                      key=lambda r: r["path"])
    if args.eps:
        want = {int(x) for x in args.eps.split(",")}
        picked = [r for r in cam_rows
                  if int(Path(r["path"]).stem.split("_")[-1]) in want]
    else:
        picked = cam_rows[: args.episodes]

    label = args.label or ("positive" if args.repo.endswith("_anomaly") else "negative")
    short = args.repo.split("/")[1].replace("industrial_", "").replace("domotic_", "")
    prefix = args.prefix or short.replace("_anomaly", "").replace("_expert", "")

    for r in picked:
        ep = Path(r["path"]).stem.replace("episode_", "e")
        cid = f"{args.event}-{prefix}-{'anom' if label == 'positive' else 'ok'}-{ep}"
        d = ROOT / "clips" / cid
        d.mkdir(parents=True, exist_ok=True)
        raw = d / "source.mp4"
        url = f"{BASE}/{args.repo}/resolve/main/{urllib.parse.quote(r['path'])}"
        if subprocess.run(["curl", "-sL", "--max-time", "300", "-o", str(raw), url]).returncode \
                or raw.stat().st_size < 10_000:
            print(f"  {cid}: download failed"); raw.unlink(missing_ok=True); continue
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(raw),
                        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                               "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,fps=25",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-an",
                        str(d / "clip.mp4")], check=True)
        raw.unlink()
        dur = float(json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
             str(d / "clip.mp4")], capture_output=True, text=True).stdout)["format"]["duration"])
        counterpart = (args.repo.replace("_anomaly", "_expert") if label == "positive"
                       else args.repo.replace("_expert", "_anomaly"))
        lines = [
            f"# From {args.repo} ({r['path']}). NOT YET SCOREABLE — watch it, then set",
            "# label/onset_s and write ground_truth by hand.",
            "#",
            "# The anomaly SETS mix normal and abnormal episodes: soldering_anomaly's own",
            "# meta/tasks.jsonl assigns 0:4 to normal samples. Taking the first episodes",
            "# of an '_anomaly' repo therefore yields clips with nothing wrong in them,",
            "# which is exactly the mistake this --eps flag exists to prevent.",
            f"id: {cid}",
            "tier: field",
            f"event: {args.event}",
            f"label: UNVERIFIED          # intended: {label}",
            "pair: null",
            "onset_s: null",
            f"duration_s: {dur:.2f}",
            "ground_truth: >-",
            "  TODO — describe what is actually visible.",
        ]
        if args.anomaly:
            lines += ["dataset_anomaly: >-", f"  {args.anomaly}"]
        lines += [
            "source:",
            "  kind: dataset",
            "  provider: huggingface",
            f"  repo: {args.repo}",
            f"  file: {r['path']}",
            f"  camera: {cam}",
            "  license: apache-2.0",
            "  counterpart: >-",
            f"    {counterpart} — same rig, same camera, same task, different outcome.",
            "conditions:",
            "  viewpoint: fixed-rig",
            "  distance: near",
            "  light: bright",
            "  occlusion: none",
            "  blur: none",
            "  clutter: mid",
        ]
        (d / "meta.yaml").write_text("\n".join(lines) + "\n")
        print(f"  {cid}  {dur:.1f}s")


if __name__ == "__main__":
    main()
