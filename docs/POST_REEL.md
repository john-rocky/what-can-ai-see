# Post: the reel

Attach `cards/reel-post.mp4` (56s, 8 cuts) to the main post.

X free tier is 280 characters. A URL counts as 23 whatever its length, and CJK
counts double — so a Japanese post has an effective budget of 140 characters.
Every draft below is measured with `tools/x_len.py`; the count is on each heading.
English is what goes out. The Japanese is the same post, for checking.

---

## Main post — EN, 260/280

How much does a small on-device VLM understand? Before you ship one, you need to
know where it stops.

I tested six. One question, every 0.4s, on real footage.

They see a jar shatter, a hand enter a machine. They can't count to three.

github.com/john-rocky/what-can-ai-see

## Main post — JP, 256/280

オンデバイスで動く小型VLMは、実際どこまで理解できるのか。業務に組み込むなら、その理解度を先に知る必要がある。

6つ試した。実写映像に質問を1つ、0.4秒ごとに問い直す。

ガラスが割れるのも、機械に手が入るのも見える。3人を数えられない。

github.com/john-rocky/what-can-ai-see

### Notes on the wording

**The examples name what is actually on screen.** An earlier draft said "they read
rain, a shop sign, a cat on a bench" — all true, all measured, and none of them in
the video. A caption describing clips a viewer cannot see is the same failure as a
number without its baseline.

**The colour key moved into the video.** "Green = right, red = wrong" cost 28 of
280 characters — a tenth of the post spent explaining the artwork. It is now drawn
on the first two beats.

**"Can't count to three" is exact.** Shown two people at a table and asked whether
there are more than two: LFM2.5-VL 3B changes its mind 11 times across 34 windows
of a still scene, Qwen3-VL 2B answers yes to every one, Holo2 4B gets one clip and
not the other. MiniCPM-V 4.6 is the only model that gets both. So the honest form
is "most of them can't" — if a reader pushes, that is the correction to make.

---

## Reply 1 — EN, 183/280

The models, converted for Apple's on-device CoreAI runtime. Smallest is 658MB.

LFM2.5-VL 3B huggingface.co/mlboydaisuke/LFM2.5-VL-3B-CoreAI
450M huggingface.co/mlboydaisuke/LFM2.5-VL-450M-CoreAI
MiniCPM-V 4.6 huggingface.co/mlboydaisuke/MiniCPM-V-4.6-CoreAI

## Reply 1 — JP, 198/280

使ったモデル。AppleのCoreAIランタイム向けに変換したもので、6つとも端末上で動く。最小は658MB。

LFM2.5-VL 3B huggingface.co/mlboydaisuke/LFM2.5-VL-3B-CoreAI
450M huggingface.co/mlboydaisuke/LFM2.5-VL-450M-CoreAI
MiniCPM-V 4.6 huggingface.co/mlboydaisuke/MiniCPM-V-4.6-CoreAI

---

## Reply 2 — EN, 190/280

Qwen3-VL 2B huggingface.co/mlboydaisuke/Qwen3-VL-2B-CoreAI
North Micro Vision huggingface.co/mlboydaisuke/North-Micro-Vision-CoreAI
Holo2 4B huggingface.co/mlboydaisuke/Holo2-4B-CoreAI

Run on a Mac Studio M4 Max, not an iPhone — phone-sized models, same runtime.

## Reply 2 — JP, 162/280

Qwen3-VL 2B huggingface.co/mlboydaisuke/Qwen3-VL-2B-CoreAI
North Micro Vision huggingface.co/mlboydaisuke/North-Micro-Vision-CoreAI
Holo2 4B huggingface.co/mlboydaisuke/Holo2-4B-CoreAI

計測はMac Studio M4 Max。iPhoneでは測っていない。

---

## Reply 3 — EN, 271/280

Three things had to be fixed first.

A control clip had the event in it — every correct "yes, there's a spill" was
counted as a false alarm.

One column is not a ranking. The order changed 4 times as columns were added.

Flip every video left-right: not one answer moved.

## Reply 3 — JP, 234/280

数字が読むに値するまでに3つ直した。

対照クリップに事象が写っていた。正しい「こぼれています」を全部誤報として数えていた。

1つの列では順位にならない。列を足すたびに順位は4回変わった。

全動画を左右反転しても、答えは1つも動かなかった。

---

## Claims audit

| claim | recomputed by | caveat that must survive editing |
|---|---|---|
| six models, 0.4s stride | `runs/stream/*` | a Mac Studio M4 Max, not a phone. Reply 2 says so; if that reply is dropped the main post overclaims |
| green right / red wrong | `tools/reel_fast.py` | for a gradual event the onset is a measured threshold crossing, not a knife edge — an "early" fire on a spreading spill may be the model being right before the threshold |
| "can't count to three" | `tools/genre_score.py` | on two clips of two people: LFM2.5-VL 3B is 47%/54% with 11 and 7 changes of mind, Qwen3-VL 2B is 0%/0%, Holo2 4B 52%/0%. MiniCPM-V 4.6 gets both. So it is "most of them can't", and the post says "they" — tighten it if a reader pushes |
| "they see a jar shatter, a hand enter a machine" | `runs/stream/damage-jar-pos`, `hazard-hand-pos` | both are in the reel. Every model fires within 0.5s of the measured onset on the jar |
| smallest is 658MB | `events/models.yaml` | that model is also at chance. The post does not claim it works |
| not one answer moved under a flip | `tools/mirror_probe.py` | six genres, four models. The count clips DID move — on the questions each model was already guessing |

**Do not claim these run at this speed on a phone.** Nothing here has been measured
on an iPhone. The models are phone-class and the runtime is Apple's on-device one;
that is all the footage shows.
