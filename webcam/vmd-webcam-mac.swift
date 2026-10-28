// vmd-webcam for macOS: the player's real webcam as raw YUYV frames on stdout, for the mod to pass into the PC's Linux.
//   vmd-webcam <width> <height>      frames of exactly width*height*2 bytes, as fast as the camera gives them
//   vmd-webcam --list                the cameras there are (asks no permission)
// macOS asks once whether Minecraft may use the camera; it runs only while a Linux program has the webcam open.
import AVFoundation
import Foundation

let args = CommandLine.arguments
let kinds: [AVCaptureDevice.DeviceType]
if #available(macOS 14.0, *) {
    kinds = [.builtInWideAngleCamera, .external]
} else {
    kinds = [.builtInWideAngleCamera, .externalUnknown]
}
let devices = AVCaptureDevice.DiscoverySession(deviceTypes: kinds, mediaType: .video, position: .unspecified).devices
if args.count > 1 && args[1] == "--list" {
    for d in devices { print(d.localizedName) }
    exit(0)
}
guard args.count == 3, let width = Int(args[1]), let height = Int(args[2]) else {
    FileHandle.standardError.write("usage: vmd-webcam <width> <height> | --list\n".data(using: .utf8)!)
    exit(2)
}
guard let device = AVCaptureDevice.default(for: .video) ?? devices.first else {
    FileHandle.standardError.write("no camera\n".data(using: .utf8)!)
    exit(1)
}

final class Frames: NSObject, AVCaptureVideoDataOutputSampleBufferDelegate {
    let width: Int, height: Int
    var frame: [UInt8]
    init(width: Int, height: Int) {
        self.width = width
        self.height = height
        frame = [UInt8](repeating: 0, count: width * height * 2)
    }

    func captureOutput(_ output: AVCaptureOutput, didOutput sample: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let image = CMSampleBufferGetImageBuffer(sample) else { return }
        CVPixelBufferLockBaseAddress(image, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(image, .readOnly) }
        guard let base = CVPixelBufferGetBaseAddress(image) else { return }
        let w = CVPixelBufferGetWidth(image), h = CVPixelBufferGetHeight(image), row = CVPixelBufferGetBytesPerRow(image)
        let src = base.assumingMemoryBound(to: UInt8.self)
        // the camera's picture scaled (nearest) to the size asked for, centre-cropped to keep its shape; pixels in pairs
        let scale = max(Double(width) / Double(w), Double(height) / Double(h))
        let x0 = (Double(w) - Double(width) / scale) / 2, y0 = (Double(h) - Double(height) / scale) / 2
        for y in 0..<height {
            let sy = min(h - 1, Int(y0 + Double(y) / scale))
            for x in stride(from: 0, to: width, by: 2) {
                let sx = min(w - 2, Int(x0 + Double(x) / scale)) & ~1
                let s = sy * row + sx * 2, d = (y * width + x) * 2
                frame[d] = src[s]; frame[d + 1] = src[s + 1]; frame[d + 2] = src[s + 2]; frame[d + 3] = src[s + 3]
            }
        }
        let ok = frame.withUnsafeBytes { buf -> Bool in
            var at = 0
            while at < buf.count {
                let n = write(1, buf.baseAddress! + at, buf.count - at)
                if n <= 0 { return false }
                at += n
            }
            return true
        }
        if !ok { exit(0) } // the mod closed the pipe: the webcam is no longer wanted
    }
}

let session = AVCaptureSession()
session.sessionPreset = .high
do {
    session.addInput(try AVCaptureDeviceInput(device: device))
} catch {
    FileHandle.standardError.write("camera refused: \(error.localizedDescription)\n".data(using: .utf8)!)
    exit(1)
}
let output = AVCaptureVideoDataOutput()
output.videoSettings = [kCVPixelBufferPixelFormatTypeKey as String: kCVPixelFormatType_422YpCbCr8_yuvs] // YUYV
output.alwaysDiscardsLateVideoFrames = true
let frames = Frames(width: width, height: height)
output.setSampleBufferDelegate(frames, queue: DispatchQueue(label: "vmd-webcam"))
session.addOutput(output)
signal(SIGPIPE, SIG_IGN)
FileHandle.standardError.write("camera: \(device.localizedName)\n".data(using: .utf8)!)
session.startRunning()
dispatchMain()
