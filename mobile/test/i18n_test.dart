import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

/// Every Vietnamese string passed to tr('...') must have an English entry.
void main() {
  test('every tr() string has an English translation', () {
    final en = (jsonDecode(File('assets/i18n/en.json').readAsStringSync()) as Map).cast<String, String>();
    final pat = RegExp(r"tr\(\s*'((?:[^'\\]|\\.)*)'");
    final missing = <String>{};
    for (final f in Directory('lib').listSync(recursive: true).whereType<File>().where((f) => f.path.endsWith('.dart'))) {
      for (final m in pat.allMatches(f.readAsStringSync())) {
        final k = m.group(1)!.replaceAll(r"\'", "'");
        if (!en.containsKey(k)) missing.add(k);
      }
    }
    expect(missing, isEmpty, reason: 'Run: python tool/i18n_keys.py');
  });

  test('placeholders match between Vietnamese and English', () {
    final en = (jsonDecode(File('assets/i18n/en.json').readAsStringSync()) as Map).cast<String, String>();
    final ph = RegExp(r'\{\d\}');
    for (final e in en.entries) {
      final a = ph.allMatches(e.key).map((m) => m.group(0)).toSet();
      final b = ph.allMatches(e.value).map((m) => m.group(0)).toSet();
      expect(b, a, reason: e.key);
    }
  });
}
