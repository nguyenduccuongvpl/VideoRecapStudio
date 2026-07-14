# ADR-004: Structured JSON Output from AI Providers

* **Trạng thái**: Approved
* **Tác giả**: Principal Architect
* **Ngày**: 2026-07-14

---

## 1. Bối cảnh (Context)
Các mô hình ngôn ngữ lớn (LLM) thường sinh văn bản ở dạng tự do (free-form text). Để xây dựng Event Graph, liên kết thực thể (Entity Resolution) và lập kế hoạch clip (Timeline Compilation), hệ thống cần dữ liệu đầu ra từ AI có cấu trúc cực kỳ chặt chẽ (định dạng JSON khớp chính xác với Pydantic schemas). Nếu AI trả về văn bản tự do kèm lời dẫn giải, hệ thống sẽ lỗi parser và treo Pipeline.

## 2. Quyết định (Decision)
Chúng ta quyết định bắt buộc áp dụng **Structured Output** cho mọi tương tác gọi LLM:

1. **API Native Structured Output**:
   - Ưu tiên sử dụng tính năng gọi JSON schema chính thức của nhà cung cấp (ví dụ: `response_format={"type": "json_object", "schema": ...}` của OpenAI, hoặc `response_mime_type="application/json"` kèm `response_schema` của Gemini).
2. **Pydantic Validation & Repair**:
   - Khi nhận dữ liệu JSON từ API, hệ thống chạy kiểm định cấu trúc bằng Pydantic model đầu vào.
   - Nếu kiểm định thất bại (Validation Error), hệ thống áp dụng cơ chế tự sửa chữa giới hạn (Bounded Repair): gửi lại dữ liệu lỗi kèm thông báo lỗi cấu trúc cho LLM để yêu cầu sinh lại tối đa 2 lần. Nếu vẫn thất bại, ném ngoại lệ dừng tiến trình và chuyển sang trạng thái `FAILED`.
3. **Prompt Versioning**:
   - Mọi prompt gửi cho AI phải được lưu trong Registry và có phiên bản đi kèm ghi nhận vào `run_manifest.json` để dễ dàng tái hiện lỗi.

## 3. Hệ quả (Consequences)
* **Ưu điểm**:
  - Loại bỏ hoàn toàn lỗi vỡ cấu trúc JSON (parser errors).
  - Dữ liệu trả về có kiểu rõ ràng, tự động được chuyển hóa thành các đối tượng Python mạnh mẽ.
* **Nhược điểm**:
  - Tốn thêm chi phí và thời gian gọi lại API khi xảy ra lỗi cấu trúc (dù tỷ lệ này cực thấp khi dùng native schemas).
  - Giới hạn khả năng sử dụng các model đời cũ không hỗ trợ tính năng Native Structured Output.
