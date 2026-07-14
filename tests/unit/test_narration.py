"""Unit tests for Vietnamese text normalization, spoken pacing estimation, sensational phrase detection, and narration grounding."""

import json
import pytest
from pathlib import Path
from video_recap.application.event import Event
from video_recap.application.story import StoryOutline, Beat
from video_recap.application.narration import (
    VietnameseTextNormalizer,
    NarrationPacingEstimator,
    StyleProfileValidator,
    NarrationGenerationService,
    NarrationSegment,
)


def test_vietnamese_text_normalizer() -> None:
    """Verify standard spacing and punctuation cleanup."""
    norm = VietnameseTextNormalizer()
    text = "  Xin chào ,   đây là lời    bình . "
    assert norm.normalize(text) == "Xin chào, đây là lời bình."


def test_pacing_estimator() -> None:
    """Verify narration pacing slows down for climax and hook beats."""
    estimator = NarrationPacingEstimator(base_ms_per_word=300.0)
    text = "một hai ba bốn năm"  # 5 words

    # Hook: slow pacing (5 * 300 * 1.25 = 1875)
    hook_ms = estimator.estimate_duration_ms(text, "hook")
    assert hook_ms == 1875

    # Development: normal pacing (5 * 300 * 0.95 = 1425)
    dev_ms = estimator.estimate_duration_ms(text, "development")
    assert dev_ms == 1425


def test_style_profile_validator_cliches() -> None:
    """Verify style validator catches banned sensationalist cliché phrases."""
    validator = StyleProfileValidator()
    
    # Text contains "không ngờ rằng"
    seg = NarrationSegment(
        id="s1", beat_id="b1", text="Nhân vật bước đi và không ngờ rằng có bẫy.",
        event_ids=["e1"], visual_goal="goal", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9, claims=["enters room"]
    )
    events = [
        Event(
            event_id="e1", title="title", start_time=10.0, end_time=15.0,
            factual_summary="character enters room", observation_ids=["obs-1"], importance=0.5, confidence=0.9
        )
    ]

    errors = validator.validate_segment(seg, events)
    assert any("sensationalist/cliché" in err for err in errors)


def test_style_profile_validator_missing_evidence() -> None:
    """Verify validator flags narration segments lacking event associations."""
    validator = StyleProfileValidator()
    
    # Empty event_ids
    seg = NarrationSegment(
        id="s1", beat_id="b1", text="Xin chào quý vị.",
        event_ids=[], visual_goal="goal", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9, claims=[]
    )

    errors = validator.validate_segment(seg, [])
    assert any("ungrounded" in err for err in errors)


def test_style_profile_validator_hallucination() -> None:
    """Verify validator flags claims that deviate from source observations."""
    validator = StyleProfileValidator()

    # Claim "character flies to space" is not in event summary
    seg = NarrationSegment(
        id="s1", beat_id="b1", text="Nhân vật bay vào vũ trụ.",
        event_ids=["e1"], visual_goal="goal", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9, claims=["character flies to space"]
    )
    events = [
        Event(
            event_id="e1", title="title", start_time=10.0, end_time=15.0,
            factual_summary="character enters room", observation_ids=["obs-1"], importance=0.5, confidence=0.9
        )
    ]

    errors = validator.validate_segment(seg, events)
    assert any("not grounded" in err for err in errors)


def test_narration_generation_pipeline(tmp_path: Path) -> None:
    """Verify service compiles script outline, formats voiceover text, and writes files."""
    events = [
        Event(
            event_id="e1", title="Ev 1", start_time=10.0, end_time=15.0,
            factual_summary="character_001 enters room", observation_ids=["obs-1"], importance=0.5, confidence=0.9
        )
    ]

    outline = StoryOutline(
        beats=[
            Beat(
                beat_id="beat_hook", beat_type="hook", event_ids=["e1"],
                title="Mở đầu", narrative_summary="S1", duration_sec=5.0
            )
        ],
        target_duration_sec=5.0,
        actual_duration_sec=5.0
    )

    service = NarrationGenerationService(
        normalizer=VietnameseTextNormalizer(),
        pacing_estimator=NarrationPacingEstimator(),
        style_validator=StyleProfileValidator(),
    )

    draft, report = service.generate_narration("proj-1", outline, events, cta_enabled=True)

    assert len(draft.segments) == 1
    assert "nhân vật 001 bước vào phòng" in draft.segments[0].text.lower()
    # CTA enabled check
    assert "theo dõi" in draft.segments[0].text.lower()

    # Write files check
    service.write_artifacts(draft, report, tmp_path)
    assert (tmp_path / "narration_draft.json").exists()
    assert (tmp_path / "narration.txt").exists()
    assert (tmp_path / "narration_generation_report.json").exists()
