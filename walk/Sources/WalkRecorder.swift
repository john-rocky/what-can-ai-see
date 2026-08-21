// WalkRecorder.swift — the walk itself: camera in, gated recording plus a VLM commentary out.
//
// Two loops at very different rates, which is the whole shape of the thing:
//
//   the detector runs on every frame (~10 fps, 36-103 MB) and decides whether the frame is
//   allowed to exist. It has to be cheap enough to never fall behind, because a frame it
//   fails to look at is a frame the gate cannot rule on.
//
//   the VLM runs when it is free (seconds per answer, gigabytes resident) on a contact
//   sheet of frames the gate already cleared. It is never in the path of the recording, so
//   a slow answer delays the commentary and nothing else.
//
// The lag between them is not a defect to hide. A description that arrives 4 seconds after
// the frames it describes is, at walking pace, about six metres back down the street — a
// place already gone. That is the finding this app exists to make visible, so every answer
// carries the timestamp of the window it was computed from, and the exporter draws it
// against the video at THAT time rather than at the time it arrived.

import AVFoundation
import CoreAIKit
import CoreAIKitVision
import CoreGraphics
import CoreImage
import Foundation
import FoundationModels
import UIKit
import os

/// Everything the screen shows, as one value. Pushed to the main actor a few times a
/// second rather than field-by-field from inside the frame loop: each `@Observable`
/// mutation schedules a SwiftUI invalidation, and doing that ten times per frame put the
/// redraw work in the same queue as the detector. That is what made the camera's
/// bufferingNewest(1) stream drop frames the gate then never ruled on.
/// The "is the VLM free" flag. It was a local `var` mutated from inside a detached Task,
/// which Swift 6 rejects and was genuinely unsound: the frame loop reads it every frame
/// while the answer task clears it seconds later, on another thread.
/// Appends one caption line and rewrites the sidecar. Was a local `String` accumulated
/// from inside the answer Task — two answers finishing close together could interleave
/// their appends and lose a line, and the file was rewritten whole from a value the frame
/// loop also held. One owner instead.
actor SidecarWriter {
    private let url: URL
    private var text = ""
    init(url: URL) { self.url = url }
    func append(_ row: WalkSaid) {
        guard let d = try? JSONEncoder().encode(row) else { return }
        text += String(decoding: d, as: UTF8.self) + "\n"
        try? text.write(to: url, atomically: true, encoding: .utf8)
    }
}

actor VLMGate {
    private var busy = false
    func take() -> Bool {
        if busy { return false }
        busy = true
        return true
    }
    func release() { busy = false }
}

/// Strips the task read-back off a model's answer. Every model here opens by restating the
/// prompt — "The image shows a contact sheet of 4 frames covering the last 3.0 seconds of a
/// camera feed, in time order: panel 1 is the earliest, panel 4 is the latest." — which is
/// 150 characters of the caption box spent saying what was asked rather than what is there.
/// On screen that left one clause of actual content before the text ran out.
///
/// The Mac side has done this since the film cards (tools/said_card.py); the app was
/// showing raw output because I ported the pipeline and not this.
enum Echo {
    private static let openers: [String] = [
        "the image shows a contact sheet", "the image is a contact sheet",
        "this contact sheet", "the contact sheet shows", "the contact sheet",
        "based on the sequence", "based on the provided contact sheet",
        "here is a detailed description", "the image shows a sequence",
        "the image depicts a sequence",
    ]

    static func trim(_ text: String) -> String {
        var t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        // Drop leading sentences that are pure restatement. Sentence at a time, because the
        // echo is sometimes two of them and the content always follows.
        for _ in 0..<3 {
            let lower = t.lowercased()
            guard openers.contains(where: { lower.hasPrefix($0) }) else { break }
            guard let dot = t.firstIndex(of: ".") else { break }
            let rest = t[t.index(after: dot)...].trimmingCharacters(in: .whitespaces)
            if rest.isEmpty { break }
            t = String(rest)
        }
        return t
    }
}

/// ONLY the fields the frame loop owns. `status`, `latest` and `lagText` are deliberately
/// not here: they are written from outside the loop — by `say()` at setup and by the answer
/// task when a caption lands — and `push` used to assign this whole struct over the top of
/// them, so a caption appeared and was wiped by the next push 160 ms later, and the status
/// line read "idle" for the entire walk. A struct that carries a field nobody in the loop
/// sets will overwrite that field with its default, every time.
struct WalkUI: Sendable {
    var gateState = "…"
    var framesWritten = 0
    var framesDropped = 0
    var framesSeen = 0
    var keptPercent: Double = 0
    /// Straight from `LiveStats`, which the kit's pipeline already computes: frames the
    /// model could not keep up with plus frames the thermal governor skipped, the median
    /// inference latency, the achieved rate, and the rate the governor is asking for. A
    /// hand-written version of all four was the first thing I reached for; it was worse,
    /// and it was already here.
    var droppedByPipeline = 0
    var pipelineFps: Double = 0
    var latencyMs: Double = 0
    var targetFps: Double = 0
    var detectorErrors = 0
    /// What the shape rule did to the most recent person-class boxes, for the screen. The
    /// filter is the difference between a walk that records and one that does not, so it
    /// has to be visible where the decision is being questioned.
    var lastPersonNote = ""
}

struct WalkSaid: Codable {
    let windowStart: Double  // when the frames it saw were captured
    let windowEnd: Double
    let arrivedAt: Double  // when the answer came back
    let lagSeconds: Double  // arrivedAt - windowEnd: the distance behind the world
    let text: String
    /// Recorded per answer, not per walk: a cut that mixes settings has to be able to say
    /// which line came from which, and a sidecar that only names the setting once cannot.
    let sampling: String
    let thermal: String
    let footprintMB: Double
    let batteryPct: Double
}

// The published state is @MainActor; the FRAME LOOP is not, and that separation is the
// whole fix. It used to run on the main actor with the detector, the CGImage conversion and
// the VLM await all in the same queue as SwiftUI's redraws — which are driven by the very
// counters this loop updates every frame. Whenever the UI was busy the camera's
// `bufferingNewest(1)` stream silently dropped whatever arrived, so the gate ruled on a
// SAMPLE of the street rather than on the street: people present in dropped frames were
// never seen, and the verdict shown on screen belonged to a frame from some milliseconds
// ago. Both directions of the reported failure come from that one line.
@MainActor
@Observable
final class WalkRecorder {
    var running = false
    var ui = WalkUI()
    var said: [WalkSaid] = []
    var visionNote = "—"
    var armed = false
    var armNote = "not tested"

    // Read-through accessors so the view reads the same names it always did.
    /// Written outside the frame loop, so they are stored rather than read through `ui`.
    var status = "idle"
    var latest = "—"
    var lagText = "—"

    var gateState: String { ui.gateState }
    var framesWritten: Int { ui.framesWritten }
    var framesDropped: Int { ui.framesDropped }
    var framesSeen: Int { ui.framesSeen }
    var keptPercent: Double { ui.keptPercent }
    var droppedByPipeline: Int { ui.droppedByPipeline }
    var pipelineFps: Double { ui.pipelineFps }
    var latencyMs: Double { ui.latencyMs }
    var targetFps: Double { ui.targetFps }
    var detectorErrors: Int { ui.detectorErrors }
    var lastPersonNote: String { ui.lastPersonNote }

    private let log = Logger(subsystem: "com.whatcanaisee.walk", category: "walk")
    private var vision: LiveVision?
    private var detector: KitDetector?
    /// Main-actor, because `TranslationSession` is not Sendable. Fed by the view's
    /// `.translationTask`; the caption task hops to it once per answer, not per frame.
    let translator = Translator()
    /// Off by default. Translation is a demo affordance, not part of any measurement — the
    /// Mac runs score the model's own English, and scoring a translation would be scoring
    /// my translator.
    var translateToJapanese = false
    /// Milliseconds the translator adds, beside the caption's own lag so the two are
    /// comparable rather than conflated.
    var translateMs: Double = 0
    /// One threshold, used by the self-test and the gate alike. Below the usual 0.5 because
    /// a missed person is the harmful error here; see PersonGate.
    let gateThreshold: Float = 0.20
    private var task: Task<Void, Never>?

    /// Session, so the preview layer can render the camera for free.
    var captureSession: AVCaptureSession? { vision?.captureSession }

    // Tunables. The window matches tools/stream.py so a walk can be scored with the same
    // code as the film runs — 4 panels over a few seconds, one question.
    private let detectorID = "yolox-s"  // 36 MB; the gate needs cheap, not accurate

    /// Which VLM answers. `.system` is Apple's own model: already in the OS, so nothing to
    /// download and no incremental resident memory, which on a phone is not a footnote —
    /// it is the difference between an app that ships and one that asks for 653 MB first.
    /// It is also what every developer gets for free, so it is the baseline the shipped
    /// models have to beat to be worth shipping. Whether the OS model can take an image at
    /// all is a RUNTIME question (`capabilities.contains(.vision)`), not a compile-time one;
    /// the walk logs the answer rather than assuming it.
    enum Engine: String, CaseIterable {
        case system  // Apple's SystemLanguageModel — 0 MB, already in the OS
        case lfm450m = "lfm2.5-vl-450m"  // 653 MB
        case minicpm = "minicpm-v-4.6"  // 2145 MB
        case lfm3b = "lfm2.5-vl-3b"  // 2815 MB
        case qwen2b = "qwen3-vl-2b"  // 3278 MB

        /// iOS download size, so the picker states the cost of each choice on the screen
        /// where the choice is made. From catalog.json; there is no 1.2B VL model — the
        /// LFM2.5-1.2B on HF is `pipeline_tag: text-generation`, no vision tower, no iOS
        /// variant, so it cannot appear here however convenient the size would be.
        var megabytes: Int {
            switch self {
            case .system: 0
            case .lfm450m: 653
            case .minicpm: 2145
            case .lfm3b: 2815
            case .qwen2b: 3278
            }
        }

        var short: String {
            switch self {
            case .system: "FM"
            case .lfm450m: "450M"
            case .minicpm: "MiniCPM"
            case .lfm3b: "LFM 3B"
            case .qwen2b: "Qwen 2B"
            }
        }
    }

    var engine: Engine = .system

    /// Argmax, or the sampler the runtime picks by default.
    ///
    /// Measured, three passes over the same 27 windows on this phone: Apple's system model
    /// on its default settings had a content-word overlap of 0.21 between runs, and one
    /// judgment window named the event in 1 of 3 passes. With `.greedy` the same three
    /// passes were identical, refusals included. The catalog models on the Mac are already
    /// greedy by default and do not move either way.
    ///
    /// Both settings are worth having on a walk and they answer different questions.
    /// `greedy` is what a measurement needs — the same street twice has to give the same
    /// sentence, or a difference cannot be attributed to the street. `sampled` is what a
    /// deployment actually gets if the caller does not ask, and watching it name the same
    /// shopfront two different ways is the argument for asking.
    enum Sampling: String, CaseIterable {
        case greedy
        case sampled
        var short: String { self == .greedy ? "greedy" : "default (samples)" }
    }
    var sampling: Sampling = .greedy
    private let windowSeconds = 3.0
    private let panels = 4
    private let prompt =
        "The image is a contact sheet of 4 frames covering the last 3.0 seconds of a camera "
        + "feed, in time order: panel 1 is the earliest, panel 4 is the latest. Describe "
        + "what is happening."

    /// Asked the moment the app opens, not when a walk starts. "Is Apple's own model
    /// lighter" is only a real option if it can take an image at all, and that is a fact
    /// about this OS build on this phone — so it is read and shown before anything is
    /// committed to, rather than discovered after a model has been downloaded.
    func probeSystemModel() {
        let m = SystemLanguageModel.default
        let vision = m.capabilities.contains(.vision)
        visionNote = "system model: available \(m.isAvailable), vision \(vision)"
        // Logger AND print: the unified log survives a kill, but `devicectl --console`
        // only streams stdout — a probe that logs and does not print reads as a silent
        // launch when it is driven from a script.
        log.notice("system model: available=\(m.isAvailable) vision=\(vision)")
        print("SYSMODEL available=\(m.isAvailable) vision=\(vision)")
    }

    /// Loads the detector and makes it prove itself on the bundled people-fixtures. Held
    /// afterwards, so the walk uses the exact instance that passed — testing one detector
    /// and walking with another would prove nothing.
    func arm() async {
        guard detector == nil else { return }
        armNote = "loading detector (\(detectorID))…"
        do {
            let d = try await KitDetector(catalog: detectorID)
            armNote = "testing the gate…"
            let r = await GateSelfTest.run(
                detector: d, threshold: gateThreshold,
                gate: PersonGate(scoreThreshold: gateThreshold))
            for l in r.lines { print("GATE \(l)") }
            print("GATE \(r.summary)")
            armNote = r.summary
            armed = r.passed
            if r.passed { detector = d }
        } catch {
            armNote = "NOT ARMED — detector failed to load: \(error)"
            armed = false
        }
    }

    func start() {
        guard !running, armed else { return }
        running = true
        UIApplication.shared.isIdleTimerDisabled = true
        // .detached: a Task inherited from a @MainActor method stays on the main actor,
        // which is exactly what was wrong before.
        task = Task.detached(priority: .userInitiated) { await self.run() }
    }

    func stop() {
        task?.cancel()
        task = nil
        // Release the session, not just stop it. Leaving `vision` set meant a second Start
        // built a new LiveVision while the old one still held the capture device: the new
        // stream produced nothing and the app looked frozen. `stop()` is the only place
        // that can clear it, because `run()` returns after the stream finishes and cannot
        // tell a cancel from a natural end.
        vision?.stop()
        vision = nil
        running = false
        UIApplication.shared.isIdleTimerDisabled = false
        status = "stopped"
    }

    /// One-shot status text from off the main actor. Distinct from `push`, which carries
    /// the whole per-frame struct: these are setup and teardown messages, not a stream.
    nonisolated private func say(_ text: String) async {
        await MainActor.run { self.status = text }
    }

    nonisolated private func run() async {
        do {
            // Snapshot the settings once. They cannot change mid-walk — the pickers are
            // disabled while running — and reading them per frame would be a main-actor hop
            // inside the loop, which is the thing this whole change is removing.
            let (detectorOpt, engineNow, samplingNow) = await MainActor.run {
                (self.detector, self.engine, self.sampling)
            }
            guard let detector = detectorOpt else {
                await say("not armed — run the gate self-test first")
                await MainActor.run { self.running = false }
                return
            }
            let sysVision = SystemLanguageModel.default.capabilities.contains(.vision)
            let sysReady = SystemLanguageModel.default.isAvailable

            var kitVLM: KitVisionModel?
            if engineNow == .system {
                guard sysReady, sysVision else {
                    await say(
                        "system model cannot take images here (available \(sysReady), "
                            + "vision \(sysVision)) — pick another engine")
                    await MainActor.run { self.running = false }
                    return
                }
            } else {
                await say("loading VLM (\(engineNow.rawValue))…")
                kitVLM = try await KitVisionModel(catalog: engineNow.rawValue)
            }

            let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            let stamp = Int(Date().timeIntervalSince1970)
            let clipURL = docs.appendingPathComponent("walk-\(stamp).mov")
            let sidecarURL = docs.appendingPathComponent("walk-\(stamp).jsonl")

            // The kit's pipeline, not a loop of my own. `LiveVision.results` is the
            // generic two-stage entry point: `prepare` is the synchronous CPU half and
            // `infer` is the model, run on separate detached tasks so one overlaps the
            // other, with a thermal governor backing the rate off on a hot phone and a
            // count of everything it had to drop.
            //
            // Writing this loop by hand instead is what broke the app. Mine ran on the main
            // actor next to SwiftUI's redraws, which its own per-frame counter updates were
            // triggering, so the camera's newest-only stream silently discarded whatever
            // arrived while the UI was busy: people present in dropped frames were never
            // ruled on, and the verdict on screen belonged to a frame from some
            // milliseconds ago. Both directions of "detects nobody / detects nothing" come
            // from that. Everything I then wrote to diagnose it — gap timing, loop timing,
            // a dropped counter — already existed here as `LiveStats`.
            //
            // The frame rides through both stages alongside the detections, which is the
            // kit's own pattern (see CoreAI.watch(for:)): the CGImage render costs more than
            // the detector, so it happens after a decision needs it, not on every frame.
            let vision = LiveVision(
                options: LiveVision.Options(
                    framesPerSecond: 10, preset: .hd1280x720,
                    dataOutputSize: LiveVision.captureSize(
                        forModelInput: detector.inputSize)))
            await MainActor.run { self.vision = vision }

            let th = gateThreshold
            let results = try await vision.results(
                prepare: { frame in (try detector.prepare(frame.pixelBuffer), frame) },
                infer: { staged in
                    (try await detector.detect(staged.0, scoreThreshold: th), staged.1)
                })
            await say("walking")

            var v = WalkUI()
            var lastPush = 0.0
            @Sendable func push(_ value: WalkUI) async {
                await MainActor.run { self.ui = value }
            }

            var gate = PersonGate(scoreThreshold: gateThreshold)
            var writer: ClipWriter?
            let t0 = Date()
            var recent: [(CGImage, Double)] = []
            let vlmGate = VLMGate()
            let sidecar = SidecarWriter(url: sidecarURL)

            for try await result in results {
                if Task.isCancelled { break }
                let (dets, frame) = result.value
                let now = Date().timeIntervalSince(t0)
                v.framesSeen += 1

                // Straight from the pipeline rather than timed by hand. `dropped` is frames
                // the model could not keep up with plus frames the thermal governor skipped
                // — the number that says whether the gate is ruling on the street or on a
                // sample of it.
                v.droppedByPipeline += result.stats.dropped
                v.pipelineFps = result.stats.framesPerSecond
                v.latencyMs = Double(result.stats.latency.components.seconds) * 1000
                    + Double(result.stats.latency.components.attoseconds) / 1e15
                v.targetFps = result.stats.targetFramesPerSecond

                // The commentary buffer is fed from the live frame, not from what the gate
                // released: nothing with a person in it reaches DISK, which is what someone
                // asking on the street cares about, while a caption is read once on screen
                // and kept nowhere. Rendered here because a caption is about to need it.
                // Append ALWAYS, trim from the front. The guard here used to be
                // `recent.count < panels * 2`, which stopped accepting frames the moment
                // the buffer filled — so the VLM kept re-reading the first eight frames of
                // the walk and its answer never changed. A ring, not a bucket.
                if let img = frame.cgImage() {
                    recent.append((img, now))
                    if recent.count > panels * 3 { recent.removeFirst(recent.count - panels * 3) }
                }

                // What is it actually calling a person? A gate that fires on every frame of
                // an empty room is either seeing something real that I cannot see in the
                // preview, or reading a buffer that does not match what the preview shows.
                // Printing the box tells the two apart: a plausible box over a plausible
                // object is the first, a box in a corner at a fixed size is the second.
                // Both sides of the filter. `kept` is what the gate acts on; `cut` is what
                // the shape rule threw away and why. Logging only the raw list made a
                // working filter look broken; logging only the kept list would hide the
                // opposite failure, a filter quietly rejecting real people.
                let keptPeople = gate.people(in: dets)
                let rawPeople = dets.filter { $0.classID == personClassID }
                let cut = rawPeople.count - keptPeople.count
                if !rawPeople.isEmpty {
                    v.lastPersonNote = shapeNote(rawPeople, kept: keptPeople)
                }
                if v.framesSeen % 10 == 1 {
                    let desc = rawPeople.prefix(3).map {
                        let w = Double($0.box.width), h = Double($0.box.height)
                        let ok = w / max(h, 0.01) <= gate.maxAspect && w * h <= gate.maxArea
                        return String(format: "%.2f %.1fx %@", $0.score, w / max(h, 0.01),
                                      ok ? "KEEP" : "cut")
                    }.joined(separator: " | ")
                    print("DETS n=\(dets.count) person_raw=\(rawPeople.count) "
                        + "kept=\(keptPeople.count) cut=\(cut) fps=\(String(format: "%.1f", v.pipelineFps))"
                        + (desc.isEmpty ? "" : "  \(desc)"))
                }

                switch gate.offer(frame: frame.pixelBuffer, at: now, detections: dets) {
                case .blocked(let n):
                    v.gateState = "PERSON (\(n)) — not recording"
                case .cooling(let left):
                    v.gateState = String(format: "clear in %.1fs", left)
                case .open(let commit):
                    v.gateState = "recording"
                    if writer == nil, let first = commit.first {
                        let w = CVPixelBufferGetWidth(first.pixelBuffer)
                        let h = CVPixelBufferGetHeight(first.pixelBuffer)
                        writer = try? ClipWriter(url: clipURL, width: w, height: h)
                    }
                    for f in commit { await writer?.append(f) }
                }
                v.framesWritten = await writer?.framesWritten ?? 0
                v.framesDropped = gate.droppedCount
                let kept = v.framesWritten + gate.pendingCount
                v.keptPercent = v.framesSeen > 0
                    ? 100 * Double(kept) / Double(v.framesSeen) : 0

                if now - lastPush > 0.16 {
                    lastPush = now
                    await push(v)
                }

                if recent.count >= panels, await vlmGate.take() {
                    let window = Array(recent.suffix(panels))
                    let wStart = window.first!.1
                    let wEnd = window.last!.1
                    let sheet = ContactSheet.compose(window.map { $0.0 })
                    Task { [weak self] in
                        guard let self else { return }
                        var text = ""
                        do {
                            let opts = GenerationOptions(
                                samplingMode: samplingNow == .greedy ? .greedy : nil,
                                maximumResponseTokens: 96)
                            if let kitVLM {
                                text = try await LanguageModelSession(model: kitVLM).respond(
                                    to: Prompt { self.prompt; Attachment(sheet) },
                                    options: opts
                                ).content
                            } else {
                                text = try await LanguageModelSession().respond(
                                    to: Prompt { self.prompt; Attachment(sheet) },
                                    options: opts
                                ).content
                            }
                        } catch {
                            text = "ERROR \(error)"
                        }
                        let arrived = Date().timeIntervalSince(t0)
                        let row = WalkSaid(
                            windowStart: wStart, windowEnd: wEnd, arrivedAt: arrived,
                            lagSeconds: arrived - wEnd, text: text,
                            sampling: samplingNow.rawValue,
                            thermal: WalkProbe.thermal(),
                            footprintMB: WalkProbe.footprintMB(),
                            batteryPct: WalkProbe.batteryPercent())
                        // Translate the TRIMMED text, not the raw answer: the prompt echo is
                        // 150 characters of restatement and translating it would pay for
                        // words that are then thrown away.
                        let shown = Echo.trim(text)
                        var display = shown
                        if await MainActor.run(body: { self.translateToJapanese }) {
                            display = await self.translator.translate(shown)
                            await MainActor.run {
                                self.translateMs = self.translator.medianMs
                            }
                        }
                        await MainActor.run {
                            self.said.append(row)
                            self.latest = display
                            self.lagText = String(
                                format: "%.1fs behind", row.lagSeconds)
                        }
                        print(String(
                            format: "CAPTION t=%.1f lag=%.1fs %@",
                            wStart, row.lagSeconds,
                            String(text.prefix(90)).replacingOccurrences(of: "\n", with: " ")))
                        await sidecar.append(row)
                        await vlmGate.release()
                    }
                }
            }

            let pending = gate.discardPending()
            let out = await writer?.finish()
            // Build the message once and log THAT, rather than reading `status` back off
            // the main actor — a read that a nonisolated context cannot make, and that
            // would report whatever the UI happened to hold rather than what just happened.
            let done = "saved \(out?.lastPathComponent ?? "nothing") "
                + "(\(v.framesWritten) frames written, \(gate.droppedCount) dropped, "
                + "\(pending) unflushed)"
            await say(done)
            log.notice("\(done, privacy: .public)")
        } catch {
            let msg = "ERROR \(error)"
            await say(msg)
            log.error("\(msg, privacy: .public)")
        }
        // Tear down here as well as in stop(). A run can end without stop() being pressed —
        // the stream finishing, a throw, the task being cancelled — and every one of those
        // paths used to leave `vision` holding the camera, so the NEXT Start built a second
        // session on top of a live one and delivered no frames at all.
        await MainActor.run {
            self.vision?.stop()
            self.vision = nil
            self.running = false
        }
    }
}

/// "2 person boxes: 1 kept, 1 cut (3.7x wide)" — the shape rule, stated where someone is
/// looking at an empty room wondering why it says PERSON.
nonisolated func shapeNote(_ raw: [Detection], kept: [Detection]) -> String {
    let cut = raw.count - kept.count
    guard cut > 0 else { return "\(raw.count) person box(es), all kept" }
    let widest = raw.map { Double($0.box.width) / max(Double($0.box.height), 0.01) }.max() ?? 0
    return String(format: "%d person box(es): %d kept, %d cut (widest %.1fx wide)",
                  raw.count, kept.count, cut, widest)
}

extension WalkRecorder {
    /// `CameraFrame.cgImage()` would do this, but its initializer is internal to the kit —
    /// the type is only ever handed OUT of a feed, never constructed. Same conversion, one
    /// shared CIContext: a fresh context per frame allocates a Metal command queue every
    /// time and shows up as a stutter in the detector loop.
    nonisolated(unsafe) private static let ciContext = CIContext()

    nonisolated static func cgImage(from buffer: CVPixelBuffer) -> CGImage? {
        let image = CIImage(cvPixelBuffer: buffer)
        return ciContext.createCGImage(image, from: image.extent)
    }
}

/// The same 2x2 layout `tools/sheet.py` builds on the Mac, so a walk window and a film
/// window are the same kind of input and the answers are comparable.
enum ContactSheet {
    static func compose(_ images: [CGImage], side: Int = 512) -> CGImage {
        let cell = side / 2
        let ctx = CGContext(
            data: nil, width: side, height: side, bitsPerComponent: 8, bytesPerRow: 0,
            space: CGColorSpaceCreateDeviceRGB(),
            bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)!
        ctx.setFillColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
        ctx.fill(CGRect(x: 0, y: 0, width: side, height: side))
        for (i, img) in images.prefix(4).enumerated() {
            // Row 0 on top: CoreGraphics origin is bottom-left, so panel 1 (earliest) has
            // to be drawn at the HIGH y. Getting this backwards silently reverses time and
            // every "the sequence progresses" answer becomes a description of the reverse.
            let col = i % 2
            let row = i / 2
            ctx.draw(
                img,
                in: CGRect(
                    x: col * cell, y: side - cell - row * cell, width: cell, height: cell))
        }
        return ctx.makeImage()!
    }
}
