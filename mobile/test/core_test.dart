import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:image/image.dart' as img;
import 'package:pc_cleaner/core/action_log.dart';
import 'package:pc_cleaner/core/analysis.dart';
import 'package:pc_cleaner/core/grouping.dart';
import 'package:pc_cleaner/core/models.dart';
import 'package:pc_cleaner/core/promo.dart';
import 'package:pc_cleaner/i18n.dart';

MediaItem item(String id, {
  int size = 1000,
  int w = 400,
  int h = 300,
  DateTime? at,
  bool fav = false,
  bool shot = false,
  MediaKind kind = MediaKind.image,
}) =>
    MediaItem(
      id: id,
      kind: kind,
      size: size,
      width: w,
      height: h,
      created: at ?? DateTime(2026, 1, 1),
      modified: at ?? DateTime(2026, 1, 1),
      isFavorite: fav,
      isScreenshot: shot,
    );

/// A test picture with real structure (gradient + shapes).
img.Image picture(int seed, {int w = 256, int h = 192}) {
  final im = img.Image(width: w, height: h);
  for (var y = 0; y < h; y++) {
    for (var x = 0; x < w; x++) {
      im.setPixelRgb(x, y, (x * 255 ~/ w + seed * 40) % 256, (y * 255 ~/ h + seed * 70) % 256, (seed * 90) % 256);
    }
  }
  img.fillCircle(im, x: 60 + seed * 23 % 120, y: 80, radius: 35, color: img.ColorRgb8(250, 250, 250));
  img.fillRect(im, x1: 150, y1: 20 + seed * 13 % 100, x2: 220, y2: 90 + seed * 13 % 100, color: img.ColorRgb8(20, 20, 30));
  return im;
}

ImageInfo info(img.Image im) => analyzeEncoded(Uint8List.fromList(img.encodePng(im)))!;

void main() {
  group('analysis', () {
    test('hamming counts differing bits', () {
      expect(hamming(0, 0), 0);
      expect(hamming(0xFF, 0), 8);
      expect(hamming(-1, 0), 64);
    });

    test('the same picture resized or re-encoded keeps almost the same hash', () {
      final a = picture(1);
      final small = img.copyResize(a, width: 128);
      final jpeg = img.decodeJpg(img.encodeJpg(a, quality: 60))!;
      expect(hamming(info(a).dhash, info(small).dhash), lessThanOrEqualTo(4));
      expect(hamming(info(a).dhash, info(jpeg).dhash), lessThanOrEqualTo(4));
    });

    test('different pictures are far apart', () {
      expect(hamming(info(picture(1)).dhash, info(picture(4)).dhash), greaterThan(10));
    });

    test('blur lowers sharpness well below the blurry limit', () {
      final sharp = info(picture(2));
      final blurred = info(img.gaussianBlur(picture(2), radius: 6));
      expect(sharp.sharpness, greaterThan(blurrySharpness));
      expect(blurred.sharpness, lessThan(blurrySharpness));
    });

    test('a pocket shot is detected as dark', () {
      final dark = img.Image(width: 256, height: 192);
      img.fill(dark, color: img.ColorRgb8(6, 5, 7));
      expect(info(dark).brightness, lessThan(darkBrightness));
    });

    test('same algorithm as the desktop app: 9x8 brighter-than-right bits', () {
      // A left-to-right brightening ramp: every pixel is darker than its right
      // neighbour, so every bit is 0. Reversed, every bit is 1.
      final g = Uint8List(90 * 80);
      for (var y = 0; y < 80; y++) {
        for (var x = 0; x < 90; x++) {
          g[y * 90 + x] = x * 2;
        }
      }
      expect(dhashGrey(g, 90, 80), 0);
      final r = Uint8List.fromList([for (var i = 0; i < g.length; i++) 200 - g[i]]);
      expect(dhashGrey(r, 90, 80), -1); // all 64 bits set
    });
  });

  group('grouping', () {
    test('exact groups need the same content hash, keep favourite then oldest', () async {
      final a = item('a', size: 500, at: DateTime(2026, 1, 3));
      final b = item('b', size: 500, at: DateTime(2026, 1, 1));
      final c = item('c', size: 500, at: DateTime(2026, 1, 2), fav: true);
      final d = item('d', size: 500); // same size, different content
      final e = item('e', size: 999);
      final hashes = {'a': 'X', 'b': 'X', 'c': 'X', 'd': 'Y', 'e': 'X'};
      final groups = await groupExact([a, b, c, d, e], (i) async => hashes[i.id]);
      expect(groups, hasLength(1));
      expect(groups.first.items.map((i) => i.id), ['c', 'b', 'a']);
      expect(groups.first.keep.id, 'c');
      expect(groups.first.reclaimable, 1000);
    });

    test('content hash is only computed for same-size candidates', () async {
      final asked = <String>[];
      await groupExact([item('a', size: 1), item('b', size: 2), item('c', size: 2)], (i) async {
        asked.add(i.id);
        return 'h';
      });
      expect(asked, unorderedEquals(['b', 'c']));
    });

    test('similar photos group, keeping the sharpest full-resolution one', () {
      final t = DateTime(2026, 5, 1, 10);
      final items = [item('1', at: t), item('2', at: t.add(const Duration(seconds: 2))), item('3', at: t)];
      final m = {
        '1': const ImageInfo(dhash: 0x0F0F0F0F0F0F0F0F, sharpness: 100, brightness: 120),
        '2': const ImageInfo(dhash: 0x0F0F0F0F0F0F0F0E, sharpness: 300, brightness: 120),
        '3': const ImageInfo(dhash: 0x70F0F0F0F0F0F0F0, sharpness: 300, brightness: 120),
      };
      final gs = groupSimilar(items, m);
      expect(gs, hasLength(1));
      expect(gs.first.items.map((i) => i.id), ['2', '1']);
      expect(gs.first.keep.id, '2');
    });

    test('real pictures: shots of one scene group, a different scene does not', () {
      final t = DateTime(2026, 5, 1, 10);
      final base = picture(3);
      final brighter = img.adjustColor(picture(3), brightness: 1.15);
      final noisy = img.noise(picture(3), 12);
      final other = picture(6);
      final items = [
        item('a', at: t),
        item('b', at: t.add(const Duration(seconds: 1))),
        item('c', at: t.add(const Duration(seconds: 2))),
        item('d', at: t.add(const Duration(seconds: 3))),
      ];
      final m = {'a': info(base), 'b': info(brighter), 'c': info(noisy), 'd': info(other)};
      final g = groupSimilar(items, m).single;
      expect(g.items.map((i) => i.id), unorderedEquals(['a', 'b', 'c']));
    });

    test('analysis survives the cache round trip, including negative hashes', () {
      final i = info(picture(5));
      final neg = ImageInfo(dhash: -12345, sharpness: i.sharpness, brightness: i.brightness, tiny: i.tiny);
      final back = ImageInfo.fromJson(neg.toJson());
      expect(back.dhash, -12345);
      expect(back.tiny, i.tiny);
      expect(ImageInfo.fromJson(i.toJson()).dhash, i.dhash);
    });

    test('a favourite is always the one kept', () {
      final items = [item('1'), item('2', fav: true)];
      final m = {
        '1': const ImageInfo(dhash: 5, sharpness: 900, brightness: 100),
        '2': const ImageInfo(dhash: 5, sharpness: 10, brightness: 100),
      };
      expect(groupSimilar(items, m).single.keep.id, '2');
    });

    test('lookalikes far apart in time only group when nearly identical', () {
      final m = {
        'a': const ImageInfo(dhash: 0, sharpness: 100, brightness: 100),
        'b': const ImageInfo(dhash: 0x7, sharpness: 100, brightness: 100), // 3 bits apart
      };
      final near = [item('a', at: DateTime(2026, 1, 1, 10)), item('b', at: DateTime(2026, 1, 1, 10, 30))];
      final far = [item('a', at: DateTime(2024, 1, 1)), item('b', at: DateTime(2026, 1, 1))];
      expect(groupSimilar(near, m), hasLength(1));
      expect(groupSimilar(far, m), isEmpty);
    });

    test('screenshots and exact duplicates are not shown again as similar', () {
      final m = {
        'a': const ImageInfo(dhash: 1, sharpness: 100, brightness: 100),
        'b': const ImageInfo(dhash: 1, sharpness: 100, brightness: 100),
        'c': const ImageInfo(dhash: 1, sharpness: 100, brightness: 100),
      };
      expect(groupSimilar([item('a', shot: true), item('b', shot: true)], m), isEmpty);
      expect(groupSimilar([item('a'), item('b'), item('c')], m, exclude: {'a'}).single.items, hasLength(2));
    });

    test('default selection never includes the kept photo or favourites', () {
      final g = MediaGroup([item('k'), item('f', fav: true), item('x')], keep: item('k'));
      expect(defaultSelection(g), {'x'});
    });

    test('a selection that removes a whole group is refused', () {
      final g = MediaGroup([item('a'), item('b')], keep: item('a'));
      expect(selectionKeepsOnePerGroup([g], {'b'}), isTrue);
      expect(selectionKeepsOnePerGroup([g], {'a', 'b'}), isFalse);
    });

    test('blurry list skips screenshots and videos', () {
      final m = {
        'a': const ImageInfo(dhash: 0, sharpness: 5, brightness: 100),
        's': const ImageInfo(dhash: 0, sharpness: 1, brightness: 100),
        'ok': const ImageInfo(dhash: 0, sharpness: 500, brightness: 100),
        'd': const ImageInfo(dhash: 0, sharpness: 500, brightness: 4),
      };
      final out = findBlurry([item('a'), item('s', shot: true), item('ok'), item('d')], m);
      expect(out.map((i) => i.id), unorderedEquals(['a', 'd']));
    });

    test('large videos are sorted biggest first and respect the limit', () {
      final v = [
        item('v1', kind: MediaKind.video, size: 200 << 20),
        item('v2', kind: MediaKind.video, size: 500 << 20),
        item('v3', kind: MediaKind.video, size: 10 << 20),
      ];
      expect(findLargeVideos(v).map((i) => i.id), ['v2', 'v1']);
    });

    test('a result without removed items drops groups that fall below 2', () {
      final g = MediaGroup([item('a'), item('b')], keep: item('a'));
      final r = ScanResult(all: [item('a'), item('b')], exact: [g], similar: [], blurry: [], screenshots: [], largeVideos: [], finishedAt: DateTime(2026));
      final r2 = r.without({'b'});
      expect(r2.exact, isEmpty);
      expect(r2.all.map((i) => i.id), ['a']);
    });
  });

  group('journal', () {
    late Directory dir;
    setUp(() => dir = Directory.systemTemp.createTempSync('pcc'));
    tearDown(() => dir.deleteSync(recursive: true));

    test('survives a restart and skips a damaged line', () async {
      final f = File('${dir.path}/log.jsonl');
      final log = ActionLog(f);
      await log.load();
      await log.add(LogEntry.of('exact', [item('1', size: 10), item('2', size: 20, kind: MediaKind.video)]));
      await f.writeAsString('${await f.readAsString()}{"broken\n', flush: true);
      final again = ActionLog(f);
      await again.load();
      expect(again.entries, hasLength(1));
      expect(again.entries.first.bytes, 30);
      expect(again.entries.first.kinds, ['image', 'video']);
      await again.markRestored(again.entries.first);
      final third = ActionLog(f);
      await third.load();
      expect(third.entries.first.restored, isTrue);
    });

    test('old entries are pruned after 90 days', () async {
      final log = ActionLog(null);
      await log.add(LogEntry(at: DateTime.now().subtract(const Duration(days: 120)), category: 'exact', ids: ['1'], kinds: ['image'], bytes: 1));
      await log.add(LogEntry.of('similar', [item('2')]));
      await log.prune();
      expect(log.entries.single.category, 'similar');
    });
  });

  group('promo', () {
    final data = PromoData.parse(File('assets/promo/promo.json').readAsStringSync());

    test('the shared promo file lists the four businesses with all links', () {
      expect(data.places, hasLength(4));
      for (final p in data.places) {
        expect(p.phone, isNotEmpty);
        expect(p.website, startsWith('https://'));
        expect(p.maps, startsWith('https://'));
        expect(p.facebook, startsWith('https://'));
        expect(p.taglineFor('vi'), isNotEmpty);
        expect(p.taglineFor('en'), isNotEmpty);
      }
    });

    test('website links carry UTM tags and keep the address', () {
      final u = Uri.parse(data.places.first.websiteFor('kham_pha'));
      expect(u.host, 'hotel.tananpalace.com');
      expect(u.queryParameters['utm_source'], 'pccleaner_android');
      expect(u.queryParameters['utm_campaign'], 'kham_pha');
    });

    test('phone link has digits only', () {
      expect(data.places.first.telUri, 'tel:02253529168');
    });

    test('thank-you card rotates through the places', () {
      expect({for (var i = 0; i < 8; i++) data.pick(i).id}, hasLength(4));
    });
  });

  group('formatting', () {
    test('Vietnamese uses a decimal comma, English a point', () {
      setLang('vi');
      expect(fmtBytes(1536 * 1024 * 1024), '1,5 GB');
      expect(fmtInt(12345), '12.345');
      setLang('en');
      expect(fmtBytes(1536 * 1024 * 1024), '1.5 GB');
      expect(fmtInt(12345), '12,345');
      setLang('vi');
    });
  });
}
