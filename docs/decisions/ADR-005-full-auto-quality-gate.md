# ADR-005: Full Auto Quality Gate & Fallback to Needs Review

* **Trạng thái**: Approved
* **Tác giả**: Principal Architect
* **Ngày**: 2026-07-14

---

## 1. Bối cảnh (Context)
Trong chế độ tự động hoàn toàn (Full Auto Mode), người dùng mong muốn bấm một nút và nhận được video recap hoàn thiện mà không cần kiểm duyệt. Tuy nhiên, AI hoặc các thuật toán xử lý âm thanh đôi khi tạo ra lỗi nghiêm trọng (như bịa tình tiết cốt truyện, clip không liên quan đến thoại, âm lượng thuyết minh bị vỡ). Việc xuất bản video bị lỗi chất lượng làm giảm trải nghiệm người dùng và thương hiệu phần mềm.

## 2. Quyết định (Decision)
Chúng ta quyết định áp dụng chính sách **Quality Gate** bắt buộc cho chế độ Full Auto Mode:

1. **Kiểm duyệt tự động trước khi xuất**:
   - Khi hoàn thành giai đoạn render video thử nghiệm (`preview.mp4`), hệ thống bắt buộc phải kích hoạt module QA chạy kiểm định độc lập đối chiếu các tiêu chí kỹ thuật và nghiệp vụ.
2. **Ngưỡng chất lượng tối thiểu**:
   - Nếu bất kỳ chỉ số chất lượng nào (như phát hiện câu thuyết minh không có bằng chứng, video có frame đen lỗi, âm lượng bị clipping) không đạt ngưỡng cấu hình tối thiểu, hệ thống **nghiêm cấm** việc xuất file `final.mp4`.
3. **Cơ chế Fallback**:
   - Job lập tức dừng tiến trình tự động và chuyển trạng thái sang `NEEDS_REVIEW`.
   - Giao diện người dùng sẽ hiển thị danh sách các lỗi QA được đánh dấu màu nổi bật trên timeline và chuyển sang **Review Mode**. Người dùng có thể sửa đổi thủ công hoặc chọn "Force Override QA" (nếu chấp nhận lỗi) để hoàn thành việc xuất bản.

## 3. Hệ quả (Consequences)
* **Ưu điểm**:
  - Đảm bảo 100% video xuất bản ở chế độ tự động đều đạt tiêu chuẩn chất lượng tối thiểu.
  - Ngăn ngừa các lỗi ngớ ngẩn do AI hoặc đồng bộ hóa gây ra.
* **Nhược điểm**:
  - Trải nghiệm Full Auto có thể bị gián đoạn giữa chừng và yêu cầu con người can thiệp khi có lỗi chất lượng.
