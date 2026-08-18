# Scenes worth measuring

The demand side, written before any footage is searched for. Searching first
produces whatever stock libraries happen to sell, and then the questions get bent
to fit it.

Two tests. A scenario has to pass both.

**1. What breaks when the model is wrong?** Not how dramatic the footage is. A
volcano detected correctly proves nothing — nobody puts a 3B model on a volcano.
Two people at a café table miscounted is the most interesting result this project
has produced and the footage is furniture.

**2. What would a 2020s CV pipeline do here?** If a person detector, a pose model
and a background subtractor would handle it, a VLM doing it worse is not a result.
This test cuts hard, and it should: half the first draft of this list failed it.

## The second test, applied to what has already been measured

The benchmark keeps producing evidence against its own subject, and that has to be
faced before more scenarios are written:

| scenario | classical method | measured outcome |
|---|---|---|
| a person enters an area | background subtraction | **0.99** balanced accuracy, self-swept (F21) |
| a hand enters a machine's path | background subtraction | **beats every VLM**, 0 false alarms (F15) |
| a person falls | YOLO + pose | not run here, but it is the textbook case |
| a machine stopped | frame differencing | structurally blind — but so is every VLM, all at chance (F20) |
| **a thin run of coffee spreads** | swept background subtraction | **+5.5s and 10 false alarms; the 3B +0.3s and 2** (F16) |

Only the last row is a reason to run a VLM. The change is too small for a pixel
threshold and COCO has no class for "spill", so the classical side needs a
per-scene rule that somebody has to write and maintain.

That is the shape to look for.

## What a VLM can be asked that a detector cannot

1. **A rule stated in words.** "Is this person wearing the right protection for
   this area." A detector needs the rule compiled into geometry and classes; a VLM
   takes the sentence.
2. **Objects nobody enumerated.** COCO has 80 classes. "Is there something on the
   line that should not be" is unanswerable by a model that can only name 80 things.
3. **States that are not objects.** Wet, dry, on, off, open, cooked, cracked. There
   is no bounding box for "the hob is lit".
4. **Relations and intent.** Handed to someone versus put down. Waiting versus lost.
5. **Text in context.** Not OCR — whether the label matches the box it is on.
6. **Normality.** "Does this look wrong", with nobody having said what wrong is.

Every scenario below has to sit in one of those six, or it is a demo.

---

## Passes both tests

**A pan is on a lit hob and the kitchen is empty.**
*State, not object.* A detector sees a pan; it cannot see that the ring is on. The
absence half is where models invent (F23), so this pulls two levers at once.
Wrong-way costs: a miss is a fire, a false alarm is a device switched off in a week.

**Something is on the conveyor that does not belong.**
*Unenumerated object.* The whole point is that nobody listed what could be there.
A detector can only report the 80 things it knows, and the answer is always "none
of them".

**The floor is wet in a place people walk.**
*State, not object,* and one every model reads correctly when asked and **never
volunteers** (6–20%, F23). That gap is the product: it works only if someone knew
to ask.

**The label on the box does not match what is in it.**
*Text in context.* OCR reads the label. Deciding it is the wrong label needs both
halves compared.

**A spill is spreading and nobody has noticed.**
*The one measured win.* Small change, no COCO class, and the 3B beat a swept pixel
method on exactly this (F16). Worth extending to other liquids and surfaces.

**Someone is doing the task in the wrong order.**
*Rule in words.* Assembly and food prep both have orders that matter. A detector
sees hands and parts; the sequence is the rule.

## Fails the second test — do not build these

| scenario | why not |
|---|---|
| a person falls | pose estimation, solved |
| a person enters a restricted area | background subtraction scores 0.99 here (F21) |
| a hand enters a machine | measured: classical wins outright (F15) |
| an item leaves a shelf | background subtraction plus a detector |
| how long is the queue | a person detector counts better than any VLM here does (F17) |
| a machine stopped | frame differencing, and every VLM is at chance anyway (F20) |

These stay on the page because knowing a VLM is *not* needed is worth publishing —
F15 and F21 are that result — but they are findings about the classical baseline,
not scenarios to source new footage for.

## Open question this list cannot answer yet

Every "passes" entry above is a *state* or a *rule*. None of them has been sourced
yet, and the sourcing findings so far (F6, F19, F23) say states are exactly what
stock footage does not carry: a wet floor and a dry floor look like the same shop.

If that holds, the honest conclusion is that the cases where a small VLM earns its
place are the cases nobody films — and that is itself the most useful thing this
project could report to someone sizing a PoC.

Add to this list whenever a use case surfaces. It is meant to outrun the corpus.
