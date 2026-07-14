# Data Flow & Execution Pipeline — VideoRecapStudio

Tài liệu này mô tả chi tiết luồng di chuyển dữ liệu qua các giai đoạn (stages) của Pipeline và trình bày sơ đồ tuần tự (Sequence Diagram) từ đầu vào video nguồn đến kết quả đầu ra.

---

## 1. Bản đồ Dữ liệu Đầu vào & Đầu ra (Stage Inputs & Outputs)

Mỗi giai đoạn trong Pipeline nhận đầu vào từ các Artifacts đã được tạo ở các bước trước đó và ghi dữ liệu đầu ra thành một Artifact mới. Cơ chế này đảm bảo tính độc lập và khả năng khôi phục (Resume) từ điểm dừng lỗi:

| Giai đoạn (Stage) | Đầu vào (Inputs) | Đầu ra (Outputs) |
| :--- | :--- | :--- |
| **VALIDATING** | `project.json` | `run_manifest.json` (khởi tạo) |
| **INGESTING** | Video nguồn | `media_info.json`, `analysis_proxy.mp4` |
| **TRANSCRIBING** | `media_info.json` | `transcript.json` |
| **DETECTING_SHOTS**| `media_info.json` | `shots.json` |
| **OBSERVING** | `shots.json`, `transcript.json` | `observations.json` |
| **BUILDING_EVENTS**| `observations.json` | `entities.json`, `events.json`, `event_graph.json` |
| **PLANNING_STORY** | `event_graph.json` | `story_outline.json` |
| **WRITING_NARRATION**| `story_outline.json` | `narration.json` |
| **PLANNING_TIMELINE**| `narration.json`, `shots.json` | `timeline.json` |
| **GENERATING_SPEECH**| `timeline.json` | `narration.wav`, `narration.srt` |
| **RENDERING_PREVIEW**| `timeline.json`, `narration.wav` | `preview.mp4` |
| **VALIDATING_PREVIEW**| `preview.mp4` | `qa_report.json` (preview) |
| **NEEDS_REVIEW** | (Dừng để người dùng chỉnh sửa trên UI) | `narration.json` (sửa đổi), `timeline.json` (sửa đổi) |
| **RENDERING_FINAL** | `timeline.json`, `narration.wav` | `final.mp4` |
| **VALIDATING_FINAL** | `final.mp4` | `qa_report.json` (final), `run_manifest.json` (hoàn tất) |

---

## 2. Sơ đồ Tuần tự Đầu cuối (End-to-End Sequence Diagram)

Sơ đồ Mermaid dưới đây biểu diễn cách tương tác giữa người dùng, giao diện (DesktopUI), bộ điều phối (PipelineOrchestrator), các dịch vụ nền (Infrastructure Providers) và cơ sở dữ liệu SQLite:

```mermaid
sequenceDiagram
    autonumber
    actor User as Người dùng
    participant UI as DesktopUI (PySide6)
    participant Orch as PipelineOrchestrator
    participant DB as SQLite Database
    participant AI as AIProvider (Gemini)
    participant Med as MediaService (FFmpeg)

    User->>UI: Chọn Video & Bấm "Run"
    UI->>DB: Khởi tạo Project & Job (State: CREATED)
    UI->>Orch: Khởi chạy Pipeline Job ID
    Orch->>DB: Cập nhật State: INGESTING
    Orch->>Med: Chạy ffprobe quét Video
    Med-->>Orch: Trả về media_info.json
    Orch->>DB: Cập nhật State: OBSERVING
    
    Orch->>AI: Gửi Keyframes & Transcript phân tích
    AI-->>Orch: Trả về observations.json
    Orch->>DB: Cập nhật State: BUILDING_EVENTS
    
    Orch->>AI: Tạo Event Graph & Dàn ý câu chuyện
    AI-->>Orch: Trả về event_graph.json & story_outline.json
    Orch->>DB: Cập nhật State: WRITING_NARRATION
    
    Orch->>AI: Viết lời thoại tiếng Việt có evidence
    AI-->>Orch: Trả về narration.json
    Orch->>DB: Cập nhật State: GENERATING_SPEECH
    
    Orch->>Med: Ghép render preview & Phân tích QA
    Med-->>Orch: Trả về preview.mp4 & qa_report.json
    
    alt QA Fail (Không đạt Quality Gates)
        Orch->>DB: Cập nhật State: NEEDS_REVIEW
        Orch-->>UI: Hiển thị giao diện Review Mode & Lỗi QA
        User->>UI: Sửa lời thoại / Căn chỉnh clip
        User->>UI: Bấm Duyệt / Override QA
        UI->>Orch: Yêu cầu kết xuất cuối (Final Render)
    end

    Orch->>DB: Cập nhật State: RENDERING_FINAL
    Orch->>Med: Render final.mp4
    Med-->>Orch: Hoàn tất tệp final.mp4
    Orch->>DB: Cập nhật State: COMPLETED
    Orch-->>UI: Thông báo thành công
    UI-->>User: Hiển thị Video thành phẩm cuối cùng
```
