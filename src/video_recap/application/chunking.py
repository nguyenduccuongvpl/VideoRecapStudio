"""Application components for segmenting videos into analysis chunks and reconciling observations."""

import logging
from pathlib import Path
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field
from video_recap.application.shot import Shot
from video_recap.domain.models import Observation

logger = logging.getLogger("Chunking")


class AnalysisChunk(BaseModel):
    """Represents a time segment of the source video designated for parallel or chunked analysis."""

    chunk_id: str = Field(..., description="Unique identifier for the chunk.")
    start_sec: float = Field(..., ge=0.0, description="Start time in seconds relative to video start.")
    end_sec: float = Field(..., ge=0.0, description="End time in seconds relative to video start.")
    overlap_sec: float = Field(default=0.0, ge=0.0, description="Overlap with the next chunk in seconds.")

    @property
    def duration(self) -> float:
        return self.end_sec - self.start_sec


class ChunkOverlapPolicy(BaseModel):
    """Configuration parameters for splitting and overlapping video chunks."""

    target_duration_sec: float = Field(600.0, ge=60.0, description="Target chunk length in seconds (default 10 mins).")
    overlap_duration_sec: float = Field(20.0, ge=0.0, description="Overlap duration in seconds.")
    align_to_shots: bool = Field(True, description="Whether to shift cut borders to the nearest shot boundaries.")


class AnalysisChunkPlanner:
    """Plans video segmentation into chunks, optionally aligning boundaries to scene shots."""

    def __init__(self, policy: ChunkOverlapPolicy) -> None:
        self.policy = policy

    def plan_chunks(
        self,
        total_duration_sec: float,
        shots: List[Shot],
        max_file_size_bytes: Optional[int] = None,
    ) -> List[AnalysisChunk]:
        """Divide the timeline into a list of aligned AnalysisChunks.

        Args:
            total_duration_sec: Total length of the video in seconds.
            shots: List of detected Shots.
            max_file_size_bytes: Optional constraint to reduce chunk sizes if needed.

        Returns:
            List of planned AnalysisChunks.
        """
        if total_duration_sec <= 0.0:
            return []

        chunks = []
        current_start = 0.0
        chunk_idx = 0

        # Extract shot boundaries (end times in seconds)
        shot_ends = sorted(list({s.end_ms / 1000.0 for s in shots}))

        while current_start < total_duration_sec:
            target_end = current_start + self.policy.target_duration_sec

            if target_end >= total_duration_sec:
                end_sec = total_duration_sec
                overlap = 0.0
                next_start = total_duration_sec
            else:
                end_sec = target_end
                # Align to nearest shot boundary if enabled
                if self.policy.align_to_shots and shot_ends:
                    # Find the shot end closest to target_end
                    closest_end = min(shot_ends, key=lambda x: abs(x - target_end))
                    
                    # Ensure we don't align to something behind current start
                    if closest_end > current_start + 10.0:
                        end_sec = closest_end

                overlap = self.policy.overlap_duration_sec
                next_start = end_sec - overlap
                
                # Prevent infinite loops/no-progress
                if next_start <= current_start:
                    next_start = current_start + (self.policy.target_duration_sec / 2.0)

            chunk_id = f"chunk_{chunk_idx:03d}"
            chunks.append(
                AnalysisChunk(
                    chunk_id=chunk_id,
                    start_sec=current_start,
                    end_sec=end_sec,
                    overlap_sec=overlap if next_start < total_duration_sec else 0.0,
                )
            )

            current_start = next_start
            chunk_idx += 1

        return chunks


class ObservationDeduplicator:
    """Deduplicates observations occurring in overlap regions based on temporal proximity and description."""

    def __init__(self, time_tolerance_sec: float = 3.0, similarity_threshold: float = 0.4) -> None:
        self.time_tolerance_sec = time_tolerance_sec
        self.similarity_threshold = similarity_threshold

    def calculate_similarity(self, s1: str, s2: str) -> float:
        """Calculate Jaccard similarity of word tokens using word prefixes."""
        w1 = {w[:4] for w in s1.lower().split() if len(w) > 2}
        w2 = {w[:4] for w in s2.lower().split() if len(w) > 2}
        if not w1 or not w2:
            return 0.0
        return len(w1 & w2) / len(w1 | w2)

    def deduplicate(self, observations: List[Observation]) -> List[Observation]:
        """Sort and merge duplicate observations.

        Args:
            observations: List of observations from all chunks.

        Returns:
            Deduplicated and merged list of observations.
        """
        if not observations:
            return []

        # Sort by timestamp
        sorted_obs = sorted(observations, key=lambda o: o.timestamp)
        merged: List[Observation] = []

        for obs in sorted_obs:
            duplicate_found = False
            
            for i, existing in enumerate(merged):
                # Check if within time tolerance
                time_diff = abs(existing.timestamp - obs.timestamp)
                if time_diff <= self.time_tolerance_sec:
                    # Check semantic similarity of descriptions
                    sim = self.calculate_similarity(existing.description, obs.description)
                    if sim >= self.similarity_threshold or existing.description in obs.description or obs.description in existing.description:
                        # Duplicate detected! Merge them.
                        duplicate_found = True
                        
                        # Merge strategy:
                        # 1. Keep highest confidence
                        # 2. Combine source flags (OR logic)
                        # 3. Take description of higher confidence, or longer description if equal
                        keep_existing = existing.confidence >= obs.confidence
                        if existing.confidence == obs.confidence:
                            keep_existing = len(existing.description) >= len(obs.description)

                        merged_desc = existing.description if keep_existing else obs.description
                        merged_confidence = max(existing.confidence, obs.confidence)
                        merged_timestamp = existing.timestamp if keep_existing else obs.timestamp

                        merged[i] = Observation(
                            id=existing.id,  # Preserve the original ID
                            timestamp=merged_timestamp,
                            description=merged_desc,
                            confidence=merged_confidence,
                            visual_source=existing.visual_source or obs.visual_source,
                            audio_source=existing.audio_source or obs.audio_source,
                        )
                        break
            
            if not duplicate_found:
                merged.append(obs)

        return merged


class ObservationReconciler:
    """Reconciles observations gathered from individual chunk analysis into a single consolidated timeline."""

    def __init__(self, deduplicator: ObservationDeduplicator) -> None:
        self.deduplicator = deduplicator

    def reconcile(self, chunk_observations: List[List[Observation]]) -> List[Observation]:
        """Aggregate observations from all chunks and resolve overlaps.

        Args:
            chunk_observations: List of observation lists, one list per analyzed chunk.

        Returns:
            Deduplicated, consolidated timeline of observations.
        """
        flat_obs = []
        for obs_list in chunk_observations:
            flat_obs.extend(obs_list)

        return self.deduplicator.deduplicate(flat_obs)
