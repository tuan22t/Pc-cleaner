import 'dart:math' as math;

import 'package:material_ui/material_ui.dart';

import '../core/models.dart';
import '../data/media_source.dart';
import '../i18n.dart';
import '../main.dart' show AppScope;
import '../state.dart';
import 'explore_screen.dart' show PlaceActions;
import 'review_screens.dart';
import 'swipe_screen.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, required this.onOpenTab});
  final void Function(int tab) onOpenTab;

  @override
  Widget build(BuildContext context) {
    final s = AppScope.of(context);
    final r = s.result;
    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            _Header(),
            const SizedBox(height: 14),
            if (s.permission == PermissionState.denied) ...[
              _PermissionCard(state: s),
              const SizedBox(height: 12),
            ],
            if (s.permission == PermissionState.limited) ...[
              _LimitedBanner(state: s),
              const SizedBox(height: 12),
            ],
            if (s.lastCleanup != null) ...[
              _CleanupDoneCard(done: s.lastCleanup!, state: s, onExplore: () => onOpenTab(2)),
              const SizedBox(height: 12),
            ],
            _StorageCard(state: s),
            const SizedBox(height: 12),
            if (s.permission != PermissionState.denied) ...[
              _ScanCard(state: s),
              const SizedBox(height: 12),
            ],
            if (r != null) ..._categories(context, s, r),
            const SizedBox(height: 18),
            _PrivacyNote(),
          ],
        ),
      ),
    );
  }

  List<Widget> _categories(BuildContext context, AppState s, ScanResult r) {
    int sum(Iterable<MediaItem> xs) => xs.fold(0, (a, i) => a + i.size);
    final tiles = <Widget>[
      _CategoryTile(
        icon: Icons.copy_all_outlined,
        color: const Color(0xFFD64545),
        title: tr('Ảnh trùng y hệt'),
        subtitle: r.exact.isEmpty
            ? tr('Không có')
            : tr('{0} nhóm · thừa {1}', [fmtInt(r.exact.length), fmtBytes(r.exact.fold(0, (a, g) => a + g.reclaimable))]),
        enabled: r.exact.isNotEmpty,
        onTap: () => _open(context, GroupReviewScreen(category: 'exact', title: tr('Ảnh trùng y hệt'))),
      ),
      _CategoryTile(
        icon: Icons.burst_mode_outlined,
        color: const Color(0xFF2F6FED),
        title: tr('Ảnh giống nhau'),
        subtitle: r.similar.isEmpty
            ? tr('Không có')
            : tr('{0} nhóm · có thể giải phóng {1}', [fmtInt(r.similar.length), fmtBytes(r.similar.fold(0, (a, g) => a + g.reclaimable))]),
        enabled: r.similar.isNotEmpty,
        onTap: () => _open(context, GroupReviewScreen(category: 'similar', title: tr('Ảnh giống nhau'))),
      ),
      _CategoryTile(
        icon: Icons.blur_on,
        color: const Color(0xFFC98A12),
        title: tr('Ảnh mờ hoặc tối'),
        subtitle: r.blurry.isEmpty ? tr('Không có') : tr('{0} ảnh · {1}', [fmtInt(r.blurry.length), fmtBytes(sum(r.blurry))]),
        enabled: r.blurry.isNotEmpty,
        onTap: () => _open(context, ListReviewScreen(category: 'blurry', title: tr('Ảnh mờ hoặc tối'))),
      ),
      _CategoryTile(
        icon: Icons.screenshot_outlined,
        color: const Color(0xFF7B5CD6),
        title: tr('Ảnh chụp màn hình'),
        subtitle: r.screenshots.isEmpty ? tr('Không có') : tr('{0} ảnh · {1}', [fmtInt(r.screenshots.length), fmtBytes(sum(r.screenshots))]),
        enabled: r.screenshots.isNotEmpty,
        onTap: () => _open(context, ListReviewScreen(category: 'screenshots', title: tr('Ảnh chụp màn hình'))),
      ),
      _CategoryTile(
        icon: Icons.movie_outlined,
        color: const Color(0xFF2C9A5B),
        title: tr('Video nặng'),
        subtitle: r.largeVideos.isEmpty ? tr('Không có video trên {0} MB', [s.settings.videoMb]) : tr('{0} video · {1}', [fmtInt(r.largeVideos.length), fmtBytes(sum(r.largeVideos))]),
        enabled: r.largeVideos.isNotEmpty,
        onTap: () => _open(context, ListReviewScreen(category: 'videos', title: tr('Video nặng'))),
      ),
      _CategoryTile(
        icon: Icons.swipe_outlined,
        color: const Color(0xFFE0782B),
        title: tr('Vuốt để dọn'),
        subtitle: tr('Xem lại từng tháng: vuốt trái để bỏ, vuốt phải để giữ'),
        enabled: r.photoCount > 0,
        onTap: () => _open(context, const SwipeScreen()),
      ),
    ];
    return [
      Padding(
        padding: const EdgeInsets.only(left: 4, bottom: 8, top: 4),
        child: Text(tr('Kết quả quét'), style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
      ),
      Card(child: Column(children: _divided(context, tiles))),
    ];
  }

  List<Widget> _divided(BuildContext context, List<Widget> xs) {
    final out = <Widget>[];
    for (var i = 0; i < xs.length; i++) {
      if (i > 0) out.add(Divider(height: 1, indent: 64, color: Theme.of(context).colorScheme.outlineVariant.withValues(alpha: .5)));
      out.add(xs[i]);
    }
    return out;
  }

  void _open(BuildContext context, Widget screen) {
    Navigator.of(context).push(MaterialPageRoute(builder: (_) => screen));
  }
}

class _Header extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Row(children: [
      Container(
        width: 40,
        height: 40,
        decoration: BoxDecoration(color: const Color(0xFF2F6FED), borderRadius: BorderRadius.circular(12)),
        child: const Icon(Icons.auto_awesome, color: Colors.white),
      ),
      const SizedBox(width: 12),
      Expanded(
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('PC Cleaner', style: t.titleLarge?.copyWith(fontWeight: FontWeight.w800)),
          Text(tr('Dọn ảnh và video an toàn, miễn phí'), style: t.bodySmall?.copyWith(color: Theme.of(context).colorScheme.onSurfaceVariant)),
        ]),
      ),
    ]);
  }
}

class _PermissionCard extends StatelessWidget {
  const _PermissionCard({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Icon(Icons.photo_library_outlined, size: 36, color: Color(0xFF2F6FED)),
          const SizedBox(height: 10),
          Text(tr('Cho phép xem ảnh và video'), style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
          const SizedBox(height: 6),
          Text(tr('PC Cleaner cần quyền xem ảnh và video để tìm ảnh trùng, ảnh mờ và video nặng. Mọi phân tích diễn ra ngay trên điện thoại, không gửi đi đâu.')),
          const SizedBox(height: 14),
          FilledButton(
            onPressed: () async {
              final p = await state.askPermission();
              if (p == PermissionState.denied) await state.source.openSettings();
            },
            child: Text(tr('Cho phép truy cập ảnh')),
          ),
        ]),
      ),
    );
  }
}

class _LimitedBanner extends StatelessWidget {
  const _LimitedBanner({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    return MaterialBanner(
      padding: const EdgeInsets.all(12),
      content: Text(tr('Bạn mới cho phép một số ảnh. Để tìm ảnh trùng trong cả thư viện, hãy chọn "Cho phép tất cả".')),
      actions: [TextButton(onPressed: state.source.openSettings, child: Text(tr('Mở cài đặt')))],
    );
  }
}

class _StorageCard extends StatelessWidget {
  const _StorageCard({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final st = state.storage;
    final r = state.result;
    final cs = Theme.of(context).colorScheme;
    final t = Theme.of(context).textTheme;
    final frac = st?.usedFraction ?? 0;
    final gaugeColor = frac > .9 ? cs.error : (frac > .75 ? const Color(0xFFC98A12) : cs.primary);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(children: [
          SizedBox(
            width: 104,
            height: 104,
            child: CustomPaint(
              painter: _Gauge(frac, gaugeColor, cs.surfaceContainerHighest),
              child: Center(
                child: Column(mainAxisSize: MainAxisSize.min, children: [
                  Text('${(frac * 100).round()}%', style: t.headlineSmall?.copyWith(fontWeight: FontWeight.w800)),
                  Text(tr('đã dùng'), style: t.bodySmall),
                ]),
              ),
            ),
          ),
          const SizedBox(width: 18),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('Bộ nhớ điện thoại'), style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
              const SizedBox(height: 4),
              if (st != null) ...[
                Text(tr('Còn trống {0} / {1}', [fmtBytes(st.free), fmtBytes(st.total)])),
              ],
              if (r != null) ...[
                const SizedBox(height: 10),
                _Legend(color: const Color(0xFF2F6FED), label: tr('Ảnh'), value: '${fmtInt(r.photoCount)} · ${fmtBytes(r.photoBytes)}'),
                _Legend(color: const Color(0xFF2C9A5B), label: tr('Video'), value: '${fmtInt(r.videoCount)} · ${fmtBytes(r.videoBytes)}'),
              ],
            ]),
          ),
        ]),
      ),
    );
  }
}

class _Legend extends StatelessWidget {
  const _Legend({required this.color, required this.label, required this.value});
  final Color color;
  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 3),
      child: Row(children: [
        Container(width: 9, height: 9, decoration: BoxDecoration(color: color, shape: BoxShape.circle)),
        const SizedBox(width: 7),
        Text('$label: ', style: const TextStyle(fontWeight: FontWeight.w600)),
        Flexible(child: Text(value, overflow: TextOverflow.ellipsis)),
      ]),
    );
  }
}

class _Gauge extends CustomPainter {
  _Gauge(this.frac, this.color, this.track);
  final double frac;
  final Color color;
  final Color track;

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Rect.fromLTWH(6, 6, size.width - 12, size.height - 12);
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 11
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(rect, 0, math.pi * 2, false, p..color = track);
    canvas.drawArc(rect, -math.pi / 2, math.pi * 2 * frac.clamp(0, 1), false, p..color = color);
  }

  @override
  bool shouldRepaint(_Gauge o) => o.frac != frac || o.color != color || o.track != track;
}

class _ScanCard extends StatelessWidget {
  const _ScanCard({required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final cs = Theme.of(context).colorScheme;
    final p = state.progress;
    final r = state.result;
    if (p != null) {
      final label = switch (p.stage) {
        'list' => tr('Đang đọc danh sách ảnh và video...'),
        'analyse' => tr('Đang phân tích ảnh {0}/{1}', [fmtInt(p.done), fmtInt(p.total)]),
        _ => tr('Đang so sánh ảnh...'),
      };
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(label, style: t.titleSmall),
            const SizedBox(height: 10),
            LinearProgressIndicator(value: p.stage == 'analyse' ? p.fraction : null, minHeight: 8, borderRadius: BorderRadius.circular(4)),
            const SizedBox(height: 8),
            Align(alignment: Alignment.centerRight, child: TextButton(onPressed: state.cancelScan, child: Text(tr('Dừng')))),
          ]),
        ),
      );
    }
    if (r == null) {
      return Card(
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(tr('Tìm ảnh trùng, ảnh giống nhau, ảnh mờ và video nặng'), style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            const SizedBox(height: 6),
            Text(tr('Quét chỉ đọc, không xóa gì. Bạn xem lại và tự quyết định.'), style: t.bodyMedium?.copyWith(color: cs.onSurfaceVariant)),
            const SizedBox(height: 14),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(vertical: 14)),
                onPressed: state.scan,
                icon: const Icon(Icons.search),
                label: Text(tr('Quét ngay')),
              ),
            ),
          ]),
        ),
      );
    }
    return Card(
      color: cs.primaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Row(children: [
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(tr('Có thể giải phóng khoảng'), style: t.bodyMedium?.copyWith(color: cs.onPrimaryContainer)),
              Text(fmtBytes(r.suggestedBytes), style: t.headlineMedium?.copyWith(fontWeight: FontWeight.w800, color: cs.onPrimaryContainer)),
              Text(tr('từ ảnh trùng và ảnh giống nhau'), style: t.bodySmall?.copyWith(color: cs.onPrimaryContainer)),
            ]),
          ),
          OutlinedButton.icon(onPressed: state.scan, icon: const Icon(Icons.refresh), label: Text(tr('Quét lại'))),
        ]),
      ),
    );
  }
}

class _CategoryTile extends StatelessWidget {
  const _CategoryTile({required this.icon, required this.color, required this.title, required this.subtitle, required this.onTap, this.enabled = true});
  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final VoidCallback onTap;
  final bool enabled;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      enabled: enabled,
      onTap: onTap,
      contentPadding: const EdgeInsets.symmetric(horizontal: 14, vertical: 4),
      leading: Container(
        width: 38,
        height: 38,
        decoration: BoxDecoration(color: color.withValues(alpha: enabled ? .14 : .06), borderRadius: BorderRadius.circular(10)),
        child: Icon(icon, color: enabled ? color : color.withValues(alpha: .4)),
      ),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text(subtitle),
      trailing: const Icon(Icons.chevron_right),
    );
  }
}

class _CleanupDoneCard extends StatelessWidget {
  const _CleanupDoneCard({required this.done, required this.state, required this.onExplore});
  final CleanupDone done;
  final AppState state;
  final VoidCallback onExplore;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    final place = done.place;
    return Card(
      color: const Color(0xFF2C9A5B).withValues(alpha: .12),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(18, 14, 8, 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            const Icon(Icons.check_circle, color: Color(0xFF2C9A5B)),
            const SizedBox(width: 8),
            Expanded(
              child: Text(tr('Đã giải phóng {0}', [fmtBytes(done.bytes)]),
                  style: t.titleMedium?.copyWith(fontWeight: FontWeight.w700)),
            ),
            IconButton(onPressed: state.dismissCleanup, icon: const Icon(Icons.close), tooltip: tr('Đóng')),
          ]),
          Text(tr('{0} mục đã vào thùng rác, khôi phục được trong 30 ngày.', [fmtInt(done.count)])),
          if (place != null) ...[
            const SizedBox(height: 12),
            Text(tr('PC Cleaner miễn phí nhờ {0}. Ghé thăm khi bạn có dịp:', [place.name]),
                style: t.bodyMedium?.copyWith(fontWeight: FontWeight.w600)),
            const SizedBox(height: 2),
            Text(place.taglineFor(currentLang), style: t.bodySmall),
            const SizedBox(height: 6),
            PlaceActions(place: place, placement: 'sau_khi_don', compact: true),
          ],
        ]),
      ),
    );
  }
}

class _PrivacyNote extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final cs = Theme.of(context).colorScheme;
    return Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Icon(Icons.lock_outline, size: 16, color: cs.onSurfaceVariant),
      const SizedBox(width: 6),
      Expanded(
        child: Text(
          tr('Mọi phân tích diễn ra ngay trên điện thoại. Ứng dụng không có quyền truy cập Internet nên không thể gửi ảnh hay dữ liệu của bạn đi đâu.'),
          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: cs.onSurfaceVariant),
        ),
      ),
    ]);
  }
}
