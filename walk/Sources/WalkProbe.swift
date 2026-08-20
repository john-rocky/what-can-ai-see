// WalkProbe.swift — what the phone is doing to itself during a walk.
//
// Same three probes as the bench app's Probe.swift, under a different name so the two
// targets can be built into one workspace later without a symbol clash. On a walk the
// thermal and battery numbers stop being background detail: a thirty-minute walk IS the
// always-on monitoring scenario, and whether the phone survives it is the answer.
//
// A tokens/second figure is not the number a person deploying this needs. Three others
// decide whether a thing ships:
//
//   footprint   `phys_footprint` is what jetsam accounts. A 5.5 GB model either fits
//               under this process's limit or the app is killed with no error text —
//               the log simply stops. Recording it every task turns that silence into
//               a number.
//   headroom    `os_proc_available_memory()` is the MB left before the kill. Logging it
//               next to the footprint is what distinguishes "it fits" from "it fits on
//               a phone that has just been rebooted with nothing else open".
//   thermal     The Mac numbers are steady-state because a Mac Studio has a fan. A phone
//               asked to run a VLM continuously will throttle, and "always-on monitoring"
//               is exactly the use case where that matters. A benchmark that stops after
//               ten windows never sees it.
//
// All three are cheap to read, so they are read per task rather than at the ends: the
// interesting shape is the curve, and a before/after pair cannot show a curve.
//
// The target is iOS-only, but every platform-specific call is still guarded. Without the
// guards the file will not typecheck in an editor pointed at the macOS SDK, which makes
// every unrelated error in it invisible.

import Foundation
import os

#if canImport(Darwin)
    import Darwin
#endif
#if canImport(UIKit)
    import UIKit
#endif

enum WalkProbe {
    static let log = Logger(subsystem: "com.whatcanaisee.walk", category: "bench")

    /// `phys_footprint` in MB — the figure jetsam accounts per process.
    static func footprintMB() -> Double {
        var info = task_vm_info_data_t()
        var count = mach_msg_type_number_t(
            MemoryLayout<task_vm_info_data_t>.size / MemoryLayout<natural_t>.size)
        let kr = withUnsafeMutablePointer(to: &info) { ptr -> kern_return_t in
            ptr.withMemoryRebound(to: integer_t.self, capacity: Int(count)) {
                task_info(mach_task_self_, task_flavor_t(TASK_VM_INFO), $0, &count)
            }
        }
        return kr == KERN_SUCCESS ? Double(info.phys_footprint) / 1_048_576 : -1
    }

    /// MB left before this process hits its jetsam limit; -1 where the OS has no such notion.
    static func availableMB() -> Double {
        #if os(iOS)
            return Double(os_proc_available_memory()) / 1_048_576
        #else
            return -1
        #endif
    }

    /// nominal / fair / serious / critical. `serious` is where the CPU and GPU clocks are
    /// already being pulled down, so a throughput number taken after that point describes a
    /// throttled phone and has to be labelled as one.
    static func thermal() -> String {
        switch ProcessInfo.processInfo.thermalState {
        case .nominal: return "nominal"
        case .fair: return "fair"
        case .serious: return "serious"
        case .critical: return "critical"
        @unknown default: return "unknown"
        }
    }

    /// Battery percentage, or -1 when the device will not report it. Monitoring runs are
    /// judged on power as much as speed, and a run that drained 18% in four minutes is a
    /// finding whether or not it was fast.
    static func batteryPercent() -> Double {
        #if canImport(UIKit)
            UIDevice.current.isBatteryMonitoringEnabled = true
            let level = UIDevice.current.batteryLevel
            return level < 0 ? -1 : Double(level) * 100
        #else
            return -1
        #endif
    }

    static func snapshot() -> [String: Any] {
        [
            "footprint_mb": (footprintMB() * 10).rounded() / 10,
            "available_mb": (availableMB() * 10).rounded() / 10,
            "thermal": thermal(),
            "battery_pct": (batteryPercent() * 10).rounded() / 10,
        ]
    }
}
