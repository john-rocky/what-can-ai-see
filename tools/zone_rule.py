#!/usr/bin/env python3
"""Turn detector boxes into an anomaly verdict, and count the knobs it took.

A detector does not detect anomalies. RF-DETR returns COCO classes; COCO has no
"spill", no "broken glass", no "heap of coffee grounds". The only way to get an
alarm out of it is to write the rule yourself, and every rule needs decisions that
someone has to make per camera and per event:

  presence   alarm if any box of class C is present.
             knobs: the class, the score threshold.
  zone       alarm if a box of class C overlaps a polygon by more than F.
             knobs: the class, the score threshold, the polygon, the overlap fraction.

That count is not incidental — it is half of what this comparison measures. The
VLM took one sentence of English and no per-scene setup. Whatever accuracy the
classical side reaches, it reaches after a person drew a shape on the image.

Both rules are reported, cheapest first, so the extra cost of the polygon is
visible against whatever accuracy it buys.

usage:
  zone_rule.py --stream runs/stream/hazard-hand-pos --classes person
  zone_rule.py --stream runs/stream/hazard-hand-pos --classes person \\
               --polygon 300,80,950,80,950,430,300,430 --overlap 0.05
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def poly_area(pts: list[tuple[float, float]]) -> float:
    s = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2


def box_poly_overlap(box: dict, poly: list[tuple[float, float]], w: int, h: int) -> float:
    """Fraction of the box's area inside the polygon's bounding rectangle.

    A bounding-rectangle test rather than true polygon clipping: the rule is a
    baseline, and a real integrator drawing a rectangle on a camera view is the
    common case. Using exact clipping would make the baseline stronger than the
    thing it stands in for."""
    px = [p[0] / w for p in poly]
    py = [p[1] / h for p in poly]
    rx0, rx1 = min(px), max(px)
    ry0, ry1 = min(py), max(py)
    bx0, by0 = box["x"], box["y"]
    bx1, by1 = bx0 + box["w"], by0 + box["h"]
    ix0, iy0 = max(rx0, bx0), max(ry0, by0)
    ix1, iy1 = min(rx1, bx1), min(ry1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    inter = (ix1 - ix0) * (iy1 - iy0)
    barea = max(1e-9, (bx1 - bx0) * (by1 - by0))
    return inter / barea


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stream", type=Path, required=True)
    ap.add_argument("--detections", default="detect-rf-detr.jsonl")
    ap.add_argument("--classes", default="person",
                    help="comma-separated COCO labels that count as the event")
    ap.add_argument("--score", type=float, default=0.3)
    ap.add_argument("--polygon", default=None, help="x,y,... in 1280x720 coordinates")
    ap.add_argument("--overlap", type=float, default=0.05)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    idx = json.loads((args.stream / "frames_index.json").read_text())
    spec = json.loads((args.stream / "windows.json").read_text())
    want = {c.strip() for c in args.classes.split(",") if c.strip()}
    poly = None
    if args.polygon:
        v = [float(x) for x in args.polygon.split(",")]
        poly = list(zip(v[0::2], v[1::2]))

    by_frame: dict[str, list[dict]] = {}
    for line in (args.stream / args.detections).read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        by_frame[r["id"]] = r.get("boxes", []) if r.get("ok") else []

    method = "zone" if poly else "presence"
    rows, fired_windows = [], 0
    for w in idx["windows"]:
        hit = False
        for fid in w["frames"]:
            for b in by_frame.get(fid, []):
                if b["label"] not in want or b["score"] < args.score:
                    continue
                if poly is None:
                    hit = True
                elif box_poly_overlap(b, poly, args.width, args.height) >= args.overlap:
                    hit = True
                if hit:
                    break
            if hit:
                break
        fired_windows += hit
        rows.append({
            "id": f"{spec['clip']}|w{w['i']:03d}|gate",
            "model": f"baseline-detect-{method}",
            "ok": True,
            "answer": "Yes" if hit else "No",
            "ms": 0,
        })

    out = args.out or (args.stream / f"baseline-detect-{method}.jsonl")
    out.write_text("\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n")

    first = next((w["t_end"] for w, r in zip(spec["windows"], rows)
                  if r["answer"] == "Yes"), None)
    onset = spec.get("onset_s")
    knobs = ["class", "score"] + (["polygon", "overlap"] if poly else [])
    print(json.dumps({
        "clip": spec["clip"], "method": method, "classes": sorted(want),
        "knobs": knobs, "n_knobs": len(knobs),
        "windows": len(rows), "fired": fired_windows,
        "first_fire_s": first, "onset_s": onset,
        "latency_s": (round(first - onset, 2) if (first is not None and onset) else None),
        "out": str(out),
    }))


if __name__ == "__main__":
    main()
