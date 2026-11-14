# PC Cleaner – Dọn dẹp máy tính

Ứng dụng dọn dẹp ổ đĩa cho **Windows** và **macOS**, viết bằng Python, giao diện cửa sổ (pywebview).

Tài liệu thuyết minh tính năng và nguyên lý hoạt động: [docs/thuyet-minh.md](docs/thuyet-minh.md).

## Tính năng hiện có (giai đoạn 1–2)

- **Tổng quan ổ đĩa**: dung lượng đã dùng/còn trống của từng ổ và thư mục cá nhân.
- **Phân tích dung lượng**: quét một ổ hoặc thư mục, xem cây thư mục theo dung lượng kèm sơ đồ treemap, bấm để đi sâu vào từng thư mục.
- **File lớn nhất**, **file cũ ít dùng** (không sửa trong 6 tháng / 1 năm / 2 năm), **dung lượng theo loại file**.
- **File trùng lặp**: lọc theo kích thước → băm nhanh đầu/cuối file → SHA-256 toàn bộ. Chỉ liệt kê file giống nhau tuyệt đối; mặc định giữ bản cũ nhất.
- **Khu cách ly + hoàn tác**: không xóa thẳng. File được chuyển vào khu cách ly, có nút *Hoàn tác* trả về chỗ cũ, và *Xóa hẳn* khi chắc chắn.
- **Nhật ký** mọi thao tác.
- Kết quả quét và mã băm được lưu trong SQLite, lần sau quét trùng nhanh hơn.

## Nguyên tắc an toàn

- Quét chỉ **đọc**, không thay đổi gì.
- Không bao giờ di chuyển/xóa file trong thư mục hệ thống và chương trình
  (Windows: `Windows`, `Program Files`, `ProgramData`, `AppData`…; macOS: `/System`, `/Library`, `/Applications`, `~/Library`…).
- Không theo symlink/junction, không tính trùng hard link.
- Máy chủ giao diện chỉ nghe ở `127.0.0.1` và yêu cầu mã bí mật sinh mỗi lần mở.

## Chạy thử

Cần Python 3.10 trở lên.

```bash
pip install -r requirements.txt   # pywebview, để mở cửa sổ riêng
python run.py                      # mở cửa sổ ứng dụng
python run.py --browser            # hoặc mở trong trình duyệt
```

Dữ liệu ứng dụng (cache, khu cách ly, nhật ký):
- Windows: `%LOCALAPPDATA%\PCCleaner`
- macOS: `~/Library/Application Support/PCCleaner`

## Đóng gói .exe / .app

GitHub Actions (`.github/workflows/build.yml`) chạy kiểm thử trên Windows và macOS rồi đóng gói bằng PyInstaller.
Tải bản dựng ở tab **Actions → build → Artifacts**. Đóng gói tay:

```bash
pip install -r requirements-build.txt
pyinstaller --noconfirm --windowed --name PCCleaner --add-data "pccleaner/web:pccleaner/web" run.py   # macOS
pyinstaller --noconfirm --windowed --name PCCleaner --add-data "pccleaner/web;pccleaner/web" run.py   # Windows
```

## Kiểm thử

```bash
python -m unittest discover -s tests -v
```

## Lộ trình

- [x] Giai đoạn 1: quét ổ đĩa, báo cáo dung lượng, file lớn, giao diện
- [x] Giai đoạn 2: tìm file trùng lặp chính xác
- [x] Ảnh gần giống nhau (perceptual hash)
- [x] Rác hệ thống: Temp, bản cập nhật cũ, crash dump, thumbnail cache (Windows); `~/Library/Caches`, logs (macOS)
- [x] Chương trình khởi động/chạy nền: chỉ tắt, không gỡ, bật lại 1 chạm; tạo điểm khôi phục trước (Windows)
- [x] Gợi ý sắp xếp thư mục, xem trước trước khi di chuyển
- [x] Dọn dẹp theo lịch
- [x] Giai đoạn A: an toàn dữ liệu (0.3.0)
- [x] Giai đoạn B: kiến trúc và kiểm thử (0.4.0)
- [x] Giai đoạn C: giao diện, tiếng Anh, chế độ tối (0.5.0)
- [ ] Giai đoạn D: bộ cài, ký số, tự cập nhật, khu đồng hành (0.6.0, đang làm)
- [ ] Giai đoạn F: nhiều thiết bị
