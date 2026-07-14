# ADR-007: PySide6 for Desktop Presentation Layer

* **Trạng thái**: Approved
* **Tác giả**: Principal Architect
* **Ngày**: 2026-07-14

---

## 1. Bối cảnh (Context)
Ứng dụng cần có giao diện Desktop chạy trên Windows hỗ trợ cả hai chế độ: Full Auto và Review Mode. Giao diện Review Mode yêu cầu các tính năng tương tác cao: hiển thị timeline, xem trước video đồng bộ hóa trực tiếp, chỉnh sửa text và nghe thử âm thanh, khóa các phân đoạn, hiển thị trạng thái log real-time và bảng biểu chỉ số QA. Bộ thư viện UI tích hợp sẵn của Python là Tkinter quá đơn sơ và khó lập trình các widget tương tác cao.

## 2. Quyết định (Decision)
Chúng ta quyết định chọn **PySide6** (Qt for Python) làm bộ thư viện UI chính thức cho Presentation Layer:

1. **Sử dụng Signals/Slots**:
   - Sử dụng cơ chế Signals/Slots an toàn luồng (thread-safe) của Qt để giao tiếp giữa Main UI Thread và các Background Worker Threads.
2. **Custom Widgets**:
   - Lập trình các widget chuyên biệt cho Timeline và Segment Editor bằng các class kế thừa từ `QWidget` và sử dụng layout của Qt để đáp ứng tính năng tương tác kéo thả, zoom, căn chỉnh thời lượng.
3. **Decoupling Business Logic**:
   - Nghiêm cấm đặt logic xử lý FFmpeg, gọi API hay lưu SQLite bên trong các class giao diện của Qt. UI chỉ đóng vai trò thu thập tham số, phát ra các signals gọi các Application Services và hiển thị dữ liệu được đẩy về.

## 3. Hệ quả (Consequences)
* **Ưu điểm**:
  - Giao diện hiện đại, mượt mà và hỗ trợ tùy chỉnh hoàn toàn (style-sheet, bo góc, dark-mode).
  - Khả năng xử lý đa luồng (threading) cực tốt, tránh hoàn toàn lỗi treo/đơ giao diện.
  - Hỗ trợ xây dựng các widget phức tạp cho dựng timeline và preview video.
* **Nhược điểm**:
  - Dung lượng đóng gói ứng dụng (package size) sẽ tăng đáng kể do bộ thư viện Qt khá nặng.
  - Tốn thêm thời gian viết code giao diện so với các framework đơn giản như Tkinter.
