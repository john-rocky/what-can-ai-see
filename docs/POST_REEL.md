# Post: the reel

Attach `cards/reel-events.mp4` (56s, 8 cuts). English is what goes out; the
Japanese below each is the same post, not a translation of a different one.

Every number below is recomputed by `tools/verify_claims.py` and `tools/genre_score.py`
from `runs/`. Nothing is quoted that was not measured.

---

## Main post

> Six vision-language models small enough to run on a phone. One plain English
> question each, re-asked every 0.4 seconds, on real footage.
>
> A cat on a bench, rain on a window, a shop sign, coffee hitting a table, a hand
> going into a machine.
>
> Watch the moment each one decides. Green is right, red is wrong.
>
> Most of the time they are right, and it is genuinely strange to watch — a 3.9 GB
> file, no cloud, answering questions about a scene it has never been shown, four
> hundred milliseconds at a time.
>
> Then you ask two women at a table whether there are more than two people, and one
> model changes its mind eleven times without anything moving.
>
> Everything — harness, ground truth, every answer: github.com/john-rocky/what-can-ai-see

【JP】

> スマホで動くサイズの vision-language モデル6つに、実写映像について英語で1つ質問を
> して、0.4秒ごとに問い直す。
>
> ベンチの上の猫、窓の雨、店の看板、テーブルにこぼれるコーヒー、機械に入る手。
>
> それぞれが判断する瞬間を見てほしい。緑が正解、赤が不正解。
>
> ほとんど当たる。そしてそれを見ているのが妙な感覚になる。3.9GBのファイルが、
> クラウドなしで、見たことのない場面について、0.4秒ごとに答えを出している。
>
> ところが、テーブルに向かい合う2人を見せて「3人以上いますか」と聞くと、
> 画面で何も動いていないのに、あるモデルは11回意見を変える。
>
> ハーネスも正解データも全モデルの全回答も: github.com/john-rocky/what-can-ai-see

---

## Reply 1 — the models

> The models, converted for Apple's CoreAI runtime. All six run on-device; the
> smallest is 658 MB.
>
> LFM2.5-VL 3B      huggingface.co/mlboydaisuke/LFM2.5-VL-3B-CoreAI
> LFM2.5-VL 450M    huggingface.co/mlboydaisuke/LFM2.5-VL-450M-CoreAI
> MiniCPM-V 4.6     huggingface.co/mlboydaisuke/MiniCPM-V-4.6-CoreAI
> Qwen3-VL 2B       huggingface.co/mlboydaisuke/Qwen3-VL-2B-CoreAI
> North Micro Vision  huggingface.co/mlboydaisuke/North-Micro-Vision-CoreAI
> Holo2 4B          huggingface.co/mlboydaisuke/Holo2-4B-CoreAI

【JP】

> 使ったモデル。Apple の CoreAI ランタイム向けに変換したもので、6つとも端末上で動く。
> 一番小さいもので658MB。
>
> （同じリンク）

---

## Reply 2 — what it cost to make the numbers mean anything

> Three things had to be fixed before any of this was worth reading.
>
> A control clip had the event in it. The dataset called five episodes "normal";
> one of them had a coffee spill. Every model's correct "yes, there is a spill" was
> counted as a false alarm. The result was backwards for hours.
>
> Ranking by one column is not a ranking. On recall every model is perfect. On
> false alarms a model that mostly says No comes third of seven — it was answering
> at chance. The order changed four times as columns were added.
>
> The clips are public, so the models may have seen them. Flipping every video
> left-right changes the meaning of nothing. Across six genres and four models, not
> one answer moved.

【JP】

> 数字が読むに値するようになるまでに、3つ直す必要があった。
>
> 対照用のクリップに事象が写っていた。データセットが「正常」としていた5本のうち
> 1本にコーヒーがこぼれていて、各モデルの正しい「はい、こぼれています」を
> 誤報として数えていた。数時間、結果が逆さまだった。
>
> 1つの列で並べても順位にならない。recall で見れば全モデルが完璧。誤報率で見れば
> 「だいたいNoと言うモデル」が7つ中3位に来る——実際は偶然と同じだった。列を足す
> たびに順位は4回変わった。
>
> 素材は公開データなので、モデルが学習で見ている可能性がある。左右反転しても意味は
> 何も変わらない。6ジャンル・4モデルで、答えは1つも動かなかった。

---

## Claims audit

| claim | recomputed by | caveat that must survive editing |
|---|---|---|
| six models, on-device, 0.4s stride | `runs/stream/*` | a Mac Studio M4 Max, not a phone. The models are phone-sized and the runtime is the same; the latency is not a phone's |
| green right / red wrong | `tools/reel_fast.py` | for a gradual event the onset is a measured threshold crossing, not a knife edge — an "early" fire on a spreading spill may be the model being right before the threshold |
| eleven changes of mind | `tools/genre_score.py` | LFM2.5-VL 3B on `count-4035246`, 34 windows |
| 3.9 GB, no cloud | `events/models.yaml` | that is LFM2.5-VL 3B. The smallest is 658 MB and it is at chance |
| not one answer moved under a flip | `tools/mirror_probe.py` | six genres, four models. The count clips DID move — on the questions each model was already guessing |

**Do not claim these run at this speed on a phone.** Nothing in this project has
been measured on an iPhone. The models are phone-class and the runtime is Apple's
on-device one; that is all the footage shows.
