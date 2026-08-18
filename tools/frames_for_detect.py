#!/usr/bin/env python3
"""Extract the frames a detector baseline needs, and index them by window.

The VLM saw a 4-panel contact sheet per window. A detector sees individual
frames, so the fair unit is: run the detector on every frame in the window and
let the rule decide. Frames are extracted once per clip and shared across
windows, since windows overlap heavily at a 0.4s stride.

usage: frames_for_detect.py --stream runs/stream/hazard-hand-pos --fps 10
"""
from __future__ import annotations
import argparse, json, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--stream", type=Path, required=True)
ap.add_argument("--fps", type=int, default=10)
a = ap.parse_args()

spec = json.loads((a.stream / "windows.json").read_text())
video = ROOT / "clips" / spec["clip"] / "clip.mp4"
fdir = a.stream / "frames"
fdir.mkdir(parents=True, exist_ok=True)
if not any(fdir.glob("f*.png")):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(video),
                    "-vf", f"fps={a.fps}", "-y", str(fdir / "f%05d.png")], check=True)
frames = sorted(fdir.glob("f*.png"))

lines = [json.dumps({"id": f"{spec['clip']}|f{i:05d}", "image": str(f.resolve())})
         for i, f in enumerate(frames)]
(a.stream / "frames.jsonl").write_text("\n".join(lines) + "\n")
(a.stream / "frames_index.json").write_text(json.dumps({
    "clip": spec["clip"], "fps": a.fps, "n_frames": len(frames),
    "windows": [{"i": w["i"], "t_start": w["t_start"], "t_end": w["t_end"],
                 "frames": [f"{spec['clip']}|f{k:05d}"
                            for k in range(int(w["t_start"] * a.fps),
                                           min(len(frames), int(w["t_end"] * a.fps)))]}
                for w in spec["windows"]],
}, indent=1))
print(f"{len(frames)} frames at {a.fps}fps -> {a.stream}/frames.jsonl")
