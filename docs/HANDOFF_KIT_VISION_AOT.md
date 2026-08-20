# Handoff: `KitVisionModel` cannot load an iOS vision tower (AOT `.aimodelc`)

> **FIXED and device-verified, 2026-08-20.** `GraphBundle.resolve(in:)` in
> `Sources/CoreAIKit/GraphBundle.swift` now resolves the graph for every paired-bundle
> runtime; `KitVisionModel`'s own resolver is gone. On the iPhone 17 Pro:
> `STATS model=lfm2.5-vl-450m n=27 load_s=1.6 mean_s=4.71 peak_fp_mb=157 fail=0`.
> All 27 windows answered. See "Outcome" at the bottom — the two "do NOT assume"
> questions below are both answered there, and the catalog question is resolved.

**Repo to change:** `~/code/coreai-kit` (at `ade0a56`)
**File:** `Sources/CoreAIKit/Vision/KitVisionModel.swift`, `resolveVisionModel(in:)`, line 250
**Found by:** `what-can-ai-see`, 2026-08-20, running a VLM benchmark on an iPhone 17 Pro
**Blocks:** every catalog VLM on iOS. Right now the only VLM that runs on the phone is
Apple's own `SystemLanguageModel`.

---

## Symptom, verbatim

`tools/phone_run.sh lfm2.5-vl-450m` in `what-can-ai-see`, on iPhone 17 Pro / iOS 27.0
(24A5418b). The 653 MB download completes (238 s), then:

```
ERROR load lfm2.5-vl-450m: failedToSpecialize("Asset at file:///var/mobile/Containers/Data/
Application/.../Library/Application Support/CoreAIKit/Models/mlboydaisuke/
LFM2.5-VL-450M-CoreAI/f6648f9.../ios-h18p/lfm2_5_vl_450m_vision_fp16/
lfm2_5_vl_450m_vision_fp16.aimodel is malformed: Missing hash file")
```

Note the tail: `..._vision_fp16.aimodel`. That file does not exist in the repo.

## Cause

`resolveVisionModel(in:)` only ever considers `.aimodel`:

```swift
private static func resolveVisionModel(in root: URL) throws -> URL {
    let fm = FileManager.default
    if let entries = try? fm.contentsOfDirectory(at: root, includingPropertiesForKeys: nil),
        let aimodel = entries.first(where: { $0.pathExtension == "aimodel" })
    {
        return aimodel
    }
    return root.appendingPathComponent("\(root.lastPathComponent).aimodel")
}
```

The iOS bundle for LFM2.5-VL 450M ships only the AOT form. Under
`ios-h18p/lfm2_5_vl_450m_vision_fp16/` the HF repo contains exactly one entry:

```
lfm2_5_vl_450m_vision_fp16.h18p.aimodelc/     <- a directory
    main.hash
    main-h18p.mlirb
    metadata.json
    stats.json
    main-h18p-delegates/MPSGraph/mpsExecutable.mpsgraphpackage/{manifest.plist,
        resources.bin, specialized_model_0.mpsgraph}
```

So the `contentsOfDirectory` branch finds nothing with extension `aimodel`, the fallback
appends `.aimodel`, and the runtime is handed a path to a file that was never published.

`LFM2.5-VL-3B-CoreAI` has the same shape (`ios-h18p/lfm2_5_vl_3b_vision_fp16/…h18p.aimodelc`)
and will fail identically.

## The fix is already written, twice, in this package

This is not a design decision — two other resolvers in the same target already handle both
forms, and this one was missed.

`Sources/CoreAIKit/OCR/KitMineruReader.swift:309` is the one to copy:

```swift
private static func aimodel(in dir: URL) throws -> URL {
    // The dir itself may be the model (a JIT `*.aimodel` or an AOT `*.aimodelc`), else it
    // holds one. AOT (`.aimodelc`) wins so an iOS bundle carrying both prefers precompiled.
    if dir.pathExtension == "aimodel" || dir.pathExtension == "aimodelc" { return dir }
    let items = try FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)
    if let aotc = items.first(where: { $0.pathExtension == "aimodelc" }) { return aotc }
    guard let model = items.first(where: { $0.pathExtension == "aimodel" }) else {
        throw KitVisionError.bundleMissingMain
    }
    return model
}
```

`Sources/CoreAIKit/Parakeet/KitParakeetModel.swift:210` does the same thing a different way
(`if ext == "aimodel" || ext == "aimodelc"`).

**AOT must win when both are present.** An iOS bundle that carries both and picks the JIT
`.aimodel` pays on-device specialization every cold start — which is the cost the AOT build
exists to remove. `KitMineruReader` states this in its comment; keep that ordering.

## Verify

From `~/code/what-can-ai-see` (the app is already installed on the paired iPhone 17 Pro,
UDID `A6F3E849-1947-5202-9AD1-9C881CA58EEF`):

```sh
export DEVELOPMENT_TEAM=MFN25KNUGJ
export DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.5.app/Contents/Developer
xcodebuild -project phone/wcas-phone.xcodeproj -scheme wcas-phone \
  -destination 'generic/platform=iOS' -configuration Release -allowProvisioningUpdates build
xcrun devicectl device install app --device A6F3E849-1947-5202-9AD1-9C881CA58EEF \
  "$(find ~/Library/Developer/Xcode/DerivedData/wcas-phone-*/Build/Products/Release-iphoneos \
     -maxdepth 1 -name 'wcas-phone.app' | head -1)"
tools/phone_run.sh lfm2.5-vl-450m
```

Pass looks like a `STATS model=lfm2.5-vl-450m n=27 …` line and 27 answers in
`runs/phone/lfm2.5-vl-450m.jsonl`. The model is already downloaded on the device, so a
re-run costs load time only, not another 653 MB.

For reference, the same 27 windows through Apple's `SystemLanguageModel` on that phone:
median 2.23 s/window, peak footprint 34 MB, 26 answered and 1 refused
(`May contain unsafe content`).

## Do NOT assume while fixing this

**The decoder half is not proven to work.** The failure is on the vision asset, which is
loaded after the decoder — but nothing in the log states the decoder succeeded. If the fix
lands and a different `failedToSpecialize` appears naming the decoder bundle, that is a
second instance of the same bug, not a regression.

**`.aimodelc` is known-loadable, but not through this path.** Prior work in
`~/code/coreai/ondevice/PipelinedBench` drove `lfm2_5_vl_450m_vision_fp16.h18p.aimodelc` on
this same phone (see `_pipelined_dev_vl450m_vision.log`: `encode=33.6 ms`). That establishes
the artifact is good and the GPU accepts it; it does not establish that `GraphModel(contentsOf:)`
accepts a directory with that extension. Check that before assuming the one-line change is
enough.

---

## A separate defect, same investigation — do not conflate them

`catalog.json` claims iOS variants that the model repos do not contain:

| id | catalog `ios.path` | catalog `ios.sizeMB` | what is in the HF repo |
|---|---|---|---|
| `minicpm-v-4.6` | `gpu-pipelined/minicpmv46_vlm_decode_int8lin` | 2145 | **no `ios*` files at all** |
| `qwen3-vl-2b` | `gpu-pipelined/qwen3_vl_2b_instruct_decode_int8hu_s1` | 3278 | **no `ios*` files at all** |
| `qwen3-vl-4b` | (unchecked) | 5897 | unchecked |
| `holo2-4b` | (unchecked) | 5484 | unchecked |
| `north-micro-vision` | (unchecked) | 3500 | unchecked |

For those two the `ios` variant points at the **macOS** subtree. That is either

- deliberate (a `.aimodel` is portable and iOS JIT-specializes it on device — slow but
  workable), in which case the sizes are honest and only the `ios-h18p` models need the fix
  above; or
- a copy-paste of the macOS block, in which case the catalog is advertising an iOS
  capability that does not exist.

**Which one it is has not been determined.** It was not tested because each attempt costs a
2–3 GB download to a phone. Decide it deliberately; do not infer it from the fact that the
450M has a real `ios-h18p` subtree.

Checked with:
```sh
curl -sL "https://huggingface.co/api/models/mlboydaisuke/MiniCPM-V-4.6-CoreAI" \
  | python3 -c "import json,sys; print([f['rfilename'] for f in json.load(sys.stdin)['siblings'] if f['rfilename'].startswith('ios')])"
```

---

## Outcome

**The resolver.** Five copies of it existed in the kit, not two, and three were wrong:
`KitVisionModel` (this bug), `KitASRModel` and `KitAudioModel` (the same fabricated-path
fallback, latent only because no iOS AOT encoder is published yet), and `KitDocReader` (no
`.aimodelc` case at all). All five now call `GraphBundle.resolve(in:)`, from inside
`VLRuntime` / `ASRRuntime` / `AudioRuntime` rather than from each caller, so a sixth call
site cannot miss it. AOT still wins over JIT. Five tests cover it; deleting the AOT-first
line turns two of them red.

**"`.aimodelc` is known-loadable, but not through this path."** It is loadable through this
path. `GraphModel(contentsOf:)` is a thin wrapper over `AIModel(contentsOf:options:)` — the
same call `PipelinedBench` makes on `.h18p.aimodelc` on this phone. Confirmed on device.

**"The decoder half is not proven to work."** It works. The decoder resolves through
`metadata.json`, and the pinned revision's `ios-h18p/lfm2_5_vl_450m_decode_int8lin/metadata.json`
names `assets.main = "…h18p.aimodelc"`. No second `failedToSpecialize` appeared: the load
completed in 1.6 s, which is both halves.

**The catalog.** Not a copy-paste of the macOS block. For VLMs the paths that are actually
used come from the `VLModelID` presets in `KitVisionModel.swift`, not from `catalog.json` —
and only the 450M, the 3B and North-Micro have an `ios-h18p` subtree. The other five presets
carry no `#if os(iOS)`, so iOS deliberately takes the same `gpu-pipelined` JIT bundle, which
is why `ios.sizeMB` equals `macos.sizeMB` for exactly those entries. The open question is
narrower than this document assumed: whether a 3.2–5.9 GB JIT decoder loads on a phone at
all. `qwen3-vl-8b` (10.4 GB) is already withheld from iOS, so size is being judged somewhere
— just not at 5.9 GB. Untested, and it still costs a download per attempt.

**Numbers, this phone, 27 windows.** LFM2.5-VL-450M: median 4.68 s/window, peak footprint
157 MB, 27/27 answered. Apple's `SystemLanguageModel` on the same 27: median 2.23 s/window,
peak 34 MB, 26 answered and 1 refused. So the local VLM costs 2.1× the latency and 4.6× the
memory, and answers the window the system model refuses. Thermal state drifted from
`nominal` to `fair` during the run and per-window time went 3.52 s → 5.50 s, so the median
is a mid-throttle number, not a cold one.
