# Hướng dẫn Cài đặt & Thiết lập Môi trường (Installation Guide)

Tài liệu này hướng dẫn chi tiết cách cài đặt Python 3.12, FFmpeg, các thư viện cần thiết và xử lý các vấn đề thường gặp về biến môi trường `PATH` trên Windows và Linux.

---

## 1. Yêu cầu Cài đặt Python 3.12

**VideoRecapStudio** yêu cầu Python phiên bản **3.12** để đảm bảo tính tương thích và hiệu suất.

### Trên Windows:
1. Tải bộ cài đặt Python 3.12 chính thức tại: [python.org](https://www.python.org/downloads/)
2. Khi chạy bộ cài đặt, **bắt buộc phải tích chọn: "Add python.exe to PATH"**.
3. Tiến hành cài đặt (nên chọn Customize installation và giữ lại các cài đặt mặc định).

### Trên Linux (Ubuntu/Debian):
```bash
sudo apt update
sudo apt install software-properties-common -y
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt install python3.12 python3.12-venv python3.12-dev -y
```

---

## 2. Cài đặt FFmpeg & ffprobe

Ứng dụng phụ thuộc trực tiếp vào công cụ CLI **FFmpeg** để cắt, ghép và phân tích video.

### Trên Windows:
Có nhiều cách để cài đặt FFmpeg trên Windows:

#### Cách 1: Sử dụng WinGet (Khuyên dùng)
Mở PowerShell ở quyền Admin và chạy:
```powershell
winget install Gyan.FFmpeg
```
*Lưu ý:* Khởi động lại terminal sau khi cài đặt để cập nhật biến môi trường `PATH`.

#### Cách 2: Cài đặt thủ công
1. Tải bản build đầy đủ tại: [gyan.dev FFmpeg](https://www.gyan.dev/ffmpeg/builds/) (Tải file `ffmpeg-git-full.7z` hoặc `ffmpeg-release-full.7z`).
2. Giải nén vào một thư mục cố định (ví dụ: `C:\ffmpeg`).
3. Thêm thư mục `bin` (ví dụ: `C:\ffmpeg\bin`) vào biến môi trường `PATH` của hệ thống:
   - Tìm kiếm "Environment Variables" trong Menu Start.
   - Chọn **Environment Variables...**
   - Tìm biến **Path** trong mục *User variables* hoặc *System variables*, chọn **Edit...**
   - Chọn **New** và điền đường dẫn tới thư mục `bin` của FFmpeg.
   - Bấm **OK** để lưu lại.

### Trên Linux:
```bash
sudo apt update
sudo apt install ffmpeg -y
```

---

## 3. Các vấn đề thường gặp về PATH & Quyền thực thi

### Vấn đề 1: FFmpeg hoặc FFprobe báo lỗi "not found"
- **Triệu chứng**: Khi chạy `python -m video_recap doctor` nhận được trạng thái `FAILED` ở mục FFmpeg Executable.
- **Khắc phục**: 
  - Đảm bảo bạn đã thêm đúng thư mục `bin` (chứa `ffmpeg.exe` và `ffprobe.exe`) vào `PATH`.
  - Bạn có thể cấu hình trực tiếp đường dẫn tuyệt đối bằng cách tạo file `.env` từ `.env.example` và điền:
    ```env
    FFMPEG_PATH=C:\path\to\ffmpeg.exe
    FFPROBE_PATH=C:\path\to\ffprobe.exe
    ```

### Vấn đề 2: Chính sách kiểm soát ứng dụng (AppLocker / Windows Defender Application Control - WDAC)
- **Triệu chứng**: Gặp lỗi `WinError 4551: An Application Control policy has blocked this file` hoặc `DLL load failed` khi chạy các lệnh như `ruff` hay `mypy` từ thư mục môi trường ảo (`venv`).
- **Nguyên nhân**: Hệ thống máy trạm của bạn có cấu hình chính sách bảo mật chặn thực thi các file `.exe` hoặc tải các file `.pyd` (thư viện C-compiled) không có chữ ký số nằm trong thư mục của người dùng (`C:\Users\...`).
- **Khắc phục**:
  - Đối với các tác vụ chạy ứng dụng chính và kiểm thử (Pytest): Chạy trực tiếp qua Python hệ thống (ví dụ: sử dụng `python -m pytest` thay vì `.\venv\Scripts\pytest.exe`).
  - Gói python đáng tin cậy đã cài đặt trên hệ thống sẽ hoạt động bình thường, chỉ các executable nằm trong thư mục tạm/user mới bị chặn.
