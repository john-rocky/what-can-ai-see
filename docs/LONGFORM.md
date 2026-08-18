# The long span

## Why this, and not a longer list of scenes

The previous page tried to enumerate what a classical CV pipeline cannot do. That
enumeration is guesswork dressed as analysis: the honest position is that nobody
knows where the boundary is, which is the reason to try many things rather than to
reason about it. What *can* be stated is the other half — the cases where a
detector plainly wins are already measured here (F15, F21, F20) and are not worth
sourcing more footage for.

That leaves a search problem, and one direction in it is structural rather than
speculative.

**Every CV pipeline in production is frame-local.** A detector answers about a
frame. A tracker stitches frames into short tracks. Nothing in that stack answers
"what happened in the last hour", because the question is not a detection.

So the untried ground is not a scene type. It is a **span**.

## What the runtime makes of this

The models cannot help with a span directly. `KitVisionExecutor` takes one image
per turn and keeps nothing between turns (F1): each 1.6s window is answered by a
model with no memory of the window before it.

That is not a limitation to route around — it is the architecture anyone deploying
this will have. A camera watching all day, a model with a 1.6-second horizon, and
somebody asking what happened. The measurement is therefore:

> **How much of a long span survives a memoryless perception layer?**

Nobody has published that for phone-sized models, and it is answerable with
footage that already exists.

## Question classes that only exist over a span

Ordered by how far they are from anything a detector does.

**1. Summary.** What happened, in a paragraph, over ten minutes. Scored against a
written account of the footage. Already half-demonstrated: walking the 1956
aluminium film in order, the per-window descriptions recover its arc — rail cars,
furnace, rolling mill, coils, warehouse, kitchenware — with no memory between
windows (F23).

**2. Anomaly with no anomaly specified.** "Was anything different from the rest of
this footage." The model of normal has to come from the footage itself. This is the
one question a detector cannot be pointed at, because pointing it requires already
knowing the answer. It is also what every "AI monitoring" pitch implicitly claims.

**3. Order.** Did the steps happen in the right sequence. A detector sees each step;
the ordering is a separate fact and it is where process failures live.

**4. Duration and dwell.** How long was the machine idle, how long was the room
empty. Dwell is where every method scored at chance (F20) — but that was measured
on 15-second clips, where "stopped" has barely happened. Over ten minutes it is a
different question.

**5. Count over time.** How many people entered. Counting is the known failure
(F17, F23) and a span compounds it: errors accumulate rather than cancel.

**6. First and last.** When did it start, when did it stop. The onset work is this
question over a short span; over a long one it becomes search.

## What to measure

For each of the above, the same shape: run the span through the memoryless layer,
assemble the answers outside the model, compare against ground truth written from
the footage.

Two numbers matter and they are different:

- **Recall of events.** Of the things that happen, how many appear anywhere in the
  running commentary.
- **Survival of order.** Of the things recovered, how many are in the right
  sequence relative to each other.

A model can score well on the first and badly on the second, and that distinction
decides whether a summary is usable or merely populated.

## What would falsify the bet

If the per-window descriptions turn out to be interchangeable — if a shuffled
transcript summarises as well as an ordered one — then the span adds nothing and
this is a detection problem after all. That is a cheap test and it should be run
early, before the corpus is built out.

The second failure mode is subtler. F23 found that a still scene makes every model
invent, and a long recording is mostly still. A ten-minute span may produce a
summary made largely of things that did not happen. Recall of events would look
fine; the summary would be worthless. So invention has to be counted per span, not
just per window.

## Sourcing this needs

Long, continuous, fixed-camera, licence-clean. In order of what has been verified
to exist:

| source | verified | limit |
|---|---|---|
| Prelinger industrial films | 10,466 items, public domain, 13 min typical | 640x480, cuts every ~9s |
| archive.org CC movies | 401,541 since 2025-06 | unsurveyed |
| Wikimedia Commons | 4K and 1080p, mixed licences | ShareAlike on the largest share |

The cuts are the real problem, not the resolution: a documentary is edited, and an
edit is not a camera. `split_shots.py` handles it by treating each shot as its own
span, but that caps the span at shot length — around 9 seconds for the film already
processed. **A genuinely long single-camera recording has not yet been found**, and
finding one is the first sourcing task this page implies.
