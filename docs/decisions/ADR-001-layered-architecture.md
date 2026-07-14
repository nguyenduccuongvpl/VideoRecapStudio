# ADR-001: Clean Layered Architecture (Kiến trúc phân tầng sạch)

* **Trạng thái**: Approved
* **Tác giả**: Principal Architect
* **Ngày**: 2026-07-14

---

## 1. Bối cảnh (Context)
Dự án thế hệ trước (V1) gặp nhiều lỗi khó bảo trì do việc trộn lẫn mã nguồn xử lý giao diện (UI Tkinter) với logic gọi API AI và các câu lệnh FFmpeg. Khi có sự thay đổi về nhà cung cấp dịch vụ AI hoặc thư viện UI, lập trình viên phải sửa đổi mã nguồn ở hầu hết mọi tệp tin, dẫn đến lỗi hồi quy (regression) cao và khó viết unit tests.

## 2. Quyết định (Decision)
Chúng ta quyết định áp dụng mô hình **Clean Layered Architecture** (Kiến trúc phân tầng sạch) với các quy tắc ranh giới nghiêm ngặt:

1. **Domain Layer**: Chỉ chứa các thực thể nghiệp vụ cốt lõi và chính sách chất lượng. Không có sự phụ thuộc vào bất kỳ thư viện ngoài nào (kể cả PySide6 hay SQLite).
2. **Application Layer**: Điều phối luồng chạy (Use Cases) và khai báo các interfaces (Protocols) cho các dịch vụ ngoại vi. Tầng này chỉ được phép import từ Domain Layer.
3. **Infrastructure Layer**: Triển khai cụ thể các interfaces của Application Layer (FFmpeg, SQLite, các API client). Các SDK ngoài chỉ được import tại tầng này.
4. **Presentation Layer**: Chứa mã nguồn CLI và UI PySide6. Chỉ gọi các use cases của tầng Application, không chứa bất kỳ logic nghiệp vụ hay câu lệnh CLI nào.

Để đảm bảo quy tắc này, chúng ta viết một unit test phân tích tĩnh AST (`test_architecture.py`) tự động quét mã nguồn ở domain/application và báo lỗi lập tức nếu phát hiện các import vi phạm ranh giới.

## 3. Hệ quả (Consequences)
* **Ưu điểm**:
  - Dễ viết unit tests bằng cách mock các interface ở tầng Application.
  - Độc lập hoàn toàn với framework UI và các SDK dịch vụ (AI, Speech).
  - Tránh lỗi hồi quy khi cập nhật mã nguồn ở các phần khác nhau của hệ thống.
* **Nhược điểm**:
  - Tăng số lượng tệp tin và các class trung gian (do phải định nghĩa Interface và Mapper).
