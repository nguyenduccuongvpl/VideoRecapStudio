# ADR-008: Direct FFmpeg/ffprobe CLI via Subprocess

* **Trạng thái**: Approved
* **Tác giả**: Principal Architect
* **Ngày**: 2026-07-14

---

## 1. Bối cảnh (Context)
Ứng dụng cần gọi FFmpeg và ffprobe để phân tích media, cắt video, ghép âm thanh, trộn tiếng và chèn phụ đề. Có các wrapper Python như `ffmpeg-python` nhưng chúng thường không cập nhật kịp các filter mới nhất của FFmpeg, khó cấu hình chi tiết các tham số nén phức tạp, khó thu nhận dòng logs tiến trình thời gian thực (stderr progress parsing) và khó kiểm soát việc chấm dứt luồng con khi người dùng hủy bỏ tác vụ.

## 2. Quyết định (Decision)
Chúng ta quyết định gọi trực tiếp **FFmpeg & ffprobe CLI** thông qua thư viện `subprocess` tiêu chuẩn của Python:

1. **Subprocess Rules**:
   - **Nghiêm cấm** sử dụng tham số `shell=True` để tránh rủi ro bảo mật (command injection) và lỗi kiểm soát tiến trình trên Windows.
   - Luôn sử dụng danh sách tham số rõ ràng: `subprocess.Popen(["ffmpeg", "-y", "-i", ...])`.
2. **Tiến trình & Logs**:
   - Sử dụng các luồng đọc (streams reader) bất đồng bộ để đọc stdout và stderr của tiến trình con, phân tích tiến độ phần trăm (progress parsing) và đẩy sự kiện lên Event Bus về UI.
3. **Quản lý Vòng đời & Hủy bỏ**:
   - Lưu trữ tham chiếu tới đối tượng `Popen` của từng tác vụ đang chạy. Khi nhận tín hiệu hủy (cancellation), gọi hàm `kill()` hoặc gửi tín hiệu dừng tiến trình để giải phóng tài nguyên lập tức.

## 3. Hệ quả (Consequences)
* **Ưu điểm**:
  - Khả năng kiểm soát tuyệt đối các câu lệnh, tham số và filter của FFmpeg mà không bị giới hạn bởi thư viện bọc ngoài.
  - Dễ dàng bắt lỗi chính xác dựa trên mã thoát (exit codes) và stderr.
  - Quản lý cancellation triệt để, dọn dẹp tài nguyên tức thì khi có yêu cầu.
* **Nhược điểm**:
  - Phải tự viết mã phân tích cú pháp (parser) dòng lệnh và log của FFmpeg để hiển thị tiến độ.
  - Đòi hỏi lập trình viên có kiến thức sâu về các tham số dòng lệnh của FFmpeg.
