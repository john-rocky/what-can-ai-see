# Credits

Footage used in `cards/reel-post.mp4` and in the benchmark. No video file is
redistributed in this repository; these are the sources.

## kantine — Apache-2.0

Three clips come from kantine's LeRobot recordings on HuggingFace, licensed
Apache-2.0 (verified against the dataset cards). Apache-2.0 asks that attribution
notices be retained and that recipients get a copy of the licence, so they are
credited here and in the post's replies rather than only in metadata.

- **spill2-pos** — huggingface.co/datasets/kantine/domotic_pouringCoffee_anomaly
- **hazard-hand-pos** — huggingface.co/datasets/kantine/industrial_soldering_anomaly
- **grounds-pos** — huggingface.co/datasets/kantine/domotic_makingCoffee_anomaly

Licence: https://www.apache.org/licenses/LICENSE-2.0

## Pexels

Five clips are Pexels stock. The Pexels licence does not require attribution;
they are credited anyway, because a benchmark that asks people to check its
sources should make that one click rather than several.

- **count-4035246** — https://www.pexels.com/video/young-women-drinking-coffee-together-4035246/
- **damage-jar-pos** — https://www.pexels.com/video/high-speed-shattering-glass-jar-impact-31637076/
- **conveyor-4473187** — https://www.pexels.com/video/black-conveyor-belt-4473187/
- **office-11903981** — https://www.pexels.com/video/man-in-shirt-walking-in-corridor-11903981/
- **fall-live-neg** — https://www.pexels.com/video/a-medium-shot-of-a-man-lying-down-on-the-floor-8526604/

Licence: https://www.pexels.com/license/

## What was and was not verified

The kantine licence was checked against the HuggingFace dataset cards at the time
of writing; all three return `apache-2.0`.

**The Pexels licence page could not be fetched** — it is behind a bot check — so
the summary above is from prior knowledge and not a quote of the current terms.
Anyone relying on it should read the page. Two clauses matter for footage like
this and are worth confirming before any commercial use: identifiable people must
not be shown in a way that is offensive or implies endorsement, and unaltered
copies may not be resold.

Three clips here contain identifiable people — two women at a cafe table, a man
walking down a corridor, a man lying on a floor. They appear as ordinary scenes
with a model's verdict drawn over them; nothing in the overlay characterises the
people. That is a judgement, not a legal opinion.
