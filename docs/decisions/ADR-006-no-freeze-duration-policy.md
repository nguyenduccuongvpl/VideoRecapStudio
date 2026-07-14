# ADR-006: Prohibiting Freeze-Frame for Duration Mismatch

* **Trạng thái**: Approved
* **Tác giả**: Principal Architect
* **Ngày**: 2026-07-14

---

## 1. Bối cảnh (Context)
Khi thời lượng của giọng thuyết minh (Narration Audio) dài hơn thời lượng của phân đoạn video được gán, hệ thống V1 đã sử dụng kỹ thuật đóng băng khung hình cuối (freeze frame) hoặc làm chậm video để khớp thời gian. Điều này tạo ra các khoảng hình ảnh tĩnh giống như video bị treo, làm giảm nghiêm trọng tính thẩm mỹ và độ sống động của video recap.

## 2. Quyết định (Decision)
Chúng ta quyết định áp dụng chính sách **Nghiêm cấm đóng băng khung hình (Zero Freeze-Frame Policy)** để giải quyết vấn đề lệch thời lượng:

1. **Khớp động (Dynamic Clip Selection & Duration Fitting)**:
   - Trong quá trình lập lịch dòng thời gian (`PLANNING_TIMELINE`), hệ thống phải chọn các clip có thời lượng gốc dài hơn hoặc bằng thời lượng của giọng đọc thuyết minh.
   - Nếu một clip bị thiếu thời lượng, hệ thống phải mở rộng điểm kết thúc (Out point) của clip đó trong phạm vi cho phép của scene/shot gốc, hoặc tự động ghép thêm clip phụ liên quan từ video nguồn (có cùng Entity/Event).
2. **Quality Gate Rule**:
   - Bộ QA quét timeline và video render. Nếu phát hiện các khung hình bị đóng băng hoặc trùng lặp liên tục để bù thời lượng lệch lớn hơn 0.5 giây, báo cáo QA sẽ đánh dấu thất bại chỉ số `Q-FRZE` và đẩy Job sang `NEEDS_REVIEW`.

## 3. Hệ quả (Consequences)
* **Ưu điểm**:
  - Video đầu ra mượt mà, sống động liên tục, không bị cảm giác "đơ" hay giật hình.
  - Nâng cao tính chuyên nghiệp của thành phẩm.
* **Nhược điểm**:
  - Logic biên dịch dòng thời gian (`timeline.json`) trở nên phức tạp hơn rất nhiều, đòi hỏi cơ chế ghép nối clip động dựa trên Event và Entity.
