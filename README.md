# What can AI see?

What a small vision-language model running on a phone actually sees in real camera
footage — measured, on a Mac Studio M4 Max through Apple's CoreAI runtime, with no
cloud.

Six models are asked one plain English question about a scene, every 0.4 seconds,
over a 1.6-second sliding window, the way a camera actually runs. Their answers are
scored against ground truth written by hand and onsets measured rather than
eyeballed, and against classical baselines from before deep learning — background
subtraction and an object detector plus a hand-written rule.

**Everything here is a measurement or the code that produced it.** No videos are
redistributed: `clips/*/meta.yaml` carries the Pexels id or HuggingFace repo of
every clip, so the corpus rebuilds from this repo plus `tools/fetch_*.py`.

## The short version

| | |
|---|---|
| Ask a small VLM "did X happen?" and it says **Yes** | recall 1.00 in 98 of 136 cells, false-alarm rate 1.00 in 78 of the same cells |
| Score it on matched pairs instead | of 134 pairs, **23 real detections and 99 that fired on both halves** |
| The best model against a 1995 background subtractor | 8% wrong vs 10% — a wash on false alarms, and the subtractor misses 44% of the windows after the event |
| Move the camera to the rig's second angle | **first and third place swap.** Best model −0.19, second-best +0.15 |
| Everyday questions — rain, a cat on a bench, a sign | every model, every window, correct and stable |
| "Are there more than two people?" | the one question **every** model fails |
| A model that says Yes to nothing at all | 8,152 false alarms per hour on footage where nothing happens |

Twenty-two findings, each stating what it does *not* show, are in
[`docs/FINDINGS.md`](docs/FINDINGS.md).

## Why the numbers kept moving

The ranking of these models changed four times in this project, and not once
because a measurement changed — only because a column was added.

1. Ranked on **recall**, every model is a perfect detector.
2. Ranked on **false alarms**, a model that mostly says No comes third of seven.
   It was at chance.
3. Ranked on **both**, one model leads and the smallest is at exactly 0.50.
4. Ranked on the **same events from the other camera**, first and third swap.
5. Ranked on **everyday meaning** rather than industrial incidents, the order
   changes again.

The rule that came out of it: **a single number is not a ranking of these models.**
Detection and false alarms are published together everywhere in this repo, and
`tools/verify_claims.py` recomputes every quoted figure from `runs/` and exits
non-zero on a mismatch.

## Two things worth knowing before trusting any of it

**A control clip once had the event in it.** The dataset labelled five episodes
"normal"; one had a coffee spill. Every model's correct "yes, there is a spill" was
counted as a false alarm, and the result was backwards for hours. Controls are now
verified by measurement, not by label — see F16.

**The clips are public, so the models may have seen them.** A horizontal flip
changes the meaning of nothing and the pixels of everything: across six genres and
four models, **not one answer moved**. Where answers did move, it was on the two
questions each model was already guessing at. That rules out retrieval of these
particular clips; it does not prove perception. See F22.

## Layout

```
clips/*/meta.yaml     ground truth, measured onset, camera, licence, source id
events/               one question per event; genres.yaml is the meaning axis
runs/                 every answer every model gave, as JSONL
tools/                harness, scorers, baselines, video renderers
runner/               Swift; loads a model once and streams a task file
docs/FINDINGS.md      F1-F22
```

Start with `docs/FINDINGS.md`. Every tool's docstring says what it measures and,
where it applies, what it got wrong first.

## Running it

Needs macOS 27, the Xcode 27 beta toolchain (CoreAI is not in the release SDK),
and a Pexels API key for the stock corpus.

```sh
DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.5.app/Contents/Developer \
  swift build -c release --package-path runner

python3 tools/fetch_scene.py --genres --all --limit 8   # rebuild the corpus
python3 tools/stream.py --clip clips/spill-pos --window 1.6 --stride 0.4 --panels 4
runner/.build/release/wcas-run --model lfm2.5-vl-3b \
  --tasks runs/stream/spill-pos/tasks.jsonl --out out.jsonl
python3 tools/verify_claims.py                           # check the numbers
```

## Licence

Code and measurements: MIT. The footage is not redistributed here — Pexels clips
are free to use but not to re-host, and kantine's recordings are Apache-2.0 at the
source.
