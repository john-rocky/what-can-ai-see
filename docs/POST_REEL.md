# Post: the reel

Attach `cards/reel-events.mp4` (56s, 8 cuts) to the main post.

X free tier is 280 characters. A URL counts as 23 whatever its length, and CJK
counts double — so a Japanese post has an effective budget of 140 characters.
Every draft below is measured with `tools/x_len.py`; the count is on each heading.
English is what goes out. The Japanese is the same post, for checking.

---

## Main post — EN, 275/280

Six vision-language models small enough to run on a phone. One question each,
re-asked every 0.4s on real footage.

Green = right, red = wrong.

Mostly they're right. Then two people at a table, "more than two?" — one model
changes its mind 11 times.

github.com/john-rocky/what-can-ai-see

## Main post — JP, 238/280

スマホで動くサイズのVLM6つに、実写映像へ英語で1つ質問を0.4秒ごとに問い直す。

緑が正解、赤が不正解。

ほとんど当たる。ところが2人がテーブルに向かい合う映像で「3人以上いる?」と聞くと、あるモデルは11回意見を変える。

github.com/john-rocky/what-can-ai-see

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
| changes its mind 11 times | `tools/genre_score.py` | LFM2.5-VL 3B on `count-4035246`, 34 windows |
| smallest is 658MB | `events/models.yaml` | that model is also at chance. The post does not claim it works |
| not one answer moved under a flip | `tools/mirror_probe.py` | six genres, four models. The count clips DID move — on the questions each model was already guessing |

**Do not claim these run at this speed on a phone.** Nothing here has been measured
on an iPhone. The models are phone-class and the runtime is Apple's on-device one;
that is all the footage shows.
