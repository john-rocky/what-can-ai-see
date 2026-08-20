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

@MainActor
@Observable
final class WalkRecorder {
    var running = false
    var status = "idle"
    var latest = "—"
    var lagText = "—"
    var framesWritten = 0
    var framesDropped = 0
    var gateState = "…"
    var said: [WalkSaid] = []
    /// What the OS model reported about itself, shown on screen. The whole reason to ask is
    /// that "Apple's model is lighter" is only true if it can do the job at all.
    var visionNote = "—"
    /// Non-zero means frames were discarded because the detector could not rule on them.
    /// Surfaced rather than swallowed: a run with a high count recorded far less than it
    /// looks like, and a run where this climbs steadily has a broken detector.
    var detectorErrors = 0
    /// The gate refuses to arm until the bundled people-fixtures all fire. See GateSelfTest.
    var armed = false
    var armNote = "not tested"

    private let log = Logger(subsystem: "com.whatcanaisee.walk", category: "walk")
    private var feed: CameraFeed?
    private var detector: KitDetector?
    /// One threshold, used by the self-test and the gate alike. Below the usual 0.5 because
    /// a missed person is the harmful error here; see PersonGate.
    let gateThreshold: Float = 0.20
    private var task: Task<Void, Never>?

    /// Session, so the preview layer can render the camera for free.
    var captureSession: AVCaptureSession? { feed?.captureSession }

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
            let r = await GateSelfTest.run(detector: d, threshold: gateThreshold)
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
        task = Task { await self.run() }
    }

    func stop() {
        task?.cancel()
        feed?.stop()
        running = false
        UIApplication.shared.isIdleTimerDisabled = false
        status = "stopped"
    }

    private func run() async {
        do {
            guard let detector else {
                status = "not armed — run the gate self-test first"
                running = false
                return
            }
            let sysVision = SystemLanguageModel.default.capabilities.contains(.vision)
            let sysReady = SystemLanguageModel.default.isAvailable

            var kitVLM: KitVisionModel?
            if engine == .system {
                guard sysReady, sysVision else {
                    status = "system model cannot take images here "
                        + "(available \(sysReady), vision \(sysVision)) — pick another engine"
                    running = false
                    return
                }
            } else {
                status = "loading VLM (\(engine.rawValue))…"
                kitVLM = try await KitVisionModel(catalog: engine.rawValue)
            }

            let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
            let stamp = Int(Date().timeIntervalSince1970)
            let clipURL = docs.appendingPathComponent("walk-\(stamp).mov")
            let sidecarURL = docs.appendingPathComponent("walk-\(stamp).jsonl")

            let feed = CameraFeed(framesPerSecond: 10, preset: .hd1280x720)
            self.feed = feed
            let frames = try await feed.startPixelBuffers()
            status = "walking"

            var gate = PersonGate(scoreThreshold: gateThreshold)
            var writer: ClipWriter?
            let t0 = Date()
            // Recent cleared frames, for the contact sheet. Only frames the gate released,
            // so the commentary can never describe something the recording does not contain.
            var recent: [(CGImage, Double)] = []
            var vlmBusy = false
            var sidecar = ""

            for await frame in frames {
                if Task.isCancelled { break }
                let now = Date().timeIntervalSince(t0)
                // FAIL CLOSED. `try?` here used to collapse a detector error into an empty
                // array, which the gate reads as "nobody in shot" and opens — so a detector
                // that threw on every frame would have recorded everything, silently, which
                // is the exact outcome the gate exists to prevent. A frame the detector
                // could not rule on is treated as a frame with a person in it.
                var dets: [Detection]
                do {
                    dets = try await detector.detect(
                        in: frame.pixelBuffer, scoreThreshold: gate.scoreThreshold)
                } catch {
                    detectorErrors += 1
                    gate.forceBlock(at: now)
                    gateState = "DETECTOR FAILED — not recording"
                    log.error("detector: \(error, privacy: .public)")
                    continue
                }

                switch gate.offer(frame: frame.pixelBuffer, at: now, detections: dets) {
                case .blocked(let n):
                    gateState = "PERSON (\(n)) — not recording"
                    recent.removeAll()
                case .cooling(let left):
                    gateState = String(format: "clear in %.1fs", left)
                case .open(let commit):
                    gateState = "recording"
                    if writer == nil, let first = commit.first {
                        let w = CVPixelBufferGetWidth(first.pixelBuffer)
                        let h = CVPixelBufferGetHeight(first.pixelBuffer)
                        writer = try? ClipWriter(url: clipURL, width: w, height: h)
                    }
                    for f in commit {
                        await writer?.append(f)
                        if let img = Self.cgImage(from: f.pixelBuffer) {
                            recent.append((img, f.time))
                        }
                    }
                }
                framesWritten = await writer?.framesWritten ?? 0
                framesDropped = gate.droppedCount

                recent.removeAll { now - $0.1 > windowSeconds * 2 }

                // Fire the VLM whenever it is free and a full window of cleared frames is
                // available. Not on a timer: a timer would queue answers behind a slow one
                // and the lag would compound instead of being measured.
                if !vlmBusy, recent.count >= panels,
                    let oldest = recent.first?.1, now - oldest >= windowSeconds
                {
                    let window = Array(recent.suffix(panels))
                    vlmBusy = true
                    let wStart = window.first!.1
                    let wEnd = window.last!.1
                    Task { [weak self] in
                        guard let self else { return }
                        let sheet = ContactSheet.compose(window.map { $0.0 })
                        var text = ""
                        do {
                            let opts = GenerationOptions(
                                samplingMode: self.sampling == .greedy ? .greedy : nil,
                                maximumResponseTokens: 96)
                            // Same session shape either way — SystemLanguageModel and
                            // KitVisionModel both conform to `LanguageModel`, so the only
                            // thing that changes is which one is handed in.
                            if let kitVLM {
                                let session = LanguageModelSession(model: kitVLM)
                                text = try await session.respond(
                                    to: Prompt { self.prompt; Attachment(sheet) },
                                    options: opts
                                ).content
                            } else {
                                let session = LanguageModelSession()
                                text = try await session.respond(
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
                            sampling: self.sampling.rawValue,
                            thermal: WalkProbe.thermal(),
                            footprintMB: WalkProbe.footprintMB(),
                            batteryPct: WalkProbe.batteryPercent())
                        await MainActor.run {
                            self.said.append(row)
                            self.latest = text
                            self.lagText = String(format: "%.1fs behind", row.lagSeconds)
                        }
                        if let d = try? JSONEncoder().encode(row) {
                            sidecar += String(decoding: d, as: UTF8.self) + "\n"
                            try? sidecar.write(to: sidecarURL, atomically: true, encoding: .utf8)
                        }
                        vlmBusy = false
                    }
                }
            }

            let pending = gate.discardPending()
            let out = await writer?.finish()
            status = "saved \(out?.lastPathComponent ?? "nothing") "
                + "(\(framesWritten) frames written, \(gate.droppedCount) dropped, "
                + "\(pending) unflushed)"
            log.notice("\(self.status, privacy: .public)")
        } catch {
            status = "ERROR \(error)"
            log.error("\(self.status, privacy: .public)")
        }
        running = false
    }
}

extension WalkRecorder {
    /// `CameraFrame.cgImage()` would do this, but its initializer is internal to the kit —
    /// the type is only ever handed OUT of a feed, never constructed. Same conversion, one
    /// shared CIContext: a fresh context per frame allocates a Metal command queue every
    /// time and shows up as a stutter in the detector loop.
    private static let ciContext = CIContext()

    static func cgImage(from buffer: CVPixelBuffer) -> CGImage? {
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
