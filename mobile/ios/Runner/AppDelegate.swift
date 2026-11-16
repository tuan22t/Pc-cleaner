import CryptoKit
import Flutter
import Photos
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate, FlutterImplicitEngineDelegate {
  private var media: MediaBridge?

  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  func didInitializeImplicitFlutterEngine(_ engineBridge: FlutterImplicitEngineBridge) {
    GeneratedPluginRegistrant.register(with: engineBridge.pluginRegistry)
    if let registrar = engineBridge.pluginRegistry.registrar(forPlugin: "PcCleanerMedia") {
      media = MediaBridge(messenger: registrar.messenger())
    }
  }
}

/// The bridge between the Flutter UI and the iPhone photo library
/// (same channel and method names as MainActivity.kt on Android).
///
/// Safety: nothing is deleted silently. Removal uses
/// PHAssetChangeRequest.deleteAssets, which shows iOS's own confirmation and
/// moves the items to "Recently Deleted" for 30 days, where the user can
/// restore them in the Photos app. iCloud downloads are never requested:
/// the app only looks at what is already on the phone.
final class MediaBridge {
  private let channel: FlutterMethodChannel
  private let work = DispatchQueue(label: "pccleaner.media", qos: .userInitiated, attributes: .concurrent)
  private let images = PHImageManager.default()

  init(messenger: FlutterBinaryMessenger) {
    channel = FlutterMethodChannel(name: "pccleaner/media", binaryMessenger: messenger)
    channel.setMethodCallHandler { [weak self] call, result in
      self?.handle(call, result)
    }
  }

  private func reply(_ result: @escaping FlutterResult, _ value: Any?) {
    DispatchQueue.main.async { result(value) }
  }

  private func handle(_ call: FlutterMethodCall, _ result: @escaping FlutterResult) {
    let args = call.arguments as? [String: Any] ?? [:]
    switch call.method {
    case "permissionState":
      result(permissionState())
    case "requestPermission":
      PHPhotoLibrary.requestAuthorization(for: .readWrite) { _ in
        self.reply(result, self.permissionState())
      }
    case "openSettings":
      if let url = URL(string: UIApplication.openSettingsURLString) {
        UIApplication.shared.open(url)
      }
      result(nil)
    case "storage":
      result(storage())
    case "listAll":
      work.async { self.reply(result, self.listAll()) }
    case "thumbnail":
      guard let asset = asset(args) else { return result(nil) }
      let side = args["side"] as? Int ?? 256
      loadImage(asset, side: side) { image in
        let data = image?.jpegData(compressionQuality: 0.85)
        self.reply(result, data.map { FlutterStandardTypedData(bytes: $0) })
      }
    case "grey":
      guard let asset = asset(args) else { return result(nil) }
      let side = args["side"] as? Int ?? 256
      loadImage(asset, side: side) { image in
        self.work.async { self.reply(result, image.flatMap { self.grey($0, side: side) }) }
      }
    case "contentHash":
      guard let asset = asset(args) else { return result(nil) }
      md5(asset) { self.reply(result, $0) }
    case "trash":
      let ids = refs(args).map { $0.id }
      let assets = PHAsset.fetchAssets(withLocalIdentifiers: ids, options: nil)
      if assets.count == 0 { return result(true) }
      PHPhotoLibrary.shared().performChanges({
        PHAssetChangeRequest.deleteAssets(assets)
      }) { ok, _ in self.reply(result, ok) }
    case "restore":
      // iOS has no public way to take items out of "Recently Deleted";
      // the app sends the user to the Photos app instead.
      result(false)
    case "stillTrashed":
      // Deleted items vanish from the library; the app cannot see inside
      // "Recently Deleted", so "not in the library" counts as "in the trash"
      // (the Dart side stops claiming that after 30 days).
      let r = refs(args)
      let found = PHAsset.fetchAssets(withLocalIdentifiers: r.map { $0.id }, options: nil)
      var present = Set<String>()
      found.enumerateObjects { a, _, _ in present.insert(a.localIdentifier) }
      result(r.filter { !present.contains($0.id) }.map { ["id": $0.id, "kind": $0.kind, "expires": NSNull()] })
    case "open", "openTrash":
      if let url = URL(string: "photos-redirect://") {
        UIApplication.shared.open(url)
      }
      result(true)
    default:
      result(FlutterMethodNotImplemented)
    }
  }

  // MARK: - permission and storage

  private func permissionState() -> String {
    switch PHPhotoLibrary.authorizationStatus(for: .readWrite) {
    case .authorized: return "granted"
    case .limited: return "limited"
    default: return "denied"
    }
  }

  private func storage() -> [String: Int64] {
    let url = URL(fileURLWithPath: NSHomeDirectory())
    let keys: Set<URLResourceKey> = [.volumeTotalCapacityKey, .volumeAvailableCapacityForImportantUsageKey]
    let v = try? url.resourceValues(forKeys: keys)
    return [
      "total": Int64(v?.volumeTotalCapacity ?? 0),
      "free": v?.volumeAvailableCapacityForImportantUsage ?? 0,
    ]
  }

  // MARK: - listing

  private func refs(_ args: [String: Any]) -> [(id: String, kind: String)] {
    let items = args["items"] as? [[String: Any]] ?? []
    return items.compactMap { m in
      guard let id = m["id"] as? String else { return nil }
      return (id, m["kind"] as? String ?? "image")
    }
  }

  private func asset(_ args: [String: Any]) -> PHAsset? {
    guard let id = args["id"] as? String else { return nil }
    return PHAsset.fetchAssets(withLocalIdentifiers: [id], options: nil).firstObject
  }

  private func ms(_ d: Date?) -> Int64 {
    Int64(((d ?? Date(timeIntervalSince1970: 0)).timeIntervalSince1970 * 1000).rounded())
  }

  private func listAll() -> [[String: Any]] {
    let opts = PHFetchOptions()
    opts.includeAssetSourceTypes = [.typeUserLibrary]
    let all = PHAsset.fetchAssets(with: opts)
    var out: [[String: Any]] = []
    out.reserveCapacity(all.count)
    all.enumerateObjects { a, _, _ in
      guard a.mediaType == .image || a.mediaType == .video else { return }
      let resources = PHAssetResource.assetResources(for: a)
      // Space the item takes: every stored file (photo, Live Photo video,
      // edited version).
      var size: Int64 = 0
      for r in resources {
        if let n = r.value(forKey: "fileSize") as? CLong { size += Int64(n) }
      }
      if size == 0 { size = Int64(max(1, a.pixelWidth * a.pixelHeight / 4)) }
      let primary = resources.first { $0.type == .photo || $0.type == .video } ?? resources.first
      out.append([
        "id": a.localIdentifier,
        "kind": a.mediaType == .video ? "video" : "image",
        "size": size,
        "width": a.pixelWidth,
        "height": a.pixelHeight,
        "created": self.ms(a.creationDate ?? a.modificationDate),
        "modified": self.ms(a.modificationDate ?? a.creationDate),
        "title": primary?.originalFilename ?? "",
        "path": "",
        "bucket": "",
        "favorite": a.isFavorite,
        "screenshot": a.mediaSubtypes.contains(.photoScreenshot),
        "duration": Int64((a.duration * 1000).rounded()),
      ])
    }
    return out
  }

  // MARK: - thumbnails and analysis input

  /// Local image only (no iCloud download), best quality available.
  private func loadImage(_ asset: PHAsset, side: Int, done: @escaping (UIImage?) -> Void) {
    let o = PHImageRequestOptions()
    o.isNetworkAccessAllowed = false
    o.deliveryMode = .highQualityFormat
    o.resizeMode = .fast
    let target = CGSize(width: side, height: side)
    images.requestImage(for: asset, targetSize: target, contentMode: .aspectFit, options: o) { image, _ in
      if let image = image {
        done(image)
        return
      }
      let f = PHImageRequestOptions()
      f.isNetworkAccessAllowed = false
      f.deliveryMode = .fastFormat
      self.images.requestImage(for: asset, targetSize: target, contentMode: .aspectFit, options: f) { img, _ in
        done(img)
      }
    }
  }

  /// Grey pixels with the longest side exactly `side`, so sharpness values
  /// are comparable between photos (same as the Android version).
  private func grey(_ image: UIImage, side: Int) -> [String: Any]? {
    let w = image.size.width * image.scale, h = image.size.height * image.scale
    guard w > 0, h > 0 else { return nil }
    let s = CGFloat(side) / max(w, h)
    let W = max(1, Int((w * s).rounded(.down))), H = max(1, Int((h * s).rounded(.down)))
    let fmt = UIGraphicsImageRendererFormat()
    fmt.scale = 1
    fmt.opaque = true
    let upright = UIGraphicsImageRenderer(size: CGSize(width: W, height: H), format: fmt).image { _ in
      image.draw(in: CGRect(x: 0, y: 0, width: W, height: H))
    }
    guard let cg = upright.cgImage,
      let ctx = CGContext(
        data: nil, width: W, height: H, bitsPerComponent: 8, bytesPerRow: W,
        space: CGColorSpaceCreateDeviceGray(), bitmapInfo: CGImageAlphaInfo.none.rawValue)
    else { return nil }
    ctx.interpolationQuality = .high
    ctx.draw(cg, in: CGRect(x: 0, y: 0, width: W, height: H))
    guard let p = ctx.data else { return nil }
    let data = Data(bytes: p, count: W * H)
    return ["w": W, "h": H, "px": FlutterStandardTypedData(bytes: data)]
  }

  private func md5(_ asset: PHAsset, done: @escaping (String?) -> Void) {
    let resources = PHAssetResource.assetResources(for: asset)
    guard let r = resources.first(where: { $0.type == .photo || $0.type == .video }) ?? resources.first else {
      return done(nil)
    }
    let o = PHAssetResourceRequestOptions()
    o.isNetworkAccessAllowed = false
    let box = HashBox()
    PHAssetResourceManager.default().requestData(
      for: r, options: o,
      dataReceivedHandler: { data in box.hasher.update(data: data) },
      completionHandler: { error in
        if error != nil { return done(nil) }
        done(box.hasher.finalize().map { String(format: "%02x", $0) }.joined())
      })
  }
}

private final class HashBox {
  var hasher = Insecure.MD5()
}
