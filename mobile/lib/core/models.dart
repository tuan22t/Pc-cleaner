/// Plain data types shared by the scanner, the UI and the tests.
/// Nothing here touches the phone: the Android code fills these in.
library;

import 'dart:convert';
import 'dart:typed_data';

enum MediaKind { image, video }

class MediaItem {
  const MediaItem({
    required this.id,
    required this.kind,
    required this.size,
    required this.width,
    required this.height,
    required this.created,
    required this.modified,
    this.isFavorite = false,
    this.isScreenshot = false,
    this.durationSec = 0,
    this.title = '',
    this.bucket = '',
  });

  /// MediaStore id on Android. Stable while the file exists.
  final String id;
  final MediaKind kind;

  /// Bytes on disk.
  final int size;
  final int width;
  final int height;
  final DateTime created;
  final DateTime modified;

  /// Marked as favourite in the gallery. Never pre-selected for removal.
  final bool isFavorite;
  final bool isScreenshot;
  final int durationSec;
  final String title;

  /// Album / folder name, e.g. "Camera", "Screenshots", "Zalo".
  final String bucket;

  int get pixels => width * height;
  bool get isVideo => kind == MediaKind.video;

  /// Key for the analysis cache: changes whenever the file changes.
  String get cacheKey => '$id:$size:${modified.millisecondsSinceEpoch}';

  @override
  bool operator ==(Object other) => other is MediaItem && other.id == id;

  @override
  int get hashCode => id.hashCode;

  @override
  String toString() => 'MediaItem($id, $title)';
}

/// What the scanner learned about one photo from its small thumbnail.
class ImageInfo {
  const ImageInfo({
    required this.dhash,
    required this.sharpness,
    required this.brightness,
    this.tiny,
  });

  /// 64-bit difference hash (same algorithm as the desktop app).
  final int dhash;

  /// Variance of the Laplacian: low means blurry.
  final double sharpness;

  /// Mean brightness 0..255: very low means a photo taken in a pocket.
  final double brightness;

  /// 16x16 grey version of the photo, compared with a correlation that
  /// tolerates small shifts, exposure changes and sensor noise far better
  /// than the 64-bit hash alone.
  final Uint8List? tiny;

  Map<String, dynamic> toJson() => {
        'h': dhash.toUnsigned(64).toRadixString(16),
        's': sharpness,
        'b': brightness,
        if (tiny != null) 't': base64Encode(tiny!),
      };

  static ImageInfo fromJson(Map<String, dynamic> j) => ImageInfo(
        dhash: BigInt.parse(j['h'] as String, radix: 16).toSigned(64).toInt(),
        sharpness: (j['s'] as num).toDouble(),
        brightness: (j['b'] as num).toDouble(),
        tiny: j['t'] == null ? null : base64Decode(j['t'] as String),
      );
}

/// A set of photos that are copies or near-copies of each other.
class MediaGroup {
  MediaGroup(this.items, {required this.keep});

  /// Sorted best first.
  final List<MediaItem> items;

  /// The photo the app suggests keeping (always exactly one per group).
  final MediaItem keep;

  /// Bytes freed if every photo except [keep] is removed.
  int get reclaimable =>
      items.where((i) => i != keep).fold(0, (s, i) => s + i.size);
}

class StorageStats {
  const StorageStats({required this.total, required this.free});
  final int total;
  final int free;
  int get used => total - free;
  double get usedFraction => total == 0 ? 0 : used / total;
}

/// Everything one scan found. The UI only reads this.
class ScanResult {
  ScanResult({
    required this.all,
    required this.exact,
    required this.similar,
    required this.blurry,
    required this.screenshots,
    required this.largeVideos,
    required this.finishedAt,
  });

  final List<MediaItem> all;
  final List<MediaGroup> exact;
  final List<MediaGroup> similar;
  final List<MediaItem> blurry;
  final List<MediaItem> screenshots;
  final List<MediaItem> largeVideos;
  final DateTime finishedAt;

  int get photoBytes =>
      all.where((i) => !i.isVideo).fold(0, (s, i) => s + i.size);
  int get videoBytes =>
      all.where((i) => i.isVideo).fold(0, (s, i) => s + i.size);
  int get photoCount => all.where((i) => !i.isVideo).length;
  int get videoCount => all.where((i) => i.isVideo).length;
  int get screenshotBytes => screenshots.fold(0, (s, i) => s + i.size);

  /// A conservative "you could free" figure: duplicates beyond the first
  /// copy and similar photos beyond the best one. Blurry photos and videos
  /// are left out because only the user can judge them.
  int get suggestedBytes =>
      exact.fold(0, (s, g) => s + g.reclaimable) +
      similar.fold(0, (s, g) => s + g.reclaimable);

  ScanResult without(Set<String> removedIds) {
    bool keep(MediaItem i) => !removedIds.contains(i.id);
    List<MediaGroup> regroup(List<MediaGroup> gs) {
      final out = <MediaGroup>[];
      for (final g in gs) {
        final left = g.items.where(keep).toList();
        if (left.length < 2) continue;
        out.add(MediaGroup(left, keep: left.contains(g.keep) ? g.keep : left.first));
      }
      return out;
    }

    return ScanResult(
      all: all.where(keep).toList(),
      exact: regroup(exact),
      similar: regroup(similar),
      blurry: blurry.where(keep).toList(),
      screenshots: screenshots.where(keep).toList(),
      largeVideos: largeVideos.where(keep).toList(),
      finishedAt: finishedAt,
    );
  }
}
