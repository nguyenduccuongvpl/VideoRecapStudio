# Hướng dẫn Đóng góp (Contributing Guidelines)

Tài liệu này quy định các nguyên tắc, tiêu chuẩn lập trình và quy trình đóng góp mã nguồn cho dự án **VideoRecapStudio**.

---

## 1. Tiêu chuẩn Mã nguồn (Coding Standards)

Chúng ta tuân thủ nghiêm ngặt các quy định về chất lượng code:
- **Python Version**: Sử dụng các tính năng mới của **Python 3.12**.
- **Type Hinting**: Mọi hàm, phương thức và lớp mới viết phải khai báo kiểu dữ liệu đầy đủ.
- **Ruff**: Sử dụng Ruff để tự động kiểm tra lỗi (linting) và định dạng (formatting). 
  - Quy tắc độ rộng dòng tối đa: 100 ký tự.
- **Mypy**: Chạy kiểm tra kiểu tĩnh ở chế độ nghiêm ngặt (`strict = true`). Mọi cảnh báo hoặc lỗi kiểu dữ liệu phải được khắc phục trước khi commit.

Lệnh kiểm tra:
```bash
# Định dạng code
ruff format .

# Kiểm tra lỗi tĩnh
ruff check .

# Kiểm tra kiểu dữ liệu
mypy src
```

---

## 2. Quy tắc Kiến trúc Dự án (Architecture Boundaries)

Chúng ta tuân thủ mô hình kiến trúc phân lớp sạch (Clean/Layered Architecture) với các ranh giới sau:

1. **Domain Layer (`src/video_recap/domain/`)**:
   - Chỉ chứa thực thể (entities), giá trị (value objects), chính sách (policies) và lỗi domain.
   - **Nghiêm cấm** import từ các tầng `infrastructure` hoặc `presentation`.
2. **Application Layer (`src/video_recap/application/`)**:
   - Chứa các ca sử dụng (use cases), bộ điều phối (orchestration) và các giao thức giao tiếp (protocols/interfaces).
   - Phụ thuộc vào `domain`.
   - **Nghiêm cấm** import trực tiếp từ `infrastructure` hay `presentation`.
3. **Infrastructure Layer (`src/video_recap/infrastructure/`)**:
   - Triển khai cụ thể cho các giao thức được định nghĩa ở tầng `application` (như gọi FFmpeg, kết nối SQLite, gọi OpenAI/Gemini SDK, Edge-TTS).
   - Không được để rò rỉ (leak) các kiểu dữ liệu của SDK bên ngoài qua ranh giới của Application Layer.
4. **Presentation Layer (`src/video_recap/presentation/`)**:
   - Chứa giao diện CLI và Desktop (PySide6).
   - Gọi các dịch vụ và use cases của `application`.
   - **Nghiêm cấm** chứa logic nghiệp vụ, câu lệnh FFmpeg hoặc logic thử lại (retry) API.

---

## 3. Quy chuẩn Kiểm thử (Testing Policy)

- Mọi tính năng mới viết phải đi kèm với unit tests hoặc integration tests tương ứng.
- Viết test cho cả trường hợp chạy đúng (happy path), dữ liệu không hợp lệ (invalid input) và lỗi hệ thống (failure path).
- Bộ test suite phải được thực thi thành công trước khi đóng phiên làm việc.

Chạy test bằng lệnh:
```bash
python -m pytest
```
