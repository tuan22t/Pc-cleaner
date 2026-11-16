/// A made-up photo library for tests, the web preview and screenshots.
/// Nothing here reads or changes real files.
library;

import 'dart:math' as math;
import 'dart:typed_data';

import 'package:image/image.dart' as img;

import '../core/analysis.dart' show thumbSide;
import '../core/models.dart';
import 'native_media_source.dart' show GreySource, GreyThumb;
import 'media_source.dart';

class _Spec {
  _Spec(this.scene, {this.shift = 0, this.light = 0, this.blur = 0, this.dark = false, this.screen = false});
  final int scene;
  final int shift;
  final int light;
  final int blur;
  final bool dark;
  final bool screen;
}

class DemoMediaSource implements MediaSource, GreySource {
  DemoMediaSource({this.permission = PermissionState.granted, DateTime? now, this.platform = 'demo'})
      : now = now ?? DateTime(2026, 11, 14, 9) {
    _build();
  }

  PermissionState permission;

  /// 'ios' makes the demo behave like an iPhone (no restore from the app).
  @override
  final String platform;

  @override
  bool get canRestoreInApp => platform != 'ios';

  int openTrashCalls = 0;

  @override
  Future<void> openTrash() async => openTrashCalls++;
  final DateTime now;
  final List<MediaItem> _items = [];
  final Map<String, _Spec> _spec = {};
  final Map<String, img.Image> _pix = {};
  final Map<String, Uint8List> _png = {};
  final Map<String, String> _hash = {};
  final Set<String> _trashed = {};
  final Map<String, DateTime> _trashedAt = {};

  /// Ask the user before "trashing" (set by the UI to show a dialog
  /// standing in for Android's own confirmation). Null = accept.
  Future<bool> Function(int count)? confirm;

  void _add(String id, _Spec s, {
    required int size,
    required DateTime at,
    MediaKind kind = MediaKind.image,
    bool fav = false,
    int w = 4000,
    int h = 3000,
    int dur = 0,
    String bucket = 'Camera',
    String? hash,
  }) {
    _items.add(MediaItem(
      id: id,
      kind: kind,
      size: size,
      width: w,
      height: h,
      created: at,
      modified: at,
      isFavorite: fav,
      isScreenshot: s.screen,
      durationSec: dur,
      title: s.screen ? 'Screenshot_$id.png' : (kind == MediaKind.video ? 'VID_$id.mp4' : 'IMG_$id.jpg'),
      bucket: s.screen ? 'Screenshots' : bucket,
    ));
    _spec[id] = s;
    _hash[id] = hash ?? 'h$id';
  }

  void _build() {
    final r = math.Random(7);
    var n = 1000;
    String id() => '${n++}';
    // Burst shots and several takes of the same scene.
    for (var scene = 0; scene < 9; scene++) {
      final at = now.subtract(Duration(days: 3 + scene * 11, hours: scene));
      final takes = 2 + scene % 3;
      for (var t = 0; t < takes; t++) {
        _add(id(), _Spec(scene, shift: t, light: t * 3, blur: t == takes - 1 && scene.isEven ? 2 : 0),
            size: 2600000 + r.nextInt(1800000), at: at.add(Duration(seconds: t * 3)), fav: scene == 2 && t == 1);
      }
    }
    // Exact copies (e.g. saved again from Zalo / Messenger).
    for (var scene = 9; scene < 13; scene++) {
      final at = now.subtract(Duration(days: 40 + scene * 5));
      final size = 1800000 + r.nextInt(900000);
      _add(id(), _Spec(scene), size: size, at: at, w: 2048, h: 1536, hash: 'dup$scene');
      _add(id(), _Spec(scene), size: size, at: at.add(const Duration(days: 2)), w: 2048, h: 1536, bucket: 'Zalo', hash: 'dup$scene');
      if (scene == 9) {
        _add(id(), _Spec(scene), size: size, at: at.add(const Duration(days: 9)), w: 2048, h: 1536, bucket: 'Messenger', hash: 'dup$scene');
      }
    }
    // Ordinary unique photos.
    for (var scene = 13; scene < 40; scene++) {
      _add(id(), _Spec(scene), size: 2000000 + r.nextInt(3000000), at: now.subtract(Duration(days: scene * 9, hours: r.nextInt(20))));
    }
    // Blurry and pocket shots.
    for (var k = 0; k < 4; k++) {
      _add(id(), _Spec(40 + k, blur: 7), size: 1500000 + r.nextInt(500000), at: now.subtract(Duration(days: 20 + k * 30)));
    }
    _add(id(), _Spec(44, dark: true), size: 900000, at: now.subtract(const Duration(days: 75)));
    _add(id(), _Spec(45, dark: true), size: 850000, at: now.subtract(const Duration(days: 130)));
    // Screenshots across several months.
    for (var k = 0; k < 16; k++) {
      _add(id(), _Spec(60 + k, screen: true), size: 300000 + r.nextInt(500000), w: 1080, h: 2400,
          at: now.subtract(Duration(days: k * 19 + 2, hours: k)));
    }
    // Videos.
    const vids = [(1350, 412), (820, 251), (640, 190), (410, 128), (95, 31), (30, 12)];
    for (var k = 0; k < vids.length; k++) {
      _add(id(), _Spec(80 + k), kind: MediaKind.video, size: vids[k].$1 * 1024 * 1024, dur: vids[k].$2,
          w: 1920, h: 1080, at: now.subtract(Duration(days: 15 + k * 47)));
    }
  }

  // ---------- picture generation ----------

  static const _palettes = [
    [(135, 190, 235), (255, 214, 120), (70, 140, 80)],
    [(250, 170, 120), (255, 240, 200), (60, 90, 140)],
    [(40, 60, 110), (240, 240, 210), (30, 40, 60)],
    [(180, 220, 240), (255, 255, 255), (30, 120, 170)],
    [(255, 200, 210), (255, 250, 240), (200, 90, 120)],
    [(200, 230, 200), (250, 230, 120), (90, 120, 60)],
  ];

  img.Image _render(MediaItem item) {
    final s = _spec[item.id]!;
    final landscape = item.width >= item.height;
    final w = landscape ? thumbSide : (thumbSide * item.width / item.height).round();
    final h = landscape ? (thumbSide * item.height / item.width).round() : thumbSide;
    final im = img.Image(width: w, height: h);
    final r = math.Random(s.scene * 31 + 5);
    if (s.screen) {
      final hue = _palettes[s.scene % _palettes.length][2];
      img.fill(im, color: img.ColorRgb8(245, 246, 248));
      img.fillRect(im, x1: 0, y1: 0, x2: w, y2: (h * 0.09).round(), color: img.ColorRgb8(hue.$1, hue.$2, hue.$3));
      for (var row = 0; row < 7; row++) {
        final y = (h * 0.13 + row * h * 0.11).round();
        img.fillRect(im, x1: 8, y1: y, x2: w - 8, y2: y + (h * 0.085).round(), color: img.ColorRgb8(255, 255, 255));
        img.fillCircle(im, x: 22, y: y + (h * 0.042).round(), radius: 9,
            color: img.ColorRgb8(hue.$1, hue.$2, hue.$3));
        img.fillRect(im, x1: 40, y1: y + 10, x2: 40 + r.nextInt(w - 60), y2: y + 16, color: img.ColorRgb8(60, 66, 80));
        img.fillRect(im, x1: 40, y1: y + 22, x2: 40 + r.nextInt(w ~/ 2), y2: y + 26, color: img.ColorRgb8(150, 155, 170));
      }
      return im;
    }
    final p = _palettes[s.scene % _palettes.length];
    final sky = p[0], sun = p[1], land = p[2];
    final tint = (s.scene * 23) % 50 - 25 + s.light;
    int c(int v) => (v + tint).clamp(0, 255);
    for (var y = 0; y < h; y++) {
      final t = y / h;
      img.drawLine(im, x1: 0, y1: y, x2: w - 1, y2: y,
          color: img.ColorRgb8(c((sky.$1 * (1 - t * .4)).round()), c((sky.$2 * (1 - t * .3)).round()), c(sky.$3)));
    }
    final sx = (w * (0.2 + r.nextDouble() * 0.6)).round() + s.shift;
    img.fillCircle(im, x: sx, y: (h * 0.3).round(), radius: (h * (0.1 + r.nextDouble() * 0.08)).round(),
        color: img.ColorRgb8(sun.$1, sun.$2, sun.$3));
    for (var k = 0; k < 3; k++) {
      final base = (h * (0.55 + k * 0.12)).round();
      final amp = h * (0.05 + r.nextDouble() * 0.08);
      final ph = r.nextDouble() * 6;
      final f = 0.01 + r.nextDouble() * 0.03;
      final shade = 1 - k * 0.18;
      for (var x = 0; x < w; x++) {
        final top = (base + math.sin((x + s.shift) * f + ph) * amp).round();
        img.drawLine(im, x1: x, y1: top, x2: x, y2: h - 1,
            color: img.ColorRgb8(c((land.$1 * shade).round()), c((land.$2 * shade).round()), c((land.$3 * shade).round())));
      }
    }
    for (var k = 0; k < 6; k++) {
      final tx = r.nextInt(w) + s.shift;
      final ty = (h * (0.6 + r.nextDouble() * 0.3)).round();
      img.fillRect(im, x1: tx, y1: ty - 18, x2: tx + 3, y2: ty, color: img.ColorRgb8(60, 40, 30));
      img.fillCircle(im, x: tx + 1, y: ty - 20, radius: 7, color: img.ColorRgb8(c(40), c(110), c(50)));
    }
    if (item.isVideo) {
      img.fillCircle(im, x: w ~/ 2, y: h ~/ 2, radius: 22, color: img.ColorRgba8(0, 0, 0, 120));
    }
    if (s.blur > 0) img.gaussianBlur(im, radius: s.blur);
    if (s.dark) {
      img.fill(im, color: img.ColorRgb8(8 + s.scene % 5, 8, 10));
      img.fillCircle(im, x: w ~/ 3, y: h ~/ 2, radius: 30, color: img.ColorRgb8(16, 14, 14));
      img.gaussianBlur(im, radius: 6);
    }
    return im;
  }

  img.Image _image(MediaItem item) {
    final key = _hash[item.id]!.startsWith('dup') ? _hash[item.id]! : item.id;
    return _pix.putIfAbsent(key, () => _render(item));
  }

  // ---------- MediaSource ----------

  @override
  Future<PermissionState> requestPermission() async {
    if (permission == PermissionState.denied) permission = PermissionState.granted;
    return permission;
  }

  @override
  Future<void> openSettings() async {}

  @override
  Future<List<MediaItem>> listAll() async =>
      _items.where((i) => !_trashed.contains(i.id)).toList();

  @override
  Future<Uint8List?> thumbnail(MediaItem item, int side) async =>
      _png.putIfAbsent(item.id, () => img.encodeJpg(_image(item), quality: 88));

  @override
  Future<GreyThumb?> grey(MediaItem item, int side) async {
    final im = _image(item);
    final g = Uint8List(im.width * im.height);
    var k = 0;
    for (final p in im) {
      g[k++] = ((p.r * 299 + p.g * 587 + p.b * 114) ~/ 1000).clamp(0, 255).toInt();
    }
    return GreyThumb(im.width, im.height, g);
  }

  @override
  Future<String?> contentHash(MediaItem item) async => _hash[item.id];

  @override
  Future<StorageStats> storage() async {
    const gb = 1024 * 1024 * 1024;
    final mine = _items.where((i) => !_trashed.contains(i.id)).fold(0, (s, i) => s + i.size);
    return StorageStats(total: 128 * gb, free: 128 * gb - 96 * gb - mine);
  }

  @override
  Future<bool> trash(List<MediaItem> items) async {
    final ok = await (confirm?.call(items.length) ?? Future.value(true));
    if (!ok) return false;
    for (final i in items) {
      _trashed.add(i.id);
      _trashedAt[i.id] = DateTime.now();
    }
    return true;
  }

  @override
  Future<bool> restore(List<TrashedItem> items) async {
    if (!canRestoreInApp) return false;
    for (final t in items) {
      _trashed.remove(t.id);
    }
    return true;
  }

  @override
  Future<List<TrashedItem>> stillTrashed(List<String> ids, List<String> kinds) async => [
        for (var i = 0; i < ids.length; i++)
          if (_trashed.contains(ids[i]))
            TrashedItem(
              id: ids[i],
              kind: kinds[i] == 'video' ? MediaKind.video : MediaKind.image,
              expires: _trashedAt[ids[i]]!.add(const Duration(days: 30)),
            ),
      ];

  @override
  Future<void> openInGallery(MediaItem item) async {}
}
