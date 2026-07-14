"""Unit tests for duration fitting, audio-visual alignment, transition planning, chronology validation, and production sheet compilation."""

import json
import pytest
from pathlib import Path
from video_recap.application.candidate import ClipCandidate
from video_recap.application.narration import NarrationDraft, NarrationSegment
from video_recap.application.ranking import ScoreBreakdown, SelectionExplanation
from video_recap.application.timeline import (
    DurationFittingService,
    TransitionPlanner,
    TimelineValidator,
    TimelineCompiler,
)


def test_duration_fitting_trimming_overflow() -> None:
    """Verify fitting service trims visual clip to match narration duration when visual is longer."""
    service = DurationFittingService()
    
    # Narration needs 3.0s (3000ms)
    segment = NarrationSegment(
        id="seg-1", beat_id="beat_hook", text="Xin chào.",
        event_ids=["e1"], visual_goal="goal", target_duration_ms=5000,
        estimated_spoken_duration_ms=3000, confidence=0.9, claims=[]
    )
    # Clip candidate is 5.0s long
    chosen_candidate = ClipCandidate(
        source_range=(10.0, 15.0), shot_ids=["s1"], candidate_type="exact_evidence",
        evidence_match=1.0, visual_goal_match=1.0, motion=0.5, sharpness=0.8,
        black_freeze_risk=0.0, entity_match=1.0, chronology=True, usable_duration=5.0
    )

    t_clips, speed_factor, seg_dur, adjustments, warnings = service.fit_segment(
        segment, chosen_candidate, [], 0.0
    )

    assert speed_factor == 1.0
    assert seg_dur == 3.0
    assert len(t_clips) == 1
    assert t_clips[0].source_start == 10.0
    assert t_clips[0].source_end == 13.0  # trimmed by 2 seconds
    assert t_clips[0].playback_speed == 1.0


def test_duration_fitting_multi_clip_and_speed_adjust() -> None:
    """Verify fitting service combines multiple clips and speeds up speech for visual underflow."""
    service = DurationFittingService()
    
    # Narration needs 8.0s (8000ms)
    # Primary clip is only 2.0s
    # Another candidate is a reaction of 2.0s
    # Max combined duration = 4.0s. Max extension = 3.0s (total 7.0s).
    # Since 7.0s < 8.0s, it requires speech speed factor increase of 8.0/7.0 = 1.14 (<= 1.25)
    segment = NarrationSegment(
        id="seg-1", beat_id="beat_hook", text="Diễn biến câu chuyện.",
        event_ids=["e1"], visual_goal="goal", target_duration_ms=8000,
        estimated_spoken_duration_ms=8000, confidence=0.9, claims=[]
    )
    chosen_candidate = ClipCandidate(
        source_range=(10.0, 12.0), shot_ids=["s1"], candidate_type="exact_evidence",
        evidence_match=1.0, visual_goal_match=1.0, motion=0.5, sharpness=0.8,
        black_freeze_risk=0.0, entity_match=1.0, chronology=True, usable_duration=2.0
    )
    extra_candidate = ClipCandidate(
        source_range=(12.0, 14.0), shot_ids=["s2"], candidate_type="reaction",
        evidence_match=0.5, visual_goal_match=0.5, motion=0.5, sharpness=0.8,
        black_freeze_risk=0.0, entity_match=1.0, chronology=True, usable_duration=2.0
    )

    t_clips, speed_factor, seg_dur, adjustments, warnings = service.fit_segment(
        segment, chosen_candidate, [chosen_candidate, extra_candidate], 0.0
    )

    assert len(t_clips) == 1
    assert t_clips[0].playback_speed == 1.0  # stretch is strictly forbidden!
    assert speed_factor > 1.0  # speech speed increased to fit
    assert speed_factor <= 1.25


def test_timeline_validator_chronology_violation() -> None:
    """Verify validator flags overlaps and out-of-order segments."""
    from video_recap.application.timeline import ProductionTimeline, TimelineSegment, TimelineClip
    validator = TimelineValidator()

    # Segment 2 starts before Segment 1 ends -> chronology error!
    timeline = ProductionTimeline(
        segments=[
            TimelineSegment(
                segment_id="seg-1", beat_id="beat_hook", start_time=0.0, end_time=3.0,
                narration_text="hello", speech_speed_factor=1.0, subtitle_text="hello",
                clips=[TimelineClip(shot_id="s1", source_start=0.0, source_end=3.0, target_start=0.0, target_end=3.0)]
            ),
            TimelineSegment(
                segment_id="seg-2", beat_id="beat_setup", start_time=2.0, end_time=5.0,  # starts at 2.0, overlapping!
                narration_text="world", speech_speed_factor=1.0, subtitle_text="world",
                clips=[TimelineClip(shot_id="s2", source_start=3.0, source_end=6.0, target_start=2.0, target_end=5.0)]
            )
        ],
        total_duration_sec=5.0
    )

    errors = validator.validate(timeline)
    assert any("chronology overlap" in err for err in errors)


def test_timeline_compiler_pipeline(tmp_path: Path) -> None:
    """Verify compiler runs fit/transition pipeline, flags NEEDS_REVIEW on failures, and writes artifacts."""
    fitting = DurationFittingService()
    transition = TransitionPlanner()
    validator = TimelineValidator()

    compiler = TimelineCompiler(fitting, transition, validator)

    # Narration needs 10.0s (10000ms), but visual candidate is only 2.0s
    # Combined with max extension (3.0s) = 5.0s. Speed factor needs to be 2.0 (exceeds 1.25).
    # This will trigger compression warning and set status to NEEDS_REVIEW.
    draft = NarrationDraft(
        project_id="proj-1",
        segments=[
            NarrationSegment(
                id="seg-1", beat_id="beat_hook", text="Nhân vật bước vào.",
                event_ids=["e1"], visual_goal="visual", target_duration_ms=10000,
                estimated_spoken_duration_ms=10000, confidence=0.9, claims=[]
            )
        ]
    )

    chosen = ClipCandidate(
        source_range=(10.0, 12.0), shot_ids=["s1"], candidate_type="exact_evidence",
        evidence_match=1.0, visual_goal_match=1.0, motion=0.5, sharpness=0.8,
        black_freeze_risk=0.0, entity_match=1.0, chronology=True, usable_duration=2.0
    )

    breakdown = ScoreBreakdown(
        evidence_relevance=1.0, entity_match=1.0, visual_goal=1.0, motion_appropriateness=0.5,
        shot_quality=0.8, chronology=1.0, novelty=1.0, transition=1.0, duplicate_penalty=0.0,
        black_freeze_penalty=0.0, bad_cut_penalty=0.0, total_score=4.0
    )

    expl = SelectionExplanation(
        chosen_candidate_type="exact_evidence",
        score_breakdown=breakdown,
        notes="Best fit"
    )

    selection = {"seg-1": (chosen, expl)}
    all_candidates = {"seg-1": [chosen]}

    timeline, report = compiler.compile_timeline(draft, selection, all_candidates)

    # Since narration is 10.0s but visual is only 2.0s (underflow) and no extra candidates are available,
    # it requires manual review and status is set to NEEDS_REVIEW
    assert timeline.status == "NEEDS_REVIEW"
    assert not report.is_aligned
    assert len(report.warnings) > 0

    # Write check
    compiler.write_artifacts(timeline, report, tmp_path)
    assert (tmp_path / "timeline.json").exists()
    assert (tmp_path / "duration_report.json").exists()
