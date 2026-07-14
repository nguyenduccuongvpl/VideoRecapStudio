"""Unit tests for mapping event evidence to shots, indexing adjacent shots, evaluating quality constraints, and generating candidate clips."""

import json
import pytest
from pathlib import Path
from video_recap.application.shot import Shot
from video_recap.application.event import Event
from video_recap.application.narration import NarrationSegment
from video_recap.application.candidate import (
    ClipCandidate,
    EvidenceToShotMapper,
    ShotAdjacencyIndex,
    CandidateConstraintPolicy,
    ClipCandidateGenerator,
)


def test_evidence_to_shot_mapper() -> None:
    """Verify mapper maps event timestamp range to overlapping shots accurately."""
    mapper = EvidenceToShotMapper()
    shots = [
        Shot(id="s1", start_ms=0, end_ms=2000, start_frame=0, end_frame=60, duration=2.0, detector="mock", source_hash="h1"),
        Shot(id="s2", start_ms=2000, end_ms=5000, start_frame=60, end_frame=150, duration=3.0, detector="mock", source_hash="h1"),
        Shot(id="s3", start_ms=5000, end_ms=8000, start_frame=150, end_frame=240, duration=3.0, detector="mock", source_hash="h1"),
    ]

    # Range [1.5, 4.0] overlaps with s1 and s2
    res = mapper.map_range_to_shots(1.5, 4.0, shots)
    ids = [s.id for s in res]
    assert "s1" in ids
    assert "s2" in ids
    assert "s3" not in ids


def test_shot_adjacency_index() -> None:
    """Verify adjacency index returns preceding/succeeding shots correctly."""
    shots = [
        Shot(id="s1", start_ms=0, end_ms=2000, start_frame=0, end_frame=60, duration=2.0, detector="mock", source_hash="h1"),
        Shot(id="s2", start_ms=2000, end_ms=5000, start_frame=60, end_frame=150, duration=3.0, detector="mock", source_hash="h1"),
    ]
    idx = ShotAdjacencyIndex(shots)

    # Next shot of s1 is s2
    next_shot = idx.get_adjacent_shot("s1", 1)
    assert next_shot is not None
    assert next_shot.id == "s2"

    # Prev shot of s1 is None
    prev_shot = idx.get_adjacent_shot("s1", -1)
    assert prev_shot is None


def test_candidate_constraint_policy() -> None:
    """Verify constraint policy flags low sharpness, freeze risk, and short duration."""
    policy = CandidateConstraintPolicy()

    # Too short duration and high black freeze risk
    cand = ClipCandidate(
        source_range=(0.0, 0.4), shot_ids=["s1"], candidate_type="exact_evidence",
        evidence_match=1.0, visual_goal_match=0.9, motion=0.5, sharpness=0.9,
        black_freeze_risk=0.8, entity_match=1.0, chronology=True, usable_duration=0.4
    )

    errors = policy.evaluate(cand)
    assert any("Black/freeze risk" in err for err in errors)
    assert any("too short" in err for err in errors)


def test_clip_candidate_generator(tmp_path: Path) -> None:
    """Verify candidate generation produces expected clip categories and writes output JSON."""
    shots = [
        Shot(id="s1", start_ms=0, end_ms=2000, start_frame=0, end_frame=60, duration=2.0, detector="mock", source_hash="h1"),
        Shot(id="s2", start_ms=2000, end_ms=5000, start_frame=60, end_frame=150, duration=3.0, detector="mock", source_hash="h1"),
        Shot(id="s3", start_ms=5000, end_ms=8000, start_frame=150, end_frame=240, duration=3.0, detector="mock", source_hash="h1"),
    ]

    events = [
        Event(
            event_id="e1", title="Ev 1", start_time=2.5, end_time=4.5,
            factual_summary="character eats", observation_ids=["obs-1"], importance=0.5, confidence=0.9
        )
    ]

    segment = NarrationSegment(
        id="seg-1", beat_id="b-1", text="Nhân vật ăn tối.",
        event_ids=["e1"], visual_goal="Eat dinner", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9, claims=[]
    )

    generator = ClipCandidateGenerator(
        mapper=EvidenceToShotMapper(),
        adjacency_index=ShotAdjacencyIndex(shots),
        constraint_policy=CandidateConstraintPolicy(),
    )

    cands = generator.generate_candidates(segment, events, shots)
    types = [c.candidate_type for c in cands]

    # Verify key candidate types are generated
    assert "exact_evidence" in types
    assert "adjacent_setup" in types
    assert "reaction" in types
    assert "establishing" in types

    # Exact evidence must correspond to shot s2 (since event e1 [2.5, 4.5] matches s2 [2.0, 5.0])
    exact = next(c for c in cands if c.candidate_type == "exact_evidence")
    assert exact.shot_ids == ["s2"]

    # Setup must correspond to shot s1 (immediately before s2)
    setup = next(c for c in cands if c.candidate_type == "adjacent_setup")
    assert setup.shot_ids == ["s1"]

    # Reaction must correspond to shot s3 (immediately after s2)
    reaction = next(c for c in cands if c.candidate_type == "reaction")
    assert reaction.shot_ids == ["s3"]

    # Write file check
    output_file = tmp_path / "clip_candidates.json"
    generator.write_candidates_artifact({"seg-1": cands}, output_file)
    assert output_file.exists()

    with open(output_file, "r") as f:
        data = json.load(f)
        assert "seg-1" in data
        assert len(data["seg-1"]) > 0
