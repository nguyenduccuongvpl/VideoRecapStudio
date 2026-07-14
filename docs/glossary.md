# Glossary — Thuật ngữ Dự án VideoRecapStudio

Tài liệu này định nghĩa các thuật ngữ kỹ thuật và nghiệp vụ được sử dụng thống nhất trong toàn bộ tài liệu thiết kế và mã nguồn của **VideoRecapStudio**.

---

- **Observation (Quan sát)**: Thông tin ghi nhận thô, có tính thực tế cao về những gì xuất hiện trực tiếp trong video (hình ảnh, âm thanh, lời thoại, văn bản trên màn hình) kèm theo mốc thời gian (timestamp) bắt đầu và kết thúc cụ thể. Observations không mang tính suy diễn hay giải thích cốt truyện chung chung.
- **Entity Resolution (Đồng nhất thực thể)**: Quá trình phân tích các thực thể (nhân vật, đồ vật, địa điểm) xuất hiện rải rác trong các Observations để gộp các tên gọi khác nhau của cùng một thực thể lại làm một (ví dụ: gộp "Người đàn ông áo đen", "John Wick", "anh ta" thành một thực thể duy nhất là thực thể `John_Wick`).
- **Event (Sự kiện)**: Một hành động hoặc diễn biến có nghĩa xảy ra trong video, được định nghĩa dựa trên sự tương tác giữa các thực thể (Entities) trong một khoảng thời gian nhất định.
- **Event Graph (Đồ thị sự kiện)**: Một cấu trúc dữ liệu dạng đồ thị (Graph) liên kết các sự kiện lại với nhau. Các node là các sự kiện, các cạnh đại diện cho mối quan hệ nguyên nhân - kết quả (causality) hoặc trình tự thời gian (temporal order). Đây là cơ sở cốt lõi để AI viết lời thoại thuyết minh chính xác.
- **Story Outline (Dàn ý câu chuyện)**: Bản kế hoạch cấu trúc nội dung recap, chọn lọc những sự kiện quan trọng nhất từ Event Graph để tạo nên mạch câu chuyện mạch lạc, cuốn hút và logic.
- **Narration (Lời thoại thuyết minh)**: Phần kịch bản tiếng Việt được viết bởi AI dựa trên dàn ý câu chuyện, dùng để chuyển thành giọng nói thuyết minh lồng vào video.
- **Evidence Ref (Tham chiếu bằng chứng)**: Liên kết kỹ thuật trong lời thuyết minh trỏ trực tiếp đến ID của sự kiện hoặc mốc thời gian nguồn (source timestamp). Mỗi câu thuyết minh đều phải có ít nhất một bằng chứng từ video gốc để đảm bảo tính xác thực thông tin.
- **Grounding (Bám sát thực tế)**: Nguyên tắc kỹ thuật đảm bảo mọi thông tin, kịch bản thuyết minh hay hình ảnh lựa chọn đều phải dựa trên cơ sở dữ liệu thực tế thu thập từ video nguồn, không tự ý sáng tạo hay bịa đặt.
- **Critic (Đánh giá & Phê bình)**: Bộ kiểm duyệt nội dung dựa trên AI (AI Critic) có nhiệm vụ quét qua kịch bản thuyết minh và timeline để phát hiện các khẳng định không có căn cứ (unsupported claims), lỗi lặp từ, lỗi logic, hoặc không khớp với bằng chứng gốc.
- **Timeline Compilation (Biên dịch dòng thời gian)**: Quy trình lập lịch ghép nối, xác định chính xác phân đoạn clip nào từ video gốc sẽ được hiển thị tương ứng với câu thuyết minh nào, đồng thời xử lý các vấn đề lệch thời lượng giữa hình và tiếng.
- **Audio Ducking (Giảm âm lượng nền)**: Kỹ thuật tự động giảm âm lượng của nhạc nền hoặc âm thanh gốc của video nguồn xuống một mức nhất định (ví dụ: -15dB) trong khoảng thời gian có giọng đọc thuyết minh để người nghe nghe rõ lời bình.
- **Voice Discovery (Tự động phát hiện giọng đọc)**: Cơ chế quét và tìm kiếm danh sách các giọng thuyết minh tiếng Việt có sẵn từ hệ thống local hoặc Cloud API mà không ghi cứng (hard-code) tên giọng đọc trong mã nguồn.
- **Run Manifest (Bản khai lượt chạy)**: Tệp JSON ghi lại toàn bộ nhật ký cấu hình, dấu vân tay (hashes) của các tệp đầu vào, phiên bản của prompt AI được dùng, và thời gian thực thi của từng bước trong Pipeline.
- **Quality Gate (Cửa chất lượng)**: Các điểm chốt chặn kiểm tra tự động trước và sau khi render video nhằm kiểm duyệt chất lượng kỹ thuật và nội dung xem có đạt tiêu chuẩn hay không.
