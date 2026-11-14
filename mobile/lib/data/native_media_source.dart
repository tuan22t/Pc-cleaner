/// Photo library access through the native bridges: MediaStore on Android
/// (MainActivity.kt) and PhotoKit on iPhone (AppDelegate.swift). Both answer
/// the same channel methods.
library;

import 'package:flutter/services.dart';

import '../core/models.dart';
import 'media_source.dart';

class GreyThumb {
  const GreyThumb(this.width, this.height, this.pixels);
  final int width;
  final int height;
  final Uint8List pixels;
}

/// Sources that can hand out raw grey pixels skip JPEG decoding in Dart.
abstract class GreySource {
  Future<GreyThumb?> grey(MediaItem item, int side);
}

class NativeMediaSource implements MediaSource, GreySource {
  NativeMediaSource({required this.platform});
  static const _ch = MethodChannel('pccleaner/media');

  @override
  final String platform;

  @override
  bool get canRestoreInApp => platform == 'android';

  @override
  Future<void> openTrash() async {
    try {
      await _ch.invokeMethod('openTrash');
    } on MissingPluginException {
      // Android restores in the app itself.
    }
  }

  Map<String, String> _ref(MediaItem i) => {'id': i.id, 'kind': i.kind.name};

  PermissionState _perm(String? s) => switch (s) {
        'granted' => PermissionState.granted,
        'limited' => PermissionState.limited,
        _ => PermissionState.denied,
      };

  Future<PermissionState> permissionState() async =>
      _perm(await _ch.invokeMethod<String>('permissionState'));

  @override
  Future<PermissionState> requestPermission() async =>
      _perm(await _ch.invokeMethod<String>('requestPermission'));

  @override
  Future<void> openSettings() => _ch.invokeMethod('openSettings');

  @override
  Future<List<MediaItem>> listAll() async {
    final rows = await _ch.invokeListMethod<Map>('listAll') ?? [];
    return rows.map((r) {
      final path = (r['path'] as String? ?? '').toLowerCase();
      final title = r['title'] as String? ?? '';
      final kind = r['kind'] == 'video' ? MediaKind.video : MediaKind.image;
      return MediaItem(
        id: r['id'] as String,
        kind: kind,
        size: (r['size'] as num?)?.toInt() ?? 0,
        width: (r['width'] as num?)?.toInt() ?? 0,
        height: (r['height'] as num?)?.toInt() ?? 0,
        created: DateTime.fromMillisecondsSinceEpoch((r['created'] as num?)?.toInt() ?? 0),
        modified: DateTime.fromMillisecondsSinceEpoch((r['modified'] as num?)?.toInt() ?? 0),
        isFavorite: r['favorite'] == true,
        isScreenshot: kind == MediaKind.image && (r['screenshot'] == true || isScreenshotPath(path, title)),
        durationSec: ((r['duration'] as num?)?.toInt() ?? 0) ~/ 1000,
        title: title,
        bucket: r['bucket'] as String? ?? '',
      );
    }).where((i) => i.size > 0).toList();
  }

  @override
  Future<Uint8List?> thumbnail(MediaItem item, int side) async {
    try {
      return await _ch.invokeMethod<Uint8List>('thumbnail', {..._ref(item), 'side': side});
    } on PlatformException {
      return null;
    }
  }

  @override
  Future<GreyThumb?> grey(MediaItem item, int side) async {
    try {
      final m = await _ch.invokeMapMethod<String, dynamic>('grey', {..._ref(item), 'side': side});
      if (m == null) return null;
      return GreyThumb(m['w'] as int, m['h'] as int, m['px'] as Uint8List);
    } on PlatformException {
      return null;
    }
  }

  @override
  Future<String?> contentHash(MediaItem item) async {
    try {
      return await _ch.invokeMethod<String>('contentHash', _ref(item));
    } on PlatformException {
      return null;
    }
  }

  @override
  Future<StorageStats> storage() async {
    final m = await _ch.invokeMapMethod<String, dynamic>('storage') ?? {};
    return StorageStats(
      total: (m['total'] as num?)?.toInt() ?? 0,
      free: (m['free'] as num?)?.toInt() ?? 0,
    );
  }

  @override
  Future<bool> trash(List<MediaItem> items) async =>
      await _ch.invokeMethod<bool>('trash', {'items': items.map(_ref).toList()}) ?? false;

  @override
  Future<bool> restore(List<TrashedItem> items) async =>
      await _ch.invokeMethod<bool>('restore', {
        'items': items.map((t) => {'id': t.id, 'kind': t.kind.name}).toList(),
      }) ??
      false;

  @override
  Future<List<TrashedItem>> stillTrashed(List<String> ids, List<String> kinds) async {
    final refs = <Map<String, String>>[];
    for (var i = 0; i < ids.length; i++) {
      refs.add({'id': ids[i], 'kind': kinds[i]});
    }
    final rows = await _ch.invokeListMethod<Map>('stillTrashed', {'items': refs}) ?? [];
    return rows
        .map((r) => TrashedItem(
              id: r['id'] as String,
              kind: r['kind'] == 'video' ? MediaKind.video : MediaKind.image,
              expires: r['expires'] == null
                  ? null
                  : DateTime.fromMillisecondsSinceEpoch((r['expires'] as num).toInt()),
            ))
        .toList();
  }

  @override
  Future<void> openInGallery(MediaItem item) => _ch.invokeMethod('open', _ref(item));
}

/// Screenshots live in ".../Screenshots/" on almost every Android brand;
/// some name the file "Screenshot_..." instead.
bool isScreenshotPath(String relativePathLower, String title) {
  return relativePathLower.contains('screenshot') ||
      relativePathLower.contains('screen_shot') ||
      relativePathLower.contains('ảnh chụp màn hình') ||
      title.toLowerCase().startsWith('screenshot');
}
