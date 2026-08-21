// GateSelfTest.swift — the gate proves it works before a walk is allowed to start.
//
// The gate is a promise made to a stranger: nothing with you in it was recorded. Three
// things can break that promise silently, and none of them shows up as an error:
//
//   the detector did not load, or throws on every frame — WalkRecorder now fails closed on
//   that, but a gate that blocks 100% of frames records nothing at all, and a walk that
//   quietly produced an empty file is its own failure;
//   the person class id is wrong for this detector family — yolox works in a contiguous
//   0..79 space internally and maps to COCO ids on the way out, so `classID == 1` is
//   correct today and would silently become "bicycle" if that mapping ever moved;
//   the score threshold sits above what this detector gives a real person.
//
// So: frames that are known to contain people ship inside the app, and the SAME detector
// instance the gate will use runs over them at launch. Every one must fire, or Start stays
// disabled. Testing this by walking outside and hoping puts the person holding the phone in
// exactly the position the gate exists to avoid.
//
// The fixtures are cut by tools/gate_frames.py and span framings on purpose — a set of big
// centred people passes on a detector that would miss the figure at the end of the street,
// who is the one most likely to object. Measured on the Mac with rf-detr at threshold 0.20,
// people stayed detectable down to 0.08% of frame area (~30x30 px at 720p), though one
// single-person frame was lost at the smallest scale. It is not perfect and this test does
// not claim it is; it claims the detector is working at all, which is the failure that
// would otherwise be invisible.

import CoreAIKitVision
import CoreGraphics
import Foundation
import ImageIO

struct GateFixture: Decodable {
    let image: String
    let note: String
}

enum GateSelfTest {
    struct Result {
        let passed: Bool
        let lines: [String]
        let summary: String
    }

    /// Runs `detector` over every bundled fixture. Passes only if all of them report at
    /// least one person at `threshold` — the same threshold the gate will use, because a
    /// test run at a friendlier one proves nothing about the walk.
    static func run(detector: KitDetector, threshold: Float, gate: PersonGate) async -> Result {
        guard let url = Bundle.main.url(forResource: "gate_fixtures", withExtension: "json"),
            let data = try? Data(contentsOf: url),
            let fixtures = try? JSONDecoder().decode([GateFixture].self, from: data),
            !fixtures.isEmpty
        else {
            return Result(
                passed: false,
                lines: ["no gate fixtures in the bundle — run tools/gate_frames.py"],
                summary: "NOT ARMED — no fixtures")
        }

        var lines: [String] = []
        var failures = 0
        for f in fixtures {
            guard let image = load(f.image) else {
                lines.append("MISSING \(f.image)")
                failures += 1
                continue
            }
            do {
                let dets = try await detector.detect(in: image, scoreThreshold: threshold)
                // The same shape filter the gate applies. A self-test that accepts boxes
                // the gate would reject proves a different gate than the one that runs.
                let people = dets.filter {
                    guard $0.classID == personClassID || $0.label.lowercased() == "person"
                    else { return false }
                    let w = Double($0.box.width), h = Double($0.box.height)
                    return h > 0 && w / h <= gate.maxAspect && w * h <= gate.maxArea
                }
                let best = people.map(\.score).max() ?? 0
                if people.isEmpty {
                    failures += 1
                    lines.append("MISS  \(f.note)")
                } else {
                    lines.append(String(format: "ok %d @%.2f  %@", people.count, best, f.note))
                }
            } catch {
                failures += 1
                lines.append("ERROR \(f.note): \(error)")
            }
        }
        let passed = failures == 0
        return Result(
            passed: passed,
            lines: lines,
            summary: passed
                ? "ARMED — \(fixtures.count)/\(fixtures.count) fixtures detected a person"
                : "NOT ARMED — \(failures) of \(fixtures.count) fixtures missed")
    }

    private static func load(_ name: String) -> CGImage? {
        let stem = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        guard let url = Bundle.main.url(forResource: stem, withExtension: ext.isEmpty ? "jpg" : ext),
            let src = CGImageSourceCreateWithURL(url as CFURL, nil)
        else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }
}
