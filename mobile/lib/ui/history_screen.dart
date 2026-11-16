import 'package:material_ui/material_ui.dart';

import '../core/action_log.dart';
import '../data/media_source.dart';
import '../i18n.dart';
import '../main.dart' show AppScope;
import 'widgets.dart';

String categoryName(String c) => switch (c) {
      'exact' => tr('Ảnh trùng y hệt'),
      'similar' => tr('Ảnh giống nhau'),
      'blurry' => tr('Ảnh mờ hoặc tối'),
      'screenshots' => tr('Ảnh chụp màn hình'),
      'videos' => tr('Video nặng'),
      'swipe' => tr('Vuốt để dọn'),
      _ => c,
    };

/// The cleanup journal, with a restore button while items are still in the
/// system trash.
class HistoryScreen extends StatelessWidget {
  const HistoryScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final entries = s.log.entries;
    final t = Theme.of(context).textTheme;
    final cs = Theme.of(context).colorScheme;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Nhật ký dọn dẹp'))),
      body: ListView(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 24),
        children: [
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Row(children: [
                const Icon(Icons.savings_outlined, color: Color(0xFF2C9A5B), size: 32),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(tr('Tổng đã giải phóng'), style: t.bodyMedium),
                    Text(fmtBytes(s.settings.freedTotal), style: t.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
                  ]),
                ),
              ]),
            ),
          ),
          const SizedBox(height: 10),
          Text(
              s.isIOS
                  ? tr('Mục đã dọn nằm trong album "Đã xóa gần đây" 30 ngày. Muốn lấy lại: mở ứng dụng Ảnh, vào Bộ sưu tập > Đã xóa gần đây, chọn ảnh và bấm Khôi phục.')
                  : tr('Mục đã dọn nằm trong Thùng rác của điện thoại 30 ngày. Trong thời gian đó bạn khôi phục được bằng nút bên dưới, hoặc trong Thùng rác của ứng dụng Ảnh / Files.'),
              style: t.bodySmall?.copyWith(color: cs.onSurfaceVariant)),
          const SizedBox(height: 10),
          if (entries.isEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 40),
              child: Center(child: Text(tr('Chưa dọn lần nào.'), style: t.bodyLarge)),
            ),
          for (final e in entries) Padding(padding: const EdgeInsets.only(bottom: 10), child: _EntryCard(key: ValueKey(e.at.toIso8601String()), entry: e)),
        ],
      ),
    );
  }
}

class _EntryCard extends StatefulWidget {
  const _EntryCard({super.key, required this.entry});
  final LogEntry entry;

  @override
  State<_EntryCard> createState() => _EntryCardState();
}

class _EntryCardState extends State<_EntryCard> {
  Future<List<TrashedItem>>? _left;
  bool _working = false;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final e = widget.entry;
    final t = Theme.of(context).textTheme;
    _left ??= e.restored ? Future.value(const []) : s.recoverable(e);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 12, 12),
        child: FutureBuilder<List<TrashedItem>>(
          future: _left,
          builder: (context, snap) {
            final left = snap.data;
            String status;
            if (e.restored) {
              status = tr('Đã khôi phục');
            } else if (left == null) {
              status = '...';
            } else if (left.isEmpty) {
              status = tr('Đã xóa hẳn hoặc đã khôi phục ở nơi khác');
            } else {
              final exp = left.map((x) => x.expires).whereType<DateTime>().fold<DateTime?>(null, (a, b) => a == null || b.isBefore(a) ? b : a);
              final days = exp == null ? 30 : exp.difference(DateTime.now()).inDays.clamp(0, 30);
              status = s.isIOS
                  ? tr('Trong "Đã xóa gần đây" · còn khoảng {0} ngày', [days])
                  : tr('Trong thùng rác · còn {0} ngày để khôi phục', [days]);
            }
            return Row(children: [
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(categoryName(e.category), style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                  Text('${fmtDate(e.at)} · ${tr('{0} mục', [fmtInt(e.count)])} · ${fmtBytes(e.bytes)}'),
                  const SizedBox(height: 2),
                  Text(status, style: t.bodySmall?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
                ]),
              ),
              if (!e.restored && left != null && left.isNotEmpty && !s.source.canRestoreInApp)
                OutlinedButton(onPressed: s.source.openTrash, child: Text(tr('Mở ứng dụng Ảnh'))),
              if (!e.restored && left != null && left.isNotEmpty && s.source.canRestoreInApp)
                OutlinedButton(
                  onPressed: _working
                      ? null
                      : () async {
                          setState(() => _working = true);
                          final ok = await s.restore(e);
                          if (!mounted) return;
                          setState(() {
                            _working = false;
                            _left = null;
                          });
                          if (context.mounted) {
                            toast(context, ok ? tr('Đã khôi phục. Hãy quét lại để cập nhật kết quả.') : tr('Chưa khôi phục được.'));
                          }
                        },
                  child: Text(tr('Khôi phục')),
                ),
            ]);
          },
        ),
      ),
    );
  }
}
