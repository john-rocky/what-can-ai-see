# Post: the film commentary

Attach `cards/general-bridge-full-s.mp4` (81s, English) to the main post.

X free tier is 280 characters. A URL counts as 23 whatever its length, and CJK
counts double, so a Japanese post has an effective budget of 140. Counts below are
from `tools/x_len.py`. English is what goes out. The Japanese is the same post,
for checking.

**Stake, then setup, then question. No result.** Two drafts were cut to get here.
The first led with the answer — "two seconds later it calls the scene a forest
fire" — true, measured, and the wrong thing to write: a reader told the punchline
has no reason to watch the video, and the video is the artifact. The second opened
on the method, which asks the reader to care about a 1926 film before knowing why
it matters to them. What is left opens on the job people are already lining VLMs
up for. The findings live in the repo with their method attached.

---

## Main post — EN, 238/280

VLMs are being lined up for always-on monitoring. How much of an event can one
actually describe?

I showed a small on-device model a 1926 silent film and asked it once every
2 seconds: describe what is happening.

github.com/john-rocky/what-can-ai-see

## Main post — JP, 209/280

常時監視のような業務用途で期待されているVLM。実際、事象をどこまで説明できるのか。

オンデバイスの小型モデルに1926年のサイレント映画を見せて、2秒ごとに聞いた。何が起きているか説明せよ。

github.com/john-rocky/what-can-ai-see

---

## Reply 1 — EN, 168/280

Buster Keaton, The General (1926). Public domain in the US and Japan.

Silent film was built to be legible with no audio. Everything is carried by what
is in the frame.

## Reply 1 — JP, 157/280

バスター・キートン『The General』(1926)。米国と日本でパブリックドメイン。

サイレント映画は音なしで通じるように作られている。すべてが画面の中で完結している。

---

## Reply 2 — EN, 211/280

The models, converted for Apple's on-device CoreAI runtime.

LFM2.5-VL 3B huggingface.co/mlboydaisuke/LFM2.5-VL-3B-CoreAI
Qwen3-VL 2B huggingface.co/mlboydaisuke/Qwen3-VL-2B-CoreAI

Run on a Mac Studio M4 Max, not an iPhone. Phone-sized models, same runtime.

## Reply 2 — JP, 175/280

使ったモデル。AppleのCoreAIランタイム向けに変換したもの。

LFM2.5-VL 3B huggingface.co/mlboydaisuke/LFM2.5-VL-3B-CoreAI
Qwen3-VL 2B huggingface.co/mlboydaisuke/Qwen3-VL-2B-CoreAI

Mac Studio M4 Max で実行。iPhoneではない。

---

## Checks run before posting

**MiniCPM-V 4.6 is absent from the video and the post.** It returned nothing for
every contact-sheet window in this run. The cause is on my side, not the model's
(F24), so showing it as a blank row would be a false result.

**Public domain in the US and Japan, not the EU.** US: published before 1931,
renewal never filed. Japan: expired by every route — the corporate-name term ran
out in 1976; the individual-name term was death + 38 (Keaton d. 1966), and even
with the wartime addition for pre-war US works it ended in 2014. The EU term runs
70 years from the last surviving of director/writer/composer, so 2036 there.

**The text on screen is what the models wrote**, not the first sentence of it and
not a translation. The Japanese cut exists for review only and is never posted.

**Nothing in the post is a result**, so there is no number here to verify. The
figures behind this footage — 0 of 13 windows on the cannon's aim, re-measured at
512 output tokens — live in the repo with their method.
