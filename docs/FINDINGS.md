# Findings

A running log. Each entry says what was measured, on what, and what it does not
show. Numbers are from `runs/`; nothing here is quoted that was not measured on
this machine (Mac Studio M4 Max, 128 GB, macOS 27.0 / build 26A5406e, Xcode 27
beta 5).

---

## F1 — The budget is 64–256 visual tokens for the entire clip

*Source: `coreai-kit/Sources/CoreAIKit/Vision/VLArchitecture.swift`, read directly.*

Every VLM in the catalog resizes its input to a fixed square canvas — 448×448
(Qwen3-VL, Holo2, MiniCPM-V) or 512×512 (LFM2.5-VL, North Micro) — with
`.stretch`, and turns it into a fixed number of visual tokens:

| model | canvas | visual tokens |
|---|---|---|
| MiniCPM-V 4.6 | 448² | 64 |
| Qwen3-VL 2B / 4B / 8B, Holo2 4B | 448² | 196 |
| LFM2.5-VL 450M / 3B, North Micro | 512² | 256 |

There is no dynamic resolution and no tiling. And because `KitVisionExecutor`
takes one image per turn — *"Multi-image and KV reuse are follow-ups"* — that
token count covers the **whole clip**, not a frame.

Three consequences, all of which shaped the harness:

1. **Source resolution stops mattering** the moment a clip becomes a contact
   sheet. A 4K camera and a 480p camera produce the same 448² input. Any
   "distance / target size" axis in this benchmark is really a *panel-count* axis.
2. **The sheet must be near-square**, or `.stretch` distorts the scene and the
   benchmark measures the squash. The first version of `sheet.py` produced a
   4-panel horizontal strip at 16:3 — stretched to square that is a 5× vertical
   squash. It was replaced with a ladder shaped to stay inside 0.75–1.35 aspect.
3. **Panels compete.** `tokens_per_panel` is reported on every row because it
   predicts more of the result than parameter count does.

| encoding | panels | tokens/panel (196) | panel px at 448 |
|---|---|---|---|
| `f1` | 1 | 196 | 448 × 448 |
| `g2` | 2 | 98 | 448 × 224 |
| `g6` | 6 | 33 | 224 × 149 |
| `g12` | 12 | 16 | 149 × 112 |
| `g20` | 20 | 10 | 112 × 90 |

**Not shown:** whether more panels helps or hurts on real footage. The ladder is
built; the sweep is not run.

---

## F2 — Recall 1.00 across the board, and almost none of it is detection

*Source: `runs/floor/` — 6 synthetic floor clips (3 matched pairs), `g6`, greedy.*

The floor clips are deliberately trivial: flat colour, no clutter, no occlusion,
no motion blur, a figure filling a third of the frame. Anything that fails here
cannot do real footage.

```
model                  enc   event            recall      FA  pairOK  balAcc   lat_s
------------------------------------------------------------------------------------
lfm2.5-vl-450m         g6    fall               1.00    1.00    0.00    0.50    -2.1
lfm2.5-vl-450m         g6    line-stopped       1.00    1.00    0.00    0.50    +0.5
lfm2.5-vl-450m         g6    object-removed     1.00    1.00    0.00    0.50    -2.5
north-micro-vision     g6    fall               1.00    0.00    1.00    1.00    +1.9
north-micro-vision     g6    line-stopped       1.00    1.00    0.00    0.50     -
north-micro-vision     g6    object-removed     1.00    1.00    0.00    0.50     -
```

**Recall is 1.00 in every cell.** A conventional benchmark table would print two
perfect detectors. Pair discrimination shows one genuine detection in six cells.

- **LFM2.5-VL 450M answered "Yes" six times out of six**, and its open
  descriptions paraphrased the prompt rather than the image — *"The video clip
  shows a sequence of six frames, with panel 1 being the earliest…"* — for all
  six clips, nearly verbatim. It is flagged `degenerate`. Its `latency_s` of
  −2.1 s means it named a panel from before the event existed.
- **North Micro Vision discriminated the fall pair** (Yes on the fall, No on the
  crouch, citing panel 5). On the other two pairs it fired on the negative too.
  On `object-removed` it justified a false alarm with an object that is not in
  the clip: *"The blue ball is no longer visible in the final frame."*
- Its open descriptions are wrong about scene content even where its gate answer
  is right — it called the falling figure *"a ball rolling down a surface"*. This
  is exactly the split the `open` question exists to catch: **the gate answer
  being right is not evidence the model saw the event.**

**Not shown:** anything about real footage, and anything about the other six
models. Two of eight, one encoding, three events, synthetic input.

---

## F3 — The harness had to be rebuilt around load cost

`vlchat-cli` loads the decoder and vision tower, answers one prompt, and exits.
Measured: ~6 s end-to-end for LFM2.5-VL 450M, and a 3B did not finish a single
answer inside a 10-minute timeout. Per-task load makes a few hundred cells
unaffordable.

`runner/` loads once and streams a task file: the same 450M answers in
**1.4–1.8 s per task**, North Micro in 3–5 s. This is the only reason a full
sweep is affordable.

Two operational notes that cost time and are worth writing down:

- **The beta toolchain is required.** `swift build` against the default Xcode
  fails with `no such module 'CoreAI'`; the framework is not in the release SDK.
  `DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.5.app/Contents/Developer`.
  A prebuilt binary from an earlier beta dies at launch on a missing
  `FoundationModels` symbol — rebuild, do not reuse.
- **A local copy is not a cached model.** LFM2.5-VL 3B had 3.9 GB on disk under
  revision `31ca15a…`; the catalog pins `a47ab9b…`, so the first run downloaded
  it again. `events/models.yaml` deliberately carries no `cached` field.

---

## F4 — Stock libraries have industrial scenes, not industrial incidents

*Source: `events/survey.json`, Pexels video API, 19 events.*

The corpus is licence-clean stock only. A first survey counted search hits and
graded **all 19 events "strong"** — which was a measurement of nothing. The Pexels
API ignores negation: `person falling down` returned a woman stretching on a
table, a man doing glute bridges, a person walking down stairs and an aerial shot
of a man; `construction worker no helmet` returns workers wearing helmets.

Filtering on each clip's own title instead (`events/sources.yaml`, `title:`)
separates candidates from noise, and the picture changes:

| | positives | negatives | |
|---|---|---|---|
| `smoke-fire` | 38 | 23 | strongest — and its negatives are steam, fog, dust, welding sparks: the classic false-positive set |
| `ppe-missing` | 29 | 8 | |
| `handover` | 30 | 13 | |
| `intrusion` | 22 | 16 | |
| `line-stopped` | 9 | 37 | |
| `fall` | 6 | 37 | positives are all sport; negatives abundant |
| `shelf-empty` | **1** | 22 | |
| `jam` | **0** | 13 | not sourceable from stock at all |

The pattern: **an event that is just a scene is easy to source; an event that is
an incident is not.** Nobody films a jammed conveyor or a worker falling in a
warehouse. So `state` and `dwell` events source well, and the `motion` positives
that exist are sports and stunts. Every fall clip carries a `domain_note` saying
so — a fall result here means "can it see a fall at all", not a workplace-safety
number.

A title match is a shortlist, not ground truth. Nothing enters `clips/` scoreable:
`fetch_pexels.py` writes `label: UNVERIFIED`, and only a watched contact sheet
replaces it. Of six fetched `fall` positives, one was rejected outright
(`fall-5155837` — a low-angle shot in which only the skater's legs are ever
visible; a human cannot call it either).

**Trimming is mandatory, not tidying.** Stock clips are not shot for this. The
same skateboard clip spent three of six panels on an empty wall because the event
was short and late — scored as a miss, it would have been the harness's failure,
not the model's. `tools/trim.py` cuts an event-centred window and records it in
`meta.yaml`; the original is kept as `clip.full.mp4`.

---

## F5 — On real footage the discrimination disappears, and the question is what breaks it

*Source: `runs/field-fall/` — one verified pair, 4 encodings, 5 questions, greedy.*

The pair: **positive** `fall-5916779`, a climber loses his grip and falls off a
bouldering wall. **Negative** `fall-8526604`, a man on an exercise mat moves from
kneeling to lying flat on his back — upright, then on the ground, then staying
down, the exact trajectory of a collapse, performed deliberately.

```
model                  enc   recall      FA  pairOK  balAcc   lat_s   stab
--------------------------------------------------------------------------
lfm2.5-vl-450m         f1      1.00    1.00    0.00    0.50     -     0.00
lfm2.5-vl-450m         g2      1.00    1.00    0.00    0.50    -1.9   0.00
lfm2.5-vl-450m         g6      1.00    1.00    0.00    0.50    -2.8   0.00
lfm2.5-vl-450m         g12     1.00    1.00    0.00    0.50    -3.1   0.00
north-micro-vision     f1      0.00    1.00    0.00    0.00     -     1.00
north-micro-vision     g2      1.00    1.00    0.00    0.50    +1.1   0.50
north-micro-vision     g6      1.00    1.00    0.00    0.50    +1.1   1.00
north-micro-vision     g12     1.00    1.00    0.00    0.50    +1.3   0.50
```

North Micro Vision **discriminated the synthetic fall pair (F2) and discriminates
the real one at no encoding.** At `f1` it is worse than a coin: recall 0.00,
FA 1.00 — it calls the man on the mat a fall and the climber mid-air not a fall.

More panels genuinely helped the positive: at `f1` it answered *"No — the panel is
a climbing wall with a person actively climbing"* (true of that frame, false of
the clip), and at `g6` *"Yes, panel 5 shows a person falling to the ground."* The
temporal evidence worked. It just never suppressed the negative.

**And the negative's failure is not perception.** Same model, same image, `g6`:

| question | answer |
|---|---|
| `open` — describe what happens | *"The sequence shows a person performing a **stretching or yoga pose**…"* |
| `gate` — did a person fall? | *"**Yes**, panel 6 shows a person lying on the floor with their head tilted back, indicating a fall."* |

It reads the scene correctly when not asked about falls, and converts "person on
the floor" into "fall" when asked. The false alarm is manufactured by the
question, not by the eye. This is the strongest argument yet for keeping `open`
and `gate` as separate measurements, and for treating a gate-only benchmark as
untrustworthy.

**Prompt stability is the other alarm.** Decoding is greedy, so these are not
sampling noise: LFM2.5-VL 450M's verdict disagrees across three phrasings of the
same question on **every** clip and encoding (`stab` 0.00). North Micro flips on
half of them at `g2` and `g12`.

**Not shown:** one pair, one event. This is a worked example of the method, not a
result about falls. Six models are still downloading.

---

## F6 — Stock footage has the normal state of every process and the abnormal state of almost none

*Source: sourcing and visual curation of `fall`, `smoke-fire`, `ppe-missing`,
`line-stopped` — 46 clips fetched, every one watched as a contact sheet.*

F4 saw this as a fall-specific quirk. Three more events say it is the governing
constraint on the whole corpus.

| event | what the positive needs | what stock has |
|---|---|---|
| `ppe-missing` | a worker with a bare head on site | compliant workers. Construction footage is shot as aspirational imagery — **every** clip returned by "worker without helmet" showed a helmet |
| `line-stopped` | a line with items that do not advance | running lines, and *derelict buildings* — "abandoned factory", "abandoned industrial complex". A stopped line is not a derelict building |
| `jam` | a backlog against an obstruction | nothing. Zero title matches out of 46 candidates |
| `shelf-empty` | a gap in a facing | stocked shelves; one match in 29 |
| `fall` | a person falling | skateboarders and climbers |
| `smoke-fire` | flame or dark plume | available — because fire is a natural phenomenon people film, not a process failure |

**Nobody films the failure.** Industrial footage exists to sell the process
working. So positives are structurally absent for exactly the events a monitoring
system is bought for, while their negatives are abundant — the opposite of the
scarcity a benchmark usually has to design around.

Two things follow, and both were already in the design rather than bolted on.

**The `tier` field earns its place.** `floor` (synthetic) and `field` (stock)
answer different questions and must never be averaged together. For `line-stopped`
the synthetic pair is not a weak substitute for field footage — it is the *only*
clean form of the test, because it can put identifiable boxes in identical
positions across panels and know that is what it did.

**And a `dwell` event is unlabelable when the scene has no trackable feature.**
`line-stopped-3701070`, a close-up of a bare conveyor belt: across six panels the
belt surface is featureless and one small red item appears in a single frame.
Whether that belt is moving cannot be determined from the sheet **by a human
either**. This sharpens F1's "a contact sheet has no clock": the sheet can carry
motion, but only when the moving things are individually identifiable between
panels. Featureless surfaces lose it entirely, and no model can be marked wrong
for that.

Events that survive on stock are the ones whose positive is a **normal activity**
(`parcel-pass`, `handover`, `entry-exit`, `vehicle-arrival`, `object-removed`,
`step-complete`), a **natural phenomenon** (`smoke-fire`), or a **sports incident**
(`fall`, `object-drop`). That set still spans four of the five evidence classes,
which is enough to answer the question this benchmark exists for — but the gap is
a result to publish, not a hole to hide.

---

## F7 — The yes/no answer is close to uncorrelated with what the model perceived

*Source: `runs/field-v1/` — LFM2.5-VL 450M, 12 clips, 4 encodings, greedy.*

F5 caught North Micro Vision describing a man's deliberate lie-down as *"a
stretching or yoga pose"* and then answering **Yes** to "did a person fall?".
The 450M does the same thing in the opposite direction, and more starkly.

`smoke-fire-8365988` is an aerial shot of a burning industrial site: a black
plume with visible orange flame at its base. Same model, same image:

| enc | `open` — "describe what happens" | `gate` — "is there smoke or fire?" |
|---|---|---|
| `f1` | *"The fire is spreading rapidly, with smoke rising high into the sky."* | **Yes** |
| `g2` | *"…a dramatic scene where a fire is burning in a building, with smoke rising into the air."* | **No** |
| `g6` | *"…a gradual increase in smoke from panel 1 to panel 6, indicating a gradual escalation of the fire."* | **No** |
| `g12` | *"…a gradual increase in smoke from panel 1 to panel 12…"* | **No** |

At `g6` it reads the panel order as time *correctly*, narrates an escalating
fire, and then denies there is any fire. Perception is not the failure.

Put the two together and the claim is symmetric: **the model invents events it
did not see, and denies events it did.** So this is now a counted column rather
than an anecdote — `denied_own_description`, the number of positive clips where
the model's own free description names the event (matched against that event's
vocabulary in `sources.yaml`) while its yes/no answer says No. Restricted to
positives, where the two answers cannot both be right.

For the 450M on `smoke-fire`: **2 of 2 positives at `g2`, `g6` and `g12`.**

The encoding flips it. At one panel the model answers Yes; at two or more it
answers No, while describing the same fire either way. Nothing about the fire
got harder to see between `f1` and `g2` — the image just stopped looking like a
photograph of a fire and started looking like a grid.

The practical consequence for anyone building on these models: **do not ask a
yes/no question.** The free description carried the information in every cell
above; the gate destroyed it. A pipeline that describes and then classifies the
description would have got all four of these right.

---

## F8 — 91% of cells are at chance or worse, and a recall column would hide all of it

*Source: `runs/field-v1/scores.json` — 2 models x 4 encodings x 4 events = 32 cells,
12 clips in 6 matched pairs (3 synthetic floor, 3 field), greedy decoding.*

> **Superseded in size, not in direction.** `runs/field-v2/scores.json` is the run
> the site and the post drafts quote: 6 models x 4 encodings x 7 events = 136
> cells, 134 matched pairs. There: recall 1.00 in 98 cells, false-alarm rate 1.00
> in 78, **86 of 136 (63%) at chance or worse**, and of the 134 pairs 23 are real
> detections, 99 trigger-happy, 9 blind, 3 inverted. The 91% below is this smaller
> run and should not be quoted as the headline. The shape holds at 4x the size;
> the rate softens because the larger models are in it.

| | |
|---|---|
| cells at chance or worse (`pair_discrimination` ≤ 0.25) | **29 of 32 (91%)** |
| cells that work (≥ 0.75) | 1 of 32 |
| **`recall` = 1.00** | **27 of 32 cells** |
| **`false_alarm_rate` = 1.00** | **25 of 32 cells** |
| mean `prompt_stability` | **0.34** — 24 of 32 cells disagree across three phrasings |

Pair outcomes, summed over every cell:

| outcome | | |
|---|---|---|
| **trigger-happy** — fired on the look-alike too | 36 | **75%** |
| blind — missed it | 7 | 15% |
| **discriminated** — an actual detection | **3** | **6%** |
| inverted — worse than a coin | 2 | 4% |

Those top two rows are the whole argument. **Recall is 1.00 in 27 of 32 cells and
the false-alarm rate is 1.00 in 25 of them** — the models are not detecting
events, they are answering Yes. A conventional benchmark table would print a
column of near-perfect detectors, and a PoC built on that column would ship a
system that alarms on every clip it sees.

Three genuine detections out of forty-eight pairs. Two of the three are on
synthetic floor clips.

And **mean prompt stability of 0.34**: with greedy decoding — no sampling, no
temperature — three phrasings of the *same question about the same image*
disagree in three quarters of cells. Before any of these numbers can be improved
by a better model, the question itself has to stop being the dominant variable.

**Not shown:** two of eight models, four of nineteen events, and no condition
variants yet. This is the shape of the result, not its final value — but the
shape has been stable from the first six synthetic clips onward.

---

## F9 — The models do not compare panels. They narrate one and invent the rest.

*Source: `runs/floor/` — the synthetic `line-stopped` pair, `g6`, three models.*

The synthetic conveyor pair is the easiest possible test of reading panel order as
time. Four orange boxes on a grey belt, nothing else in frame. In `synth-stop-pos`
the boxes are at **identical pixel positions in all six panels**. In
`synth-stop-neg` they advance across every panel. A human needs about a second.

All three models answered **Yes** to both. That alone would only say they cannot
tell. What they said is worse:

**LFM2.5-VL 3B, on the clip where nothing moves:**
> *"Yes. Panel 1 shows the objects at the leftmost position, while panel 6 shows
> them at the rightmost position, indicating m[otion]…"*

It asserts the boxes travelled left to right. They did not move at all — and it
offered that invented motion as its evidence for the conveyor having stopped.

**The same model, on the clip where they do move:**
> *"Yes. Panel 6 shows the objects in their final position with no motion blur."*

Its reason is the absence of motion blur *inside one panel* — an intra-panel cue —
not the positions across panels.

**North Micro Vision, on the moving clip:**
> *"…the image displays a consistent pattern of orange squares across all panels."*

They are in six different places. It says the same thing about the stopped clip.

So the mechanism is not "the sheet has no clock" and it is not weak perception.
**These models read a panel and generalise; they do not compare panels.** The
cross-panel relationship in the answer is generated to sound right, and it is
uncorrelated with the pixels — sometimes exactly inverted.

Two consequences worth carrying into anything built on this:

1. The contact sheet does not fail gracefully as panels are added. Beyond one
   panel the model is not extracting less temporal information, it is producing
   *confabulated* temporal information, which reads identically in the output and
   is far more dangerous downstream.
2. It explains the trigger-happy rate in F8. A model that manufactures a
   cross-panel story on demand will manufacture one that matches whatever the
   question asked about — which is exactly the failure F7 measured as
   `denied_own_description` and its mirror.

**Not shown:** whether a model prompted to report each panel *separately* before
judging would do better. That is the obvious next experiment and it is not run.

---

## F10 — Asking for a per-panel enumeration produces the shape of one, not one

*Source: `runs/panels/` — the F9 follow-up. 10 clips, `g6`, 3 models, greedy,
260 max tokens so nothing is truncated.*

F9 left one obvious question: is the failure representational, or is it a
reasoning shortcut a scaffold could fix? So the same clips were asked again with
the comparison forced into the output before the verdict —

> *"First, for each of the 6 panels in order, write one short line: the panel
> number, then where the main subject or objects are within that panel. Do not
> skip a panel and do not summarise. Then, on a new line, answer …"*

**It does not help. It hurts.** Pair discrimination, `gate` → `panels`:

| model | fall | line-stopped | object-removed | smoke-fire |
|---|---|---|---|---|
| LFM2.5-VL 3B | 1/2 → **0/2** | 0/1 → 0/1 | 0/1 → 0/1 | 0/1 → 0/1 |
| North Micro Vision | 1/2 → **0/2** | 0/1 → 0/1 | 0/1 → 0/1 | 0/1 → 0/1 |
| LFM2.5-VL 450M | 0/2 → 0/2 | 0/1 → 0/1 | 0/1 → 0/1 | 0/1 → 0/1 |

Both cells that were working stopped working. Under the scaffold LFM2.5-VL 3B
answered **Yes to all ten clips** — fully degenerate.

The enumerations themselves are the finding. Asked to describe six panels of the
synthetic conveyor:

| model | what it wrote |
|---|---|
| LFM2.5-VL 3B | `1, 2, 3, 4, 5, 6` then `Yes` — **byte-identical for the stopped clip and the moving one** |
| North Micro Vision | six well-formed items, every one the same string: *"Top of the frame; conveyor belt"* |
| LFM2.5-VL 450M | ignored the instruction entirely; just `Yes` |

North Micro's is the clearest. It produced a correctly-formatted six-item list, in
order, no skips — and filled every slot with one template. **The format of
per-panel reporting is available to these models; the per-panel content is not.**

So the answer to F9's open question is that the comparison is not being skipped
for want of prompting. It cannot be elicited. Chain-of-thought scaffolding on this
class of model produces fluent scaffolding.

Two things follow for anyone building on these models:

1. **A prompt cannot fix it.** Getting cross-panel evidence out of a contact sheet
   is not a prompt-engineering problem at 0.45B–3B; the information is not
   surviving into the model's usable representation.
2. **A structured output format is not evidence of structured reasoning.** All
   three models satisfied a strict format while carrying no information through
   it — which is exactly the failure mode a JSON-schema-constrained pipeline would
   hide, because the JSON would validate.

**Not shown:** whether frame-by-frame calls — one image per turn, aggregated by
the host rather than the model — recover it. That is the architecture this result
points at, and it is not yet built.

---

## F11 — Where a working cell breaks: occlusion, not darkness and not resolution

*Source: `runs/ladder/` — the `object-removed` pair (a pair of sunglasses lifted
from a retail tray vs a shopper browsing and taking nothing), degraded one
variable at a time, both halves of the pair degraded together.*

The first attempt at this ran the ladder on `smoke-fire` and produced a flat line
at zero. That was a methodological error worth recording: **a condition ladder is
only informative on a cell the model gets right when clean.** All three models
scored 0/1 on the clean smoke-fire pair, so eighteen degraded clips measured
nothing. `tools/ladder.py` now refuses to plot a model whose level-0 cell is not a
detection, and names it instead of drawing a flat line.

Rerun on a pair that does work clean:

| model | axis | clean | L1 | L2 | L3 |
|---|---|---|---|---|---|
| LFM2.5-VL 3B | darkness | ok | ok | ok | **ok** |
| LFM2.5-VL 3B | resolution | ok | ok | ok | **ok** |
| LFM2.5-VL 3B | occlusion | ok | ok | ok | **lost** |
| North Micro Vision | darkness | ok | ok | ok | **ok** |
| North Micro Vision | resolution | ok | ok | ok | **ok** |
| North Micro Vision | occlusion | ok | ok | lost | ok |

**Darkness and resolution do not break it. Occlusion does.**

Level 3 darkness is −0.45 brightness, 0.55 contrast and heavy sensor noise. Level
3 resolution is a **60p-equivalent** round trip. Both models still discriminate
the pair through all of it.

The resolution result is not luck, and F1 predicts it exactly. The model never
sees the source resolution: the clip is flattened to a `g6` contact sheet, then
squashed onto a 448² or 512² canvas, and each panel arrives as roughly 224×149 px
worth of about 33 visual tokens. **A 60p round trip still delivers more detail than
the contact sheet was going to preserve anyway.** You cannot degrade the camera
below what the encoding already destroys — which means, for a deployment,
*sensor resolution is not the lever*. The panel budget is.

Occlusion is different because it removes evidence the encoding cannot restore.
Level 3 covers ~50% of the frame in vertical bars; when the bars fall across the
tray, the before/after comparison has nothing left to compare.

The practical read for a PoC: **if it works in good conditions, poor light and a
cheap camera probably will not kill it; blocked sightlines will.** Camera
placement matters more than camera spec.

**Not shown, and it matters:** this is **one pair**, and North Micro's occlusion
row is non-monotonic (lost at L2, recovered at L3), which is the signature of
noise rather than a curve. Treat the darkness and resolution results as the
finding and the occlusion threshold as indicative only. More pairs that work
clean are needed before any of this is a number rather than a direction.

---

## F12 — The first clean detection: +0.3s latency, zero false alarms

*Source: `runs/stream/damage-jar-*` — sliding window, 1.6s window, 0.4s stride,
5 models, 26 windows per clip.*

Everything before this measured whole clips: one inference, one verdict, no way to
say *when* a model decided. Re-running the model on a sliding window — the way a
deployed camera actually works — turns the question into "at what moment does it
change its mind", and makes detection delay a real number rather than a panel index.

The clip: a glass jar falls into frame and shatters. The pair: the same framing
with an intact glass and bottle that never break. Both cut to 11.7s, both with a
four-second held lead-in so several windows close before the event.

| model | positive (breaks at 5.3s) | negative (nothing breaks) |
|---|---|---|
| **LFM2.5-VL 3B** | 10 windows clear, fires at 5.6s — **+0.3s** | **0 of 26 windows** |
| **North Micro Vision** | one blip, then locks on at 4.8s | **0 of 26 windows** |
| Holo2 4B | locks on at 4.8s | intermittent |
| Qwen3-VL 2B | fires at 4.4s | **all 26 windows** |
| MiniCPM-V 4.6 | fires at 5.2s | noisy |

**Two models discriminate perfectly.** LFM2.5-VL 3B stays quiet for ten
consecutive windows, fires three tenths of a second after the glass breaks, and
never once fires on the intact glass. That is the first result in this project
that would survive contact with a deployment.

What separates this from every cell that failed:

1. **The event is a state change with a hard boundary.** Intact glass and a field
   of fragments share no pixels. Compare `line-stopped`, where "moving" and
   "stopped" look identical in any single frame and only differ across panels —
   the comparison F9 showed these models do not perform.
2. **There is a real before.** The source clip opens with the jar already
   falling, so the baseline is a held first frame (`tools/leadin.py`). The pixels
   are the clip's own pre-event frame; only the duration is fabricated, and the
   clip is labelled `staged` for it.

**The uncomfortable reading.** The events these models can do are the ones a
frame-differencing algorithm from 1995 could also do — a large, abrupt,
whole-scene appearance change. The events that need a VLM's semantics (did that
person fall or lie down; is the line stopped or merely slow) are the ones they
fail. That is worth stating plainly to anyone weighing a PoC.

**Not shown:** one event type, one pair. Whether this holds for other
hard-boundary events — a spill appearing, a light going out, a door opening — is
not measured.

---

## F13 — The public datasets ship the matched pair already built

*Source: [kantine](https://huggingface.co/datasets/kantine/industrial_soldering_anomaly)'s
LeRobot recordings, Apache-2.0. `runs/stream/hazard-*`, `runs/stream/spill-*`.*

F6 concluded that nobody films the failure and treated that as the ceiling on the
corpus. That conclusion was reached by searching stock libraries and never
checking research datasets — a gap left open for most of this project's life. It
was wrong.

Every industrial task in kantine's collection ships in **two versions recorded on
the same rig**: `_anomaly` and `_expert`. Same fixed camera, same lighting, same
task, different outcome. That is precisely the ablation `stage.py` and
`leadin.py` were built to fake, available as real footage, under a licence with
no redistribution restriction. Several other datasets are similarly open —
Assembly101 is CC BY-NC 4.0 with 4321 videos, eight static cameras and explicit
**mistake** annotations for the assembly errors F6 called unsourceable.

### The first result that looks deployable

`hand-in-danger-zone`: a bare hand enters the path of a soldering iron at 6.6s on
a fixed overhead camera. The negative is episode 0 of the *same* dataset — normal
operation on the same rig.

| model | positive | negative (34 windows) |
|---|---|---|
| **LFM2.5-VL 3B** | 13 windows clear, fires **+0.2s** | 4 false alarms |
| **North Micro Vision** | **+0.2s** | 3 false alarms |
| **Holo2 4B** | **+0.2s** | 5 false alarms |
| Qwen3-VL 2B | fires from window 1 | ~20 |

Three independent models, identical latency, on a real industrial safety event.

### A trap worth writing down

The `_anomaly` repositories are **not all anomalous**. Their own
`meta/tasks.jsonl` assigns index ranges: `soldering_anomaly` is
`0:4 normal, 5:9 iron on wood, 10:14 hand between iron and board`. Taking the
first two episodes of an `_anomaly` repo — the obvious thing to do — yields clips
with nothing wrong in them. That happened here, and the conclusion drawn from the
contact sheet was "the anomaly is not visible to a human", which would have
rejected the best material in the corpus. `fetch_lerobot.py --eps` now forces
explicit indices and the reason is in the code.

---

## F14 — The question is a bigger lever than the model

*Source: `runs/stream/spill-*`, the same clips scored under two event questions.*

The coffee-spill pair was first filed under `damage`, whose question reads *"Is
the object damaged — cracked, crushed, or torn?"*. A spreading pool of coffee is
none of those. Re-filed under a new `spill` event asking *"Has liquid been spilled
onto the surface?"* — same clips, same models, same windows:

| model | under "damaged — cracked/crushed/torn" | under "liquid spilled onto the surface" |
|---|---|---|
| **LFM2.5-VL 3B** | 4 windows, then goes quiet | **+0.3s, sustains 21/21; 0/34 false alarms** |
| North Micro Vision | 1 window | +0.3s, sustains — but 32/34 on the control |
| Holo2 4B | on from the start | +0.3s, sustains — but 34/34 on the control |
| Qwen3-VL 2B | on from the start | +0.3s, sustains — but 31/34 on the control |

*Right-hand column recomputed on the rebuilt pair (F16). The first version of these
numbers used a control with a spill in it, which understated the saturation: what
looked like "2/34 false alarms" for the 3B is 0/34 against a genuinely clean table.
The finding is unchanged and slightly stronger.*

Changing only the wording turned the 3B from a transient blip into a sustained
detection, and turned three other models into constant alarms.

The saturation has a clean explanation: **the scene contains liquid throughout** —
in the jug, in the cup. Asked whether liquid has been spilled *onto the surface*,
three models answer for the presence of liquid; only the 3B separates "liquid is
present" from "liquid is where it should not be". The question did not make those
models worse — it exposed a distinction they cannot draw.

Two consequences:

1. **A benchmark's question wording is part of its measurement**, not a
   presentation detail. The same clips and models spanned "unusable" to "usable"
   on wording alone.
2. **A low score is not evidence of a model failure until the question has been
   checked against the clip.** This mismatch was introduced twice by hand here —
   a hand entering a machine filed under "is anyone not wearing a hard hat", a
   spill filed under "is it cracked". `validate.py` now flags a positive whose
   ground truth shares no vocabulary with its event definition, and that guard
   immediately found a third instance: the `damage` question omitted
   *broken/shattered*, so a shattered jar was being asked whether it was
   "crushed or torn".

---

## F15 — The "a 1995 frame-differencer would catch these too" claim was wrong on three of four events, and right on the one I made the most noise about

*Source: `tools/baseline.py`, `runs/baseline-sweep.json`. Median-of-opening-frames
background, per-frame absolute difference, morphological clean, alarm when the
changed area exceeds a threshold. Same clips, same 1.6s windows, same 0.4s stride.*

F12 asserted that the events these models can do "are the ones a frame-differencing
algorithm from 1995 could also do". That was asserted, never tested. Tested now:

| event | classical baseline | LFM2.5-VL 3B |
|---|---|---|
| glass shatters | +0.7s, **26/26 false alarms** | +0.3s, **0/26** |
| ~~liquid spill~~ | ~~+4.3s, 12/34~~ | ~~−0.1s, 3/34~~ |
| grounds spill | +3.8s, 3/34 | **+1.4s, 2/34** |
| **hand in danger zone** | **+0.2s, 0/34** | +0.2s, **4/34** |

**The liquid-spill row is struck through because its negative was contaminated —
see F16.** On the rebuilt pair the two methods tie exactly (+0.3s, 0/34 each).
The corrected form of this finding is in F16; the glass-shatter row also carries
a caveat there. What survives unchanged is the *shape* of the argument, and the
hand row, which was always the one that mattered.

**The baseline was given every advantage and still lost three of four.** Its one
knob was swept over 600 values and the threshold that *maximises its own score*
was kept — fitted on the very pair it is evaluated on, which no deployed system
gets. The VLM used one sentence of English and no tuning at all.

### Why the VLM wins where it wins

The three events it takes are the ones whose scene **contains motion that is not
the event**. The coffee clips have a robot arm moving through every frame; the
glass negative has a hand and changing light. A pixel-difference method cannot
tell "the arm moved" from "coffee is on the table" — it only knows the count of
changed pixels. That is the distinction the VLM is supposed to add, and this is
the first measurement showing it actually does.

### And the one it loses is the one I called deployable

`hand-in-danger-zone` was written up as "the first result that looks deployable":
three models firing at +0.2s. Background subtraction hits the same +0.2s with
**zero** false alarms and no model. A hand entering an otherwise-still scene is
the textbook case for the classical method, and here the VLM is strictly worse
while costing a 3B forward pass every 0.4s.

So the honest ranking is the opposite of the one the demo video implies. The
*least* impressive-looking events — a stain spreading while a robot works — are
where the VLM earns its place. The most dramatic one does not need it.

### What this changes

1. **No VLM result in this benchmark should be published without its baseline
   row.** The number alone cannot distinguish "the model understood" from "the
   pixels changed".
2. **The X thread must not lead with the hand.** It leads with the event a
   thresholded difference solves better.
3. The next comparison to run is a detector-plus-zone rule (`yolox-s` and
   `rf-detr` are both in the catalog), which is what an integrator would actually
   deploy for intrusion — and which needs a polygon drawn per camera. Measuring
   that configuration cost against "one sentence, no tuning" is the other half of
   the comparison.

**Not shown:** one pair per event, and the baseline is deliberately the simplest
credible one. A tuned MOG2 with a robot-arm mask would likely close some of the
gap on the spills — and the effort of building that mask is itself the number
worth reporting.

---

## F16 — A control clip with the event in it, and the corrected comparison it forced

*Source: `tools/spill_onset.py`, `runs/stream/spill*-{pos,neg}`. Five matched
pairs, four VLMs, two classical baselines, same windows throughout.*

### The bug

The negative half of the spill pair had a spill in it.

kantine's `pouringCoffee` collection labels five episodes normal. Four have a
clean table. Episode 15 — the one this benchmark used as its control — has coffee
on it from the start. I built the pair from a contact sheet without watching the
negative, and then counted every model's correct *"yes, there is a spill"* as a
false alarm.

Measured rather than eyeballed, the difference is not subtle. Brown fraction of
the table region, HSV `(5,80,40)–(30,255,190)`:

| episode | brown fraction | labelled | actually |
|---|---|---|---|
| 15 | **0.024** | normal | has a spill |
| 11, 12, 13, 14 | 0.003 | normal | clean |

An 8× difference, invisible to me on a 4-panel sheet at 33 tokens a panel — which
is the same failure mode this benchmark exists to measure in the models.

Every number that touched that pair was backwards for hours, in a direction that
flattered the VLMs. `spill_onset.py` now measures both the onset and the
cleanliness of the control, and no pair enters the corpus without it.

### The corrected comparison

Rebuilt from verified-clean episodes and extended to five pairs, because n=2 with
one tie is n=1:

Per pair, `latency / false alarms on the control / fires on the positive before the
event began`:

| pair | what changes | LFM2.5-VL 3B | bg-diff (swept) |
|---|---|---|---|
| spill — full cup knocked over | a pool | +0.3s, 0/34, 1/13 | +0.3s, 0/34, 0/13 |
| spill2 — poured beside the cup | a thin run | **+0.3s, 2/34**, 3/13 | +5.5s, 10/34, 0/13 |
| spill3 — poured onto the table | a stain | +0.7s, 2/34, 6/13 | **+0.3s**, 10/34, 0/13 |
| grounds — heap beside the machine | a heap | **+1.4s, 2/34**, 0/14 | +3.8s, 3/34, 0/14 |
| hand — into the iron's path | a hand | +0.2s, 4/34, 0/13 | **+0.2s, 0/34**, 0/13 |

### Counting both error types the same way

The third column is the one an earlier version of this table did not have, and
leaving it out flattered the VLMs. A window on the *positive* clip that closes
before the event starts is a window where the honest answer is No, exactly like a
window on the control. The background subtractor's threshold sweep scores
`(-neg_fire - pre)` — it is penalised for those explicitly, so it has zero of them
by construction — while the VLMs were never charged for theirs.

Over all 236 windows whose correct answer is No:

| method | median latency | wrong |
|---|---|---|
| **LFM2.5-VL 3B** | +0.3s | **20/236 (8%)** |
| bg-diff, threshold swept per pair | +0.3s | 23/236 (10%) |
| Holo2 4B | +0.3s | 98/236 (42%) |
| North Micro Vision | +0.3s | 145/236 (61%) |
| Qwen3-VL 2B | +0.3s | 165/236 (70%) |

That is a different headline from "6% vs 14%". The 3B and a swept 1995 background
subtractor are **close** — 8% against 10%, at n=5, which is not a gap to build a
pitch on. Six of the 3B's ten pre-onset fires are on `spill3` alone, where the
onset is colorimetric and lags the moment a person would call it a spill; charging
the model for those is conservative, and this table does charge it.

### What actually changed in the conclusion

F15 said the VLM wins where the scene contains motion that is not the event. That
was drawn from a pair where the "win" was an artefact. The corrected data says
something narrower and better supported:

**Latency is not where any of this lives.** Every method — four VLMs and a
thresholded pixel difference — detects at the same moment, +0.3s median, across
all five pairs. The 0.4s stride is the resolution limit, so this is a tie by
construction as much as by measurement. Any pitch built on the VLM being *faster*
is unsupported.

**Against the classical baseline the aggregate is a wash; the difference is
per-pair and runs both ways.** Counting every wrong window, the 3B takes three
pairs and the pixel method two:

| pair | 3B wrong | bg-diff wrong | margin |
|---|---|---|---|
| spill | 1 | **0** | 1 window — noise |
| spill2 | **5** | 10 | 5 |
| spill3 | **8** | 10 | 2 — and the 3B is 0.4s slower here |
| grounds | **2** | 3 | 1 window — noise |
| hazard-hand | 4 | **0** | 4 |

Only `spill2` is a margin worth anything, and it is the pair where the change is
*smallest* — a thin run of coffee rather than a pool. That is the regime where a
pixel count has nothing to threshold, and it is a real and specific advantage. It
is not a general one. Three of the five margins are 1–2 windows, which at this
sample size is noise in either direction.

**Model choice matters far more than method choice.** The spread among the four
VLMs is 8% to 70%. The gap between the best VLM and the classical baseline is 8%
to 10%. Choosing the wrong small VLM costs an order of magnitude more than
choosing between "VLM" and "no VLM" — so "should we use a VLM here" is the wrong
first question.

**Not shown:** five pairs, all from one robotics rig, one camera, one lighting
setup. The baseline's threshold is fitted on the very pair it is scored on, which
flatters it — and it still loses on false alarms. The two glass-shatter pairs are
excluded from this table on purpose: their negatives come from a different scene,
so bg-diff scores 26/26 on one and 0/20 on the other, which measures how those
pairs were built rather than how the methods differ.

---

## F17 — Rank by false alarms and you get one order; rank by detection and you get nearly the reverse

*Source: `runs/stream/{spill,spill2,spill3,grounds,hazard-hand}-{pos,neg}`, six VLMs
and the swept background subtractor on identical windows.*

Adding two models to the five-pair comparison broke the ranking it had, and the
break is instructive rather than incidental.

| method | detects (windows after onset) | wrong (windows where No is correct) | balanced accuracy |
|---|---|---|---|
| **LFM2.5-VL 3B** | 93/104 (89%) | 20/236 (8%) | **0.90** |
| MiniCPM-V 4.6 * | 102/104 (98%) | 90/236 (38%) | 0.80 |
| Holo2 4B | 101/104 (97%) | 98/236 (42%) | 0.78 |
| bg-diff, swept | 58/104 (56%) | 23/236 (10%) | 0.73 |
| North Micro Vision | 101/104 (97%) | 145/236 (61%) | 0.68 |
| Qwen3-VL 2B | 104/104 (100%) | 165/236 (70%) | 0.65 |
| **LFM2.5-VL 450M** | 21/104 (20%) | 47/236 (20%) | **0.50** |

Every method except the 450M fires on all five pairs, at +0.3s median.

\* 48 of MiniCPM's 340 answers do not parse to Yes or No even with the `\boxed{}`
reader (F-parser), and an unparseable answer is scored as neither a detection nor
a false alarm. Its two columns are therefore over a smaller effective sample than
the others, in an unknown direction.

### The 450M is at chance, and the false-alarm column hid it

Ranked by false alarms alone, LFM2.5-VL 450M comes **third of seven** at 20% —
ahead of Holo2 4B, North Micro Vision and Qwen3-VL 2B, all several times its size.
That reading was one edit away from being posted.

It is answering at chance. It says Yes on 20% of the windows where the event has
happened and on 20% of the windows where it has not. **The two rates are the same
number**, which is what "the answer is uncorrelated with the event" looks like in a
table. Its balanced accuracy is 0.50 exactly. It also fired after onset on only
**one of the five pairs**, so its "+0.2s latency" is an n=1 figure and should not
be quoted at all.

A false-alarm column rewards silence. A recall column rewards noise (F8). Neither
is a ranking; each is one half of one.

### And it changes the verdict on the classical baseline

F16 concluded the 3B and the swept background subtractor were a wash: 8% wrong
against 10%. That was the false-alarm half only. The subtractor **misses 44% of
the windows after the event** — it fires, then falls below threshold as the pool
stops spreading and the scene settles. The 3B holds the alarm on 89%.

So which is better depends on a question the benchmark had not been asking:

- **"Does it fire at all, and how fast?"** — every method except the 450M detects
  all five events, median +0.3s. Genuinely a tie, and no VLM earns its cost here.
- **"Is the signal there when you look?"** — 0.90 against 0.73. If a downstream
  system samples at an arbitrary moment, or needs the alarm to persist rather than
  blink, the 3B is clearly better and the wash disappears.

### The pattern worth keeping

This is the third time the ranking in this benchmark has moved because a column was
added, not because a measurement changed: recall alone (F8), false alarms alone
(F16), and now detection sustain. Each time the previous order looked stable and
publishable.

The working rule: **a single number over these models is not a ranking of them.**
Report detection and false alarms together, always, and treat any ordering that
rests on one of them as provisional.

**Not shown:** five pairs, one rig, one camera. Balanced accuracy weights a missed
window and a false alarm equally, which no deployment does — an integrator with a
tolerance for false alarms should read the two columns, not the summary.

---

## F18 — Moving the camera swapped which model wins. Nothing here was stable.

*Source: `runs/stream/*-v2` against `runs/stream/*`, via `tools/view_compare.py`.
Four matched pairs, the same episodes from kantine's second camera
(`observation.images.logitech_2`) instead of its first. Same rig, same lighting,
same events, same questions, same 1.6s/0.4s windows, same 16:9 centre-crop
pipeline. Onsets re-measured from the new view rather than copied.*

Every kantine recording ships two synchronized cameras. This benchmark used only
the first for its entire life. The second is the same event from a low, oblique
angle instead of a high one.

| method | overhead | oblique | change |
|---|---|---|---|
| **LFM2.5-VL 3B** | **0.89** | 0.70 | **−0.19** |
| Holo2 4B | 0.74 | **0.89** | **+0.15** |
| bg-diff, swept | 0.66 | 0.56 | −0.10 |
| Qwen3-VL 2B | 0.65 | 0.74 | +0.09 |
| North Micro Vision | 0.61 | 0.69 | +0.08 |

Balanced accuracy. Overhead: 189 windows where No is correct; oblique: 184.

```
rank overhead:  3B  >  Holo2  >  bg-diff  >  Qwen  >  North Micro
rank oblique:   Holo2  >  Qwen  >  3B  >  North Micro  >  bg-diff
```

**First and third place swap.** The model this benchmark spent weeks identifying as
the one that works is third from the new angle. The model written up as too
trigger-happy to deploy is first. The classical baseline goes from third to last.

### Where the 3B's score went

Its false alarms do not move (8% → 9%). Its **detection collapses, 87% → 49%**, and
not uniformly — detections in the windows after onset:

| pair | what changes | LFM2.5-VL 3B | Holo2 4B |
|---|---|---|---|
| spill | a pool | 21/21 → 22/22 | 21/21 → 21/22 |
| spill2 | a thin run | 21/21 → **7/21** | 21/21 → 21/21 |
| spill3 | a stain | 18/21 → **10/27** | 21/21 → 15/27 |
| grounds | a heap | 12/20 → **4/18** | 17/20 → 17/18 |

It still sees the big pool from either angle. It stops seeing the small changes —
which are exactly the cases F16 identified as where it beats the pixel method. From
a shallow angle a thin run of coffee is foreshortened into a few pixels near the
table edge, and the 3B misses it two times in three.

The F16 mechanism survives and inverts into a limit: **the 3B's advantage is on
small changes, and a shallow camera angle is what makes a change small.**

### The control that had to be run first

The two views were initially built at different aspect ratios — the overhead
corpus 16:9 (centre-cropped from a 4:3 source by the original pipeline), the
oblique clips at native 4:3. Every model stretches its input to a square canvas
(F1), so this was not a free variable and the first version of this finding was
filed as provisional.

Rebuilt with the identical centre-crop and re-run, the effect of framing is:

**0 changed verdicts out of 1088** — four models, 272 windows each, byte-identical
answers between the 4:3 and 16:9 runs.

Removing a quarter of the frame and changing the stretch ratio moved nothing.
Moving the camera moved 38 points of detection. Whatever these models are keying
on, it is not the framing.

The pixel baseline is the opposite: the same re-crop **halved** its detection, 45%
→ 24%, because it counts changed pixels as a fraction of a frame whose size just
changed.

### The claim that did not survive its own control

The uncontrolled comparison had the classical baseline moving 0.66 → 0.66 — the
cleanest story in the whole project: *only the method that ignores the viewpoint is
stable under a viewpoint change*. It was an artifact. Its −0.10 from the angle and
its +0.10 from the framing cancelled exactly.

Nothing measured here is stable. The VLMs are insensitive to framing and sensitive
to viewpoint; the pixel method is sensitive to both. The tidiest result on the page
was the one that most needed the control, which is the general shape of this
project's mistakes.

### What it means for anyone sizing a PoC

**A small-VLM benchmark on one camera measures a model-camera pair, not a model.**
This benchmark's own headline moved 0.19 on a camera move that changed nothing
about the task — larger than most of the model-to-model differences it had been
reporting. A vendor comparison run on one mounting position does not transfer to a
different mounting position in the same room.

**Not shown:** four pairs, one rig, two cameras. `hazard-hand` is excluded because
from the oblique view a person's arm is in frame at t=0 and never leaves — that
pair has no window whose correct answer is No. Which is itself the point: the 6.6s
"onset" the overhead pair reports is when that crop could first see the hand, not
when the hand arrived. Determinism was checked rather than assumed: 30 tasks from
the overhead arm re-run hours later on a loaded machine returned byte-identical
answers, 30/30.

---

## F19 — Not one real-footage pair in the stock corpus has a control from the same camera

*Source: every clip in `clips/` with a `pair`, checked against its counterpart's
`source.file`.*

F6 said stock libraries have the normal state of every process and the abnormal
state of almost none. F13 corrected the ceiling that implied, by finding research
datasets that ship both. This is the sharper version of the same fact, and it is a
count rather than an impression.

Of the 17 matched pairs in the corpus outside the kantine rig:

| pair type | count | control from the same camera? |
|---|---|---|
| `line-stopped-staged-*` | 4 | **yes** — composited from the same source clip |
| `synth-*` | 3 | **yes** — same generator, one variable changed |
| everything else — fall, smoke-fire, handover, object-removed, parcel-pass, ppe-missing | **10** | **no** — two different stock videos |

**Every same-camera control in the stock tier is staged or synthetic. Zero are real
footage.** The ten real-footage pairs are each a positive from one video and a
negative from a different video, with different scenes, framing, lighting and
subjects.

### What that costs

**The classical baseline cannot be run on them at all**, and running it would be
worse than not: background subtraction on a cross-scene pair measures how different
two videos are. On the two glass-shatter pairs, which have this defect, it scored
26/26 false alarms on one and 0/20 on the other — a gap that says nothing about the
method. Those numbers are already flagged as unusable in the post drafts; this is
the general form of that flag.

**The VLM numbers are weaker than they look, in a way that is easy to miss.** A
model can separate a cross-scene pair by recognising the scene rather than the
event: "a construction site" versus "an office" is a much easier question than "did
someone fall". Pair discrimination on those ten pairs does not distinguish the two,
so a cell that scores 1.00 there is not evidence the model saw the event.

That applies to F8's headline. The 134 matched pairs behind "99 trigger-happy" are
mostly cross-scene, which makes the *failures* trustworthy — a model that says Yes
to both halves of an easy pair is certainly not detecting the event — while making
the 23 successes ambiguous. **The finding is safe in the direction it is used and
unsafe in the direction it is not**, which is worth stating explicitly because the
same table supports both readings.

### Why this is structural, not a curation failure

A matched control requires the same camera to have filmed both the incident and its
look-alike. Stock footage is shot to be sold as a scene; nobody films fifteen
seconds of a warehouse where nothing happens as a companion to the clip where
something does. The staged and synthetic pairs in this corpus exist precisely
because that gap had to be filled by construction.

The consequence for sourcing: **fixed-camera research recordings are not one option
among several, they are the only source of real matched pairs found so far.** Every
defensible number in this benchmark comes from kantine, and that is not an accident
of where I looked first.

**Not shown:** one stock library (Pexels), searched by title. A CCTV or dashcam
archive with continuous recording would have same-camera controls by construction —
none licence-clean has been found, and that search is not exhausted.

---

## F20 — On the stock events where a real control exists, nothing works

*Source: the 7 same-source pairs identified in F19 — 4 composited `line-stopped`
and 3 synthetic floor pairs — scored with the same sliding window and the same
swept baseline as the kantine rig.*

Filling in the stock tier (five VLMs plus the classical baseline on every clip)
produced its first honest numbers, and they are flat:

| method | fires on | detects | wrong | balanced |
|---|---|---|---|---|
| LFM2.5-VL 3B | 3/7 pairs | 19/61 (31%) | 15/104 (14%) | **0.58** |
| MiniCPM-V 4.6 | 5/7 | 17/61 (28%) | 16/104 (15%) | 0.56 |
| Holo2 4B | 4/7 | 24/61 (39%) | 32/104 (31%) | 0.54 |
| North Micro Vision | 7/7 | 58/61 (95%) | 90/104 (87%) | 0.54 |
| Qwen3-VL 2B | 7/7 | 61/61 (100%) | 104/104 (100%) | **0.50** |
| bg-diff, swept | 6/7 | — | — | see below |

**Every method is at chance or within noise of it.** Qwen3-VL 2B is exactly 0.50 in
the purest available form: it said Yes to all 61 windows after the event and all
104 where the answer was No.

Set against 0.90 for the same 3B on the kantine spills, this is the sharpest
statement the benchmark has produced about scope:

> The one good number in this project comes from the one evidence class that works.
> A spill **adds** something to the frame. A line stopping **removes** motion, and
> nothing here can see that.

### The baseline cannot even be run on the clearest case

`synth-stop` is a conveyor whose items sit in pixel-identical positions across
every panel. Background subtraction measures 0.0 changed pixels in all 12 windows:
**no threshold exists that fires**, so the sweep returns nothing. That is not a
failure of the baseline, it is the definition of the event — a stoppage is the
absence of change, and a change detector is structurally blind to it.

The VLMs are not blind to it in principle; they are asked a question about the
world rather than about pixels. In practice they are worse than blind — they answer
Yes anyway, which is how a 100%-detection model lands at 0.50.

### What this does to the corpus plan

`line-stopped` was one of the events in the original brief, and it is a `dwell`
class: the evidence is a *lack* over time. The `state` and `change` classes (spill,
hand entering, glass shattering) are where every working cell in this benchmark
lives. F6 predicted the sourcing difficulty of incidents; this predicts something
narrower and more useful — **which events are worth sourcing at all.**

Before spending curation effort on a new event, ask whether its evidence is
something appearing in the frame. If it is a removal, an absence, or a rate change,
the expected result is 0.50 and the corpus work will buy a null.

**Not shown:** 7 pairs, of which 4 are composited from one source clip each and 3
are synthetic. A real fixed-camera recording of a line stopping might behave
differently — vibration, operators reacting, a warning light — and none of that is
in a composite that simply freezes the frame. The result is about these pairs, and
the honest reading is "no evidence any of these models can do dwell events", not
"proven impossible".

---

## F21 — The events stock footage can supply are the events that do not need a VLM

*Source: `runs/stream/{office-11903981,office-11903990,intrusion-35054875,conveyor-4473187}`.
Four clips selected from 327 candidates, scored on the transition tier — each
positive judged on its OWN before and after, with no paired control, and the
classical baseline swept against that same clip's pre-onset windows.*

Scene-based sourcing (F-REJECTED, `tools/fetch_scene.py`) finally produced real
stock footage that supports a before/after: a fixed camera on an empty office
corridor, a person walking into it. Scored, it says something blunter than
expected.

### Transition tier — a person comes into view

| method | detects after onset | fires before it | transition | latency |
|---|---|---|---|---|
| **background subtraction, self-swept** | 77/78 (99%) | **0/20 (0%)** | **0.99** | +0.3s |
| Holo2 4B | 53/78 (68%) | 7/20 (35%) | 0.66 | +0.3s |
| LFM2.5-VL 3B | 23/78 (29%) | 4/20 (20%) | 0.55 | +0.7s |
| LFM2.5-VL 450M | 78/78 (100%) | 20/20 (100%) | **0.50** | +0.1s |
| North Micro Vision | 78/78 (100%) | 20/20 (100%) | **0.50** | +0.1s |
| Qwen3-VL 2B | 78/78 (100%) | 20/20 (100%) | **0.50** | +0.1s |
| MiniCPM-V 4.6 | 52/78 (67%) | 19/20 (95%) | **0.36** | +0.1s |

Three models answer Yes to **every window of every clip** — before the corridor
has anyone in it and after. MiniCPM lands *below* chance: it says Yes to 95% of
the empty-corridor windows and only 67% of the occupied ones, which is the wrong
way round.

Against that, a 1995 background subtractor scores **0.99**, with its one knob
fitted on the clip's own quiet opening.

### Quiet tier — a conveyor that runs and never stops

The brief asked for false alarms per hour. With a clip whose correct answer is No
throughout, that is a direct measurement and needs no pair at all:

| method | false alarms | per hour |
|---|---|---|
| Holo2 4B | 2/34 | 480 |
| LFM2.5-VL 3B | 9/34 | 2,158 |
| MiniCPM-V 4.6 | 19/34 | 4,555 |
| LFM2.5-VL 450M / North Micro / Qwen3-VL 2B | 34/34 | **8,152** |

8,152 alarms per hour is one every 0.44 seconds, on footage where nothing happens.

### The synthesis, and it is uncomfortable

Put F16 and this together:

- The events where a small VLM **beats** a pixel method are small, contained
  changes — a thin run of coffee, a heap of grounds (F16, 3B at 0.90 against 0.73).
  Those come from fixed-camera research recordings, and nowhere else so far.
- The events where **stock footage can supply a before and an after** are people
  and vehicles entering empty frames. Those are exactly the events background
  subtraction already solves, at 0.99.

**The footage that is easy to get measures the case that does not need the model.**
Which is a decent explanation for why on-device VLM demos look convincing and PoCs
disappoint: the demo is built from the footage that exists, and that footage is the
1995 problem.

**Not shown:** three positive clips and one negative, one stock library. The
baseline is flattered here in the same way F15 flagged for `hand-in-danger-zone` —
a person entering an otherwise-still scene is its textbook case, and a scene with
its own motion (the conveyor) is where its own false alarms would appear. That
comparison is not yet run: the quiet tier above scores only the VLMs, because a
self-swept threshold has nothing to fit on a clip with no onset.

---

## F22 — A mirror changes nothing, except where the model was already guessing

*Source: `tools/mirror_probe.py` over `runs/stream/*-mir`. Twelve everyday clips
from the genre corpus, horizontally flipped and re-run through four models —
373 windows each, 1,492 answers compared window for window against the originals.*

Every clip in this corpus is public: Pexels stock, kantine's HuggingFace
recordings. The models may have seen them in training, and if one is retrieving a
memorised caption rather than reading the picture then every number in this
document measures the wrong thing. That deserved a measurement rather than a
footnote.

A horizontal flip preserves the meaning exactly — a cat on a bench is still on the
bench, two people are still two people — while destroying any pixel-level match to
a training example.

### Per-window agreement between a clip and its mirror

| genre | Holo2 4B | LFM2.5-VL 3B | North Micro | Qwen3-VL 2B |
|---|---|---|---|---|
| action, ambient, animal, material, spatial, text | **100%** | **100%** | **100%** | **100%** |
| interaction (cup removed) | 91% | 100% | 94% | 100% |
| state-change (pancake) | 100% | 85% | 94% | 100% |
| **count** | 52–100% | **40–47%** | **56–72%** | 100% |
| **overall** | 94% | 90% | 93% | **100%** |

Six genres — is it raining, is the cat on the bench, is the person writing, is the
ground wet, does the sign say SALE, is the dog eating — are **bit-identical under
the flip for all four models**. Not similar: the same answer in every one of those
windows.

### Where the answers do move, it is where the model was already unreliable

The disagreements are not scattered. They land on exactly the clips each model was
already failing, and the pattern differs per model in a way that is diagnostic:

- **LFM2.5-VL 3B** flips on both two-person clips — the two it coin-flips at 47%
  and 54%. Mirrored, it scores 11% and 31%. Same indecision, resampled.
- **North Micro Vision** flips on the two *three*-person clips, which are the ones
  it fails. Its two-person clips agree 100%.
- **Holo2 4B** flips on the count clip it is 52% on and agrees perfectly on the one
  it is 0% on.
- **Qwen3-VL 2B** agrees with itself 100% everywhere, including 0% → 0% on both
  two-person clips. It is the most self-consistent model measured here and one of
  the least accurate: perfectly stable, perfectly wrong.

**A model's answer moves under the mirror precisely where it is guessing.** Where
it is confident — right or wrong — the flip changes nothing.

### What this does and does not settle

**Settles:** no evidence of pixel-level retrieval of these clips. If a model were
matching a memorised Pexels video, breaking the pixel match should break the
answer. Across six genres and four models it changed nothing at all.

**Does not settle:** a mirror cannot separate "reads the picture" from "has a prior
that happens to be right". A model answering "yes it is raining" from the general
look of rain scenes, without examining this one, also scores 100% invariance.
The probe rules out memory of *this clip*; it does not prove perception.

**Also worth stating:** the counting result never needed this probe. If these clips
had been memorised with their stock captions — "two women talking at a cafe" — the
count question would be the easy one. It is the only one every model fails.

**Not shown:** twelve clips, one transformation. A flip is the cheapest invariance
to test and the weakest; crop, colour and time-reversal would each say something
different and none is run.

---

## F23 — Ask a model what is happening in a still scene and it starts inventing

*Source: `runs/neutral/` (394 windows, 69 everyday clips, 5 models) and `runs/alu/`
(117 windows, 15 shots of a 1956 industrial film, 3 models), grounded against
RF-DETR on the same frames by `tools/grounding.py` and `tools/coverage.py`.*

Every prompt in this benchmark until now named the event it was hunting: "has
anything been spilled", "did a person fall". That measures whether a model can
confirm somebody else's hypothesis. It says nothing about what the model would
have noticed on its own, which is the thing you need before you know what a model
is *for*.

So the same footage, the same runtime, one neutral instruction — **describe what is
happening** — and the replies scored not for correctness but for what they contain.

### What each model volunteers when nothing is asked

| mentions | Holo2 4B | LFM2.5-VL 3B | MiniCPM-V 4.6 | North Micro | Qwen3-VL 2B |
|---|---|---|---|---|---|
| people | 10% | 55% | 41% | 53% | 58% |
| action | 13% | 78% | 56% | 57% | **93%** |
| spatial relation | 7% | 65% | 25% | 28% | **100%** |
| **material — wet, dirty** | 1% | **12%** | **13%** | **11%** | **20%** |
| **text on a sign** | 2% | **18%** | **21%** | **8%** | 28% |
| change over time | 7% | 68% | 41% | 31% | **94%** |
| **median length** | **9 wd** | 87 wd | 104 wd | 72 wd | **255 wd** |

**Holo2 4B does not answer a neutral question.** Nine words, and the words are the
prompt handed back verbatim. The same model scores 0.78 balanced accuracy when an
event is named. It is a judgement device, not a describer, and nothing in the
judgement numbers says so.

**Nobody volunteers materials or text.** Wet floors and written signs turn up in
6–28% of descriptions across every model. Both are read correctly when asked
directly — F17 has every model at 100% on "is the ground wet?" — so this is not a
perception limit. It is an attention one, and it means a product built on running
commentary will never hear about the wet floor unless somebody thinks to ask.

### Where the invention happens

RF-DETR gives an independent inventory of the same frame, so a named object is
either confirmed or not. Unconfirmed is not proof of invention — the detector
misses things — but every model faces the same detector with the same blind spots,
so the comparison holds.

Split by how much the scene moves, on the film:

| model | still shots | moving shots |
|---|---|---|
| LFM2.5-VL 3B | **52%** unconfirmed | 27% |
| MiniCPM-V 4.6 | **36%** | **6%** |
| Qwen3-VL 2B | **53%** | 31% |

**A still scene makes every model two to six times less checkable.** MiniCPM names
almost nothing unconfirmable while something is moving and invents freely once
nothing is. The clearest single case: a locked-off shot of a wooded hillside,
measured at 0.022 foreground change — eight identical frames — described as *"a
helicopter over a rural landscape"*. There is no helicopter.

The mechanism is not mysterious. Asked to describe, with nothing to report, a model
reports something.

**This is the failure mode that matters for continuous monitoring**, because a
camera watching a room is in the still case nearly all of the time. It is also
distinct from the false-alarm rate in F21: that is answering the wrong yes or no,
this is naming a specific object that is not there. A pipeline that consumes
running commentary is exposed to the second and not protected by measuring the
first.

### The film also settles the sourcing question

One 13.7-minute public-domain industrial film (`archive.org/details/Aluminum1956`,
Reynolds Metals, 1956) cut on scene change gives 40 shots of 8s or more, 15 of them
on a locked camera. Against 327 stock clips fetched and measured for 6 keepers, and
with one licence check instead of 327.

Walking the film in order, the descriptions recover its structure without any
memory between windows: rail cars, a furnace, a rolling mill, coils, a warehouse,
then kitchenware and appliances — the raw-material-to-home arc every corporate film
of the period is built on.

### The confound this survived

If the object detector simply saw less in a still shot, "unconfirmed" would rise
there for a reason having nothing to do with the model. Checked: on still shots it
finds **more** (mean 1.66 COCO classes per frame, 21% of frames empty) than on
moving ones (1.41, 27% empty). The split is not an artefact of the instrument, and
if anything it is understated.

**But the detector is unreliable on this footage and that limits the aggregate.**
On `alu-s026` it labels an aluminium coil a *fire hydrant* while the model
correctly reports "handling of large metal coils" — there, the unconfirmed count is
the detector being wrong. The number that survives without the detector is the one
checked by eye: eight identical frames of a hillside, a helicopter, then a fire.

**Not shown:** one film, one era, one 4:3 scan. Descriptions were sampled every
third window, not exhaustively. The grounding check covers COCO's 80 classes, so
actions, materials and weather — the categories the coverage table shows models
neglect — cannot be verified this way at all.

### A measurement bug this uncovered

`enter_onset.py` read 31 of 33 shots from the film as "camera moves", clustered at
0.30–0.51 px, while the frame edges plainly did not move. The cause was **film
grain**: phase correlation keys on high-frequency detail, and a 1956 scan's grain
is independent per frame, so the correlation peak wanders on a locked-off camera.
A Gaussian blur before correlating removes it — still shots went from 2 to 10, and
the stock corpus, where the threshold was originally calibrated, is unchanged
(fixed clips still measure 0.02–0.13, moving ones 0.7–2.2).

The threshold was tuned on clean digital video and silently wrong on film. Any
measure carried to a new kind of footage needs re-checking against eyes before its
output is believed.

---

## Open, not yet measured

- **Six of eight models.** Only LFM2.5-VL 450M and North Micro Vision have run.
  The rest are downloading at ~0.5 MB/s; ~15 GB to go. MiniCPM-V 4.6 is the one
  to watch — at 64 visual tokens it is the direct test of whether the budget,
  not the parameter count, is the binding constraint.
- **The degradation ladder.** `tools/degrade.py` renders all five axes at three
  levels and is verified to run, but nothing has been scored through it yet.
- **Everything beyond one real pair.** `runs/field-fall/` is one event, one pair.
  It demonstrates the method; it is not a result about falls.
- **`g20`**, and whether the panel ladder ever turns back down on real footage.
