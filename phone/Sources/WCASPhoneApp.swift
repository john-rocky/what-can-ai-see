// WCASPhoneApp.swift — an app only because iOS will not run a SwiftPM executable.
//
// There is no interaction to design here. The run starts on appear and streams to the
// console; the view exists so the process has something to be, and shows the tail of the
// log so a run started by hand (rather than over devicectl) is still legible.
//
// One thing the UI does earn: `isIdleTimerDisabled`. A sustained run is the point — the
// thermal curve only shows up after minutes — and a phone that sleeps mid-benchmark
// produces a throughput number with a gap in it and no indication there was a gap.

import SwiftUI

@main
struct WCASPhoneApp: App {
    var body: some Scene {
        WindowGroup { BenchView() }
    }
}

struct BenchView: View {
    @State private var lines: [String] = []
    @State private var running = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("what-can-ai-see — device bench")
                .font(.headline)
            Text(running ? "running…" : "idle")
                .font(.caption)
                .foregroundStyle(.secondary)
            ScrollView {
                VStack(alignment: .leading, spacing: 2) {
                    ForEach(Array(lines.enumerated()), id: \.offset) { _, l in
                        Text(l)
                            .font(.system(size: 11, design: .monospaced))
                            .textSelection(.enabled)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding()
        .task {
            guard !running else { return }
            running = true
            #if canImport(UIKit)
                UIApplication.shared.isIdleTimerDisabled = true
            #endif
            let log = BenchLog()
            let poll = Task {
                while !Task.isCancelled {
                    lines = await log.all().suffix(200)
                    try? await Task.sleep(for: .milliseconds(400))
                }
            }
            await Bench.run(log: log)
            lines = await log.all().suffix(200)
            poll.cancel()
            running = false
        }
    }
}

#if canImport(UIKit)
    import UIKit
#endif
