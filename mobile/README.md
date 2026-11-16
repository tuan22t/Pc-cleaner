# PC Cleaner cho Android

Bản điện thoại của PC Cleaner, viết bằng Flutter. Dọn ảnh trùng y hệt, ảnh giống nhau,
ảnh mờ hoặc tối, ảnh chụp màn hình, video nặng, và chế độ "vuốt để dọn".

Nguyên tắc an toàn (giống bản máy tính):
- Quét chỉ đọc. Không gì bị xóa khi người dùng chưa xem và bấm xác nhận.
- Xóa = chuyển vào Thùng rác của Android (giữ 30 ngày), qua hộp xác nhận của chính Android.
- Mỗi nhóm ảnh luôn giữ lại ít nhất 1 ảnh; ảnh yêu thích không bao giờ được chọn sẵn.
- Nhật ký ghi lại mọi lần dọn, có nút Khôi phục.
- Bản phát hành không có quyền Internet (CI kiểm tra tệp APK).

Cấu trúc:
- `lib/core/` thuật toán (dHash giống bản máy tính, tương quan ảnh 16x16, độ nét), nhóm ảnh, nhật ký, quét.
- `lib/data/` cầu nối MediaStore (`android_media_source.dart` + `android/.../MainActivity.kt`) và thư viện ảnh giả lập để kiểm thử.
- `lib/ui/` các màn hình.
- `assets/promo/promo.json` dùng chung với bản máy tính; ảnh tải lúc đóng gói.

Lệnh:
```
flutter test                                   # kiểm thử
PCCLEANER_SCREENSHOTS=build/screens flutter test test/screenshots_test.dart
python3 tool/i18n_keys.py                      # chuỗi chưa dịch tiếng Anh
flutter run --dart-define=DEMO=true            # chạy trên thư viện ảnh giả lập
flutter build apk --release
```
