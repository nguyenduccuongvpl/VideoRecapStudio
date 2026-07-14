"""Unit tests for event extraction, deduplication, temporal relation building, and graph validation."""

import json
import pytest
from pathlib import Path
from video_recap.application.event import (
    Event,
    EventRelation,
    EventGraph,
    EventDeduplicator,
    EventRelationBuilder,
    EventGraphValidator,
    EventExtractionService,
)
from video_recap.domain.models import Observation


def test_event_deduplicator_merges_similar_events() -> None:
    """Verify that deduplicator merges events within close temporal range and similar keywords."""
    events = [
        Event(
            event_id="e1", title="John enters room", start_time=10.0, end_time=15.0,
            participants=["character_001"], location="room", factual_summary="character_001 enters room",
            observation_ids=["obs-1"], importance=0.5, confidence=0.9
        ),
        Event(
            event_id="e2", title="John sits down", start_time=14.0, end_time=19.0,
            participants=["character_001"], location="room", factual_summary="character_001 sits down",
            observation_ids=["obs-2"], importance=0.5, confidence=0.8
        ),
    ]

    dedup = EventDeduplicator()
    merged = dedup.merge_events(events, time_tolerance=5.0)

    # They should merge because start_time of e2 (14s) is close to end_time of e1 (15s),
    # and they share the participant "character_001" and title keywords ("john").
    assert len(merged) == 1
    assert merged[0].start_time == 10.0
    assert merged[0].end_time == 19.0
    assert "obs-1" in merged[0].observation_ids
    assert "obs-2" in merged[0].observation_ids
    assert merged[0].confidence == 0.9


def test_event_relation_builder() -> None:
    """Verify builder parses temporal precedes, parallel_to, and causal relations based on keywords."""
    events = [
        Event(
            event_id="e1", title="John enters room", start_time=10.0, end_time=15.0,
            participants=["character_001"], factual_summary="character_001 enters",
            observation_ids=["obs-1"], importance=0.5, confidence=0.9
        ),
        Event(
            event_id="e2", title="Alice screams", start_time=12.0, end_time=18.0,
            participants=["character_002"], factual_summary="character_002 screams",
            observation_ids=["obs-2"], importance=0.5, confidence=0.9
        ),
        Event(
            event_id="e3", title="John leaves because of noise", start_time=25.0, end_time=30.0,
            participants=["character_001"], factual_summary="character_001 leaves because of noise",
            observation_ids=["obs-3"], importance=0.5, confidence=0.9
        ),
    ]

    builder = EventRelationBuilder()
    relations = builder.build_relations(events)

    # e1 and e2 overlap -> parallel_to
    rel_12 = next(r for r in relations if r.source_id == "e1" and r.target_id == "e2")
    assert rel_12.relation_type == "parallel_to"

    # e1 and e3 have participant continuity ("character_001"), e3 has keyword "because" -> causes
    rel_13 = next(r for r in relations if r.source_id == "e1" and r.target_id == "e3")
    assert rel_13.relation_type == "causes"


def test_event_graph_validator() -> None:
    """Verify validator flags reverse chronology, causal loops, and missing observations."""
    validator = EventGraphValidator()

    # Valid graph
    valid_graph = EventGraph(
        events=[
            Event(
                event_id="e1", title="Event 1", start_time=10.0, end_time=15.0,
                factual_summary="summary", observation_ids=["obs-1"], importance=0.5, confidence=0.9
            ),
            Event(
                event_id="e2", title="Event 2", start_time=20.0, end_time=25.0,
                factual_summary="summary", observation_ids=["obs-2"], importance=0.5, confidence=0.8
            )
        ],
        relations=[
            EventRelation(source_id="e1", target_id="e2", relation_type="precedes", evidence="none")
        ]
    )

    is_valid, errors = validator.validate(valid_graph)
    assert is_valid is True
    assert len(errors) == 0

    # 1. Invalid: Missing observations
    invalid_obs = EventGraph(
        events=[
            Event(
                event_id="e1", title="Event 1", start_time=10.0, end_time=15.0,
                factual_summary="summary", observation_ids=[], importance=0.5, confidence=0.9
            )
        ],
        relations=[]
    )
    is_valid, errors = validator.validate(invalid_obs)
    assert is_valid is False
    assert any("evidence missing" in err for err in errors)

    # 2. Invalid: Reverse Chronology
    invalid_chrono = EventGraph(
        events=[
            Event(
                event_id="e1", title="Event 1", start_time=25.0, end_time=30.0,
                factual_summary="summary", observation_ids=["obs-1"], importance=0.5, confidence=0.9
            ),
            Event(
                event_id="e2", title="Event 2", start_time=10.0, end_time=15.0,
                factual_summary="summary", observation_ids=["obs-2"], importance=0.5, confidence=0.8
            )
        ],
        relations=[
            EventRelation(source_id="e1", target_id="e2", relation_type="precedes", evidence="none")
        ]
    )
    is_valid, errors = validator.validate(invalid_chrono)
    assert is_valid is False
    assert any("Chronology conflict" in err for err in errors)

    # 3. Invalid: Causal Loop (Cycle)
    invalid_cycle = EventGraph(
        events=[
            Event(
                event_id="e1", title="Event 1", start_time=10.0, end_time=15.0,
                factual_summary="summary", observation_ids=["obs-1"], importance=0.5, confidence=0.9
            ),
            Event(
                event_id="e2", title="Event 2", start_time=20.0, end_time=25.0,
                factual_summary="summary", observation_ids=["obs-2"], importance=0.5, confidence=0.8
            )
        ],
        relations=[
            EventRelation(source_id="e1", target_id="e2", relation_type="causes", evidence="none"),
            EventRelation(source_id="e2", target_id="e1", relation_type="causes", evidence="none")
        ]
    )
    is_valid, errors = validator.validate(invalid_cycle)
    assert is_valid is False
    assert any("causal loop" in err.lower() for err in errors)


def test_event_extraction_pipeline(tmp_path: Path) -> None:
    """Verify that extraction service runs correctly and produces validation and files."""
    obs = [
        Observation(
            id="obs-1", timestamp=10.0, description="character_001 enters", confidence=0.9,
            visual_source=True, audio_source=False
        ),
        Observation(
            id="obs-2", timestamp=12.0, description="character_001 sits down", confidence=0.8,
            visual_source=True, audio_source=False
        )
    ]

    service = EventExtractionService(EventDeduplicator(), EventRelationBuilder(), EventGraphValidator())
    graph = service.extract_from_observations(obs)

    # Combined due to proximity and participant continuity
    assert len(graph.events) == 1
    assert graph.events[0].start_time == 10.0
    assert graph.events[0].end_time == 17.0
    assert "character_001" in graph.events[0].participants

    # Write files check
    service.write_artifacts(graph, tmp_path)
    assert (tmp_path / "events.json").exists()
    assert (tmp_path / "event_graph.json").exists()
    assert (tmp_path / "event_graph_report.json").exists()
