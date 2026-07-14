"""Unit tests for thread-safe logging, context propagation, secret redaction, and in-process event bus."""

import logging
import time
import zipfile
from pathlib import Path
from video_recap.domain import JobState, StageName
from video_recap.domain.events import JobStateChanged, StageProgress
from video_recap.infrastructure.logging import (
    DiagnosticBundleService,
    HumanConsoleHandler,
    InProcessEventBus,
    JSONLogHandler,
    SecretRedactionFilter,
    log_context,
    redact_secrets,
)


def test_secret_redaction_regex() -> None:
    """Test text redaction of API key secrets."""
    text_gemini = "API Key: AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6"
    text_openai = "Key = sk-1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t"
    text_safe = "No secrets here"

    assert "AIzaSy" not in redact_secrets(text_gemini)
    assert "sk-" not in redact_secrets(text_openai)
    assert "**********" in redact_secrets(text_gemini)
    assert "**********" in redact_secrets(text_openai)
    assert redact_secrets(text_safe) == text_safe


def test_secret_redaction_logging_filter() -> None:
    """Test SecretRedactionFilter integration with standard Python logging."""
    logger = logging.getLogger("TestRedactionLogger")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # Capture logs using standard stream
    import io

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(SecretRedactionFilter())
    logger.addHandler(handler)

    # Log messages with secrets
    logger.info("Connecting with key AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6")
    logger.info("Setting key = %s", "sk-1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t")

    output = stream.getvalue()
    assert "AIzaSy" not in output
    assert "sk-" not in output
    assert "**********" in output


def test_log_context_propagation() -> None:
    """Test log context nested propagation and thread local isolation."""
    from video_recap.infrastructure.logging.handlers import get_log_context

    # 1. Outer context
    with log_context(job_id="job_outer", project_id="proj_outer"):
        ctx = get_log_context()
        assert ctx["job_id"] == "job_outer"
        assert ctx["project_id"] == "proj_outer"
        assert ctx.get("stage") is None

        # 2. Inner nested context override
        with log_context(stage="INGESTING", job_id="job_inner"):
            ctx_inner = get_log_context()
            assert ctx_inner["job_id"] == "job_inner"  # Overridden
            assert ctx_inner["project_id"] == "proj_outer"  # Inherited
            assert ctx_inner["stage"] == "INGESTING"  # Added

        # Reverted back to outer context
        ctx_revert = get_log_context()
        assert ctx_revert["job_id"] == "job_outer"
        assert ctx_revert.get("stage") is None

    # Context should be empty after exiting context managers
    assert len(get_log_context()) == 0


def test_event_bus_delivery_and_ordering() -> None:
    """Test subscription, dispatch, and ordering on the Event Bus."""
    bus = InProcessEventBus()
    received_events = []

    def handler_1(event: JobStateChanged) -> None:
        received_events.append(("h1", event.new_state))

    def handler_2(event: JobStateChanged) -> None:
        received_events.append(("h2", event.new_state))

    # Subscribe both
    bus.subscribe(JobStateChanged, handler_1)
    bus.subscribe(JobStateChanged, handler_2)

    event = JobStateChanged(
        job_id="j1",
        project_id="p1",
        old_state=JobState.CREATED,
        new_state=JobState.VALIDATING,
        timestamp="2026-07-14",
    )

    # Publish
    bus.publish(event)

    # Both handlers should run in order
    assert len(received_events) == 2
    assert received_events[0] == ("h1", JobState.VALIDATING)
    assert received_events[1] == ("h2", JobState.VALIDATING)

    # Unsubscribe
    bus.unsubscribe(JobStateChanged, handler_1)
    received_events.clear()

    # Publish again
    bus.publish(event)
    assert len(received_events) == 1
    assert received_events[0] == ("h2", JobState.VALIDATING)


def test_subscriber_exception_isolation() -> None:
    """Test that one throwing subscriber does not break dispatch to other subscribers."""
    bus = InProcessEventBus()
    runs = []

    def failing_handler(event: JobStateChanged) -> None:
        raise ValueError("Broken handler")

    def working_handler(event: JobStateChanged) -> None:
        runs.append("working")

    bus.subscribe(JobStateChanged, failing_handler)
    bus.subscribe(JobStateChanged, working_handler)

    event = JobStateChanged(
        job_id="j1",
        project_id="p1",
        old_state=JobState.CREATED,
        new_state=JobState.VALIDATING,
        timestamp="2026-07-14",
    )

    # Publish: should not raise ValueError
    bus.publish(event)

    # Working handler should still have completed successfully!
    assert runs == ["working"]


def test_progress_event_throttling() -> None:
    """Test progress events throttling of intermediate values."""
    bus = InProcessEventBus(throttling_interval_sec=0.1)
    events_received = []

    def handler(event: StageProgress) -> None:
        events_received.append(event.progress)

    bus.subscribe(StageProgress, handler)

    # Event 1: Start boundary (progress = 0.0) -> Always delivered
    bus.publish(
        StageProgress(
            job_id="j",
            project_id="p",
            stage=StageName.INGESTING,
            progress=0.0,
            message="Start",
            timestamp="",
        )
    )

    # Event 2: Intermediate (progress = 0.2) -> Delivered
    bus.publish(
        StageProgress(
            job_id="j",
            project_id="p",
            stage=StageName.INGESTING,
            progress=0.2,
            message="Inter 1",
            timestamp="",
        )
    )

    # Event 3: Intermediate rapidly after Event 2 -> Throttled
    bus.publish(
        StageProgress(
            job_id="j",
            project_id="p",
            stage=StageName.INGESTING,
            progress=0.3,
            message="Inter 2",
            timestamp="",
        )
    )

    # Wait for interval to elapse
    time.sleep(0.12)

    # Event 4: Intermediate after wait -> Delivered
    bus.publish(
        StageProgress(
            job_id="j",
            project_id="p",
            stage=StageName.INGESTING,
            progress=0.5,
            message="Inter 3",
            timestamp="",
        )
    )

    # Event 5: End boundary (progress = 1.0) -> Always delivered immediately
    bus.publish(
        StageProgress(
            job_id="j",
            project_id="p",
            stage=StageName.INGESTING,
            progress=1.0,
            message="End",
            timestamp="",
        )
    )

    # Expect: 0.0, 0.2, 0.5, 1.0 (0.3 was throttled)
    assert events_received == [0.0, 0.2, 0.5, 1.0]


def test_sanitized_diagnostic_bundle(tmp_path: Path) -> None:
    """Test log packaging and verifying secrets are redacted from bundle files."""
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()

    # Write logs containing credentials
    log_file_1 = logs_dir / "pipeline.log"
    log_file_1.write_text(
        "Line 1: system started\n"
        "Line 2: setting gemini_key = AIzaSyA1B2C3D4E5F6G7H8I9J0K1L2M3N4O5P6\n",
        encoding="utf-8",
    )

    log_file_2 = logs_dir / "render.log"
    log_file_2.write_text(
        "Rendering starts...\n" "Secret key leaked: sk-1a2b3c4d5e6f7g8h9i0j1k2l3m4n5o6p7q8r9s0t\n",
        encoding="utf-8",
    )

    zip_path = tmp_path / "diagnostics.zip"
    svc = DiagnosticBundleService()
    svc.create_bundle(logs_dir, zip_path)

    # Verify zip exists
    assert zip_path.exists()

    # Extract zip and verify content is redacted
    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()

    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_dir)

    # Verify files
    files = list(extract_dir.glob("*"))
    assert len(files) == 2

    # Check contents: must be redacted
    for f in files:
        content = f.read_text(encoding="utf-8")
        assert "AIzaSy" not in content
        assert "sk-" not in content
        assert "**********" in content


def test_json_and_human_log_handlers() -> None:
    """Test custom JSON and human console log formatting handlers."""
    import io
    import json

    logger = logging.getLogger("TestFormatLogger")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    # 1. Test JSON Log Handler
    json_stream = io.StringIO()
    json_handler = JSONLogHandler(json_stream)
    logger.addHandler(json_handler)

    with log_context(
        job_id="j_fmt",
        project_id="p_fmt",
        stage="INGESTING",
        operation="PROBING",
        provider_request_id="req_123",
    ):
        logger.info("JSON log testing message")

        # Raise nested exception to test exception field inclusion
        try:
            raise ValueError("Exception test message")
        except ValueError:
            logger.exception("Failed inside task")

    output_lines = json_stream.getvalue().strip().split("\n")
    assert len(output_lines) == 2

    # Verify first log
    log_1 = json.loads(output_lines[0])
    assert log_1["job_id"] == "j_fmt"
    assert log_1["project_id"] == "p_fmt"
    assert log_1["stage"] == "INGESTING"
    assert log_1["operation"] == "PROBING"
    assert log_1["provider_request_id"] == "req_123"
    assert log_1["message"] == "JSON log testing message"

    # Verify second log containing exception
    log_2 = json.loads(output_lines[1])
    assert "exception" in log_2
    assert "ValueError: Exception test message" in log_2["exception"]

    # 2. Test Human Console Log Handler
    logger.removeHandler(json_handler)
    human_stream = io.StringIO()
    human_handler = HumanConsoleHandler(human_stream)
    logger.addHandler(human_handler)

    with log_context(stage="RENDER", operation="ENCODE"):
        logger.info("Human console testing message")

    human_output = human_stream.getvalue()
    assert "Human console testing message" in human_output
    assert "RENDER" in human_output
    assert "ENCODE" in human_output

