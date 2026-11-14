/// The only door between the app and the phone's photos.
///
/// The Android version talks to MediaStore; the demo version (used by tests,
/// the web preview and screenshots) serves made-up photos and never touches
/// anything real.
library;

import 'dart:typed_data';

import '../core/models.dart';

enum PermissionState { granted, limited, denied }

/// One item currently sitting in the system trash because of this app.
class TrashedItem {
  const TrashedItem({required this.id, required this.kind, required this.expires});
  final String id;
  final MediaKind kind;

  /// When Android deletes it for good (30 days after it was trashed).
  final DateTime? expires;
}

abstract class MediaSource {
  /// 'android', 'ios' or 'demo'.
  String get platform;

  /// Android can take items back out of its trash; iOS cannot (the user
  /// restores from Photos > Recently Deleted).
  bool get canRestoreInApp;

  /// Opens the place where trashed items can be restored by hand
  /// (iOS: the Photos app).
  Future<void> openTrash();

  Future<PermissionState> requestPermission();

  /// Opens the system settings page of this app (after a refusal).
  Future<void> openSettings();

  /// Every photo and video the app is allowed to see.
  Future<List<MediaItem>> listAll();

  /// Encoded thumbnail (JPEG/PNG), longest side about [side] pixels.
  Future<Uint8List?> thumbnail(MediaItem item, int side);

  /// Digest of the whole file, for exact-duplicate checks.
  Future<String?> contentHash(MediaItem item);

  Future<StorageStats> storage();

  /// Moves items into the system trash (Android 11+: kept 30 days).
  /// The system shows its own confirmation; returns true if the user
  /// accepted and the items were moved.
  Future<bool> trash(List<MediaItem> items);

  /// Takes items back out of the trash. Ids not in the trash are ignored.
  Future<bool> restore(List<TrashedItem> items);

  /// Which of [ids] ([kinds] parallel: 'image' / 'video') are still in the trash (others were restored or purged).
  Future<List<TrashedItem>> stillTrashed(List<String> ids, List<String> kinds);

  /// Plays a video or opens a photo in the phone's own viewer.
  Future<void> openInGallery(MediaItem item);
}
