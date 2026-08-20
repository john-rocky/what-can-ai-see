// wcas-run — load one VLM, stream a task file through it, write one JSON result per line.
//
// Why this exists: `vlchat-cli` is a one-shot. It loads the decoder + vision tower, answers,
// and exits. Load dominates — minutes for a 3B — so a benchmark of a few hundred (clip,
// encoding, question) cells built on it would spend ~99% of its wall clock loading the same
// weights over and over. Here the model loads once and every task after that costs only
// prefill + decode.
//
// Isolation: each task gets a FRESH LanguageModelSession. A held session would carry the
// previous clip's transcript into the next one, and a model that answered "yes" about clip A
// would be answering about clip A's text when asked about clip B. Freshness per task is what
// makes the cells independent.
//
// Task line:   {"id":"...","image":"/abs/path.jpg","prompt":"..."}
// Result line: {"id":"...","ok":true,"answer":"...","ms":1234,"prompt_ms":...,"model":"..."}
//
// Progress and errors go to stderr; stdout carries only the JSONL, so the harness can pipe it.

import CoreAIKit
import Foundation
import FoundationModels

// MARK: - IO helpers

func err(_ s: String, terminator: String = "\n") {
    FileHandle.standardError.write(Data((s + terminator).utf8))
}

func die(_ s: String) -> Never {
    err("wcas-run: \(s)")
    exit(1)
}

struct Task: Decodable {
    let id: String
    let image: String
    let prompt: String
}

// MARK: - Arguments

let usage = """
    usage: wcas-run --model <catalog-id> --tasks <file.jsonl> --out <file.jsonl>
                    [--max-tokens N] [--temperature F] [--resume]
                    [--greedy] [--seed N]
    """

var modelID: String?
var tasksPath: String?
var outPath: String?
var maxTokens = 96
var temperature: Double?
var resume = false
// Sampling. The default was whatever the runtime picks, which is a SAMPLER — so every
// figure in this repo was measured from one draw of a distribution and re-running the
// same window could change the answer. Measured on the phone across three passes of the
// same 27 windows: content-word overlap between runs had a median of 0.21, and one
// judgment window named the event in 1 of 3 runs. `--greedy` takes the argmax instead,
// which removes the variance rather than pinning it to one arbitrary draw.
var greedy = false
var seed: UInt64?

var argv = CommandLine.arguments.dropFirst()
while let a = argv.popFirst() {
    switch a {
    case "--model": modelID = argv.popFirst()
    case "--tasks": tasksPath = argv.popFirst()
    case "--out": outPath = argv.popFirst()
    case "--max-tokens": maxTokens = Int(argv.popFirst() ?? "") ?? maxTokens
    case "--temperature": temperature = Double(argv.popFirst() ?? "")
    case "--resume": resume = true
    case "--greedy": greedy = true
    case "--seed": seed = UInt64(argv.popFirst() ?? "")
    default: die("unknown argument \(a)\n\(usage)")
    }
}

guard let modelID, let tasksPath, let outPath else { die(usage) }

// MARK: - Load tasks

let taskData: Data
do {
    taskData = try Data(contentsOf: URL(fileURLWithPath: tasksPath))
} catch {
    die("cannot read \(tasksPath): \(error.localizedDescription)")
}

let decoder = JSONDecoder()
var tasks: [Task] = []
for (n, line) in String(decoding: taskData, as: UTF8.self)
    .split(separator: "\n", omittingEmptySubsequences: true).enumerated()
{
    do {
        tasks.append(try decoder.decode(Task.self, from: Data(line.utf8)))
    } catch {
        die("task line \(n + 1) is not a valid task: \(error)")
    }
}
guard !tasks.isEmpty else { die("no tasks in \(tasksPath)") }

// --resume: skip ids already present in the output. A benchmark run that dies at task 180 of
// 200 should not re-pay for the 179 that succeeded.
var done = Set<String>()
let outURL = URL(fileURLWithPath: outPath)
if resume, let existing = try? String(contentsOf: outURL, encoding: .utf8) {
    for line in existing.split(separator: "\n") {
        if let obj = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
            let id = obj["id"] as? String
        {
            done.insert(id)
        }
    }
    err("resume: \(done.count) already done")
}
let pending = tasks.filter { !done.contains($0.id) }
guard !pending.isEmpty else {
    err("nothing to do — all \(tasks.count) tasks already in \(outPath)")
    exit(0)
}

// MARK: - Load the model, once

err("loading \(modelID) …")
let loadStart = Date()
let vlm: KitVisionModel
do {
    vlm = try await KitVisionModel(
        catalog: modelID,
        downloadProgress: { p in
            err(String(format: "\rdownloading %3.0f%%", p.fraction * 100),
                terminator: p.fraction < 1 ? "" : "\n")
        })
} catch {
    die("cannot load \(modelID): \(error.localizedDescription)")
}
let loadSeconds = Date().timeIntervalSince(loadStart)
err(String(format: "loaded in %.1fs — %d task(s)", loadSeconds, pending.count))

// MARK: - Run

// createFile(atPath:contents:) TRUNCATES an existing file — it is not a no-op, which
// an earlier version of this line claimed. Combined with --resume (which reads the
// existing ids first, then opened the sink) it silently destroyed exactly the results
// it was resuming from: the file came back holding only the newly-run tasks. Create it
// only when it is genuinely absent.
if !FileManager.default.fileExists(atPath: outPath) {
    FileManager.default.createFile(atPath: outPath, contents: nil)
}
guard let sink = FileHandle(forWritingAtPath: outPath) else { die("cannot write \(outPath)") }
sink.seekToEndOfFile()

// A seed only means anything for a sampler, so --seed implies top-k sampling; --greedy
// wins if both are given, because "deterministic" is the stronger request.
let sampling: GenerationOptions.SamplingMode? =
    greedy ? .greedy : (seed.map { .random(top: 50, seed: $0) })
let options = GenerationOptions(
    samplingMode: sampling, temperature: temperature, maximumResponseTokens: maxTokens)
if let sampling { err("sampling: \(sampling.kind)") }

func emit(_ payload: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys])
    else { return }
    sink.write(data)
    sink.write(Data("\n".utf8))
}

var failures = 0
for (i, task) in pending.enumerated() {
    let started = Date()
    var payload: [String: Any] = [
        "id": task.id, "model": modelID, "max_tokens": maxTokens,
        "load_s": (loadSeconds * 1000).rounded() / 1000,
    ]
    if let temperature { payload["temperature"] = temperature }

    do {
        let image = try ImageFile.load(URL(fileURLWithPath: task.image))
        // Fresh session per task — see the isolation note at the top.
        let session = LanguageModelSession(model: vlm)
        let reply = try await session.respond(
            to: Prompt {
                task.prompt
                Attachment(image.cgImage, orientation: image.orientation)
            }, options: options)
        payload["ok"] = true
        payload["answer"] = reply.content
    } catch {
        failures += 1
        payload["ok"] = false
        payload["error"] = "\(error)"
    }
    payload["ms"] = Int(Date().timeIntervalSince(started) * 1000)
    emit(payload)

    let ok = (payload["ok"] as? Bool) ?? false
    err(String(format: "[%3d/%3d] %@ %@ (%dms)", i + 1, pending.count,
               ok ? "ok  " : "FAIL", task.id, payload["ms"] as? Int ?? 0))
}

try? sink.close()
err("done — \(pending.count - failures)/\(pending.count) ok, output \(outPath)")
exit(failures > 0 && failures == pending.count ? 1 : 0)
