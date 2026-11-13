# Thuyết minh phần mềm PC Cleaner – Dọn dẹp máy tính

Phiên bản 0.1 · Tháng 11/2026 · Dùng cho Windows và macOS

## 1. Giới thiệu

Sau một thời gian sử dụng, ổ đĩa máy tính thường bị đầy bởi video cũ, bộ cài đặt đã dùng xong, ảnh chụp bị sao chép nhiều lần và đủ loại file người dùng không còn nhớ tới. Máy chạy chậm, báo hết dung lượng, nhưng người dùng không biết nên xóa gì để không mất dữ liệu quan trọng.

PC Cleaner giúp trả lời ba câu hỏi:

1. Cái gì đang chiếm chỗ trên máy?
2. Trong số đó, cái gì có thể dọn được?
3. Dọn thế nào để không bao giờ mất nhầm dữ liệu?

Nguyên tắc xuyên suốt của phần mềm là **an toàn trước, gọn gàng sau**: phần mềm chỉ đọc khi quét, không tự ý xóa bất cứ thứ gì, và mọi thao tác dọn dẹp đều có thể hoàn tác.

![Trang chủ của phần mềm](images/trang-chu.png)

## 2. Tính năng và tác dụng

| Tính năng | Phần mềm làm gì | Tác dụng với người dùng |
|---|---|---|
| Tổng quan ổ đĩa | Hiện dung lượng đã dùng và còn trống của từng ổ, cảnh báo khi ổ sắp đầy | Biết ngay máy còn bao nhiêu chỗ |
| Thư mục chiếm chỗ | Vẽ sơ đồ ô vuông: thư mục càng nặng thì ô càng to; bấm vào để xem bên trong | Tìm ra "thủ phạm" chiếm dung lượng trong vài giây |
| File lớn nhất | Liệt kê các file nặng nhất, kèm loại file và thời gian sửa lần cuối | Dọn nhanh những file chiếm nhiều chỗ nhất |
| File cũ lâu không dùng | Tìm file lớn không được sửa trong 6 tháng, 1 năm hoặc 2 năm | Phát hiện video, bộ cài, bản sao lưu đã bị bỏ quên |
| File trùng lặp | Tìm các file giống hệt nhau về nội dung, dù khác tên hoặc nằm ở thư mục khác | Bỏ bản thừa, giữ lại một bản, lấy lại dung lượng bị lãng phí |
| Theo loại file | Thống kê video, ảnh, tài liệu, bộ cài… mỗi loại chiếm bao nhiêu | Hiểu thói quen lưu trữ, biết nên dọn nhóm nào trước |
| Khu cách ly và hoàn tác | File bị dọn được cất vào khu cách ly; có nút Lấy lại và Xóa vĩnh viễn | Không sợ xóa nhầm, đổi ý lúc nào cũng được |
| Nhật ký thao tác | Ghi lại mọi lần dọn, lấy lại, xóa vĩnh viễn và lý do file được giữ nguyên | Kiểm tra lại được mọi việc phần mềm đã làm |

### 2.1. Thư mục chiếm chỗ

Sau khi quét, phần mềm hiện sơ đồ ô vuông (treemap). Mỗi ô là một thư mục hoặc file, diện tích ô tỉ lệ với dung lượng. Bên dưới là danh sách sắp xếp từ nặng đến nhẹ. Bấm vào một thư mục để đi sâu vào trong, bấm "Quay lại" hoặc thanh đường dẫn phía trên để trở ra. Nút "Xem vị trí" mở thư mục đó trong File Explorer (Windows) hoặc Finder (macOS).

![Sơ đồ thư mục chiếm chỗ](images/thu-muc-chiem-cho.png)

### 2.2. File lớn nhất và file cũ lâu không dùng

Hai báo cáo này liệt kê file theo dung lượng, kèm nhóm (Video, Ảnh, Tài liệu, Nén/bộ cài…) và thời gian sửa lần cuối ghi dễ hiểu, ví dụ "3 năm trước". Người dùng đánh dấu những file không cần nữa, thanh dưới cùng cho biết đã chọn bao nhiêu file và sẽ giải phóng bao nhiêu dung lượng. File thuộc hệ thống hoặc chương trình có biểu tượng khóa và không thể chọn.

![Danh sách file lớn nhất](images/file-lon.png)

### 2.3. File trùng lặp

Phần mềm tìm những file có nội dung giống hệt nhau từng byte, kể cả khi tên khác nhau (ví dụ "IMG_001.jpg" và "IMG_001 (1).jpg"). Mỗi nhóm trùng được hiện cùng nhau. Phần mềm tự đề xuất giữ lại một bản (nhãn "Giữ lại") và đánh dấu sẵn các bản thừa. Người dùng có thể đổi lựa chọn trước khi dọn.

Cách chọn bản giữ lại, theo thứ tự ưu tiên:

1. Bản còn tồn tại trên ổ đĩa.
2. Bản nằm ngoài các thư mục tạm như Downloads, Desktop.
3. Bản có tên không giống bản sao (không có chữ "copy", "(1)", "bản sao"…).
4. Bản cũ nhất, rồi đến bản có đường dẫn ngắn nhất.

![Kết quả tìm file trùng lặp](images/file-trung.png)

### 2.4. Dọn dẹp an toàn và hoàn tác

Khi bấm "Dọn", phần mềm hỏi lại và liệt kê đúng những file sắp được dọn. Sau khi đồng ý, file được chuyển vào khu cách ly chứ không bị xóa. Ngay sau đó có thông báo kèm nút "Hoàn tác" để đổi ý tức thì. Trong mục "Khu cách ly & hoàn tác", mỗi lần dọn là một dòng với nút "Lấy lại" (trả mọi file về đúng chỗ cũ) và "Xóa vĩnh viễn" (giải phóng dung lượng thật sự, phải xác nhận thêm một lần).

![Hộp thoại xác nhận trước khi dọn](images/xac-nhan-don.png)

![Khu cách ly và nút lấy lại](images/khu-cach-ly.png)

## 3. Hướng dẫn sử dụng nhanh

1. Mở phần mềm, ở trang Tổng quan bấm "Quét thư mục này" ở ô Thư mục cá nhân (nên bắt đầu ở đây), hoặc chọn một ổ đĩa hay một thư mục khác.
2. Chờ thanh tiến trình chạy xong. Phần mềm tự chuyển sang trang Thư mục chiếm chỗ.
3. Xem các báo cáo ở menu bên trái: File lớn nhất, File cũ lâu không dùng, File trùng lặp, Theo loại file.
4. Đánh dấu những file không cần, bấm "Dọn", đọc lại danh sách và bấm "Dọn ngay".
5. Dùng máy vài ngày. Nếu không thiếu gì, vào Khu cách ly và bấm "Xóa vĩnh viễn" để giải phóng dung lượng. Nếu cần lại file nào, bấm "Lấy lại".

## 4. Nguyên lý hoạt động

### 4.1. Kiến trúc tổng thể

Phần mềm gồm ba lớp, tất cả chạy ngay trên máy người dùng, không gửi dữ liệu ra ngoài Internet:

| Lớp | Thành phần | Vai trò |
|---|---|---|
| Giao diện | Cửa sổ ứng dụng (pywebview) hiển thị trang HTML/JavaScript | Hiện báo cáo, nhận thao tác của người dùng |
| Máy chủ nội bộ | Máy chủ HTTP nhỏ viết bằng Python, chỉ nghe ở địa chỉ 127.0.0.1 | Nhận yêu cầu từ giao diện, chạy tác vụ quét/tìm trùng ở chế độ nền |
| Lõi xử lý và dữ liệu | Các mô-đun quét, tìm trùng, cách ly; cơ sở dữ liệu SQLite | Đọc ổ đĩa, tính toán, lưu kết quả và nhật ký |

Máy chủ nội bộ sinh một mã bí mật ngẫu nhiên mỗi lần mở phần mềm. Mọi yêu cầu phải kèm mã này, nên trang web hay chương trình khác trên máy không thể điều khiển phần mềm.

### 4.2. Quét ổ đĩa

Bộ quét đi qua cây thư mục theo kiểu "ngăn xếp": lấy một thư mục, đọc danh sách bên trong, thư mục con được đưa vào ngăn xếp để đọc tiếp, còn với mỗi file thì ghi lại tên, đuôi, dung lượng và thời gian sửa. Quá trình này **chỉ đọc**, không mở nội dung file và không thay đổi gì.

Một số điểm kỹ thuật bảo đảm kết quả đúng và an toàn:

- Không đi theo lối tắt (symlink) và junction trên Windows, để tránh vòng lặp vô tận và tránh đếm một thư mục hai lần. Thư mục OneDrive vẫn được quét bình thường.
- Trên macOS và Linux, các "hard link" (nhiều tên trỏ tới cùng một dữ liệu) chỉ được tính dung lượng một lần.
- Bỏ qua các vùng ảo hoặc do hệ thống quản lý như thư mục khôi phục hệ thống của Windows, /System/Volumes của macOS.
- Thư mục không có quyền đọc được bỏ qua và đếm lại để báo cho người dùng, quá trình quét không bị dừng.

Sau khi đọc xong, dung lượng được cộng dồn từ thư mục con lên thư mục cha chỉ trong một lượt duyệt ngược, nhờ thư mục con luôn được đánh số sau thư mục cha. Toàn bộ kết quả được ghi vào SQLite, nên mở lại báo cáo cũ hay chuyển giữa các trang không cần quét lại. Người dùng có thể bấm "Dừng lại" bất cứ lúc nào; khi đó kết quả dang dở được bỏ đi, không để lại dữ liệu sai.

### 4.3. Tìm file trùng lặp

So sánh trực tiếp mọi cặp file sẽ rất chậm. Phần mềm dùng phương pháp lọc ba tầng, mỗi tầng loại bỏ phần lớn ứng viên trước khi đến tầng tốn kém hơn:

| Tầng | Cách làm | Vì sao |
|---|---|---|
| 1. Kích thước | Nhóm các file có cùng dung lượng (byte) | Hai file khác dung lượng chắc chắn khác nhau. Không cần đọc file, rất nhanh |
| 2. Băm nhanh | Đọc 64 KB đầu và 64 KB cuối của file, tính mã SHA-256 | Loại nhanh phần lớn file cùng dung lượng nhưng khác nội dung |
| 3. Băm toàn bộ | Đọc toàn bộ file, tính mã SHA-256 | Xác nhận chắc chắn hai file giống hệt nhau từng byte |

SHA-256 là hàm băm mật mã: mỗi nội dung cho ra một "dấu vân tay" dài 64 ký tự. Hai file khác nhau gần như không thể có cùng dấu vân tay, nên phần mềm chỉ báo trùng khi nội dung thật sự giống nhau. Phần mềm đã được kiểm thử với cả trường hợp hai file cùng dung lượng, cùng phần đầu và phần cuối nhưng khác một byte ở giữa: chúng không bị báo trùng.

Mã băm được lưu lại kèm dung lượng và thời gian sửa của file. Lần tìm sau, file nào chưa thay đổi thì dùng lại mã cũ, không phải đọc lại.

Với các file OneDrive chỉ lưu trên mây (chưa tải về máy), phần mềm không tính mã băm, vì đọc chúng sẽ khiến Windows tải file về.

### 4.4. Cách ly, hoàn tác và xóa vĩnh viễn

Khi dọn, mỗi file được **di chuyển** (không xóa) vào thư mục cách ly riêng của phần mềm:

- Windows: `%LOCALAPPDATA%\PCCleaner\quarantine`
- macOS: `~/Library/Application Support/PCCleaner/quarantine`

Mỗi lần dọn có một mã riêng. Với từng file, phần mềm ghi vào nhật ký: vị trí gốc, vị trí trong khu cách ly, dung lượng, lý do và thời điểm.

- **Lấy lại**: đọc nhật ký và chuyển từng file về đúng vị trí gốc. Nếu ở vị trí gốc đã có một file khác, phần mềm không ghi đè mà báo lại cho người dùng.
- **Xóa vĩnh viễn**: chỉ thực hiện khi người dùng bấm và xác nhận. Phần mềm xóa bản trong khu cách ly và chỉ cộng vào "dung lượng đã giải phóng" những file thật sự được xóa.

### 4.5. Các lớp bảo vệ chống mất dữ liệu

| Lớp bảo vệ | Cách hoạt động |
|---|---|
| Quét chỉ đọc | Bộ quét không mở, không sửa, không xóa file nào |
| Thư mục được bảo vệ | Không bao giờ dọn file trong thư mục hệ thống và chương trình. Windows: Windows, Program Files, ProgramData, AppData… macOS: /System, /Library, /Applications, ~/Library… Không bao giờ dọn ổ đĩa gốc hay thư mục dữ liệu của chính phần mềm |
| Chống lối tắt đánh lừa | Kiểm tra cả đường dẫn thật của file sau khi đi qua mọi lối tắt, nên một lối tắt trỏ vào thư mục hệ thống không thể dùng để dọn file hệ thống |
| Kiểm tra lại file trùng | Ngay trước khi dọn, băm lại từng file trùng để chắc nội dung chưa đổi kể từ lúc quét |
| Luôn giữ một bản | Nếu người dùng lỡ chọn tất cả các bản trong một nhóm trùng, phần mềm tự giữ lại một bản |
| Xác nhận trước khi dọn | Hộp thoại liệt kê đúng những file sắp được dọn |
| Cách ly thay vì xóa | File bị dọn vẫn nằm trong khu cách ly, lấy lại được bất cứ lúc nào |
| Không ghi đè khi lấy lại | Nếu vị trí cũ đã có file khác, file đó được giữ nguyên |
| Nhật ký đầy đủ | Mọi thao tác và mọi file bị từ chối kèm lý do đều được ghi lại |

## 5. Yêu cầu hệ thống và cài đặt

- Windows 10/11 (64-bit) hoặc máy Mac chip Apple (M1 trở lên). Bản cho Mac chip Intel chưa được đóng gói sẵn, nhưng vẫn chạy được từ mã nguồn.
- Bản đóng gói sẵn (.exe cho Windows, .app cho macOS) được tạo tự động trên GitHub Actions sau mỗi lần cập nhật mã nguồn.
- Bản .app cho macOS chưa được ký số: lần đầu mở, bấm chuột phải vào ứng dụng rồi chọn "Open".
- Chạy từ mã nguồn: cài Python 3.10 trở lên, chạy `pip install -r requirements.txt` rồi `python run.py`.

Dữ liệu của phần mềm (bộ nhớ đệm kết quả quét, khu cách ly, nhật ký) nằm trong thư mục `PCCleaner` đã nêu ở mục 4.4. Phần mềm không gửi bất kỳ dữ liệu nào ra ngoài máy.

## 6. Kiểm thử

Bộ kiểm thử tự động chạy trên cả Windows và macOS sau mỗi lần cập nhật, gồm các trường hợp:

- Dung lượng thư mục được cộng dồn đúng.
- Chỉ báo trùng những file giống hệt nhau; file cùng dung lượng, cùng đầu cuối nhưng khác ở giữa không bị báo trùng.
- Dọn rồi lấy lại trả file về đúng chỗ; xóa vĩnh viễn báo đúng dung lượng.
- File hệ thống bị từ chối, kể cả khi đi qua lối tắt.
- Chọn tất cả bản trùng vẫn giữ lại một bản; file đã thay đổi sau khi quét không bị dọn.
- Lấy lại không ghi đè file mới; dừng quét giữa chừng không để lại dữ liệu.
- Quét bỏ qua lối tắt và junction, không lặp vô tận.

## 7. Lộ trình phát triển

| Giai đoạn | Nội dung | Trạng thái |
|---|---|---|
| 1 | Quét ổ đĩa, báo cáo dung lượng, file lớn, file cũ, giao diện | Đã xong |
| 2 | Tìm file trùng lặp chính xác, khu cách ly và hoàn tác | Đã xong |
| 3 | Tìm ảnh gần giống nhau (ảnh chụp liên tiếp, ảnh đã nén lại) | Sắp làm |
| 4 | Dọn rác hệ thống: thư mục Temp, bản cập nhật cũ, file lỗi, bộ nhớ đệm ảnh thu nhỏ (Windows); bộ nhớ đệm và nhật ký ứng dụng (macOS) | Sắp làm |
| 5 | Quản lý chương trình khởi động cùng máy và chạy nền: chỉ tắt, không gỡ, bật lại một chạm; tạo điểm khôi phục hệ thống trước khi thay đổi (Windows) | Sắp làm |
| 6 | Gợi ý sắp xếp thư mục, xem trước trước khi di chuyển | Sắp làm |
| 7 | Dọn dẹp theo lịch | Sắp làm |
