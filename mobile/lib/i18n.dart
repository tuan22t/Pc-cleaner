/// Same approach as the desktop app: the Vietnamese text is the key, the
/// English text lives in assets/i18n/en.json. Missing English falls back to
/// Vietnamese, and test/i18n_test.dart lists any key without a translation.
library;

import 'dart:convert';

import 'package:flutter/services.dart' show rootBundle;

String _lang = 'vi';
Map<String, String> _en = {};

String get currentLang => _lang;

Future<void> loadTranslations() async {
  try {
    final raw = await rootBundle.loadString('assets/i18n/en.json');
    _en = (jsonDecode(raw) as Map<String, dynamic>).map((k, v) => MapEntry(k, v as String));
  } catch (_) {
    _en = {};
  }
}

void setLang(String lang) => _lang = lang == 'en' ? 'en' : 'vi';

/// Translate [vi]; `{0}`, `{1}`... are replaced by [args].
String tr(String vi, [List<Object?> args = const []]) {
  var s = _lang == 'en' ? (_en[vi] ?? vi) : vi;
  for (var i = 0; i < args.length; i++) {
    s = s.replaceAll('{$i}', '${args[i]}');
  }
  return s;
}

/// "1,2 GB" in Vietnamese, "1.2 GB" in English.
String fmtBytes(num bytes) {
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  var v = bytes.toDouble();
  var u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u++;
  }
  final digits = (u == 0 || v >= 100) ? 0 : (v >= 10 ? 1 : 1);
  var s = v.toStringAsFixed(digits);
  if (s.endsWith('.0')) s = s.substring(0, s.length - 2);
  if (_lang == 'vi') s = s.replaceAll('.', ',');
  return '$s ${units[u]}';
}

/// 12.345 (vi) / 12,345 (en).
String fmtInt(int n) {
  final s = n.abs().toString();
  final b = StringBuffer();
  for (var i = 0; i < s.length; i++) {
    if (i > 0 && (s.length - i) % 3 == 0) b.write(_lang == 'vi' ? '.' : ',');
    b.write(s[i]);
  }
  return (n < 0 ? '-' : '') + b.toString();
}

String fmtDate(DateTime d) {
  String two(int x) => x.toString().padLeft(2, '0');
  return _lang == 'vi' ? '${two(d.day)}/${two(d.month)}/${d.year}' : '${d.year}-${two(d.month)}-${two(d.day)}';
}

String fmtMonth(DateTime d) =>
    _lang == 'vi' ? 'Tháng ${d.month}/${d.year}' : '${_months[d.month - 1]} ${d.year}';

const _months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

String fmtDuration(int sec) {
  final m = sec ~/ 60, s = sec % 60;
  if (m >= 60) return '${m ~/ 60}:${(m % 60).toString().padLeft(2, '0')}:${s.toString().padLeft(2, '0')}';
  return '$m:${s.toString().padLeft(2, '0')}';
}
