/// Runs a full scan: list media, analyse photos (with a cache so rescans are
/// fast), then build every group and list. Read-only: nothing is changed.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import '../data/android_media_source.dart' show GreySource, GreyThumb;
import '../data/media_source.dart';
import 'analysis.dart';
import 'grouping.dart';
import 'models.dart';

class ScanProgress {
  const ScanProgress(this.stage, this.done, this.total);

  /// list | analyse | compare
  final String stage;
  final int done;
  final int total;
  double get fraction => total == 0 ? 0 : done / total;
}

/// Analysis results keyed by [MediaItem.cacheKey]; stored as JSON.
class AnalysisCache {
  AnalysisCache(this.file);
  final File? file;
  Map<String, ImageInfo> _m = {};
  bool _loaded = false;

  Future<void> load() async {
    if (_loaded) return;
    _loaded = true;
    final f = file;
    if (f == null || !await f.exists()) return;
    try {
      final j = jsonDecode(await f.readAsString()) as Map<String, dynamic>;
      _m = j.map((k, v) => MapEntry(k, ImageInfo.fromJson(v as Map<String, dynamic>)));
    } catch (_) {
      _m = {}; // a damaged cache only costs one slow scan
    }
  }

  ImageInfo? operator [](String key) => _m[key];
  void operator []=(String key, ImageInfo v) => _m[key] = v;
  int get length => _m.length;

  /// Keep only keys still in the library, then write.
  Future<void> save(Set<String> liveKeys) async {
    _m.removeWhere((k, _) => !liveKeys.contains(k));
    final f = file;
    if (f == null) return;
    await f.parent.create(recursive: true);
    final tmp = File('${f.path}.tmp');
    await tmp.writeAsString(jsonEncode(_m.map((k, v) => MapEntry(k, v.toJson()))), flush: true);
    await tmp.rename(f.path);
  }
}

class ScanOptions {
  const ScanOptions({this.threshold = defaultSimilarThreshold, this.videoMinBytes = largeVideoBytes});
  final int threshold;
  final int videoMinBytes;
}

class _Job {
  _Job(this.w, this.h, this.px);
  final int w, h;
  final Uint8List px;
}

List<ImageInfo> _analyseBatch(List<_Job> jobs) =>
    [for (final j in jobs) analyzeGrey(j.px, j.w, j.h)];

class Scanner {
  Scanner(this.source, this.cache);
  final MediaSource source;
  final AnalysisCache cache;
  bool _cancel = false;

  void cancel() => _cancel = true;

  Future<ScanResult?> run({
    ScanOptions options = const ScanOptions(),
    void Function(ScanProgress)? onProgress,
  }) async {
    _cancel = false;
    onProgress?.call(const ScanProgress('list', 0, 0));
    await cache.load();
    final all = await source.listAll();
    final photos = all.where((i) => !i.isVideo).toList();
    final info = <String, ImageInfo>{};

    final todo = <MediaItem>[];
    for (final p in photos) {
      final c = cache[p.cacheKey];
      if (c != null) {
        info[p.id] = c;
      } else {
        todo.add(p);
      }
    }
    var done = photos.length - todo.length;
    onProgress?.call(ScanProgress('analyse', done, photos.length));

    const batch = 24;
    for (var start = 0; start < todo.length; start += batch) {
      if (_cancel) return null;
      final part = todo.sublist(start, (start + batch).clamp(0, todo.length));
      final thumbs = await Future.wait(part.map(_grey));
      final jobs = <_Job>[];
      final owners = <MediaItem>[];
      for (var k = 0; k < part.length; k++) {
        final t = thumbs[k];
        if (t == null) continue;
        jobs.add(_Job(t.width, t.height, t.pixels));
        owners.add(part[k]);
      }
      final results = kIsWeb ? _analyseBatch(jobs) : await compute(_analyseBatch, jobs);
      for (var k = 0; k < owners.length; k++) {
        info[owners[k].id] = results[k];
        cache[owners[k].cacheKey] = results[k];
      }
      done += part.length;
      onProgress?.call(ScanProgress('analyse', done, photos.length));
    }

    onProgress?.call(ScanProgress('compare', photos.length, photos.length));
    final exact = await groupExact(all, source.contentHash, cancelled: () => _cancel);
    if (_cancel) return null;
    final inExact = {for (final g in exact) ...g.items.map((i) => i.id)};
    final similar = groupSimilar(photos, info, threshold: options.threshold, exclude: inExact);
    await cache.save({for (final p in photos) p.cacheKey});
    return ScanResult(
      all: all,
      exact: exact,
      similar: similar,
      blurry: findBlurry(photos, info),
      screenshots: findScreenshots(photos),
      largeVideos: findLargeVideos(all, minBytes: options.videoMinBytes),
      finishedAt: DateTime.now(),
    );
  }

  Future<GreyThumb?> _grey(MediaItem i) async {
    final s = source;
    if (s is GreySource) return (s as GreySource).grey(i, thumbSide);
    return null;
  }
}
