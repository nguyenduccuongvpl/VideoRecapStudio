"""Unit tests for MockShotDetector, FfmpegShotDetector, micro-shot merges, and synthetic window splitting."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from video_recap.application.pipeline import CancellationToken
from video_recap.application.shot import Shot
from video_recap.infrastructure.media.shot_detector import (
    MockShotDetector,
    FfmpegShotDetector,
    ShotTimelineNormalizer,
)


@pytest.fixture
def mock_video(tmp_path: Path) -> Path:
    f = tmp_path / "video.mp4"
    f.write_text("fake video file content")
    return f


def test_mock_shot_detector(mock_video: Path) -> None:
    """Verify MockShotDetector generates contiguous boundaries matching total duration."""
    detector = MockShotDetector(duration=15.0, fps=30.0)
    # Use non-existent file path to fallback to mock duration (15.0s)
    shots = detector.detect_shots(mock_video.parent / "non_existent.mp4", source_hash="dummy_hash")

    # Should split every 6 seconds: 0->6, 6->12, 12->15
    assert len(shots) == 3
    
    assert shots[0].start_ms == 0
    assert shots[0].end_ms == 6000
    assert shots[0].start_frame == 0
    assert shots[0].end_frame == 180

    assert shots[1].start_ms == 6000
    assert shots[1].end_ms == 12000
    assert shots[1].start_frame == 180
    assert shots[1].end_frame == 360

    assert shots[2].start_ms == 12000
    assert shots[2].end_ms == 15000
    assert shots[2].start_frame == 360
    assert shots[2].end_frame == 450
    
    # Verify contiguity
    for i in range(len(shots) - 1):
        assert shots[i].end_ms == shots[i + 1].start_ms
        assert shots[i].end_frame == shots[i + 1].start_frame


def test_micro_shot_merging() -> None:
    """Verify shots under 0.5s are merged unless they are significant hard cuts (>0.6)."""
    normalizer = ShotTimelineNormalizer()
    source_hash = "hash"

    raw_shots = [
        Shot(
            id="s0",
            start_ms=0,
            end_ms=2000,
            start_frame=0,
            end_frame=60,
            duration=2.0,
            detector="test",
            source_hash=source_hash,
        ),
        # Micro-shot: 0.3s duration, low score, should be merged
        Shot(
            id="s1",
            start_ms=2000,
            end_ms=2300,
            start_frame=60,
            end_frame=69,
            duration=0.3,
            detector="test",
            cut_score=0.4,
            source_hash=source_hash,
        ),
        # Micro-shot: 0.3s duration, high score (>0.6), should NOT be merged
        Shot(
            id="s2",
            start_ms=2300,
            end_ms=2600,
            start_frame=69,
            end_frame=78,
            duration=0.3,
            detector="test",
            cut_score=0.85,
            source_hash=source_hash,
        ),
        Shot(
            id="s3",
            start_ms=2600,
            end_ms=5000,
            start_frame=78,
            end_frame=150,
            duration=2.4,
            detector="test",
            source_hash=source_hash,
        ),
    ]

    normalized = normalizer.normalize_timeline(raw_shots, total_duration=5.0, fps=30.0, source_hash=source_hash)

    # s1 merged into s0 (so s0 spans 0 to 2300ms)
    # s2 kept (2300ms to 2600ms)
    # s3 kept (2600ms to 5000ms)
    assert len(normalized) == 3

    assert normalized[0].start_ms == 0
    assert normalized[0].end_ms == 2300
    assert normalized[0].duration == 2.3

    assert normalized[1].start_ms == 2300
    assert normalized[1].end_ms == 2600
    assert normalized[1].duration == 0.3
    assert normalized[1].is_synthetic is False

    assert normalized[2].start_ms == 2600
    assert normalized[2].end_ms == 5000


def test_synthetic_window_splitting() -> None:
    """Verify shots longer than 30s are split into synthetic analysis windows of ~15s."""
    normalizer = ShotTimelineNormalizer()
    source_hash = "hash"

    raw_shots = [
        # 40s shot, should split into 3 synthetic shots of ~13.33s
        Shot(
            id="s0",
            start_ms=0,
            end_ms=40000,
            start_frame=0,
            end_frame=1200,
            duration=40.0,
            detector="test",
            source_hash=source_hash,
        )
    ]

    normalized = normalizer.normalize_timeline(raw_shots, total_duration=40.0, fps=30.0, source_hash=source_hash)

    assert len(normalized) == 3
    assert normalized[0].is_synthetic is True
    assert normalized[1].is_synthetic is True
    assert normalized[2].is_synthetic is True

    assert normalized[0].start_ms == 0
    assert normalized[0].end_ms == 13333

    assert normalized[1].start_ms == 13333
    assert normalized[1].end_ms == 26666

    assert normalized[2].start_ms == 26666
    assert normalized[2].end_ms == 40000


def test_ffmpeg_shot_detector_parsing(mock_video: Path) -> None:
    """Verify FfmpegShotDetector parses select filter scene cuts metadata and segments shots."""
    mock_runner = MagicMock()

    # Create dummy metadata print output in the temp file
    # We will patch tempfile.TemporaryDirectory to control output or patch `_parse_metadata_file`
    detector = FfmpegShotDetector(mock_runner)

    fake_cuts = [
        {"frame": 120, "time": 4.0, "score": 0.45},
        {"frame": 360, "time": 12.0, "score": 0.55},
    ]

    with patch.object(FfmpegShotDetector, "_probe_video_specs", return_value=(20.0, 30.0)):
        with patch.object(FfmpegShotDetector, "_parse_metadata_file", return_value=fake_cuts):
            shots = detector.detect_shots(mock_video, source_hash="test_hash")

            # Final cut at 20.0s is automatically added
            # Should return 3 normalized shots:
            # 1. 0.0 -> 4.0
            # 2. 4.0 -> 12.0
            # 3. 12.0 -> 20.0
            assert len(shots) == 3

            assert shots[0].start_ms == 0
            assert shots[0].end_ms == 4000
            assert shots[0].cut_score == 0.45

            assert shots[1].start_ms == 4000
            assert shots[1].end_ms == 12000
            assert shots[1].cut_score == 0.55

            assert shots[2].start_ms == 12000
            assert shots[2].end_ms == 20000
