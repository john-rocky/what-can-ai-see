// WalkApp.swift — the screen you actually look at while walking.
//
// One thing on it is load-bearing: the gate state, large, in a colour you can read at
// arm's length in daylight. If someone asks what you are doing, the answer has to be
// visible on the phone rather than asserted — "it stops when it sees a person, look" is
// a different conversation from "it blurs them later, trust me".
//
// Everything else is small on purpose. The commentary is there so the walk is not blind,
// the counters are there because a walk that discarded most of itself should be abandoned
// early rather than discovered afterwards.

import AVFoundation
import SwiftUI
@preconcurrency import Translation

@main
struct WalkApp: App {
    var body: some Scene {
        WindowGroup {
            TabView {
                WalkView()
                    .tabItem { Label("Walk", systemImage: "figure.walk") }
                WalksView()
                    .tabItem { Label("Walks", systemImage: "film.stack") }
            }
        }
    }
}

struct WalkView: View {
    @State private var rec = WalkRecorder()

    var body: some View {
        // `.translationTask` is how a TranslationSession is obtained — it cannot be
        // constructed. The frame loop is nonisolated and cannot reach a view, so the session
        // is handed to an actor the moment SwiftUI provides one.
        content
            .translationTask(
                source: Locale.Language(identifier: "en"),
                target: Locale.Language(identifier: "ja"),
                preferredStrategy: .lowLatency
            ) { [t = rec.translator] session in
                // `@preconcurrency import Translation` is what makes this compile.
                // `TranslationSession` is a non-Sendable class and this closure is
                // nonisolated, so Swift 6 region isolation calls every `session.translate`
                // after any suspension a "send". Four restructurings failed before the
                // import: holding the session in an actor, passing it to a method, looping
                // with a @MainActor read inside, and a single call with no loop at all. The
                // framework is simply not audited for strict concurrency yet.
                //
                // The session still never leaves this closure, and the only thing shared
                // with the caption task is `t` — a lock over Strings. See Translator.swift.
                t.setReady(true)
                defer { t.setReady(false) }
                while !Task.isCancelled {
                    guard let text = t.take() else {
                        try? await Task.sleep(for: .milliseconds(30))
                        continue
                    }
                    let started = SuspendingClock.now
                    do {
                        let out = try await session.translate(text).targetText
                        let e = (SuspendingClock.now - started).components
                        t.deliver(
                            source: text, translated: out,
                            ms: Double(e.seconds) * 1000 + Double(e.attoseconds) / 1e15,
                            failed: false)
                    } catch {
                        t.deliver(source: text, translated: text, ms: 0, failed: true)
                    }
                }
            }
            .task {
            rec.probeSystemModel()
            await rec.arm()
            // WALK_AUTOSTART=1 begins a walk without a tap, so a device run driven from
            // devicectl can be read from the console. Verifying a fix by launching and
            // watching it arm is not verifying the fix — the bugs are all downstream of
            // Start, which is why three broken builds went out looking fine.
            if ProcessInfo.processInfo.environment["WALK_AUTOSTART"] == "1", rec.armed {
                rec.start()
            }
        }
    }

    private var content: some View {
        ZStack(alignment: .top) {
            CameraPreview(session: rec.captureSession)
                .ignoresSafeArea()

            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Circle()
                        .fill(gateColor)
                        .frame(width: 18, height: 18)
                    Text(rec.gateState)
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                    Spacer()
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(.black.opacity(0.62), in: .rect(cornerRadius: 12))

                Text(rec.status)
                    .font(.caption)
                    .foregroundStyle(.white.opacity(0.85))

                // Which model is answering, and what the OS model said about itself. The
                // second line is the whole reason the picker exists: "Apple's is lighter"
                // is only an argument if it can take an image at all, and that is a runtime
                // fact this app reads rather than assumes.
                Picker("engine", selection: $rec.engine) {
                    ForEach(WalkRecorder.Engine.allCases, id: \.self) { e in
                        Text(e.short).tag(e)
                    }
                }
                .pickerStyle(.segmented)
                .disabled(rec.running)

                // The download size next to the name, because that is the number the choice
                // is actually about: 0 MB against 3.3 GB is the comparison, not the id.
                Text("\(rec.engine.rawValue) — \(rec.engine.megabytes) MB to download")
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.7))

                Picker("sampling", selection: $rec.sampling) {
                    ForEach(WalkRecorder.Sampling.allCases, id: \.self) { m in
                        Text(m.short).tag(m)
                    }
                }
                .pickerStyle(.segmented)
                .disabled(rec.running)

                Toggle("日本語", isOn: $rec.translateToJapanese)
                    .font(.system(size: 13))
                    .foregroundStyle(.white)
                    .toggleStyle(.switch)

                Text(rec.visionNote)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.7))

                Text(String(format: "kept %.0f%%   written %d   dropped %d",
                            rec.keptPercent, rec.framesWritten, rec.framesDropped))
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.75))

                // The diagnostic that decides whether the gate is even seeing the street.
                // Red when the loop is missing frames: a gate that rules on one frame in
                // three is not the gate that was described to anyone.
                // From LiveStats. `dropped` is the one that says whether the gate is
                // ruling on the street or on a sample of it; red once the pipeline is
                // shedding frames faster than it is keeping them.
                if !rec.lastPersonNote.isEmpty {
                    Text(rec.lastPersonNote)
                        .font(.system(size: 12, design: .monospaced))
                        .foregroundStyle(.yellow)
                }

                Text(String(format: "%.1f fps (target %.0f)   %.0fms   dropped %d",
                            rec.pipelineFps, rec.targetFps, rec.latencyMs,
                            rec.droppedByPipeline))
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(
                        rec.droppedByPipeline > rec.framesSeen
                            ? Color.red : Color.white.opacity(0.75))
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.75))

                Spacer()

                VStack(alignment: .leading, spacing: 4) {
                    Text(rec.translateMs > 0
                         ? String(format: "%@  +%.0fms translate", rec.lagText, rec.translateMs)
                         : rec.lagText)
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.orange)
                    // Scrollable, not clipped. A four-line cap silently threw away the end
                    // of every answer, and the end is where these models put the content.
                    ScrollView {
                        Text(rec.latest)
                            .font(.system(size: 15))
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .frame(maxHeight: 150)
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(.black.opacity(0.62), in: .rect(cornerRadius: 12))

                // The arming line, in the colour of its verdict. Start is disabled until
                // the gate has proved itself on the bundled fixtures — a walk cannot be
                // begun on the assumption that the detector works.
                Text(rec.armNote)
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(rec.armed ? .green : .orange)

                Button(rec.running ? "Stop" : (rec.armed ? "Start walk" : "gate not armed")) {
                    rec.running ? rec.stop() : rec.start()
                }
                .font(.headline)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(
                    rec.running ? .red : (rec.armed ? .blue : .gray),
                    in: .rect(cornerRadius: 12))
                .foregroundStyle(.white)
                .disabled(!rec.armed && !rec.running)
            }
            .padding()
        }
    }

    private var gateColor: Color {
        if rec.gateState.hasPrefix("PERSON") { return .red }
        if rec.gateState.hasPrefix("recording") { return .green }
        return .yellow
    }
}

/// `AVCaptureVideoPreviewLayer` is drawn by the compositor, so showing the camera costs no
/// per-frame CPU — which matters here, because every cycle the preview takes is a cycle the
/// detector does not have, and a detector that falls behind is a gate that misses people.
struct CameraPreview: UIViewRepresentable {
    let session: AVCaptureSession?

    final class PreviewView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer { layer as! AVCaptureVideoPreviewLayer }
    }

    func makeUIView(context: Context) -> PreviewView {
        let v = PreviewView()
        v.previewLayer.videoGravity = .resizeAspectFill
        v.previewLayer.session = session
        return v
    }

    func updateUIView(_ v: PreviewView, context: Context) {
        if v.previewLayer.session !== session { v.previewLayer.session = session }
    }
}
