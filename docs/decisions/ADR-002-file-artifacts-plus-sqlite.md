# ADR-002: File Artifacts + SQLite Database Metadata

* **Trạng thái**: Approved
* **Tác giả**: Principal Architect
* **Ngày**: 2026-07-14

---

## 1. Bối cảnh (Context)
Ứng dụng cần lưu giữ thông tin cấu hình dự án, tiến độ thực hiện của các công việc (Jobs) chạy nền, dữ liệu phân tích video lớn (keyframes, transcripts, observations) và video thành phẩm. Lưu trữ toàn bộ dữ liệu này vào một cơ sở dữ liệu quan hệ duy nhất sẽ gây phình to DB và làm giảm hiệu năng, trong khi chỉ dùng tệp tin phẳng (flat files) lại khó truy vấn trạng thái lịch sử và báo cáo chi phí.

## 2. Quyết định (Decision)
Chúng ta quyết định áp dụng chiến lược lưu trữ lai (Hybrid Storage Strategy):

1. **SQLite Database (`artifacts/project.db`)**:
   - Sử dụng để lưu trữ các thông tin quan hệ gọn nhẹ (Metadata): thông tin dự án, cấu hình job, trạng thái hiện tại của stage, thông tin chi phí API (Cost Metadata) và nhật ký lỗi.
   - Cho phép giao diện UI dễ dàng truy vấn lịch sử công việc và lập báo cáo nhanh.
2. **File-based Versioned Artifacts (`artifacts/`)**:
   - Mọi kết quả trung gian có cấu trúc phức tạp (như danh sách quan sát, đồ thị sự kiện, dàn ý câu chuyện, kịch bản thuyết minh) được lưu trữ dưới dạng các tệp tin JSON phẳng có schema định sẵn.
   - Các tài nguyên nhị phân lớn (như hình ảnh keyframes, audio WAV/MP3, video MP4) được lưu trữ trực tiếp trên đĩa cứng trong thư mục dự án.
   - Mỗi file Artifact đi kèm thông tin phiên bản (`schema_version`), hàm băm nội dung đầu vào (`input_hash`) và checksum kiểm định để phục vụ cơ chế khôi phục chạy từ điểm dừng lỗi (Resumable Processing).

## 3. Hệ quả (Consequences)
* **Ưu điểm**:
  - Giữ cơ sở dữ liệu SQLite siêu nhỏ gọn, dễ sao lưu và bảo trì.
  - Các tệp tin Artifact độc lập giúp lập trình viên dễ dàng debug thủ công bằng cách mở trực tiếp file JSON hoặc file media trung gian.
  - Tối ưu hiệu năng đọc/ghi tài nguyên lớn.
* **Nhược điểm**:
  - Phải quản lý đồng bộ thủ công giữa các bản ghi trong SQLite và sự tồn tại thực tế của các file Artifact trên đĩa.
