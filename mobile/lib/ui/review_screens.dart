import 'package:material_ui/material_ui.dart';

import '../core/grouping.dart';
import '../core/models.dart';
import '../i18n.dart';
import '../main.dart' show AppScope;
import 'widgets.dart';

/// Review groups of exact copies or similar photos. One photo per group is
/// always kept; the suggested selection never includes favourites.
class GroupReviewScreen extends StatefulWidget {
  const GroupReviewScreen({super.key, required this.category, required this.title});

  /// exact | similar
  final String category;
  final String title;

  @override
  State<GroupReviewScreen> createState() => _GroupReviewScreenState();
}

class _GroupReviewScreenState extends State<GroupReviewScreen> {
  Set<String>? _selected;

  List<MediaGroup> _groups(BuildContext context) {
    final r = AppScope.of(context).result;
    if (r == null) return const [];
    return widget.category == 'exact' ? r.exact : r.similar;
  }

  Set<String> _suggested(List<MediaGroup> gs) => {for (final g in gs) ...defaultSelection(g)};

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final groups = _groups(context);
    final sel = _selected ??= _suggested(groups);
    final items = {for (final g in groups) for (final i in g.items) i.id: i};
    sel.removeWhere((id) => !items.containsKey(id));
    final chosen = sel.map((id) => items[id]!).toList();
    final bytes = chosen.fold(0, (a, i) => a + i.size);
    final t = Theme.of(context).textTheme;
    final cs = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          PopupMenuButton<String>(
            onSelected: (v) => setState(() => _selected = v == 'suggest' ? _suggested(groups) : <String>{}),
            itemBuilder: (_) => [
              PopupMenuItem(value: 'suggest', child: Text(tr('Chọn theo gợi ý'))),
              PopupMenuItem(value: 'none', child: Text(tr('Bỏ chọn tất cả'))),
            ],
          ),
        ],
      ),
      body: groups.isEmpty
          ? Center(child: Text(tr('Không còn nhóm nào.')))
          : ListView.builder(
              padding: const EdgeInsets.fromLTRB(12, 8, 12, 16),
              itemCount: groups.length + 1,
              itemBuilder: (context, idx) {
                if (idx == 0) {
                  return Padding(
                    padding: const EdgeInsets.fromLTRB(4, 0, 4, 12),
                    child: Text(
                      widget.category == 'exact'
                          ? tr('Các ảnh trong mỗi nhóm giống nhau từng điểm ảnh. Ảnh có nhãn "Giữ lại" là bản gốc (cũ nhất hoặc được yêu thích).')
                          : tr('Ảnh có nhãn "Giữ lại" là tấm nét nhất. Chạm để chọn hoặc bỏ chọn, nhấn giữ để xem lớn.'),
                      style: t.bodyMedium?.copyWith(color: cs.onSurfaceVariant),
                    ),
                  );
                }
                final g = groups[idx - 1];
                return Padding(
                  padding: const EdgeInsets.only(bottom: 12),
                  child: Card(
                    child: Padding(
                      padding: const EdgeInsets.all(10),
                      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(4, 2, 4, 8),
                          child: Text(
                            tr('{0} ảnh · {1} · thừa {2}', [g.items.length, fmtDate(g.items.first.created), fmtBytes(g.reclaimable)]),
                            style: t.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                          ),
                        ),
                        GridView.count(
                          crossAxisCount: 3,
                          shrinkWrap: true,
                          physics: const NeverScrollableScrollPhysics(),
                          mainAxisSpacing: 6,
                          crossAxisSpacing: 6,
                          children: [
                            for (final i in g.items)
                              PhotoTile(
                                source: s.source,
                                item: i,
                                selected: sel.contains(i.id),
                                badge: i == g.keep ? tr('Giữ lại') : null,
                                onLongPress: () => showPreview(context, s.source, i),
                                onTap: () => setState(() {
                                  if (sel.contains(i.id)) {
                                    sel.remove(i.id);
                                  } else if (g.items.where((x) => x != i).every((x) => sel.contains(x.id))) {
                                    toast(context, tr('Mỗi nhóm luôn giữ lại ít nhất 1 ảnh.'));
                                  } else {
                                    sel.add(i.id);
                                  }
                                }),
                              ),
                          ],
                        ),
                      ]),
                    ),
                  ),
                );
              },
            ),
      bottomNavigationBar: CleanBar(
        count: chosen.length,
        bytes: bytes,
        busy: s.busy,
        onClean: () async {
          if (!selectionKeepsOnePerGroup(groups, sel)) {
            toast(context, tr('Mỗi nhóm luôn giữ lại ít nhất 1 ảnh.'));
            return;
          }
          final ok = await s.clean(widget.category, chosen);
          if (context.mounted) await afterClean(context, ok);
        },
      ),
    );
  }
}

/// Review a flat list: blurry photos, screenshots (by month) or large videos.
/// Nothing is pre-selected here: these are judgement calls for the user.
class ListReviewScreen extends StatefulWidget {
  const ListReviewScreen({super.key, required this.category, required this.title});

  /// blurry | screenshots | videos
  final String category;
  final String title;

  @override
  State<ListReviewScreen> createState() => _ListReviewScreenState();
}

class _ListReviewScreenState extends State<ListReviewScreen> {
  final Set<String> _sel = {};

  List<MediaItem> _items(BuildContext context) {
    final r = AppScope.of(context).result;
    if (r == null) return const [];
    return switch (widget.category) {
      'blurry' => r.blurry,
      'screenshots' => r.screenshots,
      _ => r.largeVideos,
    };
  }

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final items = _items(context);
    final byId = {for (final i in items) i.id: i};
    _sel.removeWhere((id) => !byId.containsKey(id));
    final chosen = _sel.map((id) => byId[id]!).toList();
    final t = Theme.of(context).textTheme;
    final cs = Theme.of(context).colorScheme;

    Widget body;
    if (items.isEmpty) {
      body = Center(child: Text(tr('Không còn mục nào.')));
    } else if (widget.category == 'videos') {
      body = ListView.separated(
        padding: const EdgeInsets.symmetric(vertical: 8),
        itemCount: items.length,
        separatorBuilder: (_, _) => const Divider(height: 1),
        itemBuilder: (context, k) {
          final v = items[k];
          final on = _sel.contains(v.id);
          return ListTile(
            onTap: () => setState(() => on ? _sel.remove(v.id) : _sel.add(v.id)),
            leading: GestureDetector(
              onTap: () => s.source.openInGallery(v),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(8),
                child: SizedBox(
                  width: 96,
                  height: 56,
                  child: Stack(fit: StackFit.expand, children: [
                    MediaThumb(source: s.source, item: v),
                    const Center(child: Icon(Icons.play_circle_fill, color: Colors.white, size: 26)),
                  ]),
                ),
              ),
            ),
            title: Text(fmtBytes(v.size), style: const TextStyle(fontWeight: FontWeight.w700)),
            subtitle: Text('${fmtDuration(v.durationSec)} · ${fmtDate(v.created)}${v.bucket.isEmpty ? '' : ' · ${v.bucket}'}'),
            trailing: Checkbox(value: on, onChanged: (_) => setState(() => on ? _sel.remove(v.id) : _sel.add(v.id))),
          );
        },
      );
    } else {
      // Sections: by month for screenshots, a single one for blurry photos.
      final sections = <String, List<MediaItem>>{};
      for (final i in items) {
        final key = widget.category == 'screenshots' ? fmtMonth(i.created) : '';
        sections.putIfAbsent(key, () => []).add(i);
      }
      body = CustomScrollView(slivers: [
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Text(
              widget.category == 'screenshots'
                  ? tr('Ảnh chụp màn hình cũ thường không cần nữa. Chọn cả tháng hoặc từng ảnh.')
                  : tr('Ảnh bị nhòe, rung tay hoặc chụp nhầm trong túi. Hãy xem lại trước khi chọn, nhấn giữ để xem lớn.'),
              style: t.bodyMedium?.copyWith(color: cs.onSurfaceVariant),
            ),
          ),
        ),
        for (final e in sections.entries) ...[
          if (e.key.isNotEmpty)
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 8, 4),
                child: Row(children: [
                  Expanded(child: Text('${e.key} · ${fmtInt(e.value.length)}', style: t.titleSmall?.copyWith(fontWeight: FontWeight.w700))),
                  TextButton(
                    onPressed: () => setState(() {
                      final all = e.value.every((i) => _sel.contains(i.id));
                      for (final i in e.value) {
                        all ? _sel.remove(i.id) : _sel.add(i.id);
                      }
                    }),
                    child: Text(e.value.every((i) => _sel.contains(i.id)) ? tr('Bỏ chọn tháng') : tr('Chọn cả tháng')),
                  ),
                ]),
              ),
            ),
          SliverPadding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            sliver: SliverGrid.count(
              crossAxisCount: widget.category == 'screenshots' ? 4 : 3,
              mainAxisSpacing: 6,
              crossAxisSpacing: 6,
              childAspectRatio: widget.category == 'screenshots' ? 0.55 : 1,
              children: [
                for (final i in e.value)
                  PhotoTile(
                    source: s.source,
                    item: i,
                    selected: _sel.contains(i.id),
                    onLongPress: () => showPreview(context, s.source, i),
                    onTap: () => setState(() => _sel.contains(i.id) ? _sel.remove(i.id) : _sel.add(i.id)),
                  ),
              ],
            ),
          ),
        ],
        const SliverToBoxAdapter(child: SizedBox(height: 16)),
      ]);
    }

    return Scaffold(
      appBar: AppBar(
        title: Text(widget.title),
        actions: [
          if (items.isNotEmpty)
            TextButton(
              onPressed: () => setState(() {
                if (_sel.length == items.length) {
                  _sel.clear();
                } else {
                  _sel.addAll(items.map((i) => i.id));
                }
              }),
              child: Text(_sel.length == items.length ? tr('Bỏ chọn') : tr('Chọn tất cả')),
            ),
        ],
      ),
      body: body,
      bottomNavigationBar: CleanBar(
        count: chosen.length,
        bytes: chosen.fold(0, (a, i) => a + i.size),
        busy: s.busy,
        onClean: () async {
          final ok = await s.clean(widget.category, chosen);
          if (context.mounted) await afterClean(context, ok);
        },
      ),
    );
  }
}
