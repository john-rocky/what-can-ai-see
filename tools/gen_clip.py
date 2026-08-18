#!/usr/bin/env python3
"""Generate a benchmark clip with a text-to-video model.

Why this tier exists: F6 established that nobody films the failure. Stock has the
normal state of every industrial process and the abnormal state of almost none, so
the events a monitoring system is bought for — a line jamming, a worker going
down, a shelf emptying, a patient falling — cannot be sourced at all.

Generation supplies exactly those, and supplies something sourcing never can: a
matched pair from the SAME seed, one prompt with the event and one without. The
backgrounds then differ only in the event, which is the ablation the whole
benchmark is built on.

It is a separate tier and must stay separate. Generated footage has its own
artefacts and unnatural motion; a model that reads a generated fall has not been
shown to read a real one. `tier: generated` never averages with `field`, and the
GAP between them is itself the interesting measurement.

usage:
  gen_clip.py --prompt "fixed security camera, factory conveyor ..." --id line-gen-01
  gen_clip.py --plan events/generated.yaml        # batch from a spec file
"""
from __future__ import annotations
import argparse, gc, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Every prompt is prefixed with this. The corpus is about fixed industrial and
# security cameras, and a generated clip with a drifting cinematic camera would
# be testing a viewpoint no deployment has — the same complaint find_static.py
# exists to catch in stock footage.
CAMERA = ("Static fixed security camera footage, locked-off tripod, no camera motion, "
          "wide shot, even lighting, documentary realism. ")
NEGATIVE = ("camera pan, camera zoom, handheld shake, cinematic dolly, text overlay, "
            "watermark, cartoon, illustration, blurry")


def build(model: str, dtype: str):
    import torch
    from diffusers import LTXPipeline
    td = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[dtype]
    pipe = LTXPipeline.from_pretrained(model, torch_dtype=td)
    pipe.to("mps")
    pipe.set_progress_bar_config(disable=False)
    return pipe


def load_plan(path: Path):
    """Expand the pair spec into (clip_id, prompt, seed) work items.

    Both halves of a pair share the seed and the scene text; only the event
    clause differs. That is what makes the background identical and the event the
    only variable — an ablation real footage cannot give."""
    import yaml
    doc = yaml.safe_load(path.read_text())
    d = doc.get("defaults", {})
    items = []
    for pr in doc["pairs"]:
        scene = " ".join(str(pr["scene"]).split())
        for half, clause in (("pos", pr["event"]), ("neg", pr["calm"])):
            items.append({
                "id": f"{pr['id']}-{half}",
                "prompt": scene + " ".join(str(clause).split()),
                "seed": pr["seed"], "event_id": pr["event_id"],
                "label": "positive" if half == "pos" else "negative",
                "pair": f"{pr['id']}-{'neg' if half == 'pos' else 'pos'}",
                "onset_hint": pr.get("onset_hint"),
                "seconds": d.get("seconds", 4.0),
                "width": d.get("width", 768), "height": d.get("height", 448),
                "steps": d.get("steps", 30),
            })
    return items


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Lightricks/LTX-Video")
    ap.add_argument("--plan", type=Path, default=None,
                    help="events/generated.yaml — batch every pair, one pipeline load")
    ap.add_argument("--only", default=None, help="comma-separated clip ids from the plan")
    ap.add_argument("--prompt", default=None)
    ap.add_argument("--id", default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--frames", type=int, default=97, help="must be 8k+1")
    ap.add_argument("--width", type=int, default=768)
    ap.add_argument("--height", type=int, default=448)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--fps", type=int, default=24)
    ap.add_argument("--dtype", default="bf16")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    if args.plan:
        items = load_plan(args.plan)
        if args.only:
            keep = {x.strip() for x in args.only.split(",")}
            items = [i for i in items if i["id"] in keep]
    elif args.prompt and args.id:
        items = [{"id": args.id, "prompt": args.prompt, "seed": args.seed,
                  "seconds": args.frames / args.fps, "width": args.width,
                  "height": args.height, "steps": args.steps}]
    else:
        sys.exit("give --plan, or --prompt and --id")

    import torch, yaml
    from diffusers.utils import export_to_video

    todo = [i for i in items
            if not (ROOT / "clips" / i["id"] / "clip.mp4").exists()]
    print(f"{len(todo)}/{len(items)} clip(s) to generate", flush=True)
    if not todo:
        return

    t0 = time.time()
    pipe = build(args.model, args.dtype)   # load ONCE for the whole batch
    print(f"pipeline loaded in {time.time() - t0:.0f}s", flush=True)

    for n, it in enumerate(todo, 1):
        # LTX requires num_frames = 8k+1.
        nf = int(round(it["seconds"] * args.fps / 8)) * 8 + 1
        g = torch.Generator(device="cpu").manual_seed(it["seed"])
        t1 = time.time()
        frames = pipe(
            prompt=CAMERA + it["prompt"], negative_prompt=NEGATIVE,
            width=it["width"], height=it["height"],
            num_frames=nf, num_inference_steps=it["steps"], generator=g,
        ).frames[0]
        gen_s = time.time() - t1

        out = ROOT / "clips" / it["id"] / "clip.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".raw.mp4")
        export_to_video(frames, str(tmp), fps=args.fps)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(tmp),
                        "-vf", "scale=1280:720:force_original_aspect_ratio=decrease,"
                               "pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=black,fps=25",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-an",
                        str(out)], check=True)
        tmp.unlink(missing_ok=True)

        if "event_id" in it:
            # UNVERIFIED on purpose: generation does not honour the requested
            # timing, and often does not produce the event at all. Every clip is
            # watched before it is scoreable, exactly like stock footage.
            (out.parent / "meta.yaml").write_text(
                f"# GENERATED by tools/gen_clip.py from events/generated.yaml.\n"
                f"# NOT field footage and never averaged with it. Watch it, then set\n"
                f"# label/onset_s by hand — the requested onset is a hint, not truth.\n"
                + yaml.safe_dump({
                    "id": it["id"], "tier": "generated", "event": it["event_id"],
                    "label": "UNVERIFIED", "intended_label": it["label"],
                    "pair": it["pair"], "onset_s": None,
                    "onset_hint_s": it["onset_hint"],
                    "duration_s": round(nf / args.fps, 2),
                    "ground_truth": "TODO — watch the clip and describe what is visible.",
                    "generation": {"model": args.model, "seed": it["seed"],
                                   "steps": it["steps"], "frames": nf,
                                   "resolution": f"{it['width']}x{it['height']}",
                                   "prompt": CAMERA + it["prompt"],
                                   "negative_prompt": NEGATIVE},
                    "caveat": ("Generated video has its own artefacts and unnatural "
                               "motion; a model reading this has not been shown to "
                               "read real footage of the same event."),
                }, sort_keys=False, allow_unicode=True, width=88))
        print(json.dumps({"n": f"{n}/{len(todo)}", "id": it["id"],
                          "gen_s": round(gen_s), "frames": nf}), flush=True)

    del pipe; gc.collect()


if __name__ == "__main__":
    main()
