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
phone/                iOS app: the same tasks, on the device the premise is about
walk/                 iOS app: live camera, a person-gate in front of the recorder
docs/FINDINGS.md      F1-F32
```

Start with `docs/FINDINGS.md`. Every tool's docstring says what it measures and,
where it applies, what it got wrong first.

## On the device

Everything above was measured on a Mac Studio M4 Max, which is a problem for a
benchmark about models that run on a phone. `phone/` closes it: the same task
files, the same prompts, the same catalog ids, on an iPhone 17 Pro.

The answers agree — content-word overlap between the two machines has a median of
0.93 over 27 windows, and the windows that disagree are the ones where nothing
happens. So F1-F26 are not desktop findings (F26).

What the desktop cannot show is the cost. LFM2.5-VL 450M answers a 3-second window
in 4.68 s on the phone, which is 12x slower than the 0.4 s stride this benchmark's
sliding window assumes, and it slows from 3.91 s to 5.59 s across two minutes as
the phone heats (F27). Apple's own `SystemLanguageModel` is 2.1x faster at 34 MB
resident and 0 MB to download — but it samples by default, so the same frame gets
a different answer each run until you ask for `.greedy` (F25).

`walk/` is the other half: a live camera, a 36 MB detector deciding frame by frame
whether recording is allowed at all, and the VLM describing whatever survived. The
gate proves itself against bundled fixtures at launch and refuses to enable Start
if it cannot find the people in them.

## Running it

Needs macOS 27, the Xcode 27 beta toolchain (CoreAI is not in the release SDK),
and a Pexels API key for the stock corpus. The two iOS apps need a paired device;
CoreAI is not in the Simulator.

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
