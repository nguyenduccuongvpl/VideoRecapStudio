# Known Non-Goals — Phạm vi ngoài dự án VideoRecapStudio

Tài liệu này liệt kê các tính năng, mục tiêu và phạm vi **nằm ngoài** định hướng phát triển của phiên bản MVP của **VideoRecapStudio** để đảm bảo tập trung tối đa nguồn lực vào chất lượng cốt lõi.

---

## 1. Không xây dựng bộ dựng phim phi tuyến tính chuyên nghiệp (Non-Linear Editor - NLE)
- **Mô tả**: Dự án không nhằm tạo ra một công cụ thay thế Adobe Premiere, DaVinci Resolve hay CapCut.
- **Giới hạn**: Giao diện Review Mode chỉ tập trung hỗ trợ người dùng tinh chỉnh kịch bản thoại thuyết minh, căn chỉnh điểm In/Out của các phân đoạn clip tự động được sinh ra và hoán đổi vị trí các phân đoạn. Ứng dụng không hỗ trợ các tính năng như chèn hiệu ứng chuyển cảnh phức tạp, vẽ mask, chèn sticker, keyframe chuyển động, hay nhiều track đè lên nhau.

## 2. Không phát triển tính năng giả lập/clone giọng nói người thật
- **Mô tả**: Ứng dụng không tích hợp hay xây dựng mô hình học máy để bắt chước/clone giọng nói của một cá nhân cụ thể nào.
- **Giới hạn**: Dự án chỉ sử dụng các dịch vụ chuyển đổi văn bản thành giọng nói (TTS) tiếng Việt chính thống có sẵn (Cloud API thương mại hoặc Microsoft Edge TTS chính thức) để tạo giọng đọc chất lượng cao, rõ ràng và truyền cảm.

## 3. Không nhận diện danh tính thật của người trong video
- **Mô tả**: Hệ thống không có nhiệm vụ xác định tên tuổi thật của các diễn viên hoặc người xuất hiện trong video (ví dụ: nhận diện diễn viên Keanu Reeves).
- **Giới hạn**: Hệ thống chỉ thực hiện việc theo dõi và định danh thực thể theo vai trò cốt truyện trong video nguồn (ví dụ: "người đàn ông mặc vest", "John Wick", "Sát thủ").

## 4. Không xây dựng tính năng lách luật bản quyền hoặc Content ID
- **Mô tả**: Dự án không cung cấp bất kỳ công cụ hoặc thuật toán nào nhằm mục đích vượt qua bộ lọc bản quyền, lật hình, thay đổi tone giọng nói, chèn nhạc nhiễu để tránh Content ID của các nền tảng chia sẻ video như YouTube, Facebook, TikTok.
- **Giới hạn**: Người dùng tự chịu trách nhiệm về bản quyền của video nguồn và video recap đầu ra.

## 5. Không hỗ trợ tự động tải nội dung từ các nền tảng bên ngoài
- **Mô tả**: Ứng dụng không tích hợp các bộ tải video từ các trang web (như YouTube downloader, torrent client...).
- **Giới hạn**: Video nguồn phải có sẵn dưới dạng tệp tin cục bộ trong máy tính của người dùng trước khi đưa vào hệ thống xử lý.

## 6. Không phụ thuộc vào Browser Automation hoặc API không chính thức
- **Mô tả**: Ứng dụng cam kết không sử dụng Selenium, Playwright, Puppeteer để cào dữ liệu hoặc tự động hóa trình duyệt nhằm gọi các API không được hỗ trợ chính thức.
- **Giới hạn**: Tất cả các kết nối đến dịch vụ AI, dịch vụ Speech, hay dịch vụ trích xuất thông tin đều phải sử dụng các API/Libraries chính thức để đảm bảo độ tin cậy lâu dài, bảo mật thông tin và hiệu suất tối đa.

## 7. Không bảo đảm chế độ tự động hoàn toàn (Full Auto Mode) thành công 100%
- **Mô tả**: Không đặt mục tiêu Full Auto Mode phải xuất ra video hoàn hảo cho mọi thể loại video nguồn.
- **Giới hạn**: Với các video không lời, video hành động có mạch truyện phức tạp, hoặc video chất lượng âm thanh/hình ảnh quá kém dẫn đến độ tự tin (Confidence score) của AI thấp, hệ thống sẽ chủ động hạ cấp công việc sang trạng thái `NEEDS_REVIEW` để người dùng kiểm duyệt thay vì xuất ra sản phẩm lỗi.
