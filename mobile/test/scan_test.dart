import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:pc_cleaner/core/action_log.dart';
import 'package:pc_cleaner/core/promo.dart';
import 'package:pc_cleaner/core/scanner.dart';
import 'package:pc_cleaner/data/demo_media_source.dart';
import 'package:pc_cleaner/state.dart';

/// End-to-end on the made-up library: scan, clean, restore. Never touches
/// real photos.
void main() {
  late Directory dir;
  setUp(() => dir = Directory.systemTemp.createTempSync('pcc'));
  tearDown(() => dir.deleteSync(recursive: true));

  test('scan finds every kind of clutter in the demo library', () async {
    final src = DemoMediaSource();
    final r = (await Scanner(src, AnalysisCache(null)).run())!;
    expect(r.exact, hasLength(4));
    expect(r.exact.first.items, hasLength(3)); // biggest group first
    expect(r.similar.length, greaterThanOrEqualTo(7));
    for (final g in r.similar) {
      // Every similar group comes from a single scene of burst shots.
      expect(g.items.map((i) => i.created.day).toSet(), hasLength(1));
    }
    expect(r.blurry.length, greaterThanOrEqualTo(6));
    expect(r.screenshots, hasLength(16));
    expect(r.largeVideos, hasLength(4));
    expect(r.suggestedBytes, greaterThan(0));
    // The favourite in scene 2 is the one kept.
    final withFav = r.similar.where((g) => g.items.any((i) => i.isFavorite));
    expect(withFav.single.keep.isFavorite, isTrue);
  });

  test('rescans reuse the analysis cache', () async {
    final cache = AnalysisCache(File('${dir.path}/cache.json'));
    final src = DemoMediaSource();
    await Scanner(src, cache).run();
    final second = AnalysisCache(File('${dir.path}/cache.json'));
    final firstProgress = <ScanProgress>[];
    await Scanner(src, second).run(onProgress: firstProgress.add);
    final analyse = firstProgress.firstWhere((p) => p.stage == 'analyse');
    expect(analyse.done, analyse.total, reason: 'every photo came from the cache');
  });

  test('cleaning writes the journal, updates results, and restore brings items back', () async {
    final src = DemoMediaSource();
    final state = AppState(
      source: src,
      log: ActionLog(File('${dir.path}/log.jsonl')),
      cache: AnalysisCache(null),
      settingsFile: File('${dir.path}/settings.json'),
      promo: PromoData.parse(File('assets/promo/promo.json').readAsStringSync()),
    );
    await state.init();
    await state.scan();
    final before = state.result!;
    final g = before.exact.first;
    final remove = g.items.where((i) => i != g.keep).toList();

    expect(await state.clean('exact', remove), isTrue);
    expect(state.log.entries.single.ids, remove.map((i) => i.id).toList());
    expect(state.result!.exact, hasLength(before.exact.length - 1));
    expect(state.lastCleanup!.bytes, remove.fold(0, (a, i) => a + i.size));
    expect(state.lastCleanup!.place, isNotNull);
    expect((await src.listAll()).map((i) => i.id), isNot(contains(remove.first.id)));

    // Persisted: a fresh start sees the same journal and freed total.
    final reloaded = ActionLog(File('${dir.path}/log.jsonl'));
    await reloaded.load();
    expect(reloaded.entries, hasLength(1));

    expect(await state.restore(state.log.entries.single), isTrue);
    expect(state.log.entries.single.restored, isTrue);
    expect((await src.listAll()).map((i) => i.id), contains(remove.first.id));
  });

  test('if the user cancels Android\'s confirmation nothing is logged', () async {
    final src = DemoMediaSource()..confirm = (_) async => false;
    final state = AppState(source: src, log: ActionLog(null), cache: AnalysisCache(null));
    await state.init();
    await state.scan();
    final g = state.result!.exact.first;
    expect(await state.clean('exact', [g.items.last]), isFalse);
    expect(state.log.entries, isEmpty);
    expect(state.result!.exact.first.items, hasLength(g.items.length));
  });
}
