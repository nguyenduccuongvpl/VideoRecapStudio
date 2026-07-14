"""Unit tests for FfmpegKeyframeExtractor, NumpyVisualAnalyzer calculations, and MockVisualAnalyzer."""

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch
from video_recap.application.pipeline import CancellationToken
from video_recap.application.shot import Shot
from video_recap.infrastructure.media.visual_analyzer import (
    FfmpegKeyframeExtractor,
    NumpyVisualAnalyzer,
    MockVisualAnalyzer,
)


@pytest.fixture
def mock_video(tmp_path: Path) -> Path:
    f = tmp_path / "video.mp4"
    f.write_text("fake video file")
    return f


@pytest.fixture
def mock_image(tmp_path: Path) -> Path:
    f = tmp_path / "keyframe.jpg"
    f.write_text("fake image file")
    return f


def test_keyframe_extractor_sampling() -> None:
    """Verify midpoint, multi-point (long shot), and dense (high motion) sampling timestamps."""
    mock_runner = MagicMock()
    extractor = FfmpegKeyframeExtractor(mock_runner)

    shot_short = Shot(
        id="s_short",
        start_ms=0,
        end_ms=4000,
        start_frame=0,
        end_frame=120,
        duration=4.0,
        detector="test",
        source_hash="hash",
    )

    shot_long = Shot(
        id="s_long",
        start_ms=0,
        end_ms=20000,
        start_frame=0,
        end_frame=600,
        duration=20.0,
        detector="test",
        source_hash="hash",
    )

    with patch("pathlib.Path.exists", return_value=True):
        # 1. Short shot (motion <= 0.5) -> midpoint only
        with patch.object(mock_runner, "run") as mock_run:
            extractor.extract_keyframes("vid.mp4", shot_short, "out_dir", motion_score=0.2)
            # Verify it seeked to midpoint (2.0s)
            args = mock_run.call_args[0][0].args
            assert "-ss" in args
            idx = args.index("-ss")
            assert float(args[idx + 1]) == 2.0

        # 2. Long shot (motion <= 0.5) -> 25%, 50%, 75%
        with patch.object(mock_runner, "run") as mock_run:
            extractor.extract_keyframes("vid.mp4", shot_long, "out_dir", motion_score=0.2)
            # 3 calls: 5.0s, 10.0s, 15.0s
            assert mock_run.call_count == 3
            seeks = [float(call[0][0].args[call[0][0].args.index("-ss") + 1]) for call in mock_run.call_args_list]
            assert seeks == [5.0, 10.0, 15.0]

        # 3. High motion shot -> dense sampling (10%, 30%, 50%, 70%, 90%)
        with patch.object(mock_runner, "run") as mock_run:
            extractor.extract_keyframes("vid.mp4", shot_short, "out_dir", motion_score=0.8)
            # 5 calls: 0.4s, 1.2s, 2.0s, 2.8s, 3.6s
            assert mock_run.call_count == 5
            seeks = [float(call[0][0].args[call[0][0].args.index("-ss") + 1]) for call in mock_run.call_args_list]
            assert seeks == [0.4, 1.2, 2.0, 2.8, 3.6]


def test_numpy_visual_analyzer_black_ratio(mock_image: Path) -> None:
    """Verify BlackFrameAnalyzer computes correct black ratio on synthetic frames."""
    mock_runner = MagicMock()
    analyzer = NumpyVisualAnalyzer(mock_runner)

    # Mock all pixels as black (< 15)
    black_arr = np.zeros((10, 10, 3), dtype=np.uint8)
    with patch.object(NumpyVisualAnalyzer, "_load_frame_numpy", return_value=(black_arr, 10, 10)):
        ratio = analyzer.analyze_black_ratio(mock_image)
        assert ratio == 1.0

    # Mock all pixels as white (>= 15)
    white_arr = np.full((10, 10, 3), 255, dtype=np.uint8)
    with patch.object(NumpyVisualAnalyzer, "_load_frame_numpy", return_value=(white_arr, 10, 10)):
        ratio = analyzer.analyze_black_ratio(mock_image)
        assert ratio == 0.0


def test_numpy_visual_analyzer_brightness(mock_image: Path) -> None:
    """Verify brightness is correctly averaged."""
    mock_runner = MagicMock()
    analyzer = NumpyVisualAnalyzer(mock_runner)

    gray_arr = np.full((10, 10, 3), 127, dtype=np.uint8)
    with patch.object(NumpyVisualAnalyzer, "_load_frame_numpy", return_value=(gray_arr, 10, 10)):
        brightness = analyzer.analyze_brightness(mock_image)
        assert pytest.approx(brightness, 0.05) == 0.5


def test_numpy_visual_analyzer_sharpness(mock_image: Path) -> None:
    """Verify sharpness calculates gradient intensity."""
    mock_runner = MagicMock()
    analyzer = NumpyVisualAnalyzer(mock_runner)

    # Flat image -> no gradient -> very low sharpness score
    flat_arr = np.full((10, 10, 3), 127, dtype=np.uint8)
    with patch.object(NumpyVisualAnalyzer, "_load_frame_numpy", return_value=(flat_arr, 10, 10)):
        sharpness = analyzer.analyze_sharpness(mock_image)
        # Should scale close to 0.0 when average gradient is 0
        assert sharpness < 0.3


def test_numpy_visual_analyzer_freeze_similarity(mock_image: Path) -> None:
    """Verify freeze similarity detects identical and completely different images."""
    mock_runner = MagicMock()
    analyzer = NumpyVisualAnalyzer(mock_runner)

    arr1 = np.full((10, 10, 3), 100, dtype=np.uint8)
    arr2 = np.full((10, 10, 3), 100, dtype=np.uint8)
    arr3 = np.full((10, 10, 3), 200, dtype=np.uint8)

    def mock_load(img_path):
        if str(img_path) == "1":
            return arr1, 10, 10
        elif str(img_path) == "2":
            return arr2, 10, 10
        else:
            return arr3, 10, 10

    with patch.object(NumpyVisualAnalyzer, "_load_frame_numpy", side_effect=mock_load):
        # Identical -> similarity = 1.0
        sim_same = analyzer.analyze_freeze_similarity("1", "2")
        assert sim_same == 1.0

        # Different -> similarity < 1.0
        sim_diff = analyzer.analyze_freeze_similarity("1", "3")
        assert sim_diff < 1.0


def test_numpy_visual_analyzer_motion(mock_video: Path) -> None:
    """Verify motion score is computed as (1.0 - mean similarity)."""
    mock_runner = MagicMock()
    analyzer = NumpyVisualAnalyzer(mock_runner)

    shot = Shot(
        id="s0",
        start_ms=0,
        end_ms=4000,
        start_frame=0,
        end_frame=120,
        duration=4.0,
        detector="test",
        source_hash="hash",
    )

    with patch.object(mock_runner, "run") as mock_run:
        with patch.object(NumpyVisualAnalyzer, "analyze_freeze_similarity", return_value=0.9):
            motion = analyzer.analyze_motion(mock_video, shot)
            # motion = 1.0 - 0.9 = 0.1
            assert pytest.approx(motion, 0.01) == 0.1
            assert mock_run.call_count == 3  # extracted 3 frames


def test_mock_visual_analyzer() -> None:
    """Verify mock visual analyzer returns static valid test scores."""
    analyzer = MockVisualAnalyzer()
    assert analyzer.analyze_black_ratio("any") == 0.05
    assert analyzer.analyze_brightness("any") == 0.65
    assert analyzer.analyze_sharpness("any") == 0.82
    assert analyzer.analyze_freeze_similarity("1", "2") == 0.98
    
    shot = Shot(
        id="s0",
        start_ms=0,
        end_ms=4000,
        start_frame=0,
        end_frame=120,
        duration=4.0,
        detector="test",
        source_hash="hash",
    )
    assert analyzer.analyze_motion("any", shot) == 0.35
    face_present, desc = analyzer.analyze_face_presence("any")
    assert face_present is True
    assert "talking-head" in desc
