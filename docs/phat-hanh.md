# Phát hành một phiên bản mới

## Các bước mỗi lần phát hành

1. Sửa số phiên bản trong `pccleaner/__init__.py` (`__version__`).
   - Bản ổn định: `0.6.1`.
   - Bản thử nghiệm: `0.7.0-beta.1`.
2. Viết mục `## <số phiên bản>` ở đầu `CHANGELOG.md`, nói ngắn gọn có gì mới.
3. Gộp vào nhánh `main`, rồi gắn thẻ đúng số phiên bản và đẩy lên:
   `git tag v0.6.1 && git push origin v0.6.1`
4. GitHub Actions sẽ tự làm phần còn lại:
   - chạy toàn bộ kiểm thử;
   - đóng gói bộ cài Windows và DMG cho Mac;
   - cài, cập nhật, gỡ thử trên máy ảo;
   - đưa hai tệp lên kho phát hành công khai;
   - ký thông báo cập nhật.

   Nếu một bước hỏng thì không có gì được phát hành. Bản beta chỉ đến người chọn
   kênh Thử nghiệm. Bản ổn định đến cả hai kênh.

## Cài đặt một lần (Settings → Secrets and variables → Actions của kho mã)

Bộ cài và thông báo cập nhật được đưa lên kho công khai `tuan22t/pc-cleaner-releases` (ghi trong `.github/workflows/build.yml`).

| Tên | Loại | Dùng để |
|---|---|---|
| `RELEASES_TOKEN` | Secret | Token GitHub (fine-grained) có quyền Contents: Read and write trên kho công khai đó (đã tạo, hết hạn 13/11/2027) |
| `UPDATE_SIGNING_KEY` | Secret | Khóa riêng để ký thông báo cập nhật (64 ký tự hex) |
| `WIN_SIGN_COMMAND` | Secret | Lệnh ký số Windows, có `$f` ở chỗ tên tệp (khi đã có chứng chỉ) |
| `MAC_CERT_P12`, `MAC_CERT_PASSWORD`, `MAC_SIGN_IDENTITY` | Secret | Chứng chỉ Developer ID của Apple (p12 dạng base64) |
| `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` | Secret | Công chứng (notarize) với Apple |

Khi chưa có chứng chỉ, các bước ký và công chứng được bỏ qua. Ứng dụng vẫn đóng gói
được, nhưng Windows sẽ hiện cảnh báo SmartScreen và Mac sẽ hiện cảnh báo Gatekeeper.

## Khóa ký bản cập nhật

- Tạo cặp khóa: `python tools/sign_update.py --new-key`.
- Khóa **riêng** (private) đặt vào secret `UPDATE_SIGNING_KEY`. Cất thêm một bản sao
  ở nơi an toàn, ngoài máy tính và ngoài kho mã.
- Khóa **công khai** (public) ghi vào `UPDATE_PUBLIC_KEY` trong
  `pccleaner/updater.py`.
- `UPDATE_BASE_URL` trong cùng tệp là
  `https://github.com/tuan22t/pc-cleaner-releases/releases/download/updates`.

Mất khóa riêng thì các bản đã cài sẽ không nhận được cập nhật tự động nữa: người dùng
phải tải bản mới bằng tay. Lộ khóa riêng thì người khác có thể giả bản cập nhật. Khi
đó cần đổi khóa ngay và phát hành bản mới có khóa công khai mới.

## Ứng dụng kiểm tra những gì trước khi cài bản cập nhật

1. Thông báo cập nhật có chữ ký Ed25519 khớp khóa công khai trong ứng dụng, đúng tên
   ứng dụng, đúng kênh, và số phiên bản lớn hơn bản đang dùng.
2. Tệp tải về đúng kích thước và đúng mã SHA-256 ghi trong thông báo.
3. Người dùng bấm "Tải và cài". Ứng dụng không tự tải hay tự cài.
4. Windows: bộ cài chạy với cửa sổ tiến trình rồi mở lại ứng dụng. Mac: mở DMG để
   người dùng kéo bản mới vào Applications.

Bản cập nhật chỉ thay chương trình. Dữ liệu, nhật ký và khu cách ly nằm trong thư mục
dữ liệu riêng nên không bị đụng tới.

## Ảnh các cơ sở đồng hành

Danh sách nằm ở `pccleaner/web/promo/promo.json`. Khi đóng gói,
`tools/fetch_promo_images.py` tải ảnh từ `image_url` và thu nhỏ còn 640×336. Muốn
đổi nội dung thì sửa tệp này rồi phát hành bản mới.
