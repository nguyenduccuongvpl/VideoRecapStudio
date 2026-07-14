# ADR-003: Provider-Agnostic Strategy & Provider Registry

* **Trạng thái**: Approved
* **Tác giả**: Principal Architect
* **Ngày**: 2026-07-14

---

## 1. Bối cảnh (Context)
Các API dịch vụ đám mây (như OpenAI GPT, Google Gemini, Azure TTS) thay đổi thường xuyên về phiên bản, cấu hình và chính sách giá. Việc lập trình ứng dụng phụ thuộc chặt chẽ (hard-code) vào một nhà cung cấp cụ thể sẽ làm giảm khả năng linh hoạt và tăng rủi ro khi dịch vụ đó bị lỗi hoặc tăng giá.

## 2. Quyết định (Decision)
Chúng ta quyết định thiết lập mô hình thiết kế **Provider Registry** độc lập với nhà cung cấp:

1. **Định nghĩa Giao thức (Protocols)**:
   - Tầng Application định nghĩa các interfaces trừu tượng cho từng dịch vụ: `AIProvider`, `TranscriptionProvider`, `SpeechProvider`.
2. **Runtime Injection & Registry**:
   - Viết module `ProviderRegistry` quản lý việc đăng ký và khởi tạo các nhà cung cấp dịch vụ tại Infrastructure Layer.
   - Khi khởi động, dựa trên tệp cấu hình `config.json` hoặc file `.env`, hệ thống sẽ lấy ra ID của Provider được lựa chọn (ví dụ: `gemini` cho AI, `edge-tts` cho Speech) và khởi tạo đối tượng thích hợp để nạp vào bộ điều phối Pipeline.
3. **Provider Boundaries**:
   - Nghiêm cấm rò rỉ (leak) bất kỳ cấu trúc dữ liệu nội bộ của SDK ngoài qua ranh giới của Application Layer. Mọi kết quả phải được chuyển đổi thành các kiểu dữ liệu thuần túy (Domain Models hoặc kiểu dữ liệu cơ bản của Python).

## 3. Hệ quả (Consequences)
* **Ưu điểm**:
  - Dễ dàng hoán đổi nhà cung cấp (ví dụ: chuyển từ gọi OpenAI Cloud sang một Local Model chạy offline) chỉ bằng cách đổi cấu hình, không cần sửa một dòng code nghiệp vụ nào.
  - Hỗ trợ thêm nhà cung cấp mới dễ dàng bằng cách viết thêm một adapter ở tầng Infrastructure và đăng ký vào Registry.
* **Nhược điểm**:
  - Phải duy trì mã nguồn mapping dữ liệu giữa SDK ngoài và domain models của hệ thống.
  - Khó tận dụng các tính năng đặc thù (proprietary features) của một nhà cung cấp nếu nó không tương thích với interface chung.
