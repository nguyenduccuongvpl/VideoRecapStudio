"""Application components for clip candidate scoring, transition analysis, duplicate tracking, and global sequence optimization."""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field
from video_recap.application.candidate import ClipCandidate
from video_recap.application.narration import NarrationSegment

logger = logging.getLogger("ClipRanking")


class ScoreBreakdown(BaseModel):
    """Detail scoring profile for a clip candidate."""

    evidence_relevance: float = Field(..., description="Match with source evidence.")
    entity_match: float = Field(..., description="Entity match score.")
    visual_goal: float = Field(..., description="Visual goal description match.")
    motion_appropriateness: float = Field(..., description="Motion suitability score.")
    shot_quality: float = Field(..., description="Individual shot quality score.")
    chronology: float = Field(..., description="Chronological order validation score.")
    novelty: float = Field(..., description="Novelty score (absence of repetition).")
    transition: float = Field(..., description="Transition match score.")
    duplicate_penalty: float = Field(..., description="Penalty applied for reused shots.")
    black_freeze_penalty: float = Field(..., description="Penalty for freeze frame risks.")
    bad_cut_penalty: float = Field(..., description="Penalty for cutting during peak action.")
    total_score: float = Field(..., description="Final aggregated score.")


class SelectionExplanation(BaseModel):
    """Detailed reasoning of why a specific clip candidate was selected."""

    chosen_candidate_type: str = Field(..., description="The category of candidate selected.")
    score_breakdown: ScoreBreakdown = Field(..., description="Full numeric score breakdown.")
    notes: str = Field(..., description="Human-readable selection rationale.")


class ClipScorer:
    """Calculates deterministic score profiles for candidates based on metadata, quality, and narration rules."""

    def __init__(self, weights: Optional[Dict[str, float]] = None) -> None:
        self.weights = weights or {
            "evidence": 0.3,
            "entity": 0.2,
            "visual_goal": 0.2,
            "motion": 0.15,
            "quality": 0.15
        }

    def score_candidate(self, candidate: ClipCandidate, segment: NarrationSegment, beat_type: str) -> ScoreBreakdown:
        """Score a single candidate against segment guidelines."""
        # Evidence & entity matches from candidate metadata
        ev_score = candidate.evidence_match * self.weights["evidence"]
        ent_score = candidate.entity_match * self.weights["entity"]
        vg_score = candidate.visual_goal_match * self.weights["visual_goal"]

        # Setup beats don't always need high motion (favor stable shots)
        motion_val = candidate.motion
        if beat_type == "setup":
            # Prefer low-to-moderate motion (e.g. optimal at 0.3 to 0.6)
            motion_suitability = 1.0 - abs(motion_val - 0.45)
        else:
            motion_suitability = motion_val
        m_score = motion_suitability * self.weights["motion"]

        # Shot quality (based on sharpness)
        q_score = candidate.sharpness * self.weights["quality"]

        # Chronology check
        chron_val = 1.0 if candidate.chronology else 0.0

        # Penalties
        bf_penalty = candidate.black_freeze_risk * 1.5
        bc_penalty = 1.0 if candidate.motion > 0.9 else 0.0  # bad cut penalty for cutting at high action peak

        total = ev_score + ent_score + vg_score + m_score + q_score - bf_penalty - bc_penalty

        return ScoreBreakdown(
            evidence_relevance=ev_score,
            entity_match=ent_score,
            visual_goal=vg_score,
            motion_appropriateness=m_score,
            shot_quality=q_score,
            chronology=chron_val,
            novelty=1.0,
            transition=0.0,  # calculated during sequence optimization
            duplicate_penalty=0.0,  # calculated during sequence optimization
            black_freeze_penalty=bf_penalty,
            bad_cut_penalty=bc_penalty,
            total_score=round(total, 4)
        )


class DuplicateUsageTracker:
    """Manages shot duplication counts and computes penalties."""

    def __init__(self, base_penalty: float = 0.6) -> None:
        self.base_penalty = base_penalty
        self.used_shots: Dict[str, int] = {}

    def add_usage(self, shot_ids: List[str]) -> None:
        """Register usage of shots."""
        for sid in shot_ids:
            self.used_shots[sid] = self.used_shots.get(sid, 0) + 1

    def calculate_penalty(self, shot_ids: List[str]) -> float:
        """Calculate penalty if any of the shots have already been selected elsewhere."""
        penalty = 0.0
        for sid in shot_ids:
            usages = self.used_shots.get(sid, 0)
            if usages > 0:
                penalty += self.base_penalty * usages
        return penalty


class TransitionCompatibilityScorer:
    """Evaluates flow and visual jump cut compatibility between consecutive candidates."""

    def calculate_score(self, prev_candidate: Optional[ClipCandidate], current_candidate: ClipCandidate) -> float:
        """Score from 0.0 to 1.0 indicating visual transition smoothness."""
        if not prev_candidate:
            return 1.0  # first clip, no transition penalty
        
        prev_end = prev_candidate.source_range[1]
        curr_start = current_candidate.source_range[0]

        # Ideal transition: consecutive shots in chronology (no jump cut)
        if 0.0 <= (curr_start - prev_end) <= 0.1:
            return 1.0
        # Overlapping shots -> visual error (crosscutting/reused frames)
        elif curr_start < prev_end:
            return 0.1
        # Normal transition cut
        return 0.7


class GlobalClipOptimizer:
    """Finds the optimal deterministic sequence of clips for all segments utilizing DFS backtracking."""

    def __init__(
        self,
        scorer: ClipScorer,
        transition_scorer: TransitionCompatibilityScorer,
        duplicate_penalty_weight: float = 0.6,
    ) -> None:
        self.scorer = scorer
        self.transition_scorer = transition_scorer
        self.duplicate_penalty_weight = duplicate_penalty_weight

    def optimize_sequence(
        self,
        segments: List[NarrationSegment],
        candidates_map: Dict[str, List[ClipCandidate]],
    ) -> Tuple[Dict[str, Tuple[ClipCandidate, SelectionExplanation]], List[str]]:
        """Determine global best candidates using DFS backtracking to handle duplicate penalties and chronology constraints."""
        warnings = []
        best_sequence: List[ClipCandidate] = []
        best_score = -999999.0
        
        # Filter segments to only those that have candidates
        active_segments = [s for s in segments if s.id in candidates_map and candidates_map[s.id]]
        missing_segments = [s for s in segments if s.id not in candidates_map or not candidates_map[s.id]]

        for ms in missing_segments:
            warnings.append(f"No candidates found for segment {ms.id}. Segment will have no associated visual clip.")

        n = len(active_segments)
        if n == 0:
            return {}, warnings

        # DFS search
        def search(idx: int, current_selection: List[ClipCandidate], used_shots: Set[str], current_score: float) -> None:
            nonlocal best_score, best_sequence
            
            if idx == n:
                if current_score > best_score:
                    best_score = current_score
                    best_sequence = list(current_selection)
                return

            seg = active_segments[idx]
            candidates = candidates_map[seg.id]
            prev_cand = current_selection[-1] if current_selection else None

            for cand in candidates:
                # 1. Chronology Constraint: start of next candidate must be >= start of previous
                if prev_cand and cand.source_range[0] < prev_cand.source_range[0]:
                    continue

                # 2. Base score breakdown
                # Note: we pass beat_id as placeholder for beat_type since we don't have full Beat here,
                # we can infer it or pass a default "development".
                beat_type = "setup" if "setup" in seg.beat_id else "climax" if "climax" in seg.beat_id else "development"
                breakdown = self.scorer.score_candidate(cand, seg, beat_type)

                # 3. Transition score
                t_score = self.transition_scorer.calculate_score(prev_cand, cand)
                
                # 4. Duplicate penalty
                dup_count = sum(1 for sid in cand.shot_ids if sid in used_shots)
                dup_penalty = dup_count * self.duplicate_penalty_weight

                # Aggregated candidate score for this step
                step_score = breakdown.total_score + (t_score * 0.15) - dup_penalty

                # Recurse
                new_used = used_shots.union(cand.shot_ids)
                current_selection.append(cand)
                search(idx + 1, current_selection, new_used, current_score + step_score)
                current_selection.pop()

        search(0, [], set(), 0.0)

        # If no chronological sequence found (DFS best_sequence is empty but n > 0),
        # fallback to greedy tie-break search and raise warning
        if not best_sequence and n > 0:
            warnings.append("Chronology constraints could not be satisfied globally. Falling back to greedy local matching.")
            # Fallback greedy selection
            used_shots = set()
            prev_cand = None
            for seg in active_segments:
                candidates = candidates_map[seg.id]
                # Pick the highest candidate regardless of chronology
                best_cand = None
                best_cand_score = -99999.0
                for cand in candidates:
                    beat_type = "setup" if "setup" in seg.beat_id else "climax" if "climax" in seg.beat_id else "development"
                    breakdown = self.scorer.score_candidate(cand, seg, beat_type)
                    t_score = self.transition_scorer.calculate_score(prev_cand, cand)
                    dup_count = sum(1 for sid in cand.shot_ids if sid in used_shots)
                    dup_penalty = dup_count * self.duplicate_penalty_weight
                    step_score = breakdown.total_score + (t_score * 0.15) - dup_penalty
                    if step_score > best_cand_score:
                        best_cand_score = step_score
                        best_cand = cand
                
                if best_cand:
                    best_sequence.append(best_cand)
                    used_shots.update(best_cand.shot_ids)
                    prev_cand = best_cand

        # Build final optimized selection dictionary
        selection: Dict[str, Tuple[ClipCandidate, SelectionExplanation]] = {}
        used_shots_final = set()
        prev_cand = None

        for idx, seg in enumerate(active_segments):
            cand = best_sequence[idx]
            beat_type = "setup" if "setup" in seg.beat_id else "climax" if "climax" in seg.beat_id else "development"
            breakdown = self.scorer.score_candidate(cand, seg, beat_type)
            
            # Recalculate transition and duplicate details for the chosen candidate
            t_score = self.transition_scorer.calculate_score(prev_cand, cand)
            dup_count = sum(1 for sid in cand.shot_ids if sid in used_shots_final)
            dup_penalty = dup_count * self.duplicate_penalty_weight

            # Apply final scores to breakdown
            breakdown.transition = round(t_score * 0.15, 4)
            breakdown.duplicate_penalty = round(dup_penalty, 4)
            breakdown.total_score = round(breakdown.total_score + breakdown.transition - breakdown.duplicate_penalty, 4)

            explanation = SelectionExplanation(
                chosen_candidate_type=cand.candidate_type,
                score_breakdown=breakdown,
                notes=f"Selected {cand.candidate_type} with final score {breakdown.total_score}. " + ", ".join(cand.reasons)
            )

            selection[seg.id] = (cand, explanation)
            used_shots_final.update(cand.shot_ids)
            prev_cand = cand

        return selection, warnings

    def write_artifacts(
        self,
        candidates_map: Dict[str, List[ClipCandidate]],
        selection: Dict[str, Tuple[ClipCandidate, SelectionExplanation]],
        output_dir: Path,
    ) -> None:
        """Write clip_rankings.json and clip_selection.json artifacts."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # 1. clip_rankings.json
        rankings_data = {}
        for seg_id, cands in candidates_map.items():
            rankings_data[seg_id] = [c.model_dump() for c in sorted(cands, key=lambda c: c.usable_duration, reverse=True)]
        with open(output_dir / "clip_rankings.json", "w", encoding="utf-8") as f:
            json.dump(rankings_data, f, indent=2, ensure_ascii=False)

        # 2. clip_selection.json
        selection_data = {}
        for seg_id, (cand, expl) in selection.items():
            selection_data[seg_id] = {
                "candidate": cand.model_dump(),
                "explanation": expl.model_dump()
            }
        with open(output_dir / "clip_selection.json", "w", encoding="utf-8") as f:
            json.dump(selection_data, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully wrote Clip Ranking & Selection artifacts to {output_dir}")
