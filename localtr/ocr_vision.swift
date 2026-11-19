// OCR helper using Apple's Vision framework (fully on-device).
// usage: ocr <image> <normalized_png_out> [lang1,lang2,...]
// Prints JSON: {"width":W,"height":H,"lines":[{"text":..,"conf":..,"box":[x0,y0,x1,y1]}]}
// Boxes are in pixels of the normalized (EXIF-orientation-corrected) PNG, origin top-left.
import CoreImage
import Foundation
import ImageIO
import UniformTypeIdentifiers
import Vision

func fail(_ msg: String) -> Never {
    let obj: [String: Any] = ["error": msg]
    let data = try! JSONSerialization.data(withJSONObject: obj)
    print(String(data: data, encoding: .utf8)!)
    exit(1)
}

let args = CommandLine.arguments
if args.count < 3 { fail("usage: ocr <image> <png_out> [langs]") }
let inURL = URL(fileURLWithPath: args[1])
let outURL = URL(fileURLWithPath: args[2])
let langs = args.count > 3 ? args[3].split(separator: ",").map(String.init) : ["en-US", "zh-Hans"]

guard let src = CGImageSourceCreateWithURL(inURL as CFURL, nil),
      let raw = CGImageSourceCreateImageAtIndex(src, 0, nil) else { fail("cannot open image") }
var orientation: UInt32 = 1
if let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any],
   let o = props[kCGImagePropertyOrientation] as? UInt32 { orientation = o }

// Normalize orientation so OCR boxes and the rendered image share one coordinate system.
var image = raw
if orientation != 1, let cgo = CGImagePropertyOrientation(rawValue: orientation) {
    let ci = CIImage(cgImage: raw).oriented(cgo)
    let ctx = CIContext()
    if let c = ctx.createCGImage(ci, from: ci.extent) { image = c }
}
guard let dest = CGImageDestinationCreateWithURL(outURL as CFURL, UTType.png.identifier as CFString, 1, nil) else {
    fail("cannot write png")
}
CGImageDestinationAddImage(dest, image, nil)
CGImageDestinationFinalize(dest)

let W = Double(image.width), H = Double(image.height)
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
let supported = (try? request.supportedRecognitionLanguages()) ?? []
let use = langs.filter { supported.contains($0) }
if !use.isEmpty { request.recognitionLanguages = use }
if #available(macOS 13.0, *) { request.automaticallyDetectsLanguage = true }

let handler = VNImageRequestHandler(cgImage: image, options: [:])
do { try handler.perform([request]) } catch { fail("vision failed: \(error)") }

var lines: [[String: Any]] = []
for obs in request.results ?? [] {
    guard let cand = obs.topCandidates(1).first else { continue }
    let bb = obs.boundingBox
    let box = [bb.minX * W, (1 - bb.maxY) * H, bb.maxX * W, (1 - bb.minY) * H]
    lines.append(["text": cand.string, "conf": Double(cand.confidence), "box": box])
}
let result: [String: Any] = ["width": Int(W), "height": Int(H), "lines": lines]
let data = try! JSONSerialization.data(withJSONObject: result)
print(String(data: data, encoding: .utf8)!)
