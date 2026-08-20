// PersonGate.swift — decides which frames are allowed to reach the disk.
//
// The requirement is not "blur people afterwards", it is "do not record them in the first
// place", so that being asked at the time has a true answer. That changes the design: the
// gate has to be in front of the writer, and it has to be wrong in only one direction.
//
// Three things make it leak if they are skipped, and the first is the one that is easy to
// miss:
//
//   PRE-ROLL.  The detector fires on the frame where a person becomes detectable, not the
//              frame where they entered. Someone walking in from the edge, small, motion-
//              blurred, is under threshold for several frames first. If frames go straight
//              to the writer, those frames are already on disk when the detector catches
//              up. So frames are held in a ring buffer for `holdBack` and only committed
//              once that long has passed with nothing seen — a detection retroactively
//              discards everything still in the buffer.
//
//   HOLD-OFF.  A detector on a moving camera flickers: present, absent, present across
//              consecutive frames of the same person. Committing during the gaps writes
//              them anyway. So the gate stays shut for `cooldown` after the LAST sighting,
//              not the first.
//
//   THRESHOLD. A missed person is the harmful error and a false alarm merely costs
//              footage, so the score threshold is deliberately far below the 0.5 a
//              detector is usually run at. Recall is the whole job here; precision is not.
//
// The type is pure and has no camera, no writer and no model in it, because the only way
// to be sure of a rule like this is to be able to read it in one screen.

import CoreAIKitVision
import CoreVideo
import Foundation

/// What the gate decided about one frame.
enum GateDecision {
    /// A person is in this frame. Nothing is written, and the buffered pre-roll was dropped.
    case blocked(count: Int)
    /// No person, but too soon after the last sighting. Nothing is buffered either.
    case cooling(secondsLeft: Double)
    /// Safe. `commit` are frames that have now survived the full hold-back and may be
    /// written; they are older than the frame just seen.
    case open(commit: [GatedFrame])
}

/// `@unchecked Sendable` for the same reason the kit's own `CameraFrame` is: `CVPixelBuffer`
/// is not marked Sendable, but the capture side never touches a buffer again once it has
/// been handed over, and everything downstream — the gate, the writer, the sheet — only
/// reads. The buffer is retained, so its contents stay valid after the capture callback
/// returns; holding it costs a slot in the capture pool, which shows up as dropped frames
/// rather than as torn ones.
struct GatedFrame: @unchecked Sendable {
    let pixelBuffer: CVPixelBuffer
    let time: Double  // seconds since the walk started
}

/// COCO class 1 is `person`. Matching on the id rather than the label string avoids the
/// case where a detector spells it differently and the gate silently never fires.
let personClassID = 1

struct PersonGate {
    /// Below the usual 0.5 on purpose. See THRESHOLD above.
    var scoreThreshold: Float = 0.20
    /// How long a frame waits in the buffer before it is allowed onto disk.
    var holdBack: Double = 2.0
    /// How long the gate stays shut after the last person was seen.
    var cooldown: Double = 3.0

    private var buffer: [GatedFrame] = []
    private var lastPersonAt: Double?

    /// Frames dropped so far, for the on-screen counter — a walk that discarded 40% of
    /// itself is worth knowing about before the walk is over, not after.
    private(set) var droppedCount = 0
    private(set) var lastSawPersonAgo: Double?

    mutating func offer(
        frame: CVPixelBuffer, at time: Double, detections: [Detection]
    ) -> GateDecision {
        let people = detections.filter {
            $0.classID == personClassID && $0.score >= scoreThreshold
        }
        if !people.isEmpty {
            lastPersonAt = time
            lastSawPersonAgo = 0
            let dropped = buffer.count
            droppedCount += dropped + 1
            buffer.removeAll(keepingCapacity: true)
            return .blocked(count: people.count)
        }
        if let last = lastPersonAt {
            lastSawPersonAgo = time - last
            let waited = time - last
            if waited < cooldown {
                // Not buffered. Buffering here and committing later would mean the frames
                // taken while the gate was shut eventually reach disk anyway.
                droppedCount += 1
                return .cooling(secondsLeft: cooldown - waited)
            }
        }
        buffer.append(GatedFrame(pixelBuffer: frame, time: time))
        var commit: [GatedFrame] = []
        while let first = buffer.first, time - first.time >= holdBack {
            commit.append(buffer.removeFirst())
        }
        return .open(commit: commit)
    }

    /// Treat this instant as if a person had been seen: drops the pre-roll and starts the
    /// hold-off. Called when the detector could not rule on a frame at all — an unreadable
    /// frame is not evidence of an empty street.
    mutating func forceBlock(at time: Double) {
        lastPersonAt = time
        droppedCount += buffer.count + 1
        buffer.removeAll(keepingCapacity: true)
    }

    /// Anything still in the buffer when the walk stops has NOT served its hold-back, so it
    /// is discarded rather than flushed. Losing the last two seconds of a walk is the
    /// correct trade for never writing a frame that was not cleared.
    mutating func discardPending() -> Int {
        let n = buffer.count
        droppedCount += n
        buffer.removeAll()
        return n
    }
}
