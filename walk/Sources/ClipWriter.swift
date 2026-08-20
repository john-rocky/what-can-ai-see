// ClipWriter.swift — writes the frames the gate cleared, and only those.
//
// Frames arrive out of real time: the gate holds each one for a couple of seconds before
// releasing it, and it drops whole stretches when a person appears. So the writer cannot
// assume a steady clock or a contiguous stream. It gets an explicit presentation time per
// frame and writes them at their real timestamps, which means a gated stretch shows up in
// the finished file as a jump rather than as a silent splice — the recording is honest
// about the fact that something was skipped.
//
// One session, one file. Restarting the writer per gap would leave a directory of clips
// that have to be reassembled with the gaps guessed back in.

import AVFoundation
import Foundation

actor ClipWriter {
    private var writer: AVAssetWriter?
    private var input: AVAssetWriterInput?
    private var adaptor: AVAssetWriterInputPixelBufferAdaptor?
    private var started = false
    private(set) var framesWritten = 0
    let url: URL

    init(url: URL, width: Int, height: Int) throws {
        self.url = url
        try? FileManager.default.removeItem(at: url)
        let w = try AVAssetWriter(outputURL: url, fileType: .mov)
        let settings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                // The recording is corpus, not a deliverable: it gets re-measured later, so
                // it is worth keeping detail that a social-media bitrate would throw away.
                AVVideoAverageBitRateKey: 8_000_000
            ],
        ]
        let i = AVAssetWriterInput(mediaType: .video, outputSettings: settings)
        i.expectsMediaDataInRealTime = false  // frames arrive delayed by the gate, not live
        let a = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: i,
            sourcePixelBufferAttributes: [
                kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_32BGRA,
                kCVPixelBufferWidthKey as String: width,
                kCVPixelBufferHeightKey as String: height,
            ])
        guard w.canAdd(i) else { throw NSError(domain: "walk", code: 2) }
        w.add(i)
        self.writer = w
        self.input = i
        self.adaptor = a
    }

    /// Takes the whole `GatedFrame` rather than its buffer: extracting the CVPixelBuffer at
    /// the call site sends a non-Sendable value across the actor boundary, which Swift 6
    /// rejects. The frame carries its own timestamp anyway — the gate released it out of
    /// real time, so a clock read here would be the wrong one.
    func append(_ frame: GatedFrame) {
        guard let writer, let input, let adaptor else { return }
        let buffer = frame.pixelBuffer
        let time = CMTime(seconds: frame.time, preferredTimescale: 600)
        if !started {
            writer.startWriting()
            writer.startSession(atSourceTime: time)
            started = true
        }
        // A writer input that is not ready has to be skipped rather than waited on: this is
        // called from the capture path, and blocking it stalls the camera and the detector
        // behind it. A dropped frame here costs one frame of the recording; a stall costs
        // the gate its timing.
        guard input.isReadyForMoreMediaData else { return }
        if adaptor.append(buffer, withPresentationTime: time) {
            framesWritten += 1
        }
    }

    func finish() async -> URL? {
        guard let writer, let input, started else { return nil }
        input.markAsFinished()
        await writer.finishWriting()
        return writer.status == .completed ? url : nil
    }
}
