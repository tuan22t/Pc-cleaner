// Saves screenshots of every screen on the made-up photo library, for the
// acceptance report. Runs only when PCCLEANER_SCREENSHOTS=<folder> is set:
//   PCCLEANER_SCREENSHOTS=build/screens flutter test test/screenshots_test.dart
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:material_ui/material_ui.dart';
import 'package:pc_cleaner/data/media_source.dart';
import 'package:pc_cleaner/main.dart';
import 'package:pc_cleaner/state.dart';

import 'helpers.dart';

final outDir = Platform.environment['PCCLEANER_SCREENSHOTS'];
final _key = GlobalKey();

Future<void> shoot(WidgetTester tester, String name) async {
  await settle(tester, ms: 250);
  final boundary = tester.renderObject<RenderRepaintBoundary>(find.byKey(_key));
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 2);
    final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
    File('$outDir/$name.png')
      ..createSync(recursive: true)
      ..writeAsBytesSync(bytes!.buffer.asUint8List());
  });
}

Future<void> open(WidgetTester tester, AppState s, {int tab = 0}) async {
  await tester.pumpWidget(RepaintBoundary(key: _key, child: PcCleanerApp(state: s, initialTab: tab)));
  await settle(tester);
}

Future<void> tapText(WidgetTester tester, String text) async {
  final f = find.text(text).first;
  await tester.ensureVisible(f);
  await tester.pumpAndSettle();
  await tester.tap(f);
  await settle(tester);
}

void main() {
  if (outDir == null) {
    test('screenshots (skipped: set PCCLEANER_SCREENSHOTS)', () {}, skip: true);
    return;
  }

  setUpAll(loadRealFonts);
  setUp(() {
    final binding = TestWidgetsFlutterBinding.ensureInitialized();
    binding.platformDispatcher.views.first
      ..physicalSize = const Size(1080, 2340)
      ..devicePixelRatio = 2.625;
  });

  for (final lang in ['vi', 'en']) {
    final t = lang == 'vi'
        ? (scan: 'Quét ngay', similar: 'Ảnh giống nhau', exact: 'Ảnh trùng y hệt', blurry: 'Ảnh mờ hoặc tối', shots: 'Ảnh chụp màn hình', videos: 'Video nặng', swipe: 'Vuốt để dọn', history: 'Nhật ký')
        : (scan: 'Scan now', similar: 'Similar photos', exact: 'Exact duplicates', blurry: 'Blurry or dark photos', shots: 'Screenshots', videos: 'Large videos', swipe: 'Swipe to clean', history: 'History');

    testWidgets('$lang: permission and start', (tester) async {
      final s = await makeState(tester, perm: PermissionState.denied, lang: lang);
      await open(tester, s);
      await shoot(tester, '$lang-00-quyen-truy-cap');
      final g = await makeState(tester, lang: lang);
      await open(tester, g);
      await shoot(tester, '$lang-01-bat-dau');
    });

    testWidgets('$lang: results and review screens', (tester) async {
      final s = await makeState(tester, lang: lang);
      await open(tester, s);
      await runScan(tester, s);
      await shoot(tester, '$lang-02-ket-qua');
      for (final (label, file) in [
        (t.exact, '03-anh-trung'),
        (t.similar, '04-anh-giong-nhau'),
        (t.blurry, '05-anh-mo'),
        (t.shots, '06-anh-chup-man-hinh'),
        (t.videos, '07-video-nang'),
      ]) {
        await tapText(tester, label);
        await shoot(tester, '$lang-$file');
        await tester.tap(find.byType(BackButton));
        await settle(tester);
      }
      await tapText(tester, t.swipe);
      await shoot(tester, '$lang-08-vuot-chon-thang');
      await tester.tap(find.textContaining(lang == 'vi' ? 'Tháng ' : '2026').first);
      await settle(tester);
      await tester.fling(find.byType(Dismissible), const Offset(-600, 0), 1500);
      await settle(tester);
      await shoot(tester, '$lang-09-vuot-de-don');
    });

    testWidgets('$lang: after cleaning, history, explore, settings', (tester) async {
      final s = await makeState(tester, lang: lang);
      await open(tester, s);
      await runScan(tester, s);
      await tapText(tester, t.similar);
      await tester.tap(find.textContaining(lang == 'vi' ? 'vào thùng rác' : 'to Trash').first);
      await settle(tester);
      await tester.drag(find.byType(Scrollable).first, const Offset(0, 600));
      await settle(tester);
      await shoot(tester, '$lang-10-sau-khi-don');
      await tester.tap(find.text(t.history));
      await settle(tester);
      await shoot(tester, '$lang-11-nhat-ky');
      await tester.tap(find.text(lang == 'vi' ? 'Khám phá' : 'Explore'));
      await settle(tester);
      await shoot(tester, '$lang-12-kham-pha');
      await tester.tap(find.text(lang == 'vi' ? 'Cài đặt' : 'Settings').last);
      await settle(tester);
      await shoot(tester, '$lang-13-cai-dat');
    });
  }

  testWidgets('dark theme', (tester) async {
    final s = await makeState(tester, theme: AppTheme.dark);
    await open(tester, s);
    await runScan(tester, s);
    await settle(tester, ms: 500);
    await shoot(tester, 'vi-toi-02-ket-qua');
    await tapText(tester, 'Ảnh giống nhau');
    await settle(tester, ms: 600);
    await shoot(tester, 'vi-toi-04-anh-giong-nhau');
  });
}
