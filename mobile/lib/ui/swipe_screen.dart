import 'package:material_ui/material_ui.dart';

import '../core/models.dart';
import '../i18n.dart';
import '../main.dart' show AppScope;
import 'widgets.dart';

/// "Vuốt để dọn": pick a month, then go through its photos one by one.
class SwipeScreen extends StatelessWidget {
  const SwipeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final photos = (s.result?.all ?? const <MediaItem>[]).where((i) => !i.isVideo).toList()
      ..sort((a, b) => b.created.compareTo(a.created));
    final months = <DateTime, List<MediaItem>>{};
    for (final p in photos) {
      months.putIfAbsent(DateTime(p.created.year, p.created.month), () => []).add(p);
    }
    final t = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: Text(tr('Vuốt để dọn'))),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Text(tr('Chọn một tháng để xem lại từng ảnh. Vuốt sang trái để bỏ, sang phải để giữ. Chỉ khi bấm nút cuối cùng ảnh mới vào thùng rác.'),
              style: t.bodyMedium?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
          const SizedBox(height: 12),
          for (final e in months.entries)
            Padding(
              padding: const EdgeInsets.only(bottom: 10),
              child: Card(
                clipBehavior: Clip.antiAlias,
                child: InkWell(
                  onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => SwipeDeck(title: fmtMonth(e.key), items: e.value))),
                  child: Padding(
                    padding: const EdgeInsets.all(10),
                    child: Row(children: [
                      for (final p in e.value.take(3))
                        Padding(
                          padding: const EdgeInsets.only(right: 6),
                          child: ClipRRect(borderRadius: BorderRadius.circular(8), child: SizedBox(width: 52, height: 52, child: MediaThumb(source: s.source, item: p))),
                        ),
                      const SizedBox(width: 6),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(fmtMonth(e.key), style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700)),
                          Text(tr('{0} ảnh · {1}', [fmtInt(e.value.length), fmtBytes(e.value.fold(0, (a, i) => a + i.size))])),
                        ]),
                      ),
                      const Icon(Icons.chevron_right),
                    ]),
                  ),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class SwipeDeck extends StatefulWidget {
  const SwipeDeck({super.key, required this.title, required this.items});
  final String title;
  final List<MediaItem> items;

  @override
  State<SwipeDeck> createState() => _SwipeDeckState();
}

class _SwipeDeckState extends State<SwipeDeck> {
  int _i = 0;
  final List<(MediaItem, bool)> _history = []; // (item, markedForRemoval)

  List<MediaItem> get _marked => [for (final h in _history) if (h.$2) h.$1];

  void _decide(bool remove) {
    if (_i >= widget.items.length) return;
    setState(() {
      _history.add((widget.items[_i], remove));
      _i++;
    });
  }

  void _undo() {
    if (_history.isEmpty) return;
    setState(() {
      _history.removeLast();
      _i--;
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final marked = _marked;
    final done = _i >= widget.items.length;
    final current = done ? null : widget.items[_i];

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          Center(
            child: Padding(
              padding: const EdgeInsets.only(right: 16),
              child: Text('${(_i + (done ? 0 : 1)).clamp(0, widget.items.length)}/${widget.items.length}', style: t.titleSmall),
            ),
          ),
        ],
      ),
      body: Column(children: [
        LinearProgressIndicator(value: widget.items.isEmpty ? 1 : _i / widget.items.length),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: current == null
                ? Center(
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      const Icon(Icons.task_alt, size: 56, color: Color(0xFF2C9A5B)),
                      const SizedBox(height: 10),
                      Text(tr('Đã xem hết tháng này'), style: t.titleLarge?.copyWith(fontWeight: FontWeight.w700)),
                      const SizedBox(height: 6),
                      Text(tr('Đánh dấu bỏ {0} ảnh ({1})', [fmtInt(marked.length), fmtBytes(marked.fold(0, (a, i) => a + i.size))])),
                    ]),
                  )
                : Dismissible(
                    key: ValueKey('${current.id}-$_i'),
                    onDismissed: (d) => _decide(d == DismissDirection.endToStart),
                    background: _SwipeHint(color: const Color(0xFF2C9A5B), icon: Icons.check, label: tr('Giữ'), alignLeft: true),
                    secondaryBackground: _SwipeHint(color: cs.error, icon: Icons.delete_outline, label: tr('Bỏ'), alignLeft: false),
                    child: GestureDetector(
                      onTap: () => showPreview(context, s.source, current),
                      child: Card(
                        clipBehavior: Clip.antiAlias,
                        child: Column(children: [
                          Expanded(child: MediaThumb(source: s.source, item: current, side: 1024, fit: BoxFit.contain)),
                          Padding(
                            padding: const EdgeInsets.all(10),
                            child: Row(children: [
                              if (current.isFavorite) const Padding(padding: EdgeInsets.only(right: 6), child: Icon(Icons.favorite, color: Colors.pink, size: 18)),
                              Expanded(child: Text('${fmtDate(current.created)} · ${fmtBytes(current.size)}${current.bucket.isEmpty ? '' : ' · ${current.bucket}'}')),
                            ]),
                          ),
                        ]),
                      ),
                    ),
                  ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
            _RoundButton(icon: Icons.close, color: cs.error, label: tr('Bỏ'), onTap: done ? null : () => _decide(true)),
            _RoundButton(icon: Icons.undo, color: cs.onSurfaceVariant, label: tr('Hoàn tác'), small: true, onTap: _history.isEmpty ? null : _undo),
            _RoundButton(icon: Icons.check, color: const Color(0xFF2C9A5B), label: tr('Giữ'), onTap: done ? null : () => _decide(false)),
          ]),
        ),
      ]),
      bottomNavigationBar: CleanBar(
        count: marked.length,
        bytes: marked.fold(0, (a, i) => a + i.size),
        busy: s.busy,
        onClean: () async {
          final ok = await s.clean('swipe', marked);
          if (context.mounted) await afterClean(context, ok);
        },
      ),
    );
  }
}

class _SwipeHint extends StatelessWidget {
  const _SwipeHint({required this.color, required this.icon, required this.label, required this.alignLeft});
  final Color color;
  final IconData icon;
  final String label;
  final bool alignLeft;

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: BoxDecoration(color: color.withValues(alpha: .15), borderRadius: BorderRadius.circular(16)),
      alignment: alignLeft ? Alignment.centerLeft : Alignment.centerRight,
      padding: const EdgeInsets.symmetric(horizontal: 28),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        Icon(icon, color: color, size: 40),
        Text(label, style: TextStyle(color: color, fontWeight: FontWeight.w700)),
      ]),
    );
  }
}

class _RoundButton extends StatelessWidget {
  const _RoundButton({required this.icon, required this.color, required this.label, required this.onTap, this.small = false});
  final IconData icon;
  final Color color;
  final String label;
  final VoidCallback? onTap;
  final bool small;

  @override
  Widget build(BuildContext context) {
    final size = small ? 48.0 : 64.0;
    return Column(mainAxisSize: MainAxisSize.min, children: [
      Material(
        shape: const CircleBorder(),
        color: color.withValues(alpha: onTap == null ? .05 : .14),
        child: InkWell(
          customBorder: const CircleBorder(),
          onTap: onTap,
          child: SizedBox(width: size, height: size, child: Icon(icon, color: onTap == null ? color.withValues(alpha: .3) : color, size: small ? 22 : 30)),
        ),
      ),
      const SizedBox(height: 4),
      GestureDetector(onTap: onTap, child: Text(label, style: Theme.of(context).textTheme.bodySmall)),
    ]);
  }
}
