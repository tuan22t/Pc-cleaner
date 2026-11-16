/// App-wide state: settings, the last scan, the cleanup journal.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart' show rootBundle;

import 'core/action_log.dart';
import 'core/grouping.dart';
import 'core/models.dart';
import 'core/promo.dart';
import 'core/scanner.dart';
import 'data/media_source.dart';
import 'i18n.dart';

enum AppTheme { system, light, dark }

class Settings {
  Settings({this.lang = 'vi', this.theme = AppTheme.system, this.threshold = defaultSimilarThreshold, this.videoMb = 100, this.cleanCount = 0, this.freedTotal = 0});
  String lang;
  AppTheme theme;
  int threshold;
  int videoMb;

  /// How many cleanups so far: picks which business the thank-you card shows.
  int cleanCount;
  int freedTotal;

  Map<String, dynamic> toJson() => {
        'lang': lang,
        'theme': theme.name,
        'threshold': threshold,
        'videoMb': videoMb,
        'cleanCount': cleanCount,
        'freedTotal': freedTotal,
      };

  static Settings fromJson(Map<String, dynamic> j) => Settings(
        lang: j['lang'] as String? ?? 'vi',
        theme: AppTheme.values.firstWhere((t) => t.name == j['theme'], orElse: () => AppTheme.system),
        threshold: (j['threshold'] as int? ?? defaultSimilarThreshold).clamp(2, 7),
        videoMb: j['videoMb'] as int? ?? 100,
        cleanCount: j['cleanCount'] as int? ?? 0,
        freedTotal: j['freedTotal'] as int? ?? 0,
      );
}

/// Shown on the home screen right after a cleanup.
class CleanupDone {
  CleanupDone(this.count, this.bytes, this.place);
  final int count;
  final int bytes;
  final Place? place;
}

class AppState extends ChangeNotifier {
  AppState({required this.source, required this.log, required this.cache, this.settingsFile, this.promo});

  final MediaSource source;
  final ActionLog log;
  final AnalysisCache cache;
  final File? settingsFile;
  PromoData? promo;

  Settings settings = Settings();
  PermissionState permission = PermissionState.denied;
  StorageStats? storage;
  ScanResult? result;
  ScanProgress? progress;
  CleanupDone? lastCleanup;
  Scanner? _scanner;
  bool busy = false;

  bool get scanning => _scanner != null;

  /// iPhone: no Internet permission concept, and restoring happens in the
  /// Photos app rather than in PC Cleaner.
  bool get isIOS => source.platform == 'ios';

  Future<void> init({PermissionState? knownPermission}) async {
    final f = settingsFile;
    if (f != null && await f.exists()) {
      try {
        settings = Settings.fromJson(jsonDecode(await f.readAsString()) as Map<String, dynamic>);
      } catch (_) {}
    }
    setLang(settings.lang);
    if (promo == null) {
      try {
        promo = PromoData.parse(await rootBundle.loadString('assets/promo/promo.json'));
      } catch (_) {}
    }
    await log.load();
    await log.prune();
    if (knownPermission != null) permission = knownPermission;
    await refreshStorage();
    notifyListeners();
  }

  Future<void> saveSettings() async {
    setLang(settings.lang);
    notifyListeners();
    final f = settingsFile;
    if (f == null) return;
    await f.parent.create(recursive: true);
    await f.writeAsString(jsonEncode(settings.toJson()), flush: true);
  }

  Future<void> refreshStorage() async {
    try {
      storage = await source.storage();
    } catch (_) {}
  }

  Future<PermissionState> askPermission() async {
    permission = await source.requestPermission();
    notifyListeners();
    return permission;
  }

  Future<void> scan() async {
    if (scanning) return;
    final s = Scanner(source, cache);
    _scanner = s;
    progress = const ScanProgress('list', 0, 0);
    notifyListeners();
    try {
      final r = await s.run(
        options: ScanOptions(threshold: settings.threshold, videoMinBytes: settings.videoMb * 1024 * 1024),
        onProgress: (p) {
          progress = p;
          notifyListeners();
        },
      );
      if (r != null) result = r;
    } finally {
      _scanner = null;
      progress = null;
      await refreshStorage();
      notifyListeners();
    }
  }

  void cancelScan() => _scanner?.cancel();

  /// Moves [items] to the system trash. The journal entry is written as soon
  /// as Android reports success, before the screen updates.
  Future<bool> clean(String category, List<MediaItem> items) async {
    if (items.isEmpty || busy) return false;
    busy = true;
    notifyListeners();
    try {
      final ok = await source.trash(items);
      if (!ok) return false;
      final entry = LogEntry.of(category, items);
      await log.add(entry);
      result = result?.without(items.map((i) => i.id).toSet());
      final p = promo;
      lastCleanup = CleanupDone(items.length, entry.bytes, p == null || p.places.isEmpty ? null : p.pick(settings.cleanCount));
      settings.cleanCount++;
      settings.freedTotal += entry.bytes;
      await saveSettings();
      await refreshStorage();
      return true;
    } finally {
      busy = false;
      notifyListeners();
    }
  }

  void dismissCleanup() {
    lastCleanup = null;
    notifyListeners();
  }

  /// What is still recoverable for a journal entry. When the system does not
  /// say when an item expires (iOS), it is 30 days after the cleanup.
  Future<List<TrashedItem>> recoverable(LogEntry e) async {
    final fallback = e.at.add(const Duration(days: 30));
    final now = DateTime.now();
    final left = await source.stillTrashed(e.ids, e.kinds);
    return [
      for (final t in left)
        if ((t.expires ?? fallback).isAfter(now))
          TrashedItem(id: t.id, kind: t.kind, expires: t.expires ?? fallback),
    ];
  }

  Future<bool> restore(LogEntry e) async {
    final items = await recoverable(e);
    if (items.isEmpty) return false;
    final ok = await source.restore(items);
    if (!ok) return false;
    await log.markRestored(e);
    result = null; // restored photos change the groups: ask for a new scan
    await refreshStorage();
    notifyListeners();
    return true;
  }
}
