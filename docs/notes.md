# Notes

Longer notes that used to be in the README. The results table is in the [README](../README.md).

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
`tools/verify_claims.py` checks the figures in the README's first three rows and exits
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
docs/FINDINGS.md      F1-F35
```

Start with `docs/FINDINGS.md`. Every tool's docstring says what it measures and,
where it applies, what it got wrong first.

## What it is for

Of the findings, the one that answers "so what" is F33. Asked for a
verdict on a single window, these models are unreliable — the cannon that fills the
frame is named in 48% of windows, the shop floor is called a shop in 54%. Majority
vote over a stretch does not rescue it: it finds 14 of 40 things that are present.

The union does. If a term appears in **two or three windows out of thirty**, it is
present — 33 of 40 found, and **0 false positives across 64 absent terms**. No clip
ever claimed a cat, a kitchen, snow or a train that was not there. Drop the bar to one
window and false positives appear at once, so the floor is low and sharp (F33).

**And that is a description of an object detector**, so the comparison has to be made.
RF-DETR was run over the same 365 window images. On terms COCO's 80 classes can
express it is a tie, 8 to 8 — from a model 6× smaller and ~100× faster, with a
per-frame confidence score. On one clip the detector won outright: children on
bicycles, where it found bicycle 10/30 and person 24/30 and the VLM found neither
(F34).

The difference is the thirteen terms COCO has no word for — *bridge*, *river*,
*cannon*, *shelf*, *shop aisle*, *crowd*, *street*, *paper bag*. The VLM named 11 of
them. A detector cannot be wrong about those because it cannot be asked.

So the sentence is narrower again: **an open vocabulary over recorded footage.** If
what you are looking for is a COCO class, use the detector. If it is a shelf or a
crowd or a bridge, this is the only thing that can be asked.

**It can index recorded footage.** "Which of these hours contains a bicycle" is a union
question. Latency does not matter to an overnight pass (F27), and the models are
character-identical across runs, so the index is stable (F25).

**It cannot answer about a frame, count anything, or read a relation.** No number
appears in 90 windows of crowds (F30). The cannon aimed at the man is named in 0 of 13
windows where it is true (F21). None of these is a threshold that can be tuned; the words are absent
at every threshold.

The useful sentence is narrow: **it tells you which recordings contain a thing, cheaply
and reproducibly, and nothing about how many, how they relate, or what just happened.**

## On the device

Everything above was measured on a Mac Studio M4 Max, which is a problem for a
benchmark about models that run on a phone. `phone/` closes it: the same task
files, the same prompts, the same catalog ids, on an iPhone 17 Pro.

LFM2.5-VL 450M's answers agree — content-word overlap between the two machines has a median of
0.93 over 27 windows, and the windows that disagree are the ones where nothing
happens. So F1-F24 are not desktop findings (F26).

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
