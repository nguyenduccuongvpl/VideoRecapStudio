"""Application components for generating and evaluating video clip candidates for narration segments."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from video_recap.application.shot import Shot
from video_recap.application.event import Event
from video_recap.application.narration import NarrationSegment

logger = logging.getLogger("ClipCandidate")


class ClipCandidate(BaseModel):
    """A potential video clip candidate to match a narration segment."""

    source_range: Tuple[float, float] = Field(..., description="Start and end time in seconds within source video.")
    shot_ids: List[str] = Field(..., description="Shot IDs encompassed by this candidate.")
    candidate_type: str = Field(
        ...,
        description="Type: exact_evidence, adjacent_setup, reaction, detail, establishing, action_continuation"
    )
    evidence_match: float = Field(..., ge=0.0, le=1.0, description="Match score with source evidence.")
    visual_goal_match: float = Field(..., ge=0.0, le=1.0, description="Match score with visual goal of narration.")
    motion: float = Field(0.5, ge=0.0, le=1.0, description="Average motion intensity of the clip.")
    sharpness: float = Field(0.8, ge=0.0, le=1.0, description="Visual sharpness metric.")
    black_freeze_risk: float = Field(0.0, ge=0.0, le=1.0, description="Risk score of black or frozen frames.")
    entity_match: float = Field(1.0, ge=0.0, le=1.0, description="Accuracy score of target characters present.")
    chronology: bool = Field(True, description="True if chronological order is satisfied.")
    usable_duration: float = Field(..., description="Duration of the candidate clip in seconds.")
    reasons: List[str] = Field(default_factory=list, description="Reasoning or notes about the candidate quality.")


class EvidenceToShotMapper:
    """Maps events and evidence timestamps to specific video shot boundaries."""

    def map_range_to_shots(self, start_sec: float, end_sec: float, shots: List[Shot]) -> List[Shot]:
        """Find shots overlapping with the given timestamp range."""
        overlapping = []
        for shot in shots:
            shot_start = shot.start_ms / 1000.0
            shot_end = shot.end_ms / 1000.0
            # Check overlap
            if max(start_sec, shot_start) < min(end_sec, shot_end):
                overlapping.append(shot)
        return overlapping


class ShotAdjacencyIndex:
    """Allows querying neighboring shots relative to reference shots."""

    def __init__(self, shots: List[Shot]) -> None:
        self.shots = sorted(shots, key=lambda s: s.start_ms)
        self.shot_map = {s.id: idx for idx, s in enumerate(self.shots)}

    def get_adjacent_shot(self, shot_id: str, offset: int) -> Optional[Shot]:
        """Get shot relative to reference shot ID. Offset -1 = before, +1 = after, etc."""
        if shot_id not in self.shot_map:
            return None
        ref_idx = self.shot_map[shot_id]
        target_idx = ref_idx + offset
        if 0 <= target_idx < len(self.shots):
            return self.shots[target_idx]
        return None


class CandidateConstraintPolicy:
    """Evaluates video quality, motion, freeze risk, and chronological safety rules."""

    def evaluate(
        self,
        candidate: ClipCandidate,
        max_black_freeze_risk: float = 0.3,
        min_sharpness: float = 0.4,
        min_duration: float = 0.5,
    ) -> List[str]:
        """Validate candidate against constraints and return validation errors/notes."""
        errors = []

        if candidate.black_freeze_risk > max_black_freeze_risk:
            errors.append(f"Black/freeze risk ({candidate.black_freeze_risk}) exceeds threshold ({max_black_freeze_risk}).")

        if candidate.sharpness < min_sharpness:
            errors.append(f"Sharpness ({candidate.sharpness}) is below threshold ({min_sharpness}).")

        if candidate.usable_duration < min_duration:
            errors.append(f"Usable duration ({candidate.usable_duration}s) is too short.")

        # Avoid cutting during active motion (e.g. motion intensity very close to 1.0 or 0.0)
        if candidate.motion > 0.9:
            errors.append("High motion intensity risk (cutting during peak action).")

        return errors


class ClipCandidateGenerator:
    """Generates candidate clips of various storytelling roles for narration segments."""

    def __init__(
        self,
        mapper: EvidenceToShotMapper,
        adjacency_index: ShotAdjacencyIndex,
        constraint_policy: CandidateConstraintPolicy,
    ) -> None:
        self.mapper = mapper
        self.adjacency_index = adjacency_index
        self.constraint_policy = constraint_policy

    def generate_candidates(
        self,
        segment: NarrationSegment,
        events: List[Event],
        shots: List[Shot],
    ) -> List[ClipCandidate]:
        """Generate multiple clip candidates matching a narration segment."""
        candidates = []
        event_map = {e.event_id: e for e in events}
        
        # Associated events for this narration segment
        segment_events = [event_map[eid] for eid in segment.event_ids if eid in event_map]
        if not segment_events:
            return []

        for event in segment_events:
            # Map event range to shots
            event_shots = self.mapper.map_range_to_shots(event.start_time, event.end_time, shots)
            if not event_shots:
                continue

            # 1. Exact evidence candidate
            exact_start = min(s.start_ms for s in event_shots) / 1000.0
            exact_end = max(s.end_ms for s in event_shots) / 1000.0
            exact_duration = exact_end - exact_start
            
            exact_cand = ClipCandidate(
                source_range=(exact_start, exact_end),
                shot_ids=[s.id for s in event_shots],
                candidate_type="exact_evidence",
                evidence_match=1.0,
                visual_goal_match=0.9,
                usable_duration=exact_duration,
                reasons=["Matches event time boundaries exactly."]
            )
            candidates.append(exact_cand)

            # 2. Adjacent setup candidate (shot immediately before)
            first_shot_id = event_shots[0].id
            before_shot = self.adjacency_index.get_adjacent_shot(first_shot_id, -1)
            if before_shot:
                b_start = before_shot.start_ms / 1000.0
                b_end = before_shot.end_ms / 1000.0
                candidates.append(
                    ClipCandidate(
                        source_range=(b_start, b_end),
                        shot_ids=[before_shot.id],
                        candidate_type="adjacent_setup",
                        evidence_match=0.4,
                        visual_goal_match=0.5,
                        usable_duration=b_end - b_start,
                        reasons=["Establishing/setup shot preceding the main action."]
                    )
                )

            # 3. Reaction candidate (shot immediately after)
            last_shot_id = event_shots[-1].id
            after_shot = self.adjacency_index.get_adjacent_shot(last_shot_id, 1)
            if after_shot:
                a_start = after_shot.start_ms / 1000.0
                a_end = after_shot.end_ms / 1000.0
                candidates.append(
                    ClipCandidate(
                        source_range=(a_start, a_end),
                        shot_ids=[after_shot.id],
                        candidate_type="reaction",
                        evidence_match=0.3,
                        visual_goal_match=0.4,
                        usable_duration=a_end - a_start,
                        reasons=["Reaction or aftermath shot following the main action."]
                    )
                )

            # 4. Detail candidate (high-quality individual shot from the event list)
            if len(event_shots) > 1:
                # Select the best shot based on mock quality metrics
                best_shot = max(event_shots, key=lambda s: s.cut_score or 0.5)
                det_start = best_shot.start_ms / 1000.0
                det_end = best_shot.end_ms / 1000.0
                candidates.append(
                    ClipCandidate(
                        source_range=(det_start, det_end),
                        shot_ids=[best_shot.id],
                        candidate_type="detail",
                        evidence_match=0.8,
                        visual_goal_match=0.7,
                        usable_duration=det_end - det_start,
                        reasons=["High-quality detail closeup/shot from within event."]
                    )
                )

            # 5. Establishing candidate (first shot of the whole video)
            if shots:
                est_shot = shots[0]
                est_start = est_shot.start_ms / 1000.0
                est_end = est_shot.end_ms / 1000.0
                candidates.append(
                    ClipCandidate(
                        source_range=(est_start, est_end),
                        shot_ids=[est_shot.id],
                        candidate_type="establishing",
                        evidence_match=0.2,
                        visual_goal_match=0.3,
                        usable_duration=est_end - est_start,
                        reasons=["Wide establishing shot of the scene."]
                    )
                )

            # 6. Action continuation candidate (encompasses evidence + reaction)
            if after_shot:
                cont_start = exact_start
                cont_end = after_shot.end_ms / 1000.0
                candidates.append(
                    ClipCandidate(
                        source_range=(cont_start, cont_end),
                        shot_ids=[s.id for s in event_shots] + [after_shot.id],
                        candidate_type="action_continuation",
                        evidence_match=0.9,
                        visual_goal_match=0.8,
                        usable_duration=cont_end - cont_start,
                        reasons=["Continuous action flowing from evidence to aftermath."]
                    )
                )

        # Filter out candidates with constraint violations or tag them
        valid_candidates = []
        for cand in candidates:
            errors = self.constraint_policy.evaluate(cand)
            if not errors:
                valid_candidates.append(cand)
            else:
                cand.reasons.extend([f"Constraint violation: {err}" for err in errors])
                # Only keep if not critical duration/black-freeze failures
                is_crit = any("too short" in err or "Black/freeze risk" in err for err in errors)
                if not is_crit:
                    valid_candidates.append(cand)

        return valid_candidates

    def write_candidates_artifact(
        self,
        segment_candidates: Dict[str, List[ClipCandidate]],
        output_path: Path,
    ) -> None:
        """Write all generated candidates to clip_candidates.json."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        serializable = {
            seg_id: [c.model_dump() for c in cands]
            for seg_id, cands in segment_candidates.items()
        }
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)
        logger.info(f"Successfully wrote Clip Candidates to {output_path}")
