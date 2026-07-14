# Quality Gates & Metrics — VideoRecapStudio

Tài liệu này định nghĩa chi tiết các tiêu chuẩn chất lượng (Quality Gates), ngưỡng chấp nhận (Thresholds) và phương pháp đo lường tự động/bán tự động cho sản phẩm đầu ra của **VideoRecapStudio**.

---

## 1. Bảng Tiêu chuẩn Chất lượng (Quality Metrics Table)

Để đảm bảo video recap xuất bản đạt chất lượng chuyên nghiệp, hệ thống áp dụng các kiểm định nghiêm ngặt tại các chặng kiểm soát chất lượng (Quality Gates). Dưới đây là danh sách các chỉ số:

| Mã Metric | Tên Chỉ số | Ngưỡng chấp nhận (Threshold) | Phương pháp Đo lường & Công cụ kiểm tra | Giai đoạn kiểm tra |
| :--- | :--- | :--- | :--- | :--- |
| **Q-FACT** | Độ chính xác thực tế của quan sát (Observation Factual Accuracy) | **$\ge$ 95%** | Đo bằng cách so sánh mẫu ngẫu nhiên (hoặc đối chiếu chéo giữa AI Critic và Ground Truth). Tỷ lệ lỗi sai lệch thực tế trên tổng số quan sát phải nhỏ hơn 5%. | `OBSERVING` |
| **Q-EVID** | Tỷ lệ phân đoạn thoại có bằng chứng (Narration segments with evidence) | **100%** | Kiểm tra cấu trúc tệp `narration.json`. Mọi câu thoại (segment) phải chứa danh sách tham chiếu hợp lệ đến ít nhất 1 `evidence_ref` và `source time range` tồn tại thực tế. | `WRITING_NARRATION` |
| **Q-UNSP** | Số lượng khẳng định không có căn cứ (Critical unsupported claims) | **0** | Sử dụng AI Critic duyệt qua `narration.json` đối chiếu với `observations.json`. Phát hiện và đếm các câu khẳng định nội dung cốt truyện nhưng không có bằng chứng hình ảnh/âm thanh tương thích hỗ trợ. | `WRITING_NARRATION` |
| **Q-ORDR** | Độ chính xác thứ tự sự kiện (Event ordering accuracy) | **$\ge$ 98%** | Kiểm tra tính liên tục thời gian trong `event_graph.json`. Không được phép có sự kiện kết quả xảy ra trước sự kiện nguyên nhân theo dòng thời gian video gốc (trừ khi có ý đồ nghệ thuật được đánh dấu rõ). | `BUILDING_EVENTS` |
| **Q-RELV** | Độ tương quan giữa clip và lời thuyết minh (Clip relevance to narration) | **$\ge$ 90%** | Sử dụng mô hình Vision-Language để đánh giá điểm tương quan ngữ nghĩa (Semantic similarity score) giữa văn bản thuyết minh và clip tương ứng trong `timeline.json`. | `PLANNING_TIMELINE` |
| **Q-FRZE** | Số lượng khung hình đóng băng lỗi (Freeze frame used to fill duration) | **0** | Cấm sử dụng bộ lọc `tpad` hoặc đóng băng hình ảnh để kéo dài thời lượng video khi giọng đọc dài hơn video (ngoại trừ trường hợp người dùng cố tình cấu hình). Đo bằng cách kiểm tra trùng lặp pixel liên tục ở cuối clip. | `PLANNING_TIMELINE` / `RENDERING_PREVIEW` |
| **Q-BLCK** | Khung hình đen ngoài ý muốn (Unintentional black frames) | **0** | Sử dụng FFmpeg filter `blackdetect` để quét qua video đã render. Không chấp nhận bất kỳ khoảng đen nào có độ dài > 0.5 giây không nằm trong kịch bản chuyển cảnh gốc. | `VALIDATING_PREVIEW` / `VALIDATING_FINAL` |
| **Q-CLIP** | Hiện tượng vỡ tiếng (Audio clipping / Distortion) | **0** | Kiểm tra mức decibel cực đại của file âm thanh đầu ra `narration.wav` và file video mix. Đảm bảo mức âm lượng không vượt quá 0 dBFS (âm lượng lý thuyết tối đa gây vỡ tiếng). | `GENERATING_SPEECH` / `VALIDATING_PREVIEW` |
| **Q-REND** | Tỷ lệ render thành công (Job render success rate) | **$\ge$ 98%** | Đo lường hiệu năng hệ thống trên tổng số lần chạy render thực tế. Tỷ lệ lỗi FFmpeg/hệ thống trong quá trình xuất video phải thấp hơn 2%. | `RENDERING_FINAL` |
| **Q-GOLD** | Regression testing với các ca kiểm thử mẫu chuẩn (Golden regression test) | **Pass 3 lần liên tiếp** | Các thay đổi về code core hoặc prompt phải chạy thành công và tạo ra kết quả giống/tốt hơn trên 3 bộ test case mẫu chuẩn (Golden test cases) trước khi được phát hành. | `QA / CI-CD` |

---

## 2. Quy trình Thực thi Quality Gate & Cơ chế Phục hồi (Failure Taxonomy & Fallback)

### 2.1. Tự động chuyển đổi sang NEEDS_REVIEW
Trong chế độ **Full Auto Mode**, hệ thống sẽ tự động chạy các script QA ở giai đoạn `VALIDATING_PREVIEW` và `VALIDATING_FINAL` để đánh giá các chỉ số chất lượng:
1. **Kiểm tra trước khi Render (Pre-render Gate)**: Quét file cấu trúc `narration.json` và `timeline.json` để kiểm tra độ tương quan (Q-RELV), bằng chứng (Q-EVID) và khẳng định không căn cứ (Q-UNSP).
2. **Kiểm tra sau khi Render (Post-render Gate)**: Chạy FFmpeg phân tích `preview.mp4` hoặc `final.mp4` để kiểm tra khung hình đen (Q-BLCK), đóng băng hình (Q-FRZE) và vỡ tiếng (Q-CLIP).

**Hành vi khi phát hiện vi phạm chỉ số (QA Failure)**:
- Hệ thống lập tức dừng tiến trình tự động xuất video cuối cùng.
- Trạng thái của Job được chuyển từ `RENDERING_*` hoặc `VALIDATING_*` sang **`NEEDS_REVIEW`**.
- Tạo tệp `qa_report.json` mô tả chi tiết lỗi (ví dụ: *"Phân đoạn 3 thiếu bằng chứng hình ảnh"* hoặc *"Phát hiện vỡ tiếng tại giây thứ 12"*).
- Giao diện UI chuyển sang **Review Mode** và đánh dấu đỏ các phân đoạn vi phạm để người dùng dễ dàng định vị và chỉnh sửa thủ công.

### 2.2. Quy tắc Ghi đè (QA Override Policy)
Người dùng chỉ có thể ép buộc hệ thống tiến hành render video final khi:
- Sửa lại các phân đoạn lỗi và chạy lại QA đạt tiêu chuẩn.
- Hoặc, nhấn nút **"Force Approve & Override QA"** trong giao diện Review Mode. Hành động này yêu cầu người dùng phải nhập lý do override (ví dụ: *"Khung hình đen cuối phim là cố ý"*). Lý do này sẽ được ghi nhận vào `qa_report.json` và `run_manifest.json` để phục vụ công tác theo dõi chất lượng.
