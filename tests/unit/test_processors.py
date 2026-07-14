"""Unit tests for media processors, normalizer caching, disk preflight check, and mock ffmpeg outputs."""

import json
import shutil
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from video_recap.application.pipeline import CancellationToken
from video_recap.application.probe import MediaProbeService
from video_recap.domain import ProcessExecutionError
from video_recap.domain.media import CommandResult, CommandSpec
from video_recap.domain.models import MediaInfo, StageName
from video_recap.infrastructure.media.processors import (
    FfmpegAudioExtractor,
    FfmpegProxyGenerator,
    FfmpegThumbnailGenerator,
    DefaultMediaNormalizer,
)


class MockProcessRunner:
    """Mock process runner to collect run specs and return fake result."""

    def __init__(self, return_code: int = 0, stdout: str = "", stderr: str = "", raise_error_on: str = None) -> None:
        self.return_code = return_code
        self.stdout = stdout
        self.stderr = stderr
        self.raise_error_on = raise_error_on
        self.specs: list[CommandSpec] = []

    def run(self, spec: CommandSpec, cancellation_token=None, progress_callback=None) -> CommandResult:
        self.specs.append(spec)
        if self.raise_error_on and any(self.raise_error_on in arg for arg in spec.args):
            raise ProcessExecutionError(
                message="Mock failure",
                command=spec.args,
                return_code=self.return_code,
                stdout=self.stdout,
                stderr=self.stderr,
            )
        return CommandResult(
            args=spec.args,
            return_code=self.return_code,
            stdout=self.stdout,
            stderr=self.stderr,
        )


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def dummy_video(tmp_path: Path) -> Path:
    f = tmp_path / "input.mp4"
    f.write_text("fake video binary content")
    return f


class DummySettings:
    max_proxy_width = 640
    max_proxy_height = 360


def test_audio_extractor_command_plan() -> None:
    """Verify FfmpegAudioExtractor generates correct ffmpeg arguments."""
    runner = MockProcessRunner()
    extractor = FfmpegAudioExtractor(runner, ffmpeg_path="/bin/ffmpeg")
    extractor.extract_audio("input.mp4", "output.wav")

    assert len(runner.specs) == 1
    args = runner.specs[0].args
    assert args[0] == "/bin/ffmpeg"
    assert "-i" in args
    assert "input.mp4" in args
    assert "-c:a" in args
    assert "pcm_s16le" in args
    assert "-ac" in args
    assert "1" in args
    assert "-ar" in args
    assert "16000" in args
    assert "output.wav" == args[-1]


def test_audio_extractor_no_audio_fallback() -> None:
    """Verify FfmpegAudioExtractor falls back to generating silence if source has no audio stream."""
    # Mock runner that fails on first run with 'Stream map select' error, then succeeds on second run
    runner = MockProcessRunner(
        return_code=1,
        stderr="Stream map select: no audio track found",
        raise_error_on="input.mp4",
    )
    extractor = FfmpegAudioExtractor(runner, ffmpeg_path="/bin/ffmpeg")
    extractor.extract_audio("input.mp4", "output.wav", duration=45.0)

    # There should be two calls: first failing extraction, second creating silent track
    assert len(runner.specs) == 2
    
    # Second command should use lavfi anullsrc filter
    args_2 = runner.specs[1].args
    assert "anullsrc=r=16000:cl=mono" in args_2
    assert "-t" in args_2
    assert "45.000000" in args_2


def test_proxy_generator_command_plan() -> None:
    """Verify FfmpegProxyGenerator scales video preserving aspect ratio and forces CFR if VFR."""
    runner = MockProcessRunner()
    generator = FfmpegProxyGenerator(runner, ffmpeg_path="/bin/ffmpeg")
    
    # 1. CFR case (no VFR flag)
    generator.generate_proxy(
        source_path="input.mp4",
        dest_path="proxy.mp4",
        max_width=640,
        max_height=360,
        is_vfr=False,
        source_width=1920,
        source_height=1080,
    )
    assert len(runner.specs) == 1
    args_cfr = runner.specs[0].args
    assert "scale=640:360" in args_cfr
    assert "-vsync" not in args_cfr

    # 2. VFR case (forces CFR conversion)
    generator.generate_proxy(
        source_path="input.mp4",
        dest_path="proxy.mp4",
        max_width=640,
        max_height=360,
        is_vfr=True,
        source_width=1920,
        source_height=1080,
    )
    assert len(runner.specs) == 2
    args_vfr = runner.specs[1].args
    assert "scale=640:360" in args_vfr
    assert "-vsync" in args_vfr
    assert "cfr" in args_vfr
    assert "-r" in args_vfr
    assert "30.0" in args_vfr


def test_thumbnail_generator_and_contact_sheet() -> None:
    """Verify FfmpegThumbnailGenerator extracts frames and tiles them using concat demuxer."""
    runner = MockProcessRunner()
    generator = FfmpegThumbnailGenerator(runner, ffmpeg_path="/bin/ffmpeg")

    # Generate 3 thumbnails
    thumbs = generator.generate_thumbnails("input.mp4", "thumbs_dir", [1.0, 2.0, 3.0])
    assert len(runner.specs) == 3
    assert len(thumbs) == 3
    assert thumbs[0] == Path("thumbs_dir/thumb_0.jpg")

    # Generate contact sheet
    generator.generate_contact_sheet(thumbs, "sheet.jpg")
    assert len(runner.specs) == 4
    args_sheet = runner.specs[3].args
    assert "-f" in args_sheet
    assert "concat" in args_sheet
    assert "tile=2x2" in args_sheet  # 3 tiles fits in 2x2 grid


def test_normalizer_insufficient_disk(dummy_video: Path, temp_workspace: Path) -> None:
    """Verify DefaultMediaNormalizer raises IOError if free disk space is insufficient."""
    probe = MagicMock(spec=MediaProbeService)
    audio = MagicMock(spec=FfmpegAudioExtractor)
    proxy = MagicMock(spec=FfmpegProxyGenerator)
    thumbs = MagicMock(spec=FfmpegThumbnailGenerator)
    
    normalizer = DefaultMediaNormalizer(probe, audio, proxy, thumbs)

    # Mock disk_usage to return 10MB free space
    mock_usage = shutil._ntuple_diskusage(total=100_000_000, used=90_000_000, free=10_000_000)
    
    with patch("shutil.disk_usage", return_code=0, return_value=mock_usage):
        with pytest.raises(IOError) as exc_info:
            normalizer.normalize(
                source_path=dummy_video,
                project_id="test_proj",
                workspace_dir=temp_workspace,
                settings=DummySettings(),
            )
        assert "Insufficient disk space" in str(exc_info.value)


def test_normalizer_caching_and_run(dummy_video: Path, temp_workspace: Path) -> None:
    """Verify normalizer executes steps, saves artifacts, and hits cache on second run."""
    # 1. First run (Cache Miss)
    probe_info = MediaInfo(
        schema_version="1.0.0",
        producer_stage=StageName.INGESTING,
        input_hashes={},
        format_name="mp4",
        duration=12.5,
        size_bytes=1000,
        streams=[],
        resolution="1920x1080",
        fps=30.0,
        has_video=True,
        has_audio=True,
    )
    
    probe = MagicMock(spec=MediaProbeService)
    probe.probe.return_value = probe_info
    
    audio = MagicMock(spec=FfmpegAudioExtractor)
    proxy = MagicMock(spec=FfmpegProxyGenerator)
    thumbs = MagicMock(spec=FfmpegThumbnailGenerator)
    
    normalizer = DefaultMediaNormalizer(probe, audio, proxy, thumbs)
    
    # Mock disk usage to return lots of space
    mock_usage = shutil._ntuple_diskusage(total=10**11, used=10**10, free=9*10**10)
    
    with patch("shutil.disk_usage", return_value=mock_usage):
        # Normalize
        res = normalizer.normalize(
            source_path=dummy_video,
            project_id="test_proj",
            workspace_dir=temp_workspace,
            settings=DummySettings(),
        )
        
        assert res["cache_hit"] is False
        assert audio.extract_audio.call_count == 1
        assert proxy.generate_proxy.call_count == 1
        assert thumbs.generate_thumbnails.call_count == 1
        
        # Verify output files exist
        media_dir = temp_workspace / "artifacts" / "media"
        assert (media_dir / "source_reference.json").exists()
        assert (media_dir / "media_info.json").exists()
        assert (media_dir / "ingest_report.json").exists()

        # Touch output binary files since normalizer mocked them
        (media_dir / "analysis_proxy.mp4").write_text("proxy data")
        (media_dir / "transcription_audio.wav").write_text("wav data")
        (media_dir / "contact_sheet.jpg").write_text("jpg data")

        # 2. Second run (Cache Hit)
        res_cache = normalizer.normalize(
            source_path=dummy_video,
            project_id="test_proj",
            workspace_dir=temp_workspace,
            settings=DummySettings(),
        )
        assert res_cache["cache_hit"] is True
        # No extra process calls should be made
        assert audio.extract_audio.call_count == 1
        assert proxy.generate_proxy.call_count == 1
        assert thumbs.generate_thumbnails.call_count == 1
