// Bench.swift — the Mac runner's loop, on the phone.
//
// Deliberately the same shape as `runner/Sources/wcas-run/main.swift`: same catalog ids,
// same task file, same fresh-session-per-task isolation, same one-JSON-line-per-result
// output. If the two differ, the difference is the device and not the harness — which is
// the only way the phone numbers can be compared to the 24 findings measured on the Mac.
//
// What it adds is the part a desktop benchmark cannot see: wall clock per window with the
// image decode included, and a memory/thermal reading beside every single answer rather
// than at the ends. See Probe.swift for why those three.
//
// Task file and images are bundled into the app (tools/stage_phone.py builds them). That
// is not laziness about file staging — a task file pushed to Documents can drift from the
// images it names, and this way the payload is one signed unit that either matches or
// does not build.

import CoreAIKit
import CoreGraphics
import Foundation
import FoundationModels
import ImageIO
import os

struct BenchTask: Decodable {
    let id: String
    let image: String  // resource name inside the bundle, not a path
    let prompt: String
}

actor BenchLog {
    private var lines: [String] = []
    private let started = Date()

    func add(_ s: String) {
        let t = String(format: "%7.1f", Date().timeIntervalSince(started))
        let line = "[\(t)] \(s)"
        lines.append(line)
        // print() so `devicectl device process launch --console` picks it up, Logger so it
        // survives a jetsam kill (the console stream dies with the process; the unified log
        // does not, and a kill is exactly the case worth reading afterwards).
        print(line)
        Probe.log.notice("\(line, privacy: .public)")
    }

    func all() -> [String] { lines }
}

enum Bench {
    static func env(_ k: String) -> String? { ProcessInfo.processInfo.environment[k] }

    static func run(log: BenchLog) async {
        let modelID = env("WCAS_MODEL") ?? "lfm2.5-vl-450m"
        let taskFile = env("WCAS_TASKS") ?? "tasks"
        let maxTokens = Int(env("WCAS_MAX_TOKENS") ?? "") ?? 96
        let limit = Int(env("WCAS_N") ?? "") ?? Int.max
        // WCAS_GREEDY=1 asks for argmax instead of sampling. On the Mac the catalog models
        // are already deterministic without it (three runs of LFM 3B over the same nine
        // windows: content-word overlap 1.00, and --greedy changed 0 of 9 answers). Apple's
        // system model on this phone was not: overlap 0.21, and one judgment window named
        // the event in 1 of 3 runs. This flag is here to find out whether that is the
        // caller's to fix.
        let greedy = env("WCAS_GREEDY") == "1"

        let dev = ProcessInfo.processInfo
        await log.add("device: \(deviceModel()) iOS \(dev.operatingSystemVersionString)")
        await log.add("physical memory: \(dev.physicalMemory / 1_048_576) MB")
        await log.add(
            "model: \(modelID)  maxTokens: \(maxTokens)  sampling: \(greedy ? "greedy" : "default")")
        await log.add("start \(jsonSnapshot(Probe.snapshot()))")

        guard let url = Bundle.main.url(forResource: taskFile, withExtension: "jsonl"),
            let data = try? Data(contentsOf: url)
        else {
            await log.add("ERROR no \(taskFile).jsonl in the app bundle — run tools/stage_phone.py")
            return
        }
        let decoder = JSONDecoder()
        var tasks: [BenchTask] = []
        for line in String(decoding: data, as: UTF8.self).split(separator: "\n") {
            if let t = try? decoder.decode(BenchTask.self, from: Data(line.utf8)) { tasks.append(t) }
        }
        tasks = Array(tasks.prefix(limit))
        guard !tasks.isEmpty else {
            await log.add("ERROR \(taskFile).jsonl has no readable tasks")
            return
        }
        await log.add("\(tasks.count) task(s)")

        // WCAS_MODEL=system runs Apple's own model instead of a catalog one. It is the
        // baseline every other row here has to beat to justify its download: 0 MB, already
        // resident, and what any developer gets without shipping anything. Whether it can
        // take an image is a runtime fact, so it is asked and logged rather than assumed.
        let sysVision = SystemLanguageModel.default.capabilities.contains(.vision)
        await log.add(
            "system model: available=\(SystemLanguageModel.default.isAvailable) "
                + "vision=\(sysVision)")

        // Cold load. On the phone this is not a footnote: the first launch downloads the
        // bundle over the network and then specializes it for this GPU, and a monitoring
        // product has to budget for both. Warm load is measured separately by relaunching.
        var vlm: KitVisionModel?
        let loadStart = SuspendingClock.now
        if modelID == "system" {
            guard SystemLanguageModel.default.isAvailable, sysVision else {
                await log.add("ERROR system model cannot take images on this build")
                await log.add("STATS model=system load=UNAVAILABLE")
                return
            }
        } else {
            await log.add("loading …")
            do {
                vlm = try await KitVisionModel(
                    catalog: modelID,
                    downloadProgress: { p in
                        if Int(p.fraction * 100) % 10 == 0 {
                            Probe.log.notice("download \(Int(p.fraction * 100))%")
                        }
                    })
            } catch {
                await log.add("ERROR load \(modelID): \(error)")
                await log.add("STATS load=FAILED \(jsonSnapshot(Probe.snapshot()))")
                return
            }
        }
        let loadS = seconds(since: loadStart)
        await log.add(
            String(format: "loaded in %.1f s  %@", loadS, jsonSnapshot(Probe.snapshot())))

        var results: [[String: Any]] = []
        var wallTotal = 0.0
        var peakFootprint = 0.0
        var failures = 0

        for (i, task) in tasks.enumerated() {
            let before = Probe.snapshot()
            let t0 = SuspendingClock.now

            var answer = ""
            var ok = true
            var errText = ""
            do {
                guard let image = loadImage(named: task.image) else {
                    throw NSError(
                        domain: "wcas", code: 1,
                        userInfo: [NSLocalizedDescriptionKey: "missing image \(task.image)"])
                }
                // Fresh session per task, matching the Mac runner. A held session would carry
                // the previous window's transcript into the next one and every "no memory
                // between turns" claim in this repo would stop being true on the phone.
                let opts = GenerationOptions(
                    samplingMode: greedy ? .greedy : nil, maximumResponseTokens: maxTokens)
                if let vlm {
                    answer = try await LanguageModelSession(model: vlm).respond(
                        to: Prompt { task.prompt; Attachment(image) }, options: opts
                    ).content
                } else {
                    answer = try await LanguageModelSession().respond(
                        to: Prompt { task.prompt; Attachment(image) }, options: opts
                    ).content
                }
            } catch {
                ok = false
                failures += 1
                errText = "\(error)"
            }

            let ms = seconds(since: t0) * 1000
            wallTotal += ms / 1000
            let after = Probe.snapshot()
            peakFootprint = max(peakFootprint, (after["footprint_mb"] as? Double) ?? 0)

            var row: [String: Any] = [
                "id": task.id, "model": modelID, "ok": ok, "ms": Int(ms),
                "max_tokens": maxTokens,
            ]
            if ok { row["answer"] = answer } else { row["error"] = errText }
            for (k, v) in after { row[k] = v }
            results.append(row)

            await log.add(
                String(
                    format: "[%3d/%3d] %@ %@ %6.0f ms  fp=%.0f avail=%.0f %@",
                    i + 1, tasks.count, ok ? "ok  " : "FAIL", task.id, ms,
                    (after["footprint_mb"] as? Double) ?? -1,
                    (after["available_mb"] as? Double) ?? -1,
                    (after["thermal"] as? String) ?? "?"))
            _ = before
        }

        let n = Double(tasks.count)
        let meanS = wallTotal / n
        // The headline the project actually needs. The sliding window in tools/stream.py
        // steps every 0.4 s; this says how far from that the phone is.
        await log.add(
            String(
                format:
                    "STATS model=%@ n=%d load_s=%.1f mean_s=%.2f windows_per_s=%.3f "
                    + "peak_fp_mb=%.0f fail=%d thermal=%@ battery=%.0f",
                modelID, tasks.count, loadS, meanS, 1.0 / meanS, peakFootprint, failures,
                Probe.thermal(), Probe.batteryPercent()))

        write(results: results, model: modelID, log: log)
    }

    // MARK: - helpers

    private static func loadImage(named: String) -> CGImage? {
        let stem = (named as NSString).deletingPathExtension
        let ext = (named as NSString).pathExtension
        guard let url = Bundle.main.url(forResource: stem, withExtension: ext.isEmpty ? "jpg" : ext)
        else { return nil }
        guard let src = CGImageSourceCreateWithURL(url as CFURL, nil) else { return nil }
        return CGImageSourceCreateImageAtIndex(src, 0, nil)
    }

    private static func seconds(since start: SuspendingClock.Instant) -> Double {
        let e = (SuspendingClock.now - start).components
        return Double(e.seconds) + Double(e.attoseconds) / 1e18
    }

    private static func jsonSnapshot(_ d: [String: Any]) -> String {
        guard let data = try? JSONSerialization.data(withJSONObject: d, options: [.sortedKeys])
        else { return "{}" }
        return String(decoding: data, as: UTF8.self)
    }

    private static func deviceModel() -> String {
        var sysinfo = utsname()
        uname(&sysinfo)
        return withUnsafePointer(to: &sysinfo.machine) {
            $0.withMemoryRebound(to: CChar.self, capacity: 1) { String(cString: $0) }
        }
    }

    /// One JSON object per line, same as the Mac runner, so tools/ can read either without
    /// knowing which machine produced it. Pulled off the device with
    /// `xcrun devicectl device copy from`.
    private static func write(results: [[String: Any]], model: String, log: BenchLog) {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let out = docs.appendingPathComponent("\(model).jsonl")
        var text = ""
        for r in results {
            if let d = try? JSONSerialization.data(withJSONObject: r, options: [.sortedKeys]) {
                text += String(decoding: d, as: UTF8.self) + "\n"
            }
        }
        do {
            try text.write(to: out, atomically: true, encoding: .utf8)
            Probe.log.notice("wrote \(out.path, privacy: .public)")
            print("RESULTS \(out.path)")
        } catch {
            print("ERROR writing results: \(error)")
        }
        _ = log
    }
}
