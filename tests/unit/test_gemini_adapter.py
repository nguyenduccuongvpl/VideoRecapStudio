"""Unit tests for GeminiVideoObservationAdapter and temporal timestamp adjustments."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from pydantic import BaseModel, Field
from video_recap.application.ai import ProviderCapabilities, ModelDescriptor
from video_recap.infrastructure.ai.gemini_adapter import (
    GeminiVideoObservationAdapter,
    calculate_sha256,
    adjust_timestamps_recursive,
)


class DummyObservation(BaseModel):
    label: str = Field(..., description="Obs label.")
    timestamp: float = Field(..., description="Seconds.")
    start_ms: float = Field(..., description="Milliseconds.")


class DummyBatch(BaseModel):
    observations: list[DummyObservation] = Field(default_factory=list)


@pytest.fixture
def mock_video(tmp_path: Path) -> Path:
    f = tmp_path / "video.mp4"
    f.write_text("dummy video content for hashing")
    return f


def test_calculate_sha256(mock_video: Path) -> None:
    """Verify correct checksum calculation."""
    checksum = calculate_sha256(mock_video)
    # Checksum of "dummy video content for hashing"
    assert len(checksum) == 64


def test_adjust_timestamps_recursive() -> None:
    """Verify absolute source timeline mapping adjusts fields correctly."""
    batch = DummyBatch(
        observations=[
            DummyObservation(label="Scene1", timestamp=2.5, start_ms=2500.0)
        ]
    )

    adjusted = adjust_timestamps_recursive(batch, source_offset=10.0)
    
    # 2.5 + 10.0 = 12.5s
    assert adjusted.observations[0].timestamp == 12.5
    # 2500.0 + (10.0 * 1000.0) = 12500.0ms
    assert adjusted.observations[0].start_ms == 12500.0


@patch("google.generativeai.list_files")
@patch("google.generativeai.upload_file")
@patch("google.generativeai.GenerativeModel")
@patch("google.generativeai.delete_file")
def test_gemini_adapter_caches_upload(
    mock_delete, mock_model, mock_upload, mock_list, mock_video: Path
) -> None:
    """Verify adapter re-uses an existing active remote file on Gemini servers."""
    caps = ProviderCapabilities(video_input=True)
    desc = ModelDescriptor(name="gemini-1.5-flash", provider_id="gemini", capabilities=caps)
    adapter = GeminiVideoObservationAdapter(desc, poll_interval_sec=0.01)

    # Mock list_files to return a file with matching display name
    checksum = calculate_sha256(mock_video)
    mock_file = MagicMock()
    mock_file.display_name = f"recap_hash_{checksum}"
    mock_file.state.name = "ACTIVE"
    mock_file.name = "files/test-file-id"
    mock_list.return_value = [mock_file]

    # Mock content response
    mock_response = MagicMock()
    mock_response.text = '{"observations": [{"label": "A", "timestamp": 1.0, "start_ms": 1000.0}]}'
    mock_response.usage_metadata.prompt_token_count = 100
    mock_response.usage_metadata.candidates_token_count = 50
    mock_model.return_value.generate_content.return_value = mock_response

    # Run
    res, meta = adapter.observe_video(mock_video, "observe", DummyBatch, source_offset=5.0)

    # Verify no upload was called (because it was cached)
    mock_upload.assert_not_called()
    # Verify mapping relative -> absolute: 1.0 + 5.0 = 6.0
    assert res.observations[0].timestamp == 6.0
    # Verify cleanup was triggered
    mock_delete.assert_called_once_with("files/test-file-id")


@patch("google.generativeai.list_files")
@patch("google.generativeai.upload_file")
@patch("google.generativeai.get_file")
@patch("google.generativeai.GenerativeModel")
@patch("google.generativeai.delete_file")
def test_gemini_adapter_polls_and_deletes(
    mock_delete, mock_model, mock_get, mock_upload, mock_list, mock_video: Path
) -> None:
    """Verify upload, polling processing states, successful response, and file delete."""
    caps = ProviderCapabilities(video_input=True)
    desc = ModelDescriptor(name="gemini-1.5-flash", provider_id="gemini", capabilities=caps)
    adapter = GeminiVideoObservationAdapter(desc, poll_interval_sec=0.01)

    # No cache files
    mock_list.return_value = []

    # Mock uploaded file transitions: PROCESSING -> ACTIVE
    uploaded_file = MagicMock()
    uploaded_file.state.name = "PROCESSING"
    uploaded_file.name = "files/new-file-id"
    mock_upload.return_value = uploaded_file

    active_file = MagicMock()
    active_file.state.name = "ACTIVE"
    active_file.name = "files/new-file-id"
    mock_get.return_value = active_file

    # Mock reasoning response
    mock_response = MagicMock()
    mock_response.text = '{"observations": []}'
    mock_model.return_value.generate_content.return_value = mock_response

    # Run
    adapter.observe_video(mock_video, "observe", DummyBatch)

    # Verify upload was called
    mock_upload.assert_called_once()
    # Verify get_file was called to poll
    mock_get.assert_called_once_with("files/new-file-id")
    # Verify cleanup
    mock_delete.assert_called_once_with("files/new-file-id")


@patch("google.generativeai.list_files")
@patch("google.generativeai.upload_file")
@patch("google.generativeai.get_file")
@patch("google.generativeai.delete_file")
def test_gemini_adapter_timeout_cleans_up(
    mock_delete, mock_get, mock_upload, mock_list, mock_video: Path
) -> None:
    """Verify that timeout during polling raises TimeoutError and deletes the remote file."""
    caps = ProviderCapabilities(video_input=True)
    desc = ModelDescriptor(name="gemini-1.5-flash", provider_id="gemini", capabilities=caps)
    # Set poll timeout to 0.05 seconds
    adapter = GeminiVideoObservationAdapter(
        desc,
        poll_interval_sec=0.01,
        poll_timeout_sec=0.05,
    )

    mock_list.return_value = []

    # File stays in PROCESSING state
    uploaded_file = MagicMock()
    uploaded_file.state.name = "PROCESSING"
    uploaded_file.name = "files/new-file-id"
    mock_upload.return_value = uploaded_file
    mock_get.return_value = uploaded_file

    with pytest.raises(TimeoutError):
        adapter.observe_video(mock_video, "observe", DummyBatch)

    # Check cleanup was triggered even on timeout
    mock_delete.assert_called_once_with("files/new-file-id")


@patch("google.generativeai.list_files")
@patch("google.generativeai.upload_file")
@patch("google.generativeai.get_file")
@patch("google.generativeai.delete_file")
def test_gemini_adapter_processing_failure_raises_error(
    mock_delete, mock_get, mock_upload, mock_list, mock_video: Path
) -> None:
    """Verify server processing failure throws RuntimeError."""
    caps = ProviderCapabilities(video_input=True)
    desc = ModelDescriptor(name="gemini-1.5-flash", provider_id="gemini", capabilities=caps)
    adapter = GeminiVideoObservationAdapter(desc, poll_interval_sec=0.01)

    mock_list.return_value = []

    # State transitions to FAILED
    uploaded_file = MagicMock()
    uploaded_file.state.name = "PROCESSING"
    uploaded_file.name = "files/new-file-id"
    mock_upload.return_value = uploaded_file

    failed_file = MagicMock()
    failed_file.state.name = "FAILED"
    failed_file.name = "files/new-file-id"
    mock_get.return_value = failed_file

    with pytest.raises(RuntimeError) as exc_info:
        adapter.observe_video(mock_video, "observe", DummyBatch)

    assert "processing failed" in str(exc_info.value)
