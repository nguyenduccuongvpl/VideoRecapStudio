"""Unit tests for candidate clip scoring, transition smoothness evaluation, duplicate shot penalization, and global backtracking optimization."""

import json
import pytest
from pathlib import Path
from video_recap.application.candidate import ClipCandidate
from video_recap.application.narration import NarrationSegment
from video_recap.application.ranking import (
    ClipScorer,
    DuplicateUsageTracker,
    TransitionCompatibilityScorer,
    GlobalClipOptimizer,
)


def test_duplicate_usage_tracker() -> None:
    """Verify duplicate usage tracker accumulates correct penalty weights."""
    tracker = DuplicateUsageTracker(base_penalty=0.5)
    
    # Empty tracker -> 0.0 penalty
    assert tracker.calculate_penalty(["s1"]) == 0.0

    # Add usage
    tracker.add_usage(["s1", "s2"])
    
    # Now s1 has 1 usage -> penalty should be 0.5
    assert tracker.calculate_penalty(["s1"]) == 0.5
    # s3 has 0 usages -> penalty should be 0.0
    assert tracker.calculate_penalty(["s3"]) == 0.0

    # s1 and s2 both used -> penalty is 0.5 + 0.5 = 1.0
    assert tracker.calculate_penalty(["s1", "s2"]) == 1.0


def test_transition_compatibility_scorer() -> None:
    """Verify scorer awards consecutive timestamps and penalizes overlap jump cuts."""
    scorer = TransitionCompatibilityScorer()

    c1 = ClipCandidate(
        source_range=(1.0, 3.0), shot_ids=["s1"], candidate_type="exact_evidence",
        evidence_match=1.0, visual_goal_match=1.0, usable_duration=2.0
    )
    c2 = ClipCandidate(
        source_range=(3.05, 5.0), shot_ids=["s2"], candidate_type="reaction",
        evidence_match=1.0, visual_goal_match=1.0, usable_duration=1.95
    )
    c_overlap = ClipCandidate(
        source_range=(2.5, 4.0), shot_ids=["s3"], candidate_type="detail",
        evidence_match=1.0, visual_goal_match=1.0, usable_duration=1.5
    )

    # Consecutive (1.0 to 3.0, and 3.05 to 5.0) -> high transition (1.0)
    assert scorer.calculate_score(c1, c2) == 1.0

    # Overlapping (start 2.5 is before prev_end 3.0) -> penalized (0.1)
    assert scorer.calculate_score(c1, c_overlap) == 0.1


def test_global_vs_greedy_optimization() -> None:
    """Verify global backtracking optimizer resolves shot duplication better than simple greedy selection."""
    scorer = ClipScorer()
    transition_scorer = TransitionCompatibilityScorer()
    optimizer = GlobalClipOptimizer(scorer, transition_scorer, duplicate_penalty_weight=1.0)

    # Segment 1 needs a clip
    seg1 = NarrationSegment(
        id="seg-1", beat_id="beat_hook", text="Nhân vật ăn.",
        event_ids=["e1"], visual_goal="eat", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9, claims=[]
    )
    # Segment 2 needs a clip
    seg2 = NarrationSegment(
        id="seg-2", beat_id="beat_setup", text="Nhân vật đi.",
        event_ids=["e2"], visual_goal="walk", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9, claims=[]
    )

    # Candidate options for seg-1
    cands_seg1 = [
        # Candidate A: uses shot s1 (excellent fit)
        ClipCandidate(
            source_range=(1.0, 3.0), shot_ids=["s1"], candidate_type="exact_evidence",
            evidence_match=1.0, visual_goal_match=1.0, motion=0.5, sharpness=0.9, usable_duration=2.0
        ),
        # Candidate B: uses shot s2 (moderate fit)
        ClipCandidate(
            source_range=(1.0, 3.0), shot_ids=["s2"], candidate_type="detail",
            evidence_match=0.7, visual_goal_match=0.6, motion=0.5, sharpness=0.8, usable_duration=2.0
        )
    ]

    # Candidate options for seg-2
    cands_seg2 = [
        # Candidate C: uses shot s1 (excellent fit for seg-2 but overlaps/duplicates s1!)
        ClipCandidate(
            source_range=(3.1, 5.0), shot_ids=["s1"], candidate_type="exact_evidence",
            evidence_match=1.0, visual_goal_match=1.0, motion=0.4, sharpness=0.9, usable_duration=1.9
        ),
        # Candidate D: uses shot s3 (excellent fit, no duplication!)
        ClipCandidate(
            source_range=(3.1, 5.0), shot_ids=["s3"], candidate_type="detail",
            evidence_match=0.9, visual_goal_match=0.9, motion=0.4, sharpness=0.9, usable_duration=1.9
        )
    ]

    # If greedy:
    # seg-1 chooses s1 (score ~1.0)
    # seg-2 is forced to choose between s1 (which has duplicate penalty -1.0 -> net score ~0.0) or s3 (net score ~0.9).
    # But global search should easily pick the sequence (Candidate A [s1], Candidate D [s3]) as the highest global sum!
    # Let's verify this global choice:
    candidates_map = {"seg-1": cands_seg1, "seg-2": cands_seg2}
    selection, warnings = optimizer.optimize_sequence([seg1, seg2], candidates_map)

    assert len(selection) == 2
    assert selection["seg-1"][0].shot_ids == ["s1"]
    assert selection["seg-2"][0].shot_ids == ["s3"]  # chosen over s1 to avoid duplicate penalty!


def test_no_valid_candidate(tmp_path: Path) -> None:
    """Verify optimizer outputs warnings when segments lack candidates, and writes outputs."""
    scorer = ClipScorer()
    transition_scorer = TransitionCompatibilityScorer()
    optimizer = GlobalClipOptimizer(scorer, transition_scorer)

    seg = NarrationSegment(
        id="seg-1", beat_id="beat_hook", text="Hello",
        event_ids=["e1"], visual_goal="goal", target_duration_ms=5000,
        estimated_spoken_duration_ms=4000, confidence=0.9, claims=[]
    )

    # Empty candidates
    selection, warnings = optimizer.optimize_sequence([seg], {})
    assert len(selection) == 0
    assert any("No candidates" in w for w in warnings)

    # Write check on empty maps
    optimizer.write_artifacts({}, {}, tmp_path)
    assert (tmp_path / "clip_rankings.json").exists()
    assert (tmp_path / "clip_selection.json").exists()
