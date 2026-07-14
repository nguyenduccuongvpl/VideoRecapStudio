# Project Scope — VideoRecapStudio

Tài liệu này xác định phạm vi chức năng, danh mục các Artifact bắt buộc phải tạo ra và chính sách bảo mật dữ liệu của ứng dụng **VideoRecapStudio**.

---

## 1. Phạm vi Tính năng (In-Scope Features)

### 1.1. Các Tác vụ xử lý Pipeline Đầu cuối (Core End-to-End Pipeline)
Hệ thống phải hỗ trợ và thực thi các giai đoạn sau của vòng đời xử lý video:
- **Media Ingestion & Probe**: Kiểm tra thông số kỹ thuật video nguồn bằng `ffprobe` (độ phân giải, fps, bitrate, định dạng âm thanh) và lưu trữ thông tin có cấu trúc.
- **Scene/Shot Detection**: Phân đoạn video nguồn thành các phân cảnh logic dựa trên các thuật toán phát hiện thay đổi khung hình (dùng PySceneDetect hoặc giải thuật tương đương).
- **Subtitle/Transcript Extraction**: Đọc và trích xuất phụ đề có sẵn trong video nguồn (nếu có) hoặc tự động chuyển đổi giọng nói thành văn bản (Speech-to-Text Fallback) sử dụng công cụ local hoặc API dịch vụ.
- **Visual & Semantic Observation**: Phân tích hình ảnh tĩnh (Keyframes) và âm thanh của từng phân cảnh để tạo các quan sát thực tế (Observations) có mốc thời gian rõ ràng.
- **Knowledge Building**: Định danh thực thể (Entity Resolution), phát hiện mối liên hệ và xây dựng Graph sự kiện (Event Graph).
- **Story Planning & Outline**: Dựa trên Event Graph để lập dàn ý câu chuyện (Story Outline) có tính nhân quả logic.
- **Narration Generation & Critique**: Viết lời bình bằng tiếng Việt dựa sát vào dàn ý, sau đó sử dụng các tác vụ Critic để rà soát lỗi logic, lỗi diễn đạt, và lỗi không bám sát bằng chứng thực tế.
- **Audio-Visual Alignment (Timeline Compilation)**: Lập kế hoạch phân bổ clip cho từng câu thoại, tính toán thời lượng khớp giữa hình ảnh và âm thanh thuyết minh (Narration Audio).
- **TTS & Audio Processing**: Sinh giọng đọc tiếng Việt chất lượng cao, thực hiện giảm âm lượng (ducking) nhạc nền hoặc âm thanh gốc của video nguồn tại các vị trí có giọng nói, trộn âm thanh (mixing) thành track âm thanh cuối cùng.
- **Preview & Final Rendering**: Ghép âm thanh thuyết minh, phụ đề (Subtitle) và hình ảnh để render video preview (chất lượng thấp, render nhanh) và video final (chất lượng cao).
- **Quality Assurance Verification**: Tự động chạy bộ QA kiểm tra tính hợp lệ của video render (chống mất khung hình, kiểm tra clipping âm thanh, kiểm tra độ đồng bộ).

### 1.2. Lưu trữ và Quản lý Dự án (Project Storage & Persistence)
- Sử dụng **SQLite** để lưu trữ thông tin Metadata về dự án (Project), các công việc (Jobs), trạng thái các bước chạy (Stages) và báo cáo chi phí ước tính (Cost Metadata).
- Mọi dữ liệu trung gian lớn (các tệp JSON, hình ảnh keyframe, tệp âm thanh WAV, clip tạm thời) được tổ chức lưu trữ trực tiếp dưới dạng các tệp tin có phiên bản trong thư mục làm việc của dự án (`workspace/artifacts/`), đảm bảo khả năng tiếp tục chạy từ bước bị lỗi (Resumable Processing) mà không cần tính toán lại từ đầu.

---

## 2. Danh mục Artifact Bắt buộc (Required Artifacts)

Mỗi Job chạy qua Pipeline thành công phải tạo ra đầy đủ các file Artifact chuẩn sau đây trong thư mục dự án để làm minh chứng và dữ liệu đầu vào cho bước tiếp theo. Việc thiếu bất kỳ file nào trong danh sách dưới đây đều bị coi là lỗi Pipeline:

| Tên Tệp Artifact | Định dạng | Mô tả Chi tiết | Giai đoạn Sinh ra |
| :--- | :--- | :--- | :--- |
| `project.json` | JSON | Thông tin cấu hình chung của dự án, đường dẫn video nguồn và các tùy chọn. | `CREATED` |
| `media_info.json` | JSON | Kết quả phân tích kỹ thuật của video nguồn (fps, resolution, duration, codec). | `INGESTING` |
| `shots.json` | JSON | Danh sách các shot/scene được phát hiện kèm thời gian bắt đầu/kết thúc. | `DETECTING_SHOTS` |
| `transcript.json` | JSON | Văn bản lời thoại gốc kèm timestamp trích xuất từ phụ đề hoặc STT. | `TRANSCRIBING` |
| `observations.json` | JSON | Danh sách các mô tả trực quan và âm thanh thực tế thu được theo từng khung giờ. | `OBSERVING` |
| `entities.json` | JSON | Danh sách thực thể được định danh (nhân vật, đồ vật, địa điểm) sau khi giải quyết trùng lặp. | `BUILDING_EVENTS` |
| `events.json` | JSON | Danh sách các sự kiện logic được định nghĩa từ Observations và Entities. | `BUILDING_EVENTS` |
| `event_graph.json` | JSON | Đồ thị liên kết mối quan hệ nguyên nhân - kết quả giữa các sự kiện. | `BUILDING_EVENTS` |
| `story_outline.json` | JSON | Bản dàn ý cấu trúc câu chuyện được phê duyệt để viết thuyết minh. | `PLANNING_STORY` |
| `narration.json` | JSON | Bản thảo và lời thoại thuyết minh tiếng Việt cuối cùng, bao gồm liên kết bằng chứng (`evidence_refs`). | `WRITING_NARRATION` |
| `timeline.json` | JSON | Kế hoạch chi tiết về cách ghép nối các clip nguồn tương ứng với mỗi câu thoại. | `PLANNING_TIMELINE` |
| `narration.wav` | WAV | File âm thanh thuyết minh thô chất lượng cao được tạo từ TTS. | `GENERATING_SPEECH` |
| `narration.srt` | SRT | File phụ đề tiếng Việt đồng bộ cho lời thoại thuyết minh mới. | `GENERATING_SPEECH` |
| `preview.mp4` | MP4 | Video xem trước độ phân giải thấp, render nhanh để đánh giá nhanh. | `RENDERING_PREVIEW` |
| `final.mp4` | MP4 | Video thành phẩm chất lượng cao hoàn chỉnh cuối cùng. | `RENDERING_FINAL` |
| `qa_report.json` | JSON | Báo cáo kiểm định chất lượng tự động của video preview hoặc final. | `VALIDATING_PREVIEW` / `VALIDATING_FINAL` |
| `run_manifest.json` | JSON | Bản khai ghi lại chi tiết các bước đã chạy, thời gian chạy, phiên bản prompt sử dụng. | `COMPLETED` |

---

## 3. Chính sách Bảo mật Dữ liệu (Privacy & Media Upload Policy)

Khi thực hiện phân tích video bằng các mô hình AI bên ngoài (như Cloud API):
- **Không gửi toàn bộ video gốc**: Tuyệt đối không upload file video gốc dung lượng lớn lên các dịch vụ API đám mây trừ khi dịch vụ đó hỗ trợ phân tích video trực tiếp (Direct Video API) và có cam kết bảo mật dữ liệu không dùng để train model.
- **Trích xuất Proxy & Keyframes**: Hệ thống mặc định chỉ trích xuất các khung hình khóa (Keyframes) tĩnh, ảnh phân giải thấp hoặc sinh file video proxy dung lượng thấp (được nén tối đa, lược bỏ các kênh không cần thiết) kèm theo transcript dạng văn bản để gửi đi phân tích.
- **Dọn dẹp tài nguyên từ xa**: Sau khi kết thúc tiến trình phân tích hoặc khi job thất bại, ứng dụng phải chủ động gửi yêu cầu xóa các file tạm đã lưu trên bộ nhớ đám mây của nhà cung cấp dịch vụ (nếu API có hỗ trợ quản lý file tạm trực tuyến).
- **Quản lý Secrets**: Không lưu trữ các API Keys, mật khẩu hay token truy cập dưới dạng plaintext trong mã nguồn, trong cơ sở dữ liệu SQLite hoặc trong các file log công khai. Mọi secrets phải được đọc thông qua biến môi trường hoặc file cấu hình `.env` được bỏ qua bởi Git.
