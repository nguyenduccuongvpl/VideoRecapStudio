"""Unit tests for observation fallback planner, prompt builder, and scaled VLM reasoning provider."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock
from video_recap.application.ai import ModelDescriptor, ProviderResponseMetadata
from video_recap.application.observation import ObservationBatch
from video_recap.application.shot import Shot
from video_recap.domain.models import Observation, TranscriptCue, TimeRange
from video_recap.infrastructure.ai.observation_fallback import (
    DefaultFrameBatchPlanner,
    DefaultContextWindowBuilder,
    DefaultFrameTranscriptObservationProvider,
)


def test_frame_batch_planner_weeds_out_duplicates() -> None:
    """Verify that near-duplicate keyframes are filtered out to conserve prompt space."""
    mock_analyzer = MagicMock()
    # Mocking: Frame 1 -> Frame 2 is 0.98 similarity (duplicate). Frame 2 -> Frame 3 is 0.80 (distinct).
    mock_analyzer.analyze_freeze_similarity.side_effect = [0.98, 0.80]

    planner = DefaultFrameBatchPlanner(mock_analyzer)
    keyframes = [
        (Path("f1.jpg"), 0.5),
        (Path("f2.jpg"), 1.0),
        (Path("f3.jpg"), 1.5),
    ]

    planned = planner.plan_keyframes(keyframes)
    # Expected: f1.jpg kept, f2.jpg skipped, f3.jpg compared to f1 (f2 skipped, next comparison is f1 to f3)
    assert len(planned) == 2
    assert planned[0][0] == Path("f1.jpg")
    assert planned[1][0] == Path("f3.jpg")


def test_context_window_builder_structures_prompt() -> None:
    """Verify prompt builder formats shots, dialogue cues, and keyframes chronologically."""
    builder = DefaultContextWindowBuilder()

    shots = [
        Shot(
            id="s1",
            start_ms=0,
            end_ms=4000,
            start_frame=0,
            end_frame=120,
            duration=4.0,
            detector="test",
            source_hash="hash",
        )
    ]
    keyframes = [
        (Path("f1.jpg"), 2.0),
    ]
    cues = [
        TranscriptCue(
            text="Hello world",
            time_range=TimeRange(start=0.5, end=3.0),
        )
    ]

    prompt = builder.build_context(shots, keyframes, cues)
    
    assert "SHOT s1" in prompt
    assert "f1.jpg" in prompt
    assert "Hello world" in prompt
    assert "strictly in the keyframes" in prompt  # Safety warning present


def test_fallback_provider_scales_confidence_and_detects_gaps() -> None:
    """Verify that observation confidence is scaled down and coverage gaps >= 5s are reported."""
    mock_reasoning = MagicMock()
    mock_meta = ProviderResponseMetadata(
        request_id="req-123",
        model_name="mock-text",
        latency_ms=50.0,
    )
    
    # Preset response: observation confidence is 0.9
    preset_batch = ObservationBatch(
        observations=[
            Observation(
                id="obs-1",
                timestamp=2.0,
                description="Visual event",
                confidence=0.9,
                visual_source=True,
                audio_source=False,
            )
        ]
    )
    mock_reasoning.generate_structured.return_value = (preset_batch, mock_meta)

    planner = DefaultFrameBatchPlanner()
    builder = DefaultContextWindowBuilder()
    provider = DefaultFrameTranscriptObservationProvider(mock_reasoning, planner, builder)

    # Video timeline of 10 seconds:
    # Shot 1: 0.0s to 10.0s.
    # Keyframe: only one at 1.0s.
    # Dialogue: only one from 0.5s to 2.0s.
    # Coverage Gap: from 4.0s to 10.0s (6 seconds gap with no frames/dialogue)
    shots = [
        Shot(
            id="s1",
            start_ms=0,
            end_ms=10000,
            start_frame=0,
            end_frame=300,
            duration=10.0,
            detector="test",
            source_hash="hash",
        )
    ]
    keyframes = [(Path("f1.jpg"), 1.0)]
    cues = [TranscriptCue(text="Hi", time_range=TimeRange(start=0.5, end=2.0))]

    result, meta = provider.observe_fallback(shots, keyframes, cues, "prompt", ObservationBatch)

    # 1. Verification of scaled confidence: 0.9 * 0.8 = 0.72
    assert result.observations[0].confidence == pytest.approx(0.72)

    # 2. Verification of modality sources
    assert result.modality_sources == ["keyframe", "transcript"]

    # 3. Verification of coverage gaps: gap detected at the end of video (4s to 10s is 6 seconds gap)
    assert len(result.coverage_gaps) == 1
    gap_start, gap_end = result.coverage_gaps[0]
    assert gap_start == 4.0
    assert gap_end == 10.0
