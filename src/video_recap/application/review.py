"""Application domain models and logic for sampling, reviewing, and analyzing factual accuracy of observations."""

import math
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
from video_recap.domain.models import Observation


class ObservationReviewRecord(BaseModel):
    """Represents a human review entry for a single observation."""

    observation_id: str = Field(..., description="Reference ID of the observation reviewed.")
    timestamp: float = Field(..., description="Timestamp in seconds.")
    description: str = Field(..., description="Text description of the observed event.")
    confidence: float = Field(..., description="Model confidence score.")
    visual_source: bool = Field(..., description="True if visual details were checked.")
    audio_source: bool = Field(..., description="True if audio details were checked.")
    label: str = Field(
        ...,
        description="Reviewer tag: 'correct', 'partial', 'wrong', or 'unverifiable'."
    )
    notes: Optional[str] = Field(None, description="Reviewer feedback notes.")


class ReviewMetrics(BaseModel):
    """Summary of accuracy metrics gathered during human review."""

    total_reviewed: int = Field(0, description="Total observations inspected.")
    correct_count: int = Field(0, description="Count of fully correct observations.")
    partial_count: int = Field(0, description="Count of partially correct observations.")
    wrong_count: int = Field(0, description="Count of incorrect/wrong observations.")
    unverifiable_count: int = Field(0, description="Count of unverifiable observations.")
    factual_accuracy: float = Field(0.0, description="Weighted accuracy score in range [0.0, 1.0].")


def calculate_accuracy_metrics(records: List[ObservationReviewRecord]) -> ReviewMetrics:
    """Calculate review statistics and weighted factual accuracy percentage.

    Weighted Accuracy formula:
        (correct + 0.5 * partial) / (total_reviewed - unverifiable)
    """
    total = len(records)
    if total == 0:
        return ReviewMetrics()

    correct = sum(1 for r in records if r.label == "correct")
    partial = sum(1 for r in records if r.label == "partial")
    wrong = sum(1 for r in records if r.label == "wrong")
    unverifiable = sum(1 for r in records if r.label == "unverifiable")

    denominator = correct + partial + wrong
    accuracy = 0.0
    if denominator > 0:
        accuracy = (correct + 0.5 * partial) / denominator

    return ReviewMetrics(
        total_reviewed=total,
        correct_count=correct,
        partial_count=partial,
        wrong_count=wrong,
        unverifiable_count=unverifiable,
        factual_accuracy=accuracy,
    )


class StratifiedObservationSampler:
    """Selects a representative subset of observations across different confidence and modality strata."""

    def sample(self, observations: List[Observation], target_size: int = 20) -> List[Observation]:
        """Perform stratified sampling on observations.

        Strata are defined by combination of:
          - Confidence tier: 'high' (>=0.8), 'medium' (0.5 to <0.8), 'low' (<0.5)
          - Modality: 'visual_only', 'audio_only', 'multimodal'
        """
        if len(observations) <= target_size:
            return sorted(observations, key=lambda o: o.timestamp)

        # 1. Classify observations into strata buckets
        strata: Dict[Tuple[str, str], List[Observation]] = {}
        for obs in observations:
            # Determine confidence tier
            if obs.confidence >= 0.8:
                conf_tier = "high"
            elif obs.confidence >= 0.5:
                conf_tier = "medium"
            else:
                conf_tier = "low"

            # Determine modality
            if obs.visual_source and obs.audio_source:
                modality = "multimodal"
            elif obs.visual_source:
                modality = "visual_only"
            else:
                modality = "audio_only"

            key = (conf_tier, modality)
            strata.setdefault(key, []).append(obs)

        # 2. Distribute target size proportionally among non-empty strata
        # Sort keys to ensure deterministic ordering
        active_keys = sorted([k for k, v in strata.items() if len(v) > 0])
        total_obs = len(observations)

        samples_per_stratum: Dict[Tuple[str, str], int] = {}
        allocated = 0

        # Initial proportional allocation
        for key in active_keys:
            stratum_len = len(strata[key])
            proportion = stratum_len / total_obs
            count = max(1, int(round(proportion * target_size)))
            # Clamp to not exceed stratum size
            count = min(count, stratum_len)
            samples_per_stratum[key] = count
            allocated += count

        # Adjust allocation to match exactly target_size
        while allocated != target_size:
            if allocated < target_size:
                # Add 1 to the stratum with the largest remainder or size that is not fully allocated
                eligible_keys = [k for k in active_keys if samples_per_stratum[k] < len(strata[k])]
                if not eligible_keys:
                    break  # Cannot allocate more
                # Choose one deterministically (e.g. largest stratum)
                best_key = max(eligible_keys, key=lambda k: len(strata[k]) - samples_per_stratum[k])
                samples_per_stratum[best_key] += 1
                allocated += 1
            else:
                # Subtract 1 from the stratum with the most allocated slots (keeping at least 1 if possible)
                eligible_keys = [k for k in active_keys if samples_per_stratum[k] > 1]
                if not eligible_keys:
                    # If all are at 1, just take any key to subtract
                    eligible_keys = active_keys
                best_key = max(eligible_keys, key=lambda k: samples_per_stratum[k])
                samples_per_stratum[best_key] -= 1
                allocated -= 1

        # 3. Deterministically sample from each bucket (take evenly spaced samples)
        sampled_observations: List[Observation] = []
        for key in active_keys:
            bucket = sorted(strata[key], key=lambda o: o.timestamp)
            num_to_take = samples_per_stratum[key]
            n = len(bucket)
            if num_to_take >= n:
                sampled_observations.extend(bucket)
            else:
                # Select evenly spaced indices
                indices = [int(i * (n - 1) / (num_to_take - 1)) if num_to_take > 1 else 0 for i in range(num_to_take)]
                for idx in indices:
                    sampled_observations.append(bucket[idx])

        # Return sorted chronologically
        return sorted(sampled_observations, key=lambda o: o.timestamp)
