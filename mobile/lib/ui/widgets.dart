import 'dart:typed_data';

import 'package:material_ui/material_ui.dart';

import '../core/models.dart';
import '../data/media_source.dart';
import '../i18n.dart';

/// Small in-memory cache so scrolling back does not ask Android again.
class ThumbCache {
  ThumbCache._();
  static final _m = <String, Future<Uint8List?>>{}; // insertion-ordered
  static const _max = 400;

  static void clear() => _m.clear();

  static Future<Uint8List?> get(MediaSource s, MediaItem i, int side) {
    final k = '${i.id}@$side';
    final hit = _m.remove(k);
    if (hit != null) {
      _m[k] = hit;
      return hit;
    }
    final f = s.thumbnail(i, side);
    _m[k] = f;
    if (_m.length > _max) _m.remove(_m.keys.first);
    return f;
  }
}

class MediaThumb extends StatelessWidget {
  const MediaThumb({super.key, required this.source, required this.item, this.side = 256, this.fit = BoxFit.cover});
  final MediaSource source;
  final MediaItem item;
  final int side;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) {
    final bg = Theme.of(context).colorScheme.surfaceContainerHighest;
    return FutureBuilder<Uint8List?>(
      future: ThumbCache.get(source, item, side),
      builder: (context, snap) {
        final b = snap.data;
        if (b == null) return ColoredBox(color: bg);
        return Image.memory(b, fit: fit, gaplessPlayback: true, errorBuilder: (_, _, _) => ColoredBox(color: bg));
      },
    );
  }
}

/// One selectable tile in a photo grid.
class PhotoTile extends StatelessWidget {
  const PhotoTile({
    super.key,
    required this.source,
    required this.item,
    required this.selected,
    required this.onTap,
    this.onLongPress,
    this.badge,
  });

  final MediaSource source;
  final MediaItem item;
  final bool selected;
  final VoidCallback onTap;
  final VoidCallback? onLongPress;
  final String? badge;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Semantics(
      selected: selected,
      label: item.title,
      child: GestureDetector(
        onTap: onTap,
        onLongPress: onLongPress,
        child: ClipRRect(
          borderRadius: BorderRadius.circular(10),
          child: Stack(fit: StackFit.expand, children: [
            MediaThumb(source: source, item: item),
            if (selected) ColoredBox(color: cs.error.withValues(alpha: 0.28)),
            Positioned(
              top: 6,
              right: 6,
              child: Container(
                width: 24,
                height: 24,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: selected ? cs.error : Colors.black26,
                  border: Border.all(color: Colors.white, width: 2),
                ),
                child: selected ? const Icon(Icons.delete_outline, size: 14, color: Colors.white) : null,
              ),
            ),
            if (item.isFavorite)
              const Positioned(top: 6, left: 6, child: Icon(Icons.favorite, color: Colors.white, size: 18, shadows: [Shadow(blurRadius: 4)])),
            if (badge != null)
              Positioned(
                left: 6,
                bottom: 6,
                child: Container(
                  padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                  decoration: BoxDecoration(color: const Color(0xFF2C9A5B), borderRadius: BorderRadius.circular(8)),
                  child: Text(badge!, style: const TextStyle(color: Colors.white, fontSize: 11, fontWeight: FontWeight.w600)),
                ),
              ),
            if (item.isVideo)
              Positioned(
                right: 6,
                bottom: 6,
                child: Text(fmtDuration(item.durationSec),
                    style: const TextStyle(color: Colors.white, fontSize: 11, shadows: [Shadow(blurRadius: 4)])),
              ),
          ]),
        ),
      ),
    );
  }
}

/// Bottom action bar of every review screen.
class CleanBar extends StatelessWidget {
  const CleanBar({super.key, required this.count, required this.bytes, required this.onClean, this.busy = false});
  final int count;
  final int bytes;
  final VoidCallback onClean;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return SafeArea(
      top: false,
      child: Container(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 12),
        decoration: BoxDecoration(color: Theme.of(context).cardTheme.color, border: Border(top: BorderSide(color: cs.outlineVariant))),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              style: FilledButton.styleFrom(backgroundColor: cs.error, foregroundColor: cs.onError, padding: const EdgeInsets.symmetric(vertical: 14)),
              onPressed: count == 0 || busy ? null : onClean,
              icon: const Icon(Icons.delete_outline),
              label: Text(count == 0 ? tr('Chưa chọn mục nào') : tr('Chuyển {0} mục ({1}) vào thùng rác', [fmtInt(count), fmtBytes(bytes)])),
            ),
          ),
          const SizedBox(height: 6),
          Text(tr('Thùng rác giữ 30 ngày, khôi phục được trong mục Nhật ký.'),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
        ]),
      ),
    );
  }
}

/// Full-screen look at one photo before deciding.
Future<void> showPreview(BuildContext context, MediaSource source, MediaItem item) {
  return showDialog(
    context: context,
    builder: (c) => Dialog(
      insetPadding: const EdgeInsets.all(16),
      clipBehavior: Clip.antiAlias,
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        AspectRatio(
          aspectRatio: item.height == 0 ? 1 : item.width / item.height,
          child: MediaThumb(source: source, item: item, side: 1024, fit: BoxFit.contain),
        ),
        Padding(
          padding: const EdgeInsets.all(12),
          child: Text('${item.title}\n${fmtDate(item.created)} · ${item.width}×${item.height} · ${fmtBytes(item.size)}${item.bucket.isEmpty ? '' : ' · ${item.bucket}'}',
              textAlign: TextAlign.center),
        ),
      ]),
    ),
  );
}

/// Shown when the user clears an action they cannot take (e.g. selecting
/// every photo of a group).
void toast(BuildContext context, String msg) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text(msg), behavior: SnackBarBehavior.floating));
}

/// After a cleanup: confirm, then pop back with the result.
Future<void> afterClean(BuildContext context, bool ok) async {
  if (!context.mounted) return;
  if (ok) {
    Navigator.of(context).pop(true);
  } else {
    toast(context, tr('Chưa chuyển gì vào thùng rác.'));
  }
}
