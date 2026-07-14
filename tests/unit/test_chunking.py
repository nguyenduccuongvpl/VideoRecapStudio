"""Unit tests for video chunk planner, shot alignment policies, and observation consolidators."""

import pytest
from video_recap.application.chunking import (
    AnalysisChunkPlanner,
    ChunkOverlapPolicy,
    ObservationDeduplicator,
    ObservationReconciler,
)
from video_recap.application.shot import Shot
from video_recap.domain.models import Observation


def test_chunk_planner_no_shot_alignment() -> None:
    """Verify that chunks split cleanly based on target duration and overlap when alignment is off."""
    policy = ChunkOverlapPolicy(
        target_duration_sec=100.0,
        overlap_duration_sec=10.0,
        align_to_shots=False,
    )
    planner = AnalysisChunkPlanner(policy)

    # 250s video, target 100s, overlap 10s:
    # Chunk 0: [0.0, 100.0]
    # Next start: 100.0 - 10.0 = 90.0
    # Chunk 1: [90.0, 190.0]
    # Next start: 190.0 - 10.0 = 180.0
    # Chunk 2: [180.0, 250.0]
    chunks = planner.plan_chunks(total_duration_sec=250.0, shots=[])

    assert len(chunks) == 3
    assert chunks[0].start_sec == 0.0
    assert chunks[0].end_sec == 100.0
    assert chunks[0].overlap_sec == 10.0

    assert chunks[1].start_sec == 90.0
    assert chunks[1].end_sec == 190.0
    assert chunks[1].overlap_sec == 10.0

    assert chunks[2].start_sec == 180.0
    assert chunks[2].end_sec == 250.0
    assert chunks[2].overlap_sec == 0.0


def test_chunk_planner_aligns_with_shots() -> None:
    """Verify chunk boundary aligns to the closest shot end timestamp."""
    policy = ChunkOverlapPolicy(
        target_duration_sec=100.0,
        overlap_duration_sec=10.0,
        align_to_shots=True,
    )
    planner = AnalysisChunkPlanner(policy)

    # Shots:
    # Shot 1 ends at 103.5 seconds (103500 ms)
    # Shot 2 ends at 205.0 seconds (205000 ms)
    shots = [
        Shot(
            id="s1",
            start_ms=0,
            end_ms=103500,
            start_frame=0,
            end_frame=3000,
            duration=103.5,
            detector="test",
            source_hash="hash",
        ),
        Shot(
            id="s2",
            start_ms=103500,
            end_ms=205000,
            start_frame=3000,
            end_frame=6150,
            duration=101.5,
            detector="test",
            source_hash="hash",
        ),
    ]

    # Video length 250s
    chunks = planner.plan_chunks(total_duration_sec=250.0, shots=shots)

    assert len(chunks) == 3
    # Chunk 0 target end is 100s, closest shot end is 103.5s
    assert chunks[0].start_sec == 0.0
    assert chunks[0].end_sec == 103.5
    assert chunks[0].overlap_sec == 10.0

    # Chunk 1 starts at 103.5 - 10 = 93.5. Target end is 93.5 + 100 = 193.5.
    # Closest shot end is 205.0s.
    assert chunks[1].start_sec == 93.5
    assert chunks[1].end_sec == 205.0
    assert chunks[1].overlap_sec == 10.0

    # Chunk 2 starts at 205.0 - 10 = 195.0. Ends at total 250.0s.
    assert chunks[2].start_sec == 195.0
    assert chunks[2].end_sec == 250.0


def test_observation_deduplication_merges_similar_entries() -> None:
    """Verify that similar observations within time tolerance are deduplicated and fields are merged."""
    deduplicator = ObservationDeduplicator(time_tolerance_sec=2.0, similarity_threshold=0.4)

    obs1 = Observation(
        id="obs-1",
        timestamp=50.2,
        description="A black cat runs across the field",
        confidence=0.9,
        visual_source=True,
        audio_source=False,
    )
    obs2 = Observation(
        id="obs-2",
        timestamp=51.0,  # within 2s tolerance
        description="Black cat running across field",  # high token similarity
        confidence=0.7,
        visual_source=False,
        audio_source=True,
    )
    obs3 = Observation(
        id="obs-3",
        timestamp=100.0,  # totally different time
        description="A black cat runs across the field",
        confidence=0.8,
        visual_source=True,
        audio_source=False,
    )

    merged = deduplicator.deduplicate([obs1, obs2, obs3])

    # Should merge obs1 and obs2, but keep obs3
    assert len(merged) == 2
    
    # Verify merged obs1 and obs2:
    # ID: preserved from obs1 (the existing one)
    # Timestamp: 50.2 (since obs1 has higher confidence)
    # Description: "A black cat runs across the field"
    # Confidence: 0.9
    # Visual Source: True
    # Audio Source: True (merged OR logic)
    merged_item = next(item for item in merged if item.timestamp < 60.0)
    assert merged_item.id == "obs-1"
    assert merged_item.timestamp == 50.2
    assert merged_item.description == "A black cat runs across the field"
    assert merged_item.confidence == 0.9
    assert merged_item.visual_source is True
    assert merged_item.audio_source is True

    # Obs 3 remains untouched
    assert any(item.timestamp == 100.0 for item in merged)


def test_observation_reconciler_consolidates_chunks() -> None:
    """Verify reconciler aggregates list of observations from multiple chunks and deduplicates."""
    deduplicator = ObservationDeduplicator(time_tolerance_sec=2.0, similarity_threshold=0.4)
    reconciler = ObservationReconciler(deduplicator)

    chunk0_obs = [
        Observation(
            id="c0-1",
            timestamp=10.0,
            description="Person waving hands",
            confidence=0.8,
            visual_source=True,
            audio_source=False,
        )
    ]
    chunk1_obs = [
        Observation(
            id="c1-1",
            timestamp=10.5,  # duplicate of c0-1
            description="Person waves hand",
            confidence=0.85,  # higher confidence
            visual_source=True,
            audio_source=False,
        ),
        Observation(
            id="c1-2",
            timestamp=80.0,
            description="Music plays",
            confidence=0.9,
            visual_source=False,
            audio_source=True,
        ),
    ]

    reconciled = reconciler.reconcile([chunk0_obs, chunk1_obs])

    assert len(reconciled) == 2
    # Verify the duplicate was resolved to the higher confidence one
    item_10s = next(item for item in reconciled if abs(item.timestamp - 10.0) < 1.0)
    assert item_10s.confidence == 0.85
    assert item_10s.timestamp == 10.5
