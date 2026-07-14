"""Unit tests for Capability Doctor."""

from unittest.mock import MagicMock, patch
from video_recap.application.doctor import run_doctor_checks
from video_recap.domain.capability import CapabilityItem, CapabilityReport


def test_report_validity() -> None:
    """Test the validity logic of CapabilityReport."""
    r_success = CapabilityReport(
        items=[
            CapabilityItem(name="Req1", status="SUCCESS", required=True, details=""),
            CapabilityItem(name="Opt1", status="WARNING", required=False, details=""),
        ]
    )
    assert r_success.is_valid

    r_failed = CapabilityReport(
        items=[
            CapabilityItem(name="Req1", status="FAILED", required=True, details=""),
            CapabilityItem(name="Opt1", status="SUCCESS", required=False, details=""),
        ]
    )
    assert not r_failed.is_valid


@patch("video_recap.application.doctor.check_module_available")
@patch("video_recap.application.doctor.get_ffmpeg_path")
@patch("video_recap.application.doctor.get_ffprobe_path")
@patch("video_recap.application.doctor.run_command")
def test_doctor_all_success(
    mock_run_cmd: MagicMock,
    mock_get_ffprobe: MagicMock,
    mock_get_ffmpeg: MagicMock,
    mock_check_module: MagicMock,
) -> None:
    """Test doctor check when all packages and FFmpeg dependencies are healthy."""
    mock_check_module.return_value = "1.0.0"
    mock_get_ffmpeg.return_value = "/usr/bin/ffmpeg"
    mock_get_ffprobe.return_value = "/usr/bin/ffprobe"

    def side_effect(cmd: list[str]) -> str:
        if "-version" in cmd:
            return "ffmpeg version 6.0 Copyright (c) 2000-2023"
        if "-encoders" in cmd:
            return "V..... libx264             libx264 H.264 / AVC"
        if "-filters" in cmd:
            return "loudnorm\nsidechaincompress\nsilencedetect"
        return ""

    mock_run_cmd.side_effect = side_effect

    report = run_doctor_checks()
    assert report.is_valid
    for item in report.items:
        assert item.status == "SUCCESS"


@patch("video_recap.application.doctor.check_module_available")
@patch("video_recap.application.doctor.get_ffmpeg_path")
@patch("video_recap.application.doctor.get_ffprobe_path")
@patch("video_recap.application.doctor.run_command")
def test_doctor_missing_required_package(
    mock_run_cmd: MagicMock,
    mock_get_ffprobe: MagicMock,
    mock_get_ffmpeg: MagicMock,
    mock_check_module: MagicMock,
) -> None:
    """Test doctor check fails when a required library (PySide6) is missing."""

    def mock_import(name: str) -> str | None:
        if name == "PySide6":
            return None
        return "1.0.0"

    mock_check_module.side_effect = mock_import
    mock_get_ffmpeg.return_value = "/usr/bin/ffmpeg"
    mock_get_ffprobe.return_value = "/usr/bin/ffprobe"

    def side_effect(cmd: list[str]) -> str:
        if "-version" in cmd:
            return "ffmpeg version 6.0"
        if "-encoders" in cmd:
            return "libx264"
        if "-filters" in cmd:
            return "loudnorm\nsidechaincompress\nsilencedetect"
        return ""

    mock_run_cmd.side_effect = side_effect

    report = run_doctor_checks()
    assert not report.is_valid

    # Find PySide6 item and assert it failed
    pyside_item = next(item for item in report.items if "PySide6" in item.name)
    assert pyside_item.status == "FAILED"
    assert pyside_item.required


@patch("video_recap.application.doctor.check_module_available")
@patch("video_recap.application.doctor.get_ffmpeg_path")
@patch("video_recap.application.doctor.get_ffprobe_path")
@patch("video_recap.application.doctor.run_command")
def test_doctor_missing_ffmpeg(
    mock_run_cmd: MagicMock,
    mock_get_ffprobe: MagicMock,
    mock_get_ffmpeg: MagicMock,
    mock_check_module: MagicMock,
) -> None:
    """Test doctor check fails when FFmpeg binary is missing from system PATH."""
    mock_check_module.return_value = "1.0.0"
    mock_get_ffmpeg.return_value = None
    mock_get_ffprobe.return_value = "/usr/bin/ffprobe"

    report = run_doctor_checks()
    assert not report.is_valid

    ffmpeg_item = next(item for item in report.items if "FFmpeg Executable" in item.name)
    assert ffmpeg_item.status == "FAILED"
    assert ffmpeg_item.required
