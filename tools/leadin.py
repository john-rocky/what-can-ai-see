#!/usr/bin/env python3
"""Give a clip a pre-event baseline by holding its first frame.

Some of the most legible events in stock footage have no "before": the jar is
already falling in frame one. Detection delay cannot be measured against that,
and a live view shows the bar red from the first window with nothing to compare.

Holding frame 0 for a few seconds supplies the baseline. The pixels are real —
it is the clip's own pre-event frame, which is exactly what a fixed inspection
camera watching an intact jar would see — but the duration is fabricated, so the
result is labelled `tier: staged` and carries the caveat. What it buys is a
measurable onset on footage a person can read instantly.

Do NOT use this to manufacture a before-state that never existed in the scene:
the held frame must already be the normal state.

usage: leadin.py --clip clips/damage-31637076 --seconds 4 --new-id damage-jar-live
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, tempfile
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument("--clip", type=Path, required=True)
ap.add_argument("--seconds", type=float, default=4.0)
ap.add_argument("--new-id", required=True)
ap.add_argument("--onset", type=float, required=True, help="onset in the ORIGINAL clip")
ap.add_argument("--pair", default=None)
ap.add_argument("--label", default="positive", choices=["positive", "negative"])
ap.add_argument("--truth", default=None)
a = ap.parse_args()

src = a.clip / "clip.mp4"
dur = float(json.loads(subprocess.run(
    ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(src)],
    capture_output=True, text=True).stdout)["format"]["duration"])
out_dir = ROOT / "clips" / a.new_id
out_dir.mkdir(parents=True, exist_ok=True)

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    still, head, body = td / "f.png", td / "head.mp4", td / "body.mp4"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-ss", "0", "-i", str(src),
                    "-frames:v", "1", "-y", str(still)], check=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-loop", "1", "-i", str(still),
                    "-t", f"{a.seconds}", "-r", "25", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-crf", "18", str(head)], check=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src),
                    "-r", "25", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                    "-an", str(body)], check=True)
    lst = td / "l.txt"
    lst.write_text(f"file '{head.resolve()}'\nfile '{body.resolve()}'\n")
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                    "-i", str(lst), "-c", "copy", str(out_dir / "clip.mp4")], check=True)

base = yaml.safe_load((a.clip / "meta.yaml").read_text())
m = dict(base)
m.update(id=a.new_id, tier="staged", label=a.label, pair=a.pair,
         onset_s=round(a.onset + a.seconds, 2), duration_s=round(dur + a.seconds, 2),
         derived_from=a.clip.name, shows_transition=True,
         lead_in={"held_first_frame_s": a.seconds,
                  "why": ("the source has no pre-event footage; frame 0 is the normal "
                          "state and is held to supply a measurable baseline"),
                  "caveat": "duration is fabricated; the held pixels are the clip's own frame 0"})
if a.truth:
    m["ground_truth"] = a.truth
(out_dir / "meta.yaml").write_text(
    f"# Lead-in staged from {a.clip.name}: frame 0 held for {a.seconds}s, then the clip.\n"
    + yaml.safe_dump(m, sort_keys=False, allow_unicode=True, width=88))
print(f"{a.new_id}: {dur:.1f}s + {a.seconds}s lead-in = {dur + a.seconds:.1f}s, "
      f"onset {a.onset + a.seconds:.1f}s")
