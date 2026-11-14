import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:pc_cleaner/core/action_log.dart';
import 'package:pc_cleaner/core/scanner.dart';
import 'package:pc_cleaner/data/demo_media_source.dart';
import 'package:pc_cleaner/data/media_source.dart';
import 'package:pc_cleaner/i18n.dart';
import 'package:pc_cleaner/main.dart';
import 'package:pc_cleaner/state.dart';

Future<AppState> makeState(WidgetTester tester, {PermissionState perm = PermissionState.granted, String lang = 'vi', AppTheme theme = AppTheme.light}) async {
  late AppState s;
  await tester.runAsync(() async {
    await loadTranslations();
    final src = DemoMediaSource(permission: perm);
    s = AppState(source: src, log: ActionLog(null), cache: AnalysisCache(null));
    await s.init(knownPermission: perm);
    s.settings
      ..lang = lang
      ..theme = theme;
    setLang(lang);
  });
  return s;
}

Future<void> pumpApp(WidgetTester tester, AppState s, {int tab = 0}) async {
  await tester.pumpWidget(PcCleanerApp(state: s, initialTab: tab));
  await settle(tester);
}

/// Lets real async work (thumbnails, image decoding, isolates) finish.
Future<void> settle(WidgetTester tester, {int ms = 150}) async {
  for (var i = 0; i < 3; i++) {
    await tester.runAsync(() => Future<void>.delayed(Duration(milliseconds: ms)));
    await tester.pump(const Duration(milliseconds: 50));
  }
  await tester.pumpAndSettle();
}

Future<void> runScan(WidgetTester tester, AppState s) async {
  await tester.runAsync(() => s.scan());
  await settle(tester);
}

/// Real fonts (Roboto + Material icons from the Flutter SDK) so screenshots
/// show text instead of boxes.
Future<void> loadRealFonts() async {
  final root = Platform.environment['FLUTTER_ROOT'] ?? '/opt/flutter';
  final dir = '$root/bin/cache/artifacts/material_fonts';
  final roboto = FontLoader('Roboto');
  for (final w in ['Regular', 'Medium', 'Bold', 'Black', 'Light']) {
    final f = File('$dir/Roboto-$w.ttf');
    if (f.existsSync()) roboto.addFont(Future.value(ByteData.sublistView(f.readAsBytesSync())));
  }
  await roboto.load();
  final icons = FontLoader('MaterialIcons');
  final f = File('$dir/MaterialIcons-Regular.otf');
  if (f.existsSync()) icons.addFont(Future.value(ByteData.sublistView(f.readAsBytesSync())));
  await icons.load();
}
