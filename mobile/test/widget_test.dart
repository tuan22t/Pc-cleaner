import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:pc_cleaner/data/media_source.dart';
import 'package:pc_cleaner/ui/widgets.dart';

import 'helpers.dart';

void main() {
  setUp(() {
    final binding = TestWidgetsFlutterBinding.ensureInitialized();
    binding.platformDispatcher.views.first
      ..physicalSize = const Size(1080, 2400)
      ..devicePixelRatio = 2.625;
  });

  testWidgets('without permission the app explains why and asks', (tester) async {
    final s = await makeState(tester, perm: PermissionState.denied);
    await pumpApp(tester, s);
    expect(find.text('Cho phép xem ảnh và video'), findsOneWidget);
    expect(find.text('Quét ngay'), findsNothing);
    await tester.tap(find.text('Cho phép truy cập ảnh'));
    await settle(tester);
    expect(find.text('Quét ngay'), findsOneWidget);
  });

  testWidgets('scan, review similar photos, keep one per group, clean, restore', (tester) async {
    final s = await makeState(tester);
    await pumpApp(tester, s);
    expect(find.text('Quét ngay'), findsOneWidget);
    // The button calls AppState.scan; run it outside the fake clock because
    // the analysis uses a background isolate.
    await runScan(tester, s);
    expect(find.text('Kết quả quét'), findsOneWidget);
    expect(find.text('Ảnh giống nhau'), findsOneWidget);

    await tester.tap(find.text('Ảnh giống nhau'));
    await settle(tester);
    expect(find.text('Giữ lại'), findsWidgets);

    // Try to select the kept photo of the first group: refused, a toast explains.
    final firstGroup = s.result!.similar.first;
    await tester.tap(find.byWidgetPredicate((w) => w is PhotoTile && w.item == firstGroup.keep));
    await tester.pump();
    expect(find.text('Mỗi nhóm luôn giữ lại ít nhất 1 ảnh.'), findsOneWidget);

    final suggested = s.result!.similar.fold<int>(0, (a, g) => a + g.items.where((i) => i != g.keep && !i.isFavorite).length);
    await tester.tap(find.textContaining('vào thùng rác').first);
    await settle(tester);
    expect(s.log.entries.single.count, suggested);
    expect(find.textContaining('Đã giải phóng'), findsOneWidget);
    expect(find.textContaining('miễn phí nhờ'), findsOneWidget); // thank-you card names a business
    expect(s.result!.similar, isEmpty);

    await tester.tap(find.text('Nhật ký'));
    await settle(tester);
    expect(find.text('Khôi phục'), findsOneWidget);
    await tester.tap(find.text('Khôi phục'));
    await settle(tester);
    expect(find.text('Đã khôi phục'), findsOneWidget);
  });

  testWidgets('swipe deck: left removes, undo puts it back', (tester) async {
    final s = await makeState(tester);
    await pumpApp(tester, s);
    await runScan(tester, s);
    await tester.ensureVisible(find.text('Vuốt để dọn'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Vuốt để dọn'));
    await settle(tester);
    await tester.tap(find.textContaining('Tháng ').first);
    await settle(tester);
    await tester.fling(find.byType(Dismissible), const Offset(-600, 0), 1500);
    await settle(tester);
    expect(find.textContaining('Chuyển 1 mục'), findsOneWidget);
    await tester.tap(find.text('Hoàn tác'));
    await settle(tester);
    expect(find.text('Chưa chọn mục nào'), findsOneWidget);
  });

  testWidgets('explore lists the four businesses with call and directions', (tester) async {
    final s = await makeState(tester);
    await pumpApp(tester, s, tab: 2);
    for (final name in ['Khách sạn Tân An Palace', 'Tiệc cưới Tân An Palace', 'Zen Love Station', 'Zen Hotel Hạ Long']) {
      await tester.scrollUntilVisible(find.text(name), 300, scrollable: find.byType(Scrollable).last);
      expect(find.text(name), findsOneWidget);
    }
    expect(find.text('Gọi'), findsWidgets);
    expect(find.text('Chỉ đường'), findsWidgets);
  });

  testWidgets('switching to English translates the interface', (tester) async {
    final s = await makeState(tester);
    await pumpApp(tester, s, tab: 3);
    await tester.tap(find.text('English'));
    await settle(tester);
    expect(find.text('Settings'), findsWidgets);
    expect(find.text('Explore'), findsOneWidget);
    expect(s.settings.lang, 'en');
  });
}
