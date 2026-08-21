// Translator.swift — the caption in Japanese, and what that costs.
//
// The question is whether translating breaks real time. Worth answering with a number rather
// than a guess: the VLM already puts the caption 2.2-3.1 s behind the world (measured on this
// phone), so a translator taking tens of milliseconds is invisible and one taking seconds
// doubles it.
//
// The shape is dictated by `TranslationSession` not being Sendable, and by Swift 6's region
// isolation being stricter than it first appears. Three attempts failed before this one:
// storing the session in an actor, passing it to a method, and looping over it while awaiting
// a @MainActor property in between. All three were rejected, and correctly — once a value
// from another isolation domain is awaited, the session in hand counts as sent.
//
// So nothing crosses. The session stays inside `.translationTask`'s closure, and the only
// thing shared between that closure and the caption task is this mailbox: two Strings and a
// lock. Both sides touch plain data, never each other's isolation.
//
// `.lowLatency` over `.highFidelity` on purpose. A caption is read once, at a glance, while
// walking; it is not a document.
//
// Failure is never fatal. No downloaded language pair, a session that never arrives, a throw
// of any kind — all fall back to the English text. A walk that stopped captioning because a
// translation failed would be worse than one that showed the original.

import Foundation
import os

/// A one-slot mailbox between the caption task and the translation closure.
///
/// `@unchecked Sendable` over an `NSLock`: every field is a String, a Double or a Bool, and
/// every access is inside the lock. An actor would be the idiomatic choice and is what the
/// first attempt used — but awaiting an actor from the translation closure is exactly the
/// hop that makes the compiler treat the session as sent.
final class Translator: @unchecked Sendable {
    private let lock = NSLock()
    private let log = Logger(subsystem: "com.whatcanaisee.walk", category: "translate")

    private var request: String?
    private var answers: [String: String] = [:]
    private var samples: [Double] = []
    private var _ready = false
    private var _medianMs: Double = 0

    var isReady: Bool { lock.withLock { _ready } }

    /// Rolling median in milliseconds — the number that answers whether this is affordable.
    /// Shown beside the caption's own lag so the two costs are compared, not conflated.
    var medianMs: Double { lock.withLock { _medianMs } }

    func setReady(_ v: Bool) { lock.withLock { _ready = v } }

    // MARK: - caption side

    /// Posts `text` and waits for the closure to answer it. Falls straight through to the
    /// English when no session has arrived, so flipping the toggle before the framework is
    /// ready degrades to a passthrough rather than a hang.
    ///
    /// Polling rather than a continuation: a continuation handed across these two contexts
    /// is one more non-Sendable value to reason about, and the wait here is milliseconds
    /// against a caption that is already seconds old.
    func translate(_ text: String) async -> String {
        guard isReady, !text.isEmpty else { return text }
        if let hit = (lock.withLock { answers[text] }) { return hit }
        lock.withLock { request = text }
        for _ in 0..<200 {  // 4 s ceiling; a translator slower than that is not usable here
            try? await Task.sleep(for: .milliseconds(20))
            if let hit = (lock.withLock { answers[text] }) { return hit }
        }
        log.error("translate timed out")
        lock.withLock { request = nil }
        return text
    }

    // MARK: - closure side

    /// What is waiting, if anything.
    func take() -> String? {
        lock.withLock {
            let r = request
            request = nil
            return r
        }
    }

    func deliver(source: String, translated: String, ms: Double, failed: Bool) {
        lock.withLock {
            if answers.count > 40 { answers.removeAll(keepingCapacity: true) }
            answers[source] = translated
            guard !failed else { return }
            samples.append(ms)
            if samples.count > 20 { samples.removeFirst() }
            _medianMs = samples.sorted()[samples.count / 2]
        }
        if !failed {
            print(String(format: "TRANSLATE %.0fms  %@", ms, String(translated.prefix(70))))
        }
    }
}
