"""Unit tests for automated script critics, causal chronology verification, and self-correcting repair loops."""

import json
import pytest
from pathlib import Path
from video_recap.application.event import Event, EventGraph, EventRelation
from video_recap.application.narration import NarrationDraft, NarrationSegment
from video_recap.application.critic import (
    GroundingCritic,
    ContinuityCritic,
    EntityConsistencyCritic,
    StyleCritic,
    RepetitionCritic,
    DurationBudgetCritic,
    CriticPipeline,
)


def test_grounding_critic_detects_unsupported_claim() -> None:
    """Verify grounding critic flags claims that lack evidence/observations."""
    critic = GroundingCritic()
    
    seg = NarrationSegment(
        id="seg-1", beat_id="b-1", text="Nhân vật bay vào vũ trụ.",
        event_ids=["e1"], visual_goal="", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9,
        claims=["character flies to space"]
    )
    events = [
        Event(
            event_id="e1", title="Ev 1", start_time=1.0, end_time=5.0,
            factual_summary="character enters room", observation_ids=["obs-1"],
            importance=0.5, confidence=0.9
        )
    ]

    findings = critic.check(seg, events)
    assert len(findings) == 1
    assert findings[0].code == "UNSUPPORTED_CLAIM"
    assert findings[0].severity == "critical"


def test_entity_consistency_critic_detects_wrong_character() -> None:
    """Verify entity consistency critic flags characters not resolved in event participants."""
    critic = EntityConsistencyCritic()
    
    # Mentioning character_002, but only character_001 is a participant in events
    seg = NarrationSegment(
        id="seg-1", beat_id="b-1", text="Nhân vật nhân_vật_002 bước vào.",
        event_ids=["e1"], visual_goal="", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9,
        claims=[]
    )
    events = [
        Event(
            event_id="e1", title="Ev 1", start_time=1.0, end_time=5.0,
            participants=["character_001"], factual_summary="enters room",
            observation_ids=["obs-1"], importance=0.5, confidence=0.9
        )
    ]

    findings = critic.check(seg, events)
    assert len(findings) == 1
    assert findings[0].code == "WRONG_CHARACTER"
    assert findings[0].claim == "character_002"


def test_style_and_repetition_critics() -> None:
    """Verify style and repetition critics check for clichés and double words."""
    style_critic = StyleCritic()
    rep_critic = RepetitionCritic()

    # Contains cliché "không ngờ rằng" and duplicate word "bước bước"
    seg = NarrationSegment(
        id="seg-1", beat_id="b-1", text="không ngờ rằng nhân vật bước bước đi.",
        event_ids=["e1"], visual_goal="", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9,
        claims=[]
    )

    style_findings = style_critic.check(seg)
    assert len(style_findings) == 1
    assert style_findings[0].code == "CLICHE_DETECTED"

    rep_findings = rep_critic.check(seg)
    assert len(rep_findings) == 1
    assert rep_findings[0].code == "REPETITION_DETECTED"


def test_critic_pipeline_auto_repair(tmp_path: Path) -> None:
    """Verify pipeline detects issues, fixes them, and writes draft outputs."""
    grounding = GroundingCritic()
    continuity = ContinuityCritic()
    entity = EntityConsistencyCritic()
    style = StyleCritic()
    repetition = RepetitionCritic()
    duration = DurationBudgetCritic()

    pipeline = CriticPipeline(grounding, continuity, entity, style, repetition, duration)

    events = [
        Event(
            event_id="e1", title="Ev 1", start_time=10.0, end_time=15.0,
            participants=["character_001"], factual_summary="character_001 enters room",
            observation_ids=["obs-1"], importance=0.5, confidence=0.9
        )
    ]
    graph = EventGraph(events=events, relations=[])

    # Draft contains duplicate word "đi đi" and cliché "không ngờ rằng"
    draft = NarrationDraft(
        project_id="proj-1",
        segments=[
            NarrationSegment(
                id="seg-1", beat_id="beat_hook", text="không ngờ rằng nhân vật 001 đi đi vào.",
                event_ids=["e1"], visual_goal="visual", target_duration_ms=5000,
                estimated_spoken_duration_ms=4000, confidence=0.9, claims=[]
            )
        ]
    )

    repaired, report = pipeline.run_validation(draft, events, graph)

    # Output status should pass after self-repair
    assert report.status == "PASSED"
    # Cliché and repetition must be removed
    assert "không ngờ rằng" not in repaired.segments[0].text
    assert "đi đi" not in repaired.segments[0].text
    assert "đi vào" in repaired.segments[0].text

    # Write files check
    pipeline.write_artifacts(repaired, report, tmp_path)
    assert (tmp_path / "critic_report.json").exists()
    assert (tmp_path / "narration_final.json").exists()


def test_critic_pipeline_chronology_violation() -> None:
    """Verify that chronological or causal violations that cannot be auto-fixed flag NEEDS_REVIEW."""
    grounding = GroundingCritic()
    continuity = ContinuityCritic()
    entity = EntityConsistencyCritic()
    style = StyleCritic()
    repetition = RepetitionCritic()
    duration = DurationBudgetCritic()

    pipeline = CriticPipeline(grounding, continuity, entity, style, repetition, duration)

    events = [
        Event(
            event_id="e1", title="Ev 1", start_time=10.0, end_time=15.0,
            participants=["character_001"], factual_summary="enters room",
            observation_ids=["obs-1"], importance=0.5, confidence=0.9
        ),
        Event(
            event_id="e2", title="Ev 2", start_time=20.0, end_time=25.0,
            participants=["character_001"], factual_summary="sits down",
            observation_ids=["obs-2"], importance=0.5, confidence=0.9
        ),
    ]

    # Event 1 causes Event 2
    graph = EventGraph(
        events=events,
        relations=[
            EventRelation(source_id="e1", target_id="e2", relation_type="causes", evidence="direct")
        ]
    )

    # Draft narrates e2 (sitting down) BEFORE e1 (entering room) -> violation!
    draft = NarrationDraft(
        project_id="proj-1",
        segments=[
            NarrationSegment(
                id="seg-1", beat_id="beat_hook", text="Nhân vật ngồi xuống.",
                event_ids=["e2"], visual_goal="visual", target_duration_ms=5000,
                estimated_spoken_duration_ms=4000, confidence=0.9, claims=[]
            ),
            NarrationSegment(
                id="seg-2", beat_id="beat_setup", text="Nhân vật bước vào.",
                event_ids=["e1"], visual_goal="visual", target_duration_ms=5000,
                estimated_spoken_duration_ms=4000, confidence=0.9, claims=[]
            ),
        ]
    )

    repaired, report = pipeline.run_validation(draft, events, graph)

    # Status must be NEEDS_REVIEW since CHRONOLOGY_VIOLATION is critical and not auto-fixable
    assert report.status == "NEEDS_REVIEW"
    assert any(f.code == "CHRONOLOGY_VIOLATION" for f in report.findings)
