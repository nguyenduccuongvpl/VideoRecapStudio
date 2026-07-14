"""Unit tests for FfmpegPreviewRenderer timeline validation and complex filter graph assembly."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from video_recap.application.pipeline import CancellationToken
from video_recap.application.renderer import (
    NarrationOverlay,
    TimelineClip,
    RenderTimeline,
)
from video_recap.domain import AudioDurationOverflowError
from video_recap.infrastructure.media.renderer import FfmpegPreviewRenderer


@pytest.fixture
def mock_video(tmp_path: Path) -> Path:
    f = tmp_path / "video.mp4"
    f.write_text("fake video")
    return f


@pytest.fixture
def mock_wav(tmp_path: Path) -> Path:
    f = tmp_path / "narration.wav"
    f.write_text("fake wav")
    return f


def test_renderer_audio_duration_overflow_raises_error(mock_video: Path, mock_wav: Path) -> None:
    """Verify that a narration overlay exceeding the clip duration throws AudioDurationOverflowError."""
    runner = MagicMock()
    renderer = FfmpegPreviewRenderer(runner)

    # 4-second clip but narration starts at 3.0s and lasts 2.0s (total = 5.0s > 4.0s)
    clip = TimelineClip(
        id="c1",
        source_start=10.0,
        source_end=14.0,
        original_audio_volume=1.0,
        narrations=[
            NarrationOverlay(
                audio_path=str(mock_wav),
                start_time_in_clip=3.0,
                duration=2.0,
            )
        ],
    )
    timeline = RenderTimeline(clips=[clip], output_width=1280, output_height=720, output_fps=30.0)

    with pytest.raises(AudioDurationOverflowError):
        renderer.render_preview(mock_video, timeline, "out.mp4")


def test_renderer_builds_correct_ffmpeg_args(mock_video: Path, mock_wav: Path) -> None:
    """Verify the structured complex filters (scale, pad, volume, adelay, amix) in FFmpeg command."""
    runner = MagicMock()
    renderer = FfmpegPreviewRenderer(runner)

    clip = TimelineClip(
        id="c1",
        source_start=5.0,
        source_end=15.0,  # 10s duration
        original_audio_volume=0.8,
        narrations=[
            NarrationOverlay(
                audio_path=str(mock_wav),
                start_time_in_clip=2.5,
                duration=4.0,
            )
        ],
    )

    with patch.object(FfmpegPreviewRenderer, "_probe_has_audio", return_value=True):
        args = renderer._build_clip_render_command(
            mock_video,
            clip,
            10.0,
            has_audio=True,
            width=1280,
            height=720,
            fps=30.0,
            output_path=Path("temp_out.mp4"),
        )

        args_str = " ".join(args)
        
        # Verify inputs
        assert str(mock_video) in args_str
        assert str(mock_wav) in args_str
        
        # Verify seek times
        assert "-ss 5.0" in args_str
        assert "-to 10.0" in args_str
        
        # Verify video filtergraph
        assert "scale=1280:720" in args_str
        assert "pad=1280:720" in args_str
        assert "fps=30.0" in args_str
        assert "format=yuv420p" in args_str
        
        # Verify audio filtergraph (volume + adelay + amix)
        assert "volume=0.8" in args_str
        assert "adelay=2500|2500" in args_str
        assert "amix=inputs=2:duration=first" in args_str
        
        # Verify output profiles
        assert "-profile:v high" in args_str
        assert "-level 4.1" in args_str
        assert "aac" in args_str


def test_renderer_silent_audio_fallback(mock_video: Path, mock_wav: Path) -> None:
    """Verify silent audio source gets generated when original audio is missing or volume is 0."""
    runner = MagicMock()
    renderer = FfmpegPreviewRenderer(runner)

    clip = TimelineClip(
        id="c1",
        source_start=0.0,
        source_end=5.0,
        original_audio_volume=0.0,  # volume 0 -> silent base
        narrations=[
            NarrationOverlay(
                audio_path=str(mock_wav),
                start_time_in_clip=1.0,
                duration=2.0,
            )
        ],
    )

    with patch.object(FfmpegPreviewRenderer, "_probe_has_audio", return_value=False):
        args = renderer._build_clip_render_command(
            mock_video,
            clip,
            5.0,
            has_audio=False,
            width=640,
            height=360,
            fps=24.0,
            output_path=Path("temp_out.mp4"),
        )

        args_str = " ".join(args)
        # Verify silent audio input
        assert "anullsrc=r=48000:cl=stereo" in args_str


def test_render_preview_orchestration(mock_video: Path, mock_wav: Path, tmp_path: Path) -> None:
    """Verify rendering plan orchestration generates commands, runs them and outputs manifest."""
    runner = MagicMock()
    renderer = FfmpegPreviewRenderer(runner)

    clip1 = TimelineClip(
        id="c1",
        source_start=0.0,
        source_end=5.0,
        original_audio_volume=1.0,
        narrations=[],
    )
    clip2 = TimelineClip(
        id="c2",
        source_start=10.0,
        source_end=15.0,
        original_audio_volume=1.0,
        narrations=[],
    )
    timeline = RenderTimeline(clips=[clip1, clip2], output_width=1280, output_height=720, output_fps=30.0)

    dest_file = tmp_path / "manual_preview.mp4"

    with patch.object(FfmpegPreviewRenderer, "_probe_has_audio", return_value=True):
        manifest = renderer.render_preview(mock_video, timeline, dest_file)
        
        # Verify execution counts: 2 clips + 1 concat command = 3 runner calls
        assert runner.run.call_count == 3
        
        assert manifest.duration == 10.0
        assert manifest.output_path == str(dest_file.absolute())
        assert len(manifest.ffmpeg_commands) == 3
        
        # Concat command checks
        concat_cmd = manifest.ffmpeg_commands[-1]
        assert "concat" in concat_cmd
        assert "-safe" in concat_cmd
