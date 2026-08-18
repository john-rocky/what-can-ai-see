// wcas-detect — the detector half of the classical baseline: load one detector, run it
// over a list of frames, print one JSON line per frame with every box.
//
// This exists for the same reason wcas-run does. CoreAIKit ships `detect-cli`, which loads
// the model, scores one image and exits; a baseline over a few thousand frames built on it
// would spend almost all its wall clock loading the same weights. Load once, stream frames.
//
// It deliberately does NOT decide anything. Object detection cannot detect "a spill" or
// "broken glass" — COCO has no such class — so turning boxes into an anomaly verdict takes
// a hand-written rule (a danger polygon, a class filter, an overlap threshold). That rule
// lives in tools/zone_rule.py where its knobs are visible and countable, because the number
// of knobs a classical pipeline needs is half of what this comparison is measuring.
//
// Input line:  {"id":"...","image":"/abs/frame.png"}
// Output line: {"id":"...","ok":true,"boxes":[{"label":"person","score":0.83,
//                                              "x":0.31,"y":0.12,"w":0.22,"h":0.44}]}
// Boxes are normalized, origin top-left, exactly as ObjectDetector returns them.

import CoreAIKitVision
import Foundation

func err(_ s: String, terminator: String = "\n") {
    FileHandle.standardError.write(Data((s + terminator).utf8))
}

func die(_ s: String) -> Never {
    err("wcas-detect: \(s)")
    exit(1)
}

struct Frame: Decodable {
    let id: String
    let image: String
}

let usage = """
    usage: wcas-detect --model <catalog-id> --frames <file.jsonl> --out <file.jsonl>
                       [--score 0.5] [--max 50] [--resume]
    """

var modelID = "rf-detr"
var framesPath: String?
var outPath: String?
var score: Float = 0.5
var maxDet = 50
var resume = false

var argv = CommandLine.arguments.dropFirst()
while let a = argv.popFirst() {
    switch a {
    case "--model": modelID = argv.popFirst() ?? modelID
    case "--frames": framesPath = argv.popFirst()
    case "--out": outPath = argv.popFirst()
    case "--score": score = Float(argv.popFirst() ?? "") ?? score
    case "--max": maxDet = Int(argv.popFirst() ?? "") ?? maxDet
    case "--resume": resume = true
    case "--list-models":
        for e in ModelCatalog.builtin.available(.detection) { print("\(e.id)  —  \(e.name)") }
        exit(0)
    default: die("unknown argument \(a)\n\(usage)")
    }
}
guard let framesPath, let outPath else { die(usage) }

let data: Data
do { data = try Data(contentsOf: URL(fileURLWithPath: framesPath)) }
catch { die("cannot read \(framesPath): \(error.localizedDescription)") }

let decoder = JSONDecoder()
var frames: [Frame] = []
for (n, line) in String(decoding: data, as: UTF8.self)
    .split(separator: "\n", omittingEmptySubsequences: true).enumerated()
{
    do { frames.append(try decoder.decode(Frame.self, from: Data(line.utf8))) }
    catch { die("frame line \(n + 1) is not valid: \(error)") }
}
guard !frames.isEmpty else { die("no frames in \(framesPath)") }

var done = Set<String>()
if resume, let existing = try? String(contentsOf: URL(fileURLWithPath: outPath), encoding: .utf8) {
    for line in existing.split(separator: "\n") {
        if let o = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
            let id = o["id"] as? String { done.insert(id) }
    }
    err("resume: \(done.count) already done")
}
let pending = frames.filter { !done.contains($0.id) }
guard !pending.isEmpty else { err("nothing to do"); exit(0) }

err("loading \(modelID) …")
let detector: ObjectDetector
do {
    detector = try await ObjectDetector(
        catalog: modelID,
        downloadProgress: { p in
            err(String(format: "\rdownloading %3.0f%%", p.fraction * 100),
                terminator: p.fraction < 1 ? "" : "\n")
        })
} catch {
    die("cannot load \(modelID): \(error.localizedDescription)")
}
err("loaded — \(pending.count) frame(s)")

// createFile TRUNCATES an existing file; only create it when genuinely absent. wcas-run
// learned this the expensive way — with --resume it silently destroyed the results it was
// resuming from.
if !FileManager.default.fileExists(atPath: outPath) {
    FileManager.default.createFile(atPath: outPath, contents: nil)
}
guard let sink = FileHandle(forWritingAtPath: outPath) else { die("cannot write \(outPath)") }
sink.seekToEndOfFile()

var failures = 0
for (i, f) in pending.enumerated() {
    var payload: [String: Any] = ["id": f.id, "model": modelID, "score_threshold": score]
    do {
        let img = try ImageFile.load(URL(fileURLWithPath: f.image))
        let dets = try await detector.detect(
            in: img.cgImage, scoreThreshold: score, maxDetections: maxDet)
        payload["ok"] = true
        payload["boxes"] = dets.map { d in
            ["label": d.label, "score": Double(d.score),
             "x": Double(d.box.origin.x), "y": Double(d.box.origin.y),
             "w": Double(d.box.width), "h": Double(d.box.height)] as [String: Any]
        }
    } catch {
        failures += 1
        payload["ok"] = false
        payload["error"] = "\(error)"
    }
    if let out = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) {
        sink.write(out)
        sink.write(Data("\n".utf8))
    }
    if (i + 1) % 50 == 0 || i + 1 == pending.count {
        err("[\(i + 1)/\(pending.count)]")
    }
}
try? sink.close()
err("done — \(pending.count - failures)/\(pending.count) ok")
exit(failures == pending.count ? 1 : 0)
