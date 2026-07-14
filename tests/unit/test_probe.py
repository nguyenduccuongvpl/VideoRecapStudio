"""Unit tests for MediaProbeService validating stream parsing, rotation, VFR detection, and validation constraints."""

import json
import pytest
from pathlib import Path
from video_recap.application.media import ProcessRunner
from video_recap.domain import ProcessExecutionError
from video_recap.domain.media import CommandResult, CommandSpec
from video_recap.application.probe import MediaProbeService, MediaProbeError


class MockProcessRunner:
    """Mock process runner to return predefined stdout/stderr outputs."""

    def __init__(self, stdout: str, return_code: int = 0, raise_err: bool = False) -> None:
        self.stdout = stdout
        self.return_code = return_code
        self.raise_err = raise_err

    def run(self, spec: CommandSpec, cancellation_token=None, progress_callback=None) -> CommandResult:
        if self.raise_err:
            raise ProcessExecutionError(
                message="Mock failure",
                command=spec.args,
                return_code=self.return_code,
                stdout=self.stdout,
                stderr="Some stderr info",
            )
        return CommandResult(
            args=spec.args,
            return_code=self.return_code,
            stdout=self.stdout,
            stderr="",
        )


@pytest.fixture
def dummy_file(tmp_path: Path) -> Path:
    f = tmp_path / "dummy.mp4"
    f.write_text("dummy content")
    return f


def test_probe_success(dummy_file: Path) -> None:
    """Test successful probe execution with standard video and audio streams."""
    probe_output = {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "duration": "120.500000",
            "size": "5000000",
            "bit_rate": "332000",
            "tags": {"creation_time": "2026-07-14T04:40:00Z"},
        },
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "duration": "120.500000",
                "disposition": {"default": 1},
            },
            {
                "index": 1,
                "codec_name": "aac",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": 2,
                "duration": "120.500000",
                "disposition": {"default": 1},
            },
        ],
    }

    runner = MockProcessRunner(stdout=json.dumps(probe_output))
    service = MediaProbeService(runner)

    info = service.probe(dummy_file)

    assert info.format_name == "mov,mp4,m4a,3gp,3g2,mj2"
    assert info.duration == 120.5
    assert info.resolution == "1920x1080"
    assert info.fps == 30.0
    assert info.has_video is True
    assert info.has_audio is True
    assert info.vfr_detected is False
    assert len(info.streams) == 2
    assert info.streams[0].codec == "h264"
    assert info.streams[1].codec == "aac"


def test_probe_rotated_video(dummy_file: Path) -> None:
    """Verify that rotation is extracted and normalized to [0, 360) range."""
    # Rotation in side_data_list
    probe_output = {
        "format": {"duration": "10.0", "size": "1000"},
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1080,
                "height": 1920,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "side_data_list": [
                    {
                        "side_data_type": "Display Matrix",
                        "rotation": "-90",
                    }
                ],
            }
        ],
    }

    runner = MockProcessRunner(stdout=json.dumps(probe_output))
    service = MediaProbeService(runner)
    info = service.probe(dummy_file)
    assert info.streams[0].rotation == 270.0  # -90 % 360 = 270


def test_probe_vfr_detection(dummy_file: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that VFR detection registers warning and sets vfr_detected to True."""
    # VFR stream where r_frame_rate != avg_frame_rate
    probe_output = {
        "format": {"duration": "60.0", "size": "1000"},
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "r_frame_rate": "60/1",
                "avg_frame_rate": "24/1",  # large discrepancy
            }
        ],
    }

    runner = MockProcessRunner(stdout=json.dumps(probe_output))
    service = MediaProbeService(runner)
    info = service.probe(dummy_file)

    assert info.vfr_detected is True
    assert any("Variable Frame Rate" in record.message for record in caplog.records)


def test_probe_no_audio_warning(dummy_file: Path, caplog: pytest.LogCaptureFixture) -> None:
    """Verify that video without audio streams logs warning but succeeds."""
    probe_output = {
        "format": {"duration": "60.0", "size": "1000"},
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "r_frame_rate": "30/1",
            }
        ],
    }

    runner = MockProcessRunner(stdout=json.dumps(probe_output))
    service = MediaProbeService(runner)
    info = service.probe(dummy_file)

    assert info.has_video is True
    assert info.has_audio is False
    assert any("contains no audio track" in record.message for record in caplog.records)


def test_probe_missing_video_stream(dummy_file: Path) -> None:
    """Verify that probe raises MediaProbeError if no video stream exists."""
    probe_output = {
        "format": {"duration": "60.0", "size": "1000"},
        "streams": [
            {
                "index": 0,
                "codec_name": "aac",
                "codec_type": "audio",
            }
        ],
    }

    runner = MockProcessRunner(stdout=json.dumps(probe_output))
    service = MediaProbeService(runner)

    with pytest.raises(MediaProbeError) as exc_info:
        service.probe(dummy_file)

    assert "has no video stream" in str(exc_info.value)


def test_probe_invalid_duration(dummy_file: Path) -> None:
    """Verify that probe raises MediaProbeError if format duration is invalid or 0."""
    probe_output = {
        "format": {"duration": "0.0", "size": "1000"},
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "r_frame_rate": "30/1",
            }
        ],
    }

    runner = MockProcessRunner(stdout=json.dumps(probe_output))
    service = MediaProbeService(runner)

    with pytest.raises(MediaProbeError) as exc_info:
        service.probe(dummy_file)

    assert "duration" in str(exc_info.value)


def test_probe_malformed_json(dummy_file: Path) -> None:
    """Verify that malformed JSON from ffprobe is gracefully handled."""
    runner = MockProcessRunner(stdout="{malformed json")
    service = MediaProbeService(runner)

    with pytest.raises(MediaProbeError) as exc_info:
        service.probe(dummy_file)

    assert "parse ffprobe JSON" in str(exc_info.value)


def test_probe_runner_failure(dummy_file: Path) -> None:
    """Verify that ProcessExecutionError from runner is mapped to MediaProbeError."""
    runner = MockProcessRunner(stdout="", return_code=1, raise_err=True)
    service = MediaProbeService(runner)

    with pytest.raises(MediaProbeError) as exc_info:
        service.probe(dummy_file)

    assert "ffprobe execution failed" in str(exc_info.value)
