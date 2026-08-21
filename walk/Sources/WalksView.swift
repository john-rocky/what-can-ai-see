// WalksView.swift — look at what the walk produced, on the phone, without a Mac.
//
// The app wrote a .mov and a .jsonl into Documents and offered no way to open either. That
// made every walk unreviewable until it was pulled over USB, which means the person doing
// the walking could not tell whether it had worked — and a walk that recorded nothing looks
// exactly like a walk that recorded everything.
//
// So: the list of walks, each with what it actually captured, a player, the captions with
// their lag, and a share sheet. The share sheet is the part that matters most in the field;
// it is how footage leaves the phone when there is no cable.

import AVKit
import SwiftUI

struct WalkFile: Identifiable, Hashable {
    let id: String  // stem, e.g. walk-1755600000
    let movie: URL?
    let sidecar: URL?
    let started: Date
    let bytes: Int64

    var hasVideo: Bool { movie != nil && bytes > 0 }
}

enum WalkStore {
    static func list() -> [WalkFile] {
        let fm = FileManager.default
        let docs = fm.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let items = (try? fm.contentsOfDirectory(
            at: docs, includingPropertiesForKeys: [.creationDateKey, .fileSizeKey])) ?? []
        var stems = Set<String>()
        for u in items where u.lastPathComponent.hasPrefix("walk-") {
            stems.insert(u.deletingPathExtension().lastPathComponent)
        }
        return stems.map { stem -> WalkFile in
            let mov = docs.appendingPathComponent("\(stem).mov")
            let side = docs.appendingPathComponent("\(stem).jsonl")
            let attrs = try? fm.attributesOfItem(atPath: mov.path)
            // The stem is a unix timestamp the recorder minted at start, which is a more
            // reliable clock than the file's creation date — the movie is created lazily,
            // on the first frame the gate released, which may be a minute in.
            let t = Double(stem.dropFirst("walk-".count)) ?? 0
            return WalkFile(
                id: stem,
                movie: fm.fileExists(atPath: mov.path) ? mov : nil,
                sidecar: fm.fileExists(atPath: side.path) ? side : nil,
                started: Date(timeIntervalSince1970: t),
                bytes: (attrs?[.size] as? Int64) ?? 0)
        }
        .sorted { $0.started > $1.started }
    }

    static func said(_ w: WalkFile) -> [WalkSaid] {
        guard let s = w.sidecar, let text = try? String(contentsOf: s, encoding: .utf8)
        else { return [] }
        let dec = JSONDecoder()
        return text.split(separator: "\n").compactMap {
            try? dec.decode(WalkSaid.self, from: Data($0.utf8))
        }
    }

    static func delete(_ w: WalkFile) {
        for u in [w.movie, w.sidecar].compactMap({ $0 }) {
            try? FileManager.default.removeItem(at: u)
        }
    }
}

struct WalksView: View {
    @State private var walks: [WalkFile] = []

    var body: some View {
        NavigationStack {
            List {
                if walks.isEmpty {
                    Text("no walks yet")
                        .foregroundStyle(.secondary)
                }
                // `ForEach(walks)` picked the Range overload here: WalkFile is Identifiable
                // AND Hashable, and the compiler resolved the wrong one. Naming the key path
                // removes the ambiguity instead of relying on which overload wins.
                ForEach(walks, id: \.id) { w in
                    NavigationLink(value: w) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(w.started.formatted(date: .abbreviated, time: .shortened))
                                .font(.headline)
                            // What it holds, stated plainly. "no video" is a real outcome —
                            // a walk down a busy street can legitimately clear nothing.
                            Text(summary(w))
                                .font(.caption)
                                // Explicit Color on both branches: `.secondary` resolves to
                                // HierarchicalShapeStyle and `.orange` to Color, and a
                                // ternary needs one type.
                                .foregroundStyle(w.hasVideo ? Color.secondary : Color.orange)
                        }
                    }
                }
                .onDelete { idx in
                    for i in idx { WalkStore.delete(walks[i]) }
                    walks = WalkStore.list()
                }
            }
            .navigationTitle("Walks")
            .navigationDestination(for: WalkFile.self) { WalkDetail(walk: $0) }
            .refreshable { walks = WalkStore.list() }
        }
        .onAppear { walks = WalkStore.list() }
    }

    private func summary(_ w: WalkFile) -> String {
        let n = WalkStore.said(w).count
        let mb = Double(w.bytes) / 1_048_576
        return w.hasVideo
            ? String(format: "%.1f MB · %d caption(s)", mb, n)
            : "no video cleared the gate · \(n) caption(s)"
    }
}

struct WalkDetail: View {
    let walk: WalkFile
    @State private var said: [WalkSaid] = []

    var body: some View {
        List {
            if let mov = walk.movie, walk.hasVideo {
                Section {
                    VideoPlayer(player: AVPlayer(url: mov))
                        .frame(height: 240)
                    ShareLink(item: mov) { Label("Share the recording", systemImage: "square.and.arrow.up") }
                }
            } else {
                Section {
                    Text("No video. Every frame was blocked by the person-gate, or the walk "
                         + "was stopped before any frame finished its hold-back.")
                        .font(.callout)
                        .foregroundStyle(.orange)
                }
            }

            Section("what the model said") {
                if said.isEmpty {
                    Text("no captions").foregroundStyle(.secondary)
                }
                ForEach(Array(said.enumerated()), id: \.offset) { _, s in
                    VStack(alignment: .leading, spacing: 4) {
                        Text(String(format: "%.1fs · %@ · %.1fs behind",
                                    s.windowStart, s.sampling, s.lagSeconds))
                            .font(.system(size: 11, design: .monospaced))
                            .foregroundStyle(.orange)
                        Text(s.text).font(.callout)
                    }
                    .padding(.vertical, 2)
                }
            }

            if let side = walk.sidecar {
                Section {
                    ShareLink(item: side) { Label("Share the captions", systemImage: "doc.text") }
                }
            }
        }
        .navigationTitle(walk.started.formatted(date: .omitted, time: .shortened))
        .onAppear { said = WalkStore.said(walk) }
    }
}
