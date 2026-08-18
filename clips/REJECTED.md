# Rejected clips

Fetched, watched, and kept out of the benchmark. Recorded rather than deleted:
a corpus that only shows what survived curation cannot be audited, and the
reasons here are findings in their own right.

The bar: **a human must be able to call the event from the contact sheet.** If a
careful person cannot, a model failing it measures the harness, not the model.

| clip | event | why |
|---|---|---|
| `fall-5155837` | fall | Low-angle skate-park shot. Only the skater's legs are ever in frame — no torso, no head, no ground contact. The fall is real; it is not visible. |
| `smoke-fire-8965440` | smoke-fire | Fire-drill scene: a man with an extinguisher enters a doorway and white vapour fills the frame. No flame, and extinguisher discharge is indistinguishable from smoke. Ground truth would be a coin flip. |
| `smoke-fire-4404144` | smoke-fire | Pexels titles it *"thick smoke coming out of the chimney"*, but the plume is white and reads as steam. The title is not evidence. |
| `smoke-fire-6527496` | smoke-fire | Genuine street-vent steam at night — a good hard negative in principle, but the drone tumbles more than 90° between panels and one panel is fully engulfed. Viewpoint rotation is an uncontrolled confound on top of the variable under test. |

## The rule this produced: white plumes are unlabelable

For `smoke-fire`, **a white plume cannot be labelled from pixels alone.** Steam,
water vapour, cryogenic venting, extinguisher discharge and genuine white smoke
are the same image. Two of the ten fetched positives were white plumes titled
"smoke".

So the curation rule for this event is:

- **positive** requires visible flame, or a distinctly dark / black plume
- **negative** is a white or pale plume in an industrial or outdoor setting
- a white plume claimed as smoke goes in neither column

This is not a corpus defect being tidied away. It is the reason smoke detection
false-alarms in the field, and it belongs in the results: the benchmark asks
models to separate dark smoke from white vapour, which is the separable part of
the problem, and does not pretend the inseparable part is scoreable.

## kantine LeRobot anomaly episodes

| clip | event | why |
|---|---|---|
| `object-drop-dishdrop-*` | object-drop | The plate does move from the arm to the table, but at every resolution I could not tell whether it was **dropped or placed**. That is precisely the distinction `object-drop` defines as its hard negative ("an object placed down deliberately"), so the ground truth would have been a guess. |
| `assembly-wrong-hatch-*` | assembly-wrong | "forgot to close the hatch / measured the wrong hole / probe on red instead of black" — real anomalies, but the difference from the expert run is a few centimetres of arm position on a small task board. Not callable by eye at clip scale. |
| `assembly-wrong-screws_sorting-*` | assembly-wrong | "screws in the wrong plate" — same problem: the plates are small and the screws smaller. |

These are not bad recordings; they are anomalies defined in the robot's coordinate
frame rather than in the image. A benchmark that scored them would be measuring
whether a model can guess, since the human writing the ground truth cannot see the
difference either.

| `assembly-wrong-grocery-*` | assembly-wrong | "items in the wrong box". The expert run does show the rule (green/yellow left, brown/orange right), but the anomaly differs from it by roughly one item — a red chilli in a bin instead of on the table. Too small to state as ground truth, and the rule might be colour or might be fruit-vs-snack; I could not tell which. |
| `spill-coffeetable-*` | spill | Annotated "pour the coffee on the table", but in the episodes fetched the table stays clean at every panel. The spill is either off-frame or too small. |

## The pattern, after 8 tasks from one collection

Three kept, five rejected, and the split is completely clean:

**Kept** — the anomaly ADDS something to the frame that was not there:
a hand, a pool of coffee, a heap of grounds.

**Rejected** — the anomaly is a *wrong choice* defined against a task rule:
wrong bin, wrong hole, wrong plate, dropped-instead-of-placed. The pixels barely
differ; what differs is the meaning, and the meaning lives in a spec the camera
never sees.

That predicts what to look for in any future dataset, and it is also the sharper
version of what this benchmark has been circling: **these models are being asked
to judge intent from appearance.** Where the intent left a mark, they can. Where
it did not, neither can the person writing the ground truth.

## Scene-search batch — 327 candidates measured, 6 kept

Fetched by `tools/fetch_scene.py` (search by PLACE, after event-name search was
shown not to work) plus the event-name batches for intrusion, entry-exit and
vehicle-arrival. Reviewed with `tools/review.py`, filtered by `tools/enter_onset.py`.

**The mechanical filter did most of the work, and it caught what eyes could not.**
Of 327 clips measured:

| outcome | n | decided by |
|---|---|---|
| camera moves (median frame-to-frame shift > 0.35 px) | **165** | phase correlation |
| something enters a fixed, quiet frame | 101 | changed-pixel rise |
| occupied or busy from the first second | 53 | changed-pixel level |
| fixed camera, nothing ever enters | 8 | — usable as QUIET footage |

I had hand-picked twelve of these as "fixed camera" from contact sheets. Measured,
**three of the twelve were fixed.** A slow dolly or a drifting drone is invisible in
six sampled frames and fatal to a before/after comparison — the first version of
the onset tool read a drone gliding down a warehouse aisle as "a forklift enters
at 0.9s".

Of the 101 that survive the camera test, only 25 have three clear windows of
lead-in before the event, and only 7 of those are new stock footage. Eyeballed,
most of the 7 fail for reasons no measurement catches:

| clip | why |
|---|---|
| `construction-8598737` | tilt-shift timelapse; figures are a few pixels, no event is callable |
| `warehouse-31751344` | cuts to a close-up of a handheld scanner and back — not one camera feed |
| `smoke-fire-25549230` | aerial above cloud at sunrise; no smoke, no fire |
| `damage-5647308` | a light bulb brightening; nothing is damaged |
| `damage-7876233` | studio product shot with a cut; the "event" is an edit |
| `warehouse-4941466` | fixed and quiet, but nothing legible happens |
| `smoke-fire-29961573` | forest fire, but burning from frame 1 — a state, not a transition |

### The structural finding

**Stock clips are cut to open on the action.** They are 8–30 seconds, sold as a
shot rather than a recording, and nobody uploads three seconds of an empty
corridor before the interesting part. That is why 101 clips with a real entry
collapse to 25 once three windows of lead-in are required, and to 6 once a human
checks what actually enters.

This is the same wall as F6 and F19 from a third direction. Fixed-camera research
recordings remain the only source that supplies a before by construction, because
they record the whole episode rather than the good part of it.

### Kept

| clip | event | why |
|---|---|---|
| `office-11903981` | entry-exit | fixed corridor, empty 11.4s, person enters, leaves at 17.3s |
| `office-11903990` | entry-exit | fixed corridor, empty 4.5s, person enters and walks away |
| `intrusion-35054875` | intrusion | fixed frame, empty 2.8s, person vaults a barrier into it |
| `workshop-6789912` | object-removed | fixed overhead bench, an item is taken at 11.5s and the gap stays |
| `conveyor-4473187` | line-stopped (negative) | a belt that runs and never stops — a hard negative with continuous motion |
| `production-29975891` and 7 others | — | fixed camera, nothing happens: QUIET footage for false-alarms-per-hour |
