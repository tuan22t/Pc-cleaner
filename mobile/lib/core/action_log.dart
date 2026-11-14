/// The cleanup journal: what was moved to the trash, when, and how to bring
/// it back. Written before the action is reported as done, one JSON object
/// per line, so a crash can never leave a removal without a record.
library;

import 'dart:convert';
import 'dart:io';

import 'models.dart';

class LogEntry {
  LogEntry({
    required this.at,
    required this.category,
    required this.ids,
    required this.kinds,
    required this.bytes,
    this.restored = false,
  });

  final DateTime at;

  /// exact | similar | blurry | screenshots | videos | swipe
  final String category;
  final List<String> ids;

  /// Parallel to [ids]: 'image' or 'video'.
  final List<String> kinds;
  final int bytes;
  bool restored;

  int get count => ids.length;

  Map<String, dynamic> toJson() => {
        'at': at.toIso8601String(),
        'category': category,
        'ids': ids,
        'kinds': kinds,
        'bytes': bytes,
        'restored': restored,
      };

  static LogEntry fromJson(Map<String, dynamic> j) => LogEntry(
        at: DateTime.parse(j['at'] as String),
        category: j['category'] as String,
        ids: (j['ids'] as List).cast<String>(),
        kinds: (j['kinds'] as List).cast<String>(),
        bytes: j['bytes'] as int,
        restored: j['restored'] as bool? ?? false,
      );

  static LogEntry of(String category, List<MediaItem> items) => LogEntry(
        at: DateTime.now(),
        category: category,
        ids: items.map((i) => i.id).toList(),
        kinds: items.map((i) => i.kind.name).toList(),
        bytes: items.fold(0, (s, i) => s + i.size),
      );
}

class ActionLog {
  ActionLog(this.file);

  /// null keeps the log in memory only (tests, web preview).
  final File? file;
  final List<LogEntry> _entries = [];
  bool _loaded = false;

  List<LogEntry> get entries => List.unmodifiable(_entries.reversed);

  Future<void> load() async {
    if (_loaded) return;
    _loaded = true;
    final f = file;
    if (f == null || !await f.exists()) return;
    for (final line in await f.readAsLines()) {
      if (line.trim().isEmpty) continue;
      try {
        _entries.add(LogEntry.fromJson(jsonDecode(line) as Map<String, dynamic>));
      } catch (_) {
        // A damaged line (e.g. power loss mid-write) is skipped, not fatal.
      }
    }
  }

  Future<void> add(LogEntry e) async {
    _entries.add(e);
    await _save();
  }

  Future<void> markRestored(LogEntry e) async {
    e.restored = true;
    await _save();
  }

  /// Entries older than the 30-day system trash can no longer be undone;
  /// keep them 90 days for the history view, then drop them.
  Future<void> prune({Duration keep = const Duration(days: 90)}) async {
    final cut = DateTime.now().subtract(keep);
    final before = _entries.length;
    _entries.removeWhere((e) => e.at.isBefore(cut));
    if (_entries.length != before) await _save();
  }

  Future<void> _save() async {
    final f = file;
    if (f == null) return;
    await f.parent.create(recursive: true);
    final tmp = File('${f.path}.tmp');
    await tmp.writeAsString(
      '${_entries.map((e) => jsonEncode(e.toJson())).join('\n')}\n',
      flush: true,
    );
    await tmp.rename(f.path); // atomic replace
  }
}
