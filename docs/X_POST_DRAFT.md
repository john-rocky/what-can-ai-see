# X post drafts

Nothing here is posted. English is what goes out; the Japanese under each post is
a check translation, not a second post.

Two series, because they do different jobs and mixing them weakens both.

- **Series A — claims.** One argument per post, with the number that backs it and
  the classical baseline beside it. Low volume, high scrutiny.
- **Series B — watch it think.** One clip, one question, the bar changing live.
  No argument, no table. Runs indefinitely; the point is accumulation.

Two hard rules, both learned the expensive way:

1. **No VLM number goes out without its baseline row.** The number alone cannot
   separate "the model understood" from "the pixels changed". An earlier draft
   led with the hand-in-danger-zone result; measurement later showed background
   subtraction beats the VLM on exactly that clip.
2. **No negative goes out unless it has been measured, not just labelled.** The
   first version of the spill pair used an episode the dataset calls "normal"
   that had a spill in it. Every model's "false alarms" on it were correct
   answers, and the result was backwards for hours.

---

## Series A — claims

### A1. The scoreboard is lying

Standalone. Posted on its own, not in a thread with A2–A7 — it is a different
measurement (one inference per clip, stock footage) and beside sliding-window
numbers it reads as a before/after that was never run.

> **A recall column will tell you a small VLM detects everything. It is answering Yes.**
>
> 6 models × 7 events × 4 ways of packing the clip into one image = 136 cells.
> Recall 1.00 in 98 of them. False-alarm rate 1.00 in 78 of the same cells.
>
> Score it instead on matched pairs — the event, and a look-alike from the same
> scene that is not it. Of **134 pairs:**
>
> · 23 real detections
> · **99 said Yes to both**
> · 9 said No to both
> · 3 got it backwards
>
> Not a model ranking and not a latency result: one inference per clip, no
> baseline, stock footage. It is a result about the metric.

> 【訳】**recall の列を見ると小型VLMは何でも検知しているように見える。ただ Yes と
> 答えているだけ。**
> 6モデル × 7事象 × クリップを1枚に畳む4通りの方式 = 136セル。
> うち98セルで recall 1.00。同じセルのうち78セルで誤報率も1.00。
> 代わりにマッチドペアで採点する（事象と、同じシーンから作った瓜二つの非事象）。
> **134ペアの内訳：**
> ・23 本物の検知
> ・**99 両方に Yes**
> ・9 両方に No
> ・3 逆
> これはモデルの優劣でも遅延の結果でもない。1クリップ1推論、ベースラインなし、
> ストック素材。指標そのものについての結果。

*Attach: `cards/live-18clips.mp4`*

### A2. Rank them by false alarms and you get one order. Rank by detection and you get nearly the reverse.

> Six small VLMs and a 1995 background subtractor, on five matched pairs from a
> fixed industrial camera. Re-asked every 0.4s over a 1.6s window.
>
> Everything that fires, fires at the same moment: +0.3s median. Latency is a tie.
>
> ```
>                     detects   false alarms   balanced
> LFM2.5-VL 3B            89%             8%       0.90
> MiniCPM-V 4.6           98%            38%       0.80
> Holo2 4B                97%            42%       0.78
> background subtract     56%            10%       0.73
> North Micro Vision      97%            61%       0.68
> Qwen3-VL 2B            100%            70%       0.65
> LFM2.5-VL 450M          20%            20%       0.50
> ```
>
> The 450M looks third-best on false alarms. It is at chance: it says Yes to 20%
> of the event and 20% of the non-event. Same number. That is what "not looking"
> reads like in a table.

> 【訳】小型VLM6つと1995年の背景差分を、固定産業カメラのマッチドペア5組で比較。
> 1.6秒の窓を0.4秒ごとに問い直す。
> 発火するものは全て同じ瞬間に発火する（中央値+0.3秒）。遅延では差がつかない。
> （表：検知率／誤報率／バランス精度）
> 450Mは誤報率だけ見ると7手法中3位に見える。実際は偶然と同じ：事象の窓の20%に
> Yes、非事象の窓の20%にYes。**同じ数字**。これが「見ていない」の表上の姿。

**Why this is A2's third version, and the rule that came out of it.**
Ranked by recall, every model is perfect (A1). Ranked by false alarms, a model that
mostly says No comes third. Ranked by both, one model leads and the smallest is at
chance. Nothing was re-measured between those three orderings — a column was added
each time.

So: **no single number ranks these models.** Always publish detection and false
alarms side by side. Any ordering resting on one of them is provisional, including
the one above if a further column is warranted.

This also overturns the previous draft's "the VLM ties the classical baseline".
It ties on false alarms (8% vs 10%) and on first-fire latency. It does not tie on
holding the alarm: the subtractor drops below threshold once the pool stops
spreading and misses 44% of the windows after the event. If a downstream system
samples at an arbitrary moment, that gap is the whole story; if it only needs the
first alarm, there is still no reason to run a 3B.

*Attach: `cards/A2-five-pairs.mp4` (162s — over the 140s standard limit; without
Premium post `cards/B3-spill2.mp4`, 32s, the pair the claim rests on).*

### A8. We moved the camera. First and third place swapped.

> Same rig, same lighting, same events, same questions. The robot arm's second
> camera instead of its first — a low angle instead of a high one.
>
> ```
>                        overhead   oblique
> LFM2.5-VL 3B               0.89      0.70
> Holo2 4B                   0.74      0.89
> background subtraction     0.66      0.56
> Qwen3-VL 2B                0.65      0.74
> North Micro Vision         0.61      0.69
> ```
>
> The model we had spent weeks identifying as the one that works is now third.
> The one we wrote off as too trigger-happy is first.
>
> Control, because these models stretch every input to a square: re-cropping the
> clips from 4:3 to 16:9 changed **0 of 1088 verdicts**. Framing is not it. The
> angle is.
>
> **A small-VLM benchmark on one camera measures a model-camera pair, not a model.**

> 【訳】同じ装置、同じ照明、同じ事象、同じ質問。カメラだけ1台目から2台目へ
> （真上から低い斜めへ）。
> （表：真上／斜め のバランス精度）
> 何週間もかけて「これが使える」と特定したモデルが3位に落ち、「誤報が多すぎる」と
> 切り捨てたモデルが1位になる。
> 対照実験：これらのモデルは入力を正方形に引き伸ばすので、4:3から16:9に切り直して
> 確認した。**1088答のうち変化は0。** 原因は画角ではなく角度。
> **1台のカメラで小型VLMを評価すると、モデルではなく「モデルとカメラの組」を測って
> いる。**

**Where it went.** The 3B's false alarms do not move (8% → 9%). Its detection
collapses, 87% → 49%, and only on the small changes:

| | 3B overhead → oblique |
|---|---|
| a full pool | 21/21 → 22/22 |
| a thin run | 21/21 → **7/21** |
| a heap of grounds | 12/20 → **4/18** |

That is the same mechanism as A2, seen from the other side: the 3B wins when the
change is small, and a shallow angle is what makes a change small.

**What we had to throw away.** Before the control, the classical baseline scored
0.66 → 0.66 — the cleanest line in the project: *the only method that ignores the
viewpoint is the only one stable under a viewpoint change*. It was two effects
cancelling. Nothing here is stable; the VLMs are insensitive to framing and
sensitive to angle, the pixel method is sensitive to both.

*Attach: side-by-side of the same spill from both cameras — not yet rendered.*

### A3. The dramatic demo does not need a VLM

> A bare hand enters the path of a soldering iron. Three VLMs fire 0.2s later.
> It is the clip you would put on a slide.
>
> Background subtraction: same 0.2s, **zero** false alarms.
> RF-DETR + "is a person present": same 0.2s, **zero**.
> LFM2.5-VL 3B: 0.2s, 4 false alarms in 34 windows.
>
> A person entering a still scene is the 1995 problem. Running a 3B every 0.4s to
> solve it is strictly worse.

> 【訳】はんだごての経路に素手が入る。3つのVLMが0.2秒後に発火する。スライドに
> 載せたくなる映像。背景差分は同じ0.2秒で誤報ゼロ。RF-DETR＋「人がいるか」も
> 同じ0.2秒で誤報ゼロ。3Bは0.2秒だが34窓中4誤報。静止した場面に人が入るのは
> 1995年の問題で、それに3Bを0.4秒ごとに回すのは純粋に劣る。

*Attach: `cards/live-hazard.mp4`*

### A4. Why the classical rule is fragile anyway

> RF-DETR looks at a shattered glass jar and reports **kite**. 169 times.
>
> "Alarm when a kite appears" then detects broken glass perfectly on that pair —
> zero false alarms. On a second shattering clip, one scene over, kite never
> fires once. The rule was a coincidence in the data.
>
> The VLM's one sentence worked on both.

> 【訳】RF-DETRは砕けたガラス瓶を見て **kite（凧）** と報告する。169回。
> 「kiteが出たら発報」という規則は、そのペアでは誤報ゼロで完璧に動く。同じ事象の
> 別シーンでは kite が一度も出ない。規則はデータ上の偶然だった。
> VLMの英文1つは両方で動いた。

### A5. The question moves more than the model

> Same clips. Same models. Same windows. One phrase changed.
>
> "Is the object damaged — cracked, crushed, or torn?" → four windows, then silence.
> "Has anything been spilled onto the surface?" → fires at the spill and holds.
>
> Three other models moved the opposite way: they answer Yes throughout, because
> the scene contains liquid the whole time — in the jug, in the cup. Only the 3B
> separates "liquid is present" from "liquid is where it should not be".
>
> A low benchmark score says nothing about a model until you have checked that
> the question describes the clip.

> 【訳】同じクリップ、同じモデル、同じ窓。変えたのは一節だけ。
> 「物体は破損しているか — ひび割れ、圧壊、破れ」→ 4窓だけ点いて沈黙。
> 「表面に何かこぼれたか」→ こぼれた瞬間に発火して持続。
> 他の3モデルは逆に動いた。場面には最初から液体がある（ジャグの中、カップの中）
> ので Yes を出し続ける。3Bだけが「液体が在る」と「あってはならない場所に在る」を
> 区別する。低いスコアは、質問がクリップを説明しているか確認するまでモデルについて
> 何も語らない。

### A6. What cannot be benchmarked from video at all

> Eight anomaly tasks from one robotics dataset. Three usable, five not, and the
> split is clean.
>
> Usable: the anomaly ADDS something to the frame — a hand, a pool, a heap.
> Not usable: the anomaly is a wrong *choice* — wrong bin, wrong hole, dropped
> instead of placed. The pixels barely differ; the meaning lives in a spec the
> camera never sees.
>
> On those five I could not write the ground truth either. Scoring them would
> measure whether the model guesses the way I do.

> 【訳】1つのロボティクスデータセットから異常タスク8種。3種は使え、5種は使えず、
> 分かれ方が完全にきれい。
> 使える：異常がフレームに何かを**足す**もの（手、液だまり、粉の山）。
> 使えない：異常が規則に対する**誤った選択**であるもの（違う箱、違う穴、置いたのか
> 落としたのか）。画素はほとんど変わらず、違いは意味にあり、その意味はカメラが
> 見ていない仕様書の中にある。
> この5種は私にも ground truth が書けなかった。採点すれば「モデルが私と同じように
> 推測するか」を測ることになる。

### A7. The bug that made the result backwards

> My negative clip had the event in it.
>
> The dataset labels five episodes "normal". Four have a clean table; one has a
> coffee spill on it. I built the control from that one without watching it, and
> then counted every model's correct "yes, there is a spill" as a false alarm.
>
> Fix: the control is now verified by measurement — brown fraction of the table,
> 0.003 on the clean episodes against 0.024 on the bad one. The onset is measured
> the same way instead of read off a contact sheet.
>
> A benchmark's worst failure is not a wrong number. It is a wrong number that
> looks right.

> 【訳】負例クリップに事象が写っていた。
> データセットは5エピソードを「正常」とラベルしている。4本はテーブルが清潔で、
> 1本にはコーヒーのこぼれがある。私はそれを見ずに対照群に選び、各モデルの正しい
> 「はい、こぼれています」を誤報として数えていた。
> 修正：対照群は測定で検証するようにした（テーブルの茶色面積、清潔なもの0.003に
> 対し不良品0.024）。onsetも同じく測定値に変え、コンタクトシートからの目視をやめた。
> ベンチマークの最悪の失敗は、間違った数字ではない。正しく見える間違った数字だ。

---

## Series B — watch it think

Format, fixed so the series is recognisable at a glance:

- the clip plays at real speed, nothing sped up, nothing cut
- one question on screen
- one bar per model — green = said No, red = said Yes, grey = not asked yet
- white line = when the event actually happened
- the matched look-alike follows immediately, same question, same rig

One pair per post. Caption states the event and the models, nothing else.

All eight are rendered and ready to post.

| # | file | len | what a viewer sees |
|---|---|---|---|
| B1 | `cards/B1-hazard-hand.mp4` | 32s | green while the robot works, red the moment a bare hand enters the iron's path — then a normal episode where three of the four VLMs go red anyway |
| B2 | `cards/B2-spill.mp4` | 32s | a full cup is knocked over; every method fires. On the clean table that follows, only the 3B and the pixel baseline stay green |
| B3 | `cards/B3-spill2.mp4` | 32s | poured beside the cup — a thin run, not a pool. The pixel baseline needs 5.5s, the 3B 0.3s. **The clearest single clip in the series** |
| B4 | `cards/B4-spill3.mp4` | 32s | poured straight onto the table; here the pixel baseline is the faster one |
| B5 | `cards/B5-grounds.mp4` | 32s | coffee grounds heap up beside the machine |
| B6 | `cards/B6-damage-jar.mp4` | 26s | a glass jar shatters; the 3B flips and never flips back |
| B7 | `cards/B7-fall-live.mp4` | 20s | a skateboarder falls — then a man lies down deliberately and the bar goes red anyway |
| B8 | `cards/B8-synth-stop.mp4` | 14s | boxes in pixel-identical positions; every model reports the line moved |

Two notes before posting these:

- **B6 shows a row labelled `baseline-detect-presence`.** On that clip it is the
  *kite* rule from A4, not a person rule. Either post B6 after A4 or say so in the
  caption; on its own the row is unreadable.
- **B7 has two models and no baseline row** — it is the only pair here not from
  the industrial rig, and it never got the full method set. Post it for the
  behaviour, not as a comparison.

Regenerate any of them with:
`python3 tools/live.py --stream runs/stream/<clip> --out <file>.mp4 --tag "<label>"`

---

## Claims audit

`python3 tools/verify_claims.py` recomputes every number below from `runs/` and
exits non-zero on a mismatch. Run it before posting; the spill numbers have been
invalidated twice already.

| claim | source | caveat that must survive editing |
|---|---|---|
| recall 1.00 in 98/136; 99 of 134 pairs trigger-happy | `runs/field-v2/scores.json` | 6 models x 7 events x 4 encodings, ONE inference per clip, stock footage — never quote beside the sliding-window numbers. The older `field-v1` file gives 27/32 and 91% at chance; that is a 2-model subset, not a second measurement |
| 3B 8% vs bg-diff 10% | `tools/verify_claims.py` over `runs/stream/*` | 5 pairs, all from one robotics rig; the baseline's threshold is fitted on the very pair it is scored on, which flatters it — and it is still a wash |
| the 8/10/42/61/70 spread | same | 236 windows whose correct answer is No: 170 on the controls, 66 on the positives before the event starts. Do not quote a version that counts only the controls |
| median latency +0.3s | same | 0.4s stride, so latency resolution is 0.4s. Every method ties; there is no speed claim here |
| hand: baselines beat 3B | `runs/stream/hazard-hand-*` | the negative happens to contain no person at all, which flatters the "person present" rule |
| kite fails to transfer | `runs/stream/damage-*` detections | 2 pairs |
| question wording flip | `runs/stream/spill-*`, two runs | greedy decoding, so not sampling noise |
| 3 of 8 tasks usable | `clips/REJECTED.md` | one collection, one annotator |

**The two claims to be most careful with**, because both are one correction old:

1. **Do not say the VLM beats the classical baseline.** It does on two pairs, loses
   on one, ties on one, and is slower on one. Aggregate 8% vs 10% at n=5 is a wash.
   The defensible claim is the *spread between VLMs* (8% to 70%) and the *regime*
   (the VLM holds when the change is small enough that a pixel count has nothing to
   threshold).
2. **Do not say latency is a VLM advantage.** Every method detects at +0.3s median.

**Do not use the two glass-shatter pairs for anything load-bearing.** Their
negatives come from a different scene, not the same rig, so background subtraction
scores 26/26 false alarms on one and 0/20 on the other — that gap measures how the
pairs were built, not how the methods differ. The five pairs in A2 do not have this
problem: every negative is a normal episode from the same dataset and camera.
