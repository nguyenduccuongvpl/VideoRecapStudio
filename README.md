# VideoRecapStudio

**VideoRecapStudio** là ứng dụng Desktop chạy trên Windows được viết bằng Python 3.12 và PySide6, hỗ trợ tự động tạo video recap/review từ một video nguồn duy nhất bằng AI và các công cụ xử lý đa phương tiện.

---

## 📖 Tài liệu Thiết kế Dự án

Hệ thống được thiết kế theo các nguyên tắc kỹ thuật nghiêm ngặt và quy trình kiểm tra chất lượng cao. Vui lòng tham khảo các tài liệu chi tiết tại thư mục [docs/](file:///c:/Users/CUONGNGUYEN/Desktop/Auto_Review_Tool/docs):

1. **[Product Charter](file:///c:/Users/CUONGNGUYEN/Desktop/Auto_Review_Tool/docs/product_charter.md)**: Tầm nhìn sản phẩm, các chế độ vận hành chính (Full Auto, Review Mode) và triết lý thiết kế.
2. **[Project Scope](file:///c:/Users/CUONGNGUYEN/Desktop/Auto_Review_Tool/docs/scope.md)**: Phạm vi các tính năng, danh sách các Artifact bắt buộc và chính sách bảo mật dữ liệu.
3. **[Quality Gates & Metrics](file:///c:/Users/CUONGNGUYEN/Desktop/Auto_Review_Tool/docs/quality_gates.md)**: Các chỉ số chất lượng, ngưỡng chấp nhận kỹ thuật và quy trình xử lý khi QA thất bại.
4. **[Glossary](file:///c:/Users/CUONGNGUYEN/Desktop/Auto_Review_Tool/docs/glossary.md)**: Bảng định nghĩa các thuật ngữ sử dụng thống nhất trong toàn bộ hệ thống.
5. **[Known Non-Goals](file:///c:/Users/CUONGNGUYEN/Desktop/Auto_Review_Tool/docs/known_non_goals.md)**: Các giới hạn và tính năng nằm ngoài phạm vi phát triển phiên bản MVP.

---

## 🛠 Yêu cầu Hệ thống & Thiết lập

### 1. Yêu cầu Hệ thống
- Hệ điều hành: Windows 10 trở lên.
- Python: Phiên bản **3.12** (bắt buộc).
- Công cụ CLI: **FFmpeg** và **ffprobe** đã được cài đặt và cấu hình biến môi trường `PATH`.

### 2. Thiết lập Môi trường
```bash
# Tạo môi trường ảo
python -m venv venv

# Kích hoạt môi trường ảo
.\venv\Scripts\activate

# Cài đặt thư viện yêu cầu
pip install -r requirements.txt
```

---

## 📐 Cấu trúc Dự án (Target Structure)

```text
VideoRecapStudio/
│
├── requirements.txt            # Thư viện Python cần thiết
├── pyproject.toml              # Cấu hình kiểm thử và định dạng (pytest, ruff, mypy)
├── README.md                   # Tài liệu giới thiệu chính
│
├── docs/                       # Tài liệu thiết kế sản phẩm
│   ├── product_charter.md
│   ├── scope.md
│   ├── quality_gates.md
│   ├── glossary.md
│   └── known_non_goals.md
│
├── src/
│   └── video_recap/            # Mã nguồn chính
│       ├── domain/             # Domain logic (Models, Errors, Policies)
│       ├── application/        # Application core (Use cases, Interfaces)
│       ├── infrastructure/     # Triển khai các dịch vụ ngoại vi (AI, Media, DB, Speech)
│       ├── presentation/       # Giao diện người dùng (CLI, PySide6 Desktop)
│       ├── config/             # Quản lý cấu hình hệ thống
│       └── qa/                 # Các công cụ kiểm định chất lượng tự động
│
├── tests/                      # Kiểm thử phần mềm
│   ├── unit/                   # Unit tests
│   ├── integration/            # Integration tests
│   ├── golden/                 # Golden regression tests
│   └── fixtures/               # Dữ liệu giả lập dùng cho test
│
├── prompts/runtime/            # Đăng ký và lưu trữ prompts cho AI
├── schemas/                    # Pydantic schemas cho JSON artifacts
├── scripts/                    # Scripts tiện ích cho quá trình phát triển
└── artifacts/                  # Lưu trữ file kết quả trung gian và cuối cùng
```
