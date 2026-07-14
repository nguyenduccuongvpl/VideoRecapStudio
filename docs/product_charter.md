# Product Charter — VideoRecapStudio

Tài liệu này xác định mục tiêu, các chế độ vận hành chính và triết lý thiết kế cốt lõi của **VideoRecapStudio**.

---

## 1. Tầm nhìn và Mục tiêu Sản phẩm (Vision & Product Goal)

**VideoRecapStudio** là một ứng dụng Desktop chạy trên Windows hỗ trợ tự động hóa toàn diện quy trình sản xuất video recap/review chất lượng cao từ một video nguồn duy nhất. 

Sản phẩm sinh ra nhằm giải quyết các lỗi cố hữu của các công cụ tự động hóa thế hệ trước (V1): chia nhỏ video theo thời gian cố định một cách cơ học, AI tự "bịa" nội dung không bám sát tình tiết thực tế, giọng đọc lệch pha với hình ảnh, và thiếu kiểm định chất lượng (QA).

Mục tiêu cốt lõi của VideoRecapStudio là:
- Đảm bảo **tính chính xác thực tế (Factual Accuracy) trên 95%** thông qua việc xây dựng một Graph sự kiện (Event Graph) có liên kết bằng chứng thời gian (Evidence Timestamps) trước khi viết kịch bản (Narration).
- Tối ưu hóa thời gian sản xuất video qua hai chế độ: **Full Auto Mode** (Tự động hoàn toàn) và **Review Mode** (Chỉnh sửa có kiểm soát).
- Độc lập hoàn toàn với nhà cung cấp dịch vụ bên ngoài (Provider-Agnostic) cho các dịch vụ AI, TTS, và STT.

---

## 2. Các Chế độ Vận hành Chính (Primary Operating Modes)

### 2.1. Chế độ Tự động Hoàn toàn (Full Auto Mode)
Dành cho quy trình làm việc nhanh gọn với cấu hình tối giản ("Zero-Input").
- **Quy trình của người dùng**:
  1. Chọn video nguồn (`.mp4`, `.mkv`, ...).
  2. Chọn Preset cấu hình mong muốn (thể loại phim, anime, tóm tắt esport...).
  3. Chọn thời lượng video recap mục tiêu (ví dụ: 5 phút, 10 phút).
  4. Chọn giọng đọc (Voice) và cấu hình xuất đầu ra (Output Profile - ví dụ: 1080p 16:9).
  5. Bấm nút **Run**.
- **Cơ chế hoạt động**:
  - Hệ thống tự động thực thi toàn bộ pipeline từ phân tích, trích xuất dữ liệu, dựng kịch bản, sinh giọng nói, trộn âm thanh, dựng timeline và kết xuất video.
  - **Quality Gate bắt buộc**: Full Auto chỉ được phép xuất video cuối cùng (`final.mp4`) khi báo cáo QA tự động đạt tất cả các ngưỡng tối thiểu (Quality Gates).
  - **Chuyển tiếp lỗi**: Nếu có bất kỳ lỗi QA hoặc lỗi hệ thống nghiêm trọng nào xảy ra, công việc (job) sẽ tự động chuyển sang trạng thái `NEEDS_REVIEW` thay vì cố gắng xuất sản phẩm lỗi.

### 2.2. Chế độ Đánh giá & Chỉnh sửa (Review Mode)
Cung cấp khả năng kiểm soát chi tiết và can thiệp thủ công từ người dùng để sửa lỗi AI.
- **Tính năng giao diện**:
  - Xem danh sách từng phân đoạn kịch bản (Narration Segment) kèm theo các bằng chứng hình ảnh (Evidence Keyframes) và khoảng thời gian nguồn (Source Timestamps).
  - Cho phép người dùng chỉnh sửa trực tiếp nội dung văn bản thuyết minh (Narration).
  - Nghe thử giọng đọc (Preview Voice) sau khi sửa.
  - Thay đổi clip được gán cho phân đoạn thuyết minh, chỉnh điểm bắt đầu/kết thúc (In/Out points) của clip.
  - Tìm kiếm và chèn thêm các clip liên quan từ video nguồn.
  - Khóa (Lock) các phân đoạn đã duyệt để tránh bị ghi đè khi chạy lại AI.
  - Gửi kịch bản đã sửa cho Critic AI đánh giá lại tính logic và mạch lạc (Run Critic).
  - Render thử một vùng timeline được chọn để kiểm tra đồng bộ.
  - Xác nhận (Approve) hoặc ghi rõ lý do ghi đè kiểm định (Override QA) để bắt buộc kết xuất video cuối cùng.

---

## 3. Triết lý Thiết kế Hệ thống Cốt lõi (Core Principles)

### 3.1. Factual Grounding qua Cấu trúc Phân tầng
AI tuyệt đối không được viết lời thuyết minh trực tiếp từ tên file, số thứ tự phân đoạn thô hoặc các prompt yêu cầu sáng tạo chung chung. Lời thuyết minh (Narration) chỉ được sinh ra khi hệ thống đã tích lũy đủ các tầng dữ liệu:
1. **Observations**: Ghi nhận trực quan chi tiết từ video nguồn (visual/audio) kèm timestamp chính xác.
2. **Entities**: Danh sách nhân vật, đồ vật, bối cảnh được định danh và đồng nhất (Entity Resolution).
3. **Events**: Các sự kiện diễn ra dựa trên hành động của thực thể (Entity actions).
4. **Event Graph**: Mạng lưới liên kết các sự kiện theo quan hệ nhân quả và trình tự thời gian.
5. **Evidence Timestamps**: Đường dẫn liên kết trực tiếp mỗi tuyên bố factual trong Narration với mã sự kiện (`event_id`) và khoảng thời gian gốc (`source time range`).

### 3.2. Triết lý "Zero-Input" không đánh đổi "Factual Accuracy"
Trong chế độ Full Auto, người dùng không cần can thiệp. Tuy nhiên, tính tiện lợi không được ưu tiên hơn độ chính xác của thông tin thuyết minh. Nếu thông tin quan sát được có độ tin cậy thấp (low confidence), hệ thống bắt buộc phải hạ cấp tiến trình và chuyển sang trạng thái `NEEDS_REVIEW` để con người xác nhận, thay vì tự ý bịa đặt nội dung.

### 3.3. Quy tắc Quality Gate Fail
Bất kỳ khi nào bước QA tự động (`VALIDATING_PREVIEW` hoặc `VALIDATING_FINAL`) phát hiện chỉ số chất lượng nằm dưới ngưỡng cấu hình (ví dụ: phát hiện câu thuyết minh không có bằng chứng, audio bị vỡ/clipping, xuất hiện khung hình đen ngoài ý muốn), hệ thống **nghiêm cấm** việc đánh dấu công việc là `COMPLETED`. Trạng thái công việc bắt buộc phải được chuyển về `NEEDS_REVIEW` hoặc `FAILED` để bảo vệ chất lượng đầu ra.

### 3.4. Kiến trúc độc lập Nhà cung cấp (Provider-Agnostic Strategy)
Toàn bộ mã nguồn cốt lõi trong Domain và Application Layer không được phép tham chiếu trực tiếp đến bất kỳ SDK cụ thể nào (như Google Generative AI, OpenAI, Microsoft Edge TTS). 
- Các giao tiếp bên ngoài phải được định nghĩa bằng các giao thức/giao diện trừu tượng (Abstract Interfaces/Protocols) trong Application Layer.
- Các implementation cụ thể (như `GeminiObservationProvider`, `EdgeTtsSpeechProvider`) được đặt riêng tại Infrastructure Layer và được inject vào runtime. Điều này cho phép thay thế nhà cung cấp hoặc model dễ dàng thông qua file cấu hình mà không cần sửa đổi logic nghiệp vụ.
