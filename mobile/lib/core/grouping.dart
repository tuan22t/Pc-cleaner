/// Turning analysed photos into groups and lists the user can review.
///
/// Safety rules (same spirit as the desktop app):
///  * every group keeps exactly one photo, chosen by [pickBest];
///  * favourites are never pre-selected for removal;
///  * nothing here removes anything: it only suggests.
library;

import 'analysis.dart';
import 'models.dart';

/// Similarity setting 2 (strict) .. 7 (loose). The default matches the
/// desktop app's default of 6 bits.
const int defaultSimilarThreshold = 6;

/// Photos taken within this window are compared with each other
/// (burst shots, several takes of the same scene).
const Duration similarTimeWindow = Duration(hours: 2);

/// Photos further apart in time only group when practically identical
/// (e.g. the same picture saved again by a chat app, re-compressed).
const int farApartMaxBits = 2;
const double farApartMinCorrelation = 0.97;

/// Minimum correlation of the 16x16 thumbnails for a sensitivity level.
double minCorrelationFor(int level) => const {2: 0.97, 3: 0.95, 4: 0.93, 5: 0.91, 6: 0.89, 7: 0.86}[level.clamp(2, 7)]!;

/// Blur / darkness limits, measured on the [thumbSide] thumbnail.
const double blurrySharpness = 60;
const double darkBrightness = 18;

/// Videos at least this big are listed as "large".
const int largeVideoBytes = 100 * 1024 * 1024;

/// Groups of byte-identical files. [contentHash] returns a digest of the
/// whole file (it is only called for files that share size and dimensions,
/// so the cost stays low).
Future<List<MediaGroup>> groupExact(
  List<MediaItem> items,
  Future<String?> Function(MediaItem) contentHash, {
  bool Function()? cancelled,
}) async {
  final bySize = <String, List<MediaItem>>{};
  for (final i in items) {
    bySize.putIfAbsent('${i.kind.name}:${i.size}:${i.width}x${i.height}', () => []).add(i);
  }
  final groups = <MediaGroup>[];
  for (final same in bySize.values) {
    if (same.length < 2) continue;
    final byHash = <String, List<MediaItem>>{};
    for (final i in same) {
      if (cancelled?.call() ?? false) return groups;
      final h = await contentHash(i);
      if (h == null) continue;
      byHash.putIfAbsent(h, () => []).add(i);
    }
    for (final g in byHash.values) {
      if (g.length < 2) continue;
      final sorted = sortForKeepExact(g);
      groups.add(MediaGroup(sorted, keep: sorted.first));
    }
  }
  groups.sort((a, b) => b.reclaimable.compareTo(a.reclaimable));
  return groups;
}

/// For exact copies the content is identical, so keep the favourite, else
/// the oldest one (usually the original; later ones came from apps saving
/// a copy).
List<MediaItem> sortForKeepExact(List<MediaItem> g) {
  final s = [...g];
  s.sort((a, b) {
    if (a.isFavorite != b.isFavorite) return a.isFavorite ? -1 : 1;
    final c = a.created.compareTo(b.created);
    if (c != 0) return c;
    return a.id.compareTo(b.id);
  });
  return s;
}

/// Groups of photos that look alike (burst shots, re-saved copies,
/// several takes of the same scene). [exclude] are ids already in an exact
/// group: they are not shown twice.
///
/// Two passes:
///  1. photos taken close together (within [similarTimeWindow]) are compared
///     with a tolerant correlation of their 16x16 thumbnails;
///  2. photos far apart in time are matched through the 64-bit hash (only
///     near-identical ones), using the desktop app's bucket trick.
/// Photos with no thumbnail data fall back to the hash with [threshold] bits.
List<MediaGroup> groupSimilar(
  List<MediaItem> items,
  Map<String, ImageInfo> info, {
  int threshold = defaultSimilarThreshold,
  Set<String> exclude = const {},
}) {
  threshold = threshold.clamp(0, 7);
  final minCorr = minCorrelationFor(threshold);
  final photos = items
      .where((i) => !i.isVideo && !i.isScreenshot && !exclude.contains(i.id) && info.containsKey(i.id))
      .toList()
    ..sort((a, b) => a.created.compareTo(b.created));
  final n = photos.length;
  final parent = List<int>.generate(n, (i) => i);
  int find(int x) {
    while (parent[x] != x) {
      parent[x] = parent[parent[x]];
      x = parent[x];
    }
    return x;
  }

  void union(int a, int b) {
    final ra = find(a), rb = find(b);
    if (ra != rb) parent[ra] = rb;
  }

  bool sameShape(MediaItem a, MediaItem b) {
    if (a.height == 0 || b.height == 0) return true;
    final ra = a.width / a.height, rb = b.width / b.height;
    return (ra - rb).abs() / ra < 0.1;
  }

  // Pass 1: neighbours in time.
  for (var a = 0; a < n; a++) {
    final pa = photos[a], ia = info[pa.id]!;
    for (var b = a + 1; b < n; b++) {
      final pb = photos[b];
      if (pb.created.difference(pa.created) > similarTimeWindow) break;
      if (!sameShape(pa, pb)) continue;
      final ib = info[pb.id]!;
      final ta = ia.tiny, tb = ib.tiny;
      final similar = (ta != null && tb != null)
          ? correlation(ta, tb) >= minCorr
          : hamming(ia.dhash, ib.dhash) <= threshold;
      if (similar) union(a, b);
    }
  }

  // Pass 2: near-identical photos anywhere in time. Hashes differing in at
  // most 7 bits share at least one of their 8 bytes (pigeonhole), so compare
  // only inside those byte buckets.
  final buckets = <int, List<int>>{};
  for (var idx = 0; idx < n; idx++) {
    final h = info[photos[idx].id]!.dhash;
    for (var k = 0; k < 8; k++) {
      buckets.putIfAbsent((k << 8) | ((h >> (8 * k)) & 0xFF), () => []).add(idx);
    }
  }
  final checked = <int>{};
  for (final members in buckets.values) {
    if (members.length < 2) continue;
    for (var x = 0; x < members.length; x++) {
      for (var y = x + 1; y < members.length; y++) {
        final a = members[x], b = members[y];
        final key = a < b ? a * n + b : b * n + a;
        if (!checked.add(key)) continue;
        final ia = info[photos[a].id]!, ib = info[photos[b].id]!;
        if (hamming(ia.dhash, ib.dhash) > farApartMaxBits) continue;
        if (!sameShape(photos[a], photos[b])) continue;
        final ta = ia.tiny, tb = ib.tiny;
        if (ta != null && tb != null && correlation(ta, tb) < farApartMinCorrelation) continue;
        union(a, b);
      }
    }
  }

  final byRoot = <int, List<MediaItem>>{};
  for (var i = 0; i < n; i++) {
    byRoot.putIfAbsent(find(i), () => []).add(photos[i]);
  }
  final groups = <MediaGroup>[];
  for (final g in byRoot.values) {
    if (g.length < 2) continue;
    final sorted = sortForKeepSimilar(g, info);
    groups.add(MediaGroup(sorted, keep: sorted.first));
  }
  groups.sort((a, b) => b.items.first.created.compareTo(a.items.first.created));
  return groups;
}

/// Best first: favourite, then full resolution, then sharpest, then biggest.
List<MediaItem> sortForKeepSimilar(List<MediaItem> g, Map<String, ImageInfo> info) {
  final maxPixels = g.map((i) => i.pixels).fold(0, (a, b) => a > b ? a : b);
  bool full(MediaItem i) => i.pixels >= maxPixels * 0.9;
  final s = [...g];
  s.sort((a, b) {
    if (a.isFavorite != b.isFavorite) return a.isFavorite ? -1 : 1;
    if (full(a) != full(b)) return full(a) ? -1 : 1;
    final sa = info[a.id]?.sharpness ?? 0, sb = info[b.id]?.sharpness ?? 0;
    if ((sa - sb).abs() > 1e-9) return sb.compareTo(sa);
    final c = b.size.compareTo(a.size);
    if (c != 0) return c;
    return a.id.compareTo(b.id);
  });
  return s;
}

/// Photos that are probably blurry or too dark (taken in a pocket).
/// Screenshots are excluded: flat app screens look "blurry" to the measure.
List<MediaItem> findBlurry(List<MediaItem> items, Map<String, ImageInfo> info) {
  final out = items.where((i) {
    if (i.isVideo || i.isScreenshot) return false;
    final x = info[i.id];
    if (x == null) return false;
    return x.sharpness < blurrySharpness || x.brightness < darkBrightness;
  }).toList();
  out.sort((a, b) => info[a.id]!.sharpness.compareTo(info[b.id]!.sharpness));
  return out;
}

List<MediaItem> findScreenshots(List<MediaItem> items) {
  final s = items.where((i) => i.isScreenshot && !i.isVideo).toList();
  s.sort((a, b) => a.created.compareTo(b.created)); // oldest first
  return s;
}

List<MediaItem> findLargeVideos(List<MediaItem> items, {int minBytes = largeVideoBytes}) {
  final v = items.where((i) => i.isVideo && i.size >= minBytes).toList();
  v.sort((a, b) => b.size.compareTo(a.size));
  return v;
}

/// Which items a review screen pre-selects for removal: every item except
/// the one to keep, and never a favourite.
Set<String> defaultSelection(MediaGroup g) =>
    g.items.where((i) => i != g.keep && !i.isFavorite).map((i) => i.id).toSet();

/// Guard used right before removing: refuses a selection that would remove
/// every photo of a group.
bool selectionKeepsOnePerGroup(List<MediaGroup> groups, Set<String> selected) {
  for (final g in groups) {
    if (g.items.every((i) => selected.contains(i.id))) return false;
  }
  return true;
}
