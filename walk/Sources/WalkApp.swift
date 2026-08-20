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

@main
struct WalkApp: App {
    var body: some Scene {
        WindowGroup { WalkView() }
    }
}

struct WalkView: View {
    @State private var rec = WalkRecorder()

    var body: some View {
        content.task {
            rec.probeSystemModel()
            await rec.arm()
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

                Text(rec.visionNote)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.7))

                Text("written \(rec.framesWritten)   dropped \(rec.framesDropped)")
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(.white.opacity(0.75))

                Spacer()

                VStack(alignment: .leading, spacing: 4) {
                    Text(rec.lagText)
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .foregroundStyle(.orange)
                    Text(rec.latest)
                        .font(.system(size: 15))
                        .foregroundStyle(.white)
                        .lineLimit(4)
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
