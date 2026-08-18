# Scenes worth measuring

The demand side. Written before any footage is searched for, because searching
first produces whatever stock libraries happen to sell — corridors, conveyors,
b-roll — and then the questions get bent to fit it. A day was lost that way.

The axis is not how dramatic the footage is. **It is what breaks when the model is
wrong.** A volcano detected correctly proves nothing; nobody puts a 3B model on a
volcano. Two people at a café table miscounted is the most interesting result this
project has produced, and the footage is furniture.

Each entry carries the cost of being wrong, because a miss and a false alarm are
not the same failure and the same model is rarely bad at both.

## What the measurements already say

These are the levers. A scenario that pulls one of them is worth building; one
that does not is a demo.

| finding | what it predicts will fail |
|---|---|
| No model can tell two people from three (F17, F23) | anything that counts — occupancy, queue length, staffing minimums |
| Materials and text are never volunteered, only confirmed when asked (F23) | wet floors, spills, warning labels, expiry dates: invisible unless somebody thought to ask |
| A still scene makes every model invent (F23) | monitoring, where nothing happens for hours |
| Moving the camera swapped first and third place (F18) | any spec written against one mounting position |
| A person lying down reads as a fall | care settings, where the distinction is the entire product |
| Question wording moves results more than model choice (F14) | every integration that writes its own prompt |

## Care and health

**A person is on the floor and has not moved.**
Cost of a miss: someone lies there. Cost of a false alarm: staff stop trusting it
within a week, which is the same as a miss but slower. The hard part is not seeing
a body on the floor; it is separating that from someone lying down deliberately,
which every model here currently fails.
*Testable now — `fall-live-neg` is exactly this and all models call it a fall.*

**Someone got out of bed at night and did not come back.**
Absence over time, not an instant. Needs memory the runtime does not have (F1),
so it must be assembled outside the model — which makes it a test of whether the
per-window descriptions carry enough to reconstruct.

**A walking aid is out of reach of the person who needs it.**
A spatial relation between two specific objects. Models volunteer spatial language
often (65–100%) but the relation has to be the right one.

## Retail

**An item left the shelf and did not go into a basket.**
Cost of a false alarm: an accusation. This is the scenario where being wrong is
worst, and it needs two events linked over time.
*Partly testable — `object-removed-5241131` is a hand taking sunglasses.*

**The shelf gap that means a product is out of stock.**
Absence again, and the model has to know what the shelf normally looks like.

**A queue formed and nobody opened a till.**
Counting, which is the known failure. Directly on the weakest lever.

## Home and consumer

**A pan was left on a lit hob and nobody is in the kitchen.**
Two facts at once: the hob state and the absence of a person. Absence is the
harder half — a still, empty kitchen is exactly the condition that makes models
invent.

**Water is running and the sink is filling.**
A liquid level rising. Related to the spill work, which is the one place a small
VLM has beaten a pixel method.

**A child is near something they should not be near.**
Proximity between two subjects. Cost of a miss is obvious; cost of a false alarm
is a parent who switches it off.

## Roads and public space

**Someone stepped into the road and the vehicle has not slowed.**
Needs both the person and the vehicle state. Camera is almost always moving, which
F18 says breaks the measurement before the model gets a chance.

**A door was propped open that should have closed.**
A state that persists, on a fixed camera, in an empty scene. The invention case.

## Factory and logistics

**A machine stopped and nobody noticed.**
Absence of motion — the dwell class, where every method scored at chance (F20) and
a pixel differencer is structurally blind because the event is the lack of change.

**Something is on the line that should not be.**
Foreign-object detection: the model has to know what normal looks like.

**A person is inside the guarded area while the machine runs.**
*Testable now — `hazard-hand-pos` is this, and it is the one case where a 1995
background subtractor beats every VLM (F15).*

## What this list is for

Sourcing is driven from here, not the other way round. A scenario stays on the
list until it has either been measured or shown to be unsourceable, and the second
outcome is a finding too — F6, F19 and F23 are all "this could not be sourced, and
here is why".

Add to it whenever a use case surfaces. The list is meant to outrun the corpus.
