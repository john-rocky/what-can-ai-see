// swift-tools-version: 6.0
import PackageDescription

// wcas-run — the batch harness. `vlchat-cli` loads the model, answers one prompt and
// exits; at ~2-5 minutes of load for a 3B that makes a few hundred benchmark runs
// impossible. This loads the model ONCE and streams a task file through it, which is
// the only reason the benchmark is affordable at all.
//
//   swift build -c release
//   .build/release/wcas-run --model lfm2.5-vl-3b --tasks tasks.jsonl --out results.jsonl
//
// Requires the Xcode 27 beta toolchain (the CoreAI framework is not in the release SDK):
//   DEVELOPER_DIR=/Applications/Xcode-27.0.0-Beta.5.app/Contents/Developer swift build -c release
let package = Package(
    name: "wcas",
    platforms: [.macOS("27.0")],
    dependencies: [
        .package(path: "../../coreai-kit")
    ],
    targets: [
        .executableTarget(
            name: "wcas-run",
            dependencies: [.product(name: "CoreAIKit", package: "coreai-kit")]
        ),
        // The detector half of the classical baseline. Same load-once-stream-many shape
        // as wcas-run, for the same reason.
        .executableTarget(
            name: "wcas-detect",
            dependencies: [.product(name: "CoreAIKitVision", package: "coreai-kit")]
        )
    ]
)
