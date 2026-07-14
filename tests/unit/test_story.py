"""Unit tests for screenplay beat mapping, time budgeting, causal ancestor retention, and story outline generation."""

import json
import pytest
from pathlib import Path
from video_recap.application.event import Event, EventGraph, EventRelation
from video_recap.application.story import (
    ImportanceBudgeter,
    BeatSelectionPolicy,
    StoryPlanningService,
)


def test_importance_budgeter_causal_ancestors() -> None:
    """Verify that budgeter includes causal ancestors of selected events even if ancestors have low importance."""
    events = [
        Event(
            event_id="e1", title="Cause event", start_time=10.0, end_time=15.0,
            factual_summary="summary", observation_ids=["obs-1"], importance=0.2, confidence=0.9
        ),
        Event(
            event_id="e2", title="Unrelated event", start_time=20.0, end_time=25.0,
            factual_summary="summary", observation_ids=["obs-2"], importance=0.8, confidence=0.9
        ),
        Event(
            event_id="e3", title="Result event", start_time=30.0, end_time=35.0,
            factual_summary="summary", observation_ids=["obs-3"], importance=0.9, confidence=0.9
        ),
    ]

    graph = EventGraph(
        events=events,
        relations=[
            EventRelation(source_id="e1", target_id="e3", relation_type="causes", evidence="direct")
        ]
    )

    budgeter = ImportanceBudgeter()
    
    # Target duration 60.0s allows exactly 2 events (60 // 30 = 2).
    # Normally, e3 (0.9) and e2 (0.8) would be chosen by importance.
    # But e3 requires its causal ancestor e1 (0.2).
    # Thus, the selected events must be e1 and e3, and e2 must be omitted!
    selected, omitted, reasons = budgeter.allocate_budget(events, graph, target_duration=60.0)

    selected_ids = [e.event_id for e in selected]
    assert "e1" in selected_ids
    assert "e3" in selected_ids
    assert "e2" not in selected_ids
    assert "e2" in omitted


def test_beat_selection_policy_short_source() -> None:
    """Verify beat mapping handles short event sources (e.g. 1 event) gracefully."""
    events = [
        Event(
            event_id="e1", title="Only Event", start_time=10.0, end_time=15.0,
            factual_summary="single event summary", observation_ids=["obs-1"], importance=0.9, confidence=0.9
        )
    ]

    policy = BeatSelectionPolicy()
    beats = policy.select_beats(events, target_duration=60.0)

    # 1 event -> only Hook beat is generated
    assert len(beats) == 1
    assert beats[0].beat_type == "hook"
    assert beats[0].event_ids == ["e1"]


def test_beat_selection_policy_multiple_beats() -> None:
    """Verify default beat mapping structure for multi-event recaps including climax and resolution."""
    events = [
        Event(
            event_id="e1", title="Ev 1", start_time=10.0, end_time=15.0,
            factual_summary="S1", observation_ids=["obs-1"], importance=0.5, confidence=0.9
        ),
        Event(
            event_id="e2", title="Ev 2", start_time=20.0, end_time=25.0,
            factual_summary="S2", observation_ids=["obs-2"], importance=0.6, confidence=0.9
        ),
        Event(
            event_id="e3", title="Ev 3", start_time=30.0, end_time=35.0,
            factual_summary="S3", observation_ids=["obs-3"], importance=0.9, confidence=0.9
        ),
        Event(
            event_id="e4", title="Ev 4", start_time=40.0, end_time=45.0,
            factual_summary="S4", observation_ids=["obs-4"], importance=0.5, confidence=0.9
        ),
    ]

    policy = BeatSelectionPolicy()
    beats = policy.select_beats(events, target_duration=120.0)

    # Verify at least hook and climax are present
    types = [b.beat_type for b in beats]
    assert "hook" in types
    assert "climax" in types

    # Hook is chronological first
    hook = next(b for b in beats if b.beat_type == "hook")
    assert hook.event_ids == ["e1"]

    # Climax should target e3 (highest importance towards the end)
    climax = next(b for b in beats if b.beat_type == "climax")
    assert climax.event_ids == ["e3"]


def test_story_planning_pipeline(tmp_path: Path) -> None:
    """Verify story planning service aggregates budgeting and mapping, computes coverage, and writes files."""
    events = [
        Event(
            event_id="e1", title="Ev 1", start_time=10.0, end_time=15.0,
            factual_summary="S1", observation_ids=["obs-1"], importance=0.5, confidence=0.9
        ),
        Event(
            event_id="e2", title="Ev 2", start_time=20.0, end_time=25.0,
            factual_summary="S2", observation_ids=["obs-2"], importance=0.7, confidence=0.9
        ),
    ]

    graph = EventGraph(events=events, relations=[])

    service = StoryPlanningService(ImportanceBudgeter(), BeatSelectionPolicy())
    outline, report = service.plan_story(events, graph, target_duration_sec=60.0)

    # 60.0s target duration permits exactly 2 events, so both should be selected
    assert outline.coverage_ratio == pytest.approx(1.0)
    assert len(report.omitted_event_ids) == 0

    service.write_artifacts(outline, report, tmp_path)
    
    assert (tmp_path / "story_outline.json").exists()
    assert (tmp_path / "omitted_events_report.json").exists()
    assert (tmp_path / "story_coverage_metrics.json").exists()
