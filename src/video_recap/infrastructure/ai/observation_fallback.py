"""Infrastructure implementation of frame + transcript fallback observation processing."""

import logging
import uuid
from pathlib import Path
from typing import List, Optional, Tuple, Type, TypeVar
from pydantic import BaseModel
from video_recap.application.ai import (
    TextReasoningProvider,
    StructuredGenerationRequest,
    ProviderResponseMetadata,
)
from video_recap.application.observation import (
    ObservationBatch,
    FrameBatchPlanner,
    ContextWindowBuilder,
    FrameTranscriptObservationProvider,
)
from video_recap.application.shot import Shot
from video_recap.application.visual import FreezeFrameAnalyzer
from video_recap.domain.models import Observation, TranscriptCue

logger = logging.getLogger("ObservationFallback")

T = TypeVar("T", bound=BaseModel)


class DefaultFrameBatchPlanner(FrameBatchPlanner):
    """Filters near-duplicate keyframes to keep context slim and focused."""

    def __init__(self, analyzer: Optional[FreezeFrameAnalyzer] = None) -> None:
        self.analyzer = analyzer

    def plan_keyframes(
        self,
        keyframes: List[Tuple[Path, float]],
        similarity_threshold: float = 0.95,
    ) -> List[Tuple[Path, float]]:
        if not keyframes:
            return []

        # Sort chronologically
        sorted_frames = sorted(keyframes, key=lambda k: k[1])
        planned = [sorted_frames[0]]

        for img_p, ts in sorted_frames[1:]:
            prev_p, _ = planned[-1]
            
            # If analyzer is provided, run freeze similarity
            if self.analyzer:
                try:
                    sim = self.analyzer.analyze_freeze_similarity(prev_p, img_p)
                    if sim >= similarity_threshold:
                        logger.info(f"Skipping near-duplicate frame: {img_p.name} (similarity: {sim:.2f})")
                        continue
                except Exception as e:
                    logger.warning(f"Failed to calculate similarity between {prev_p.name} and {img_p.name}: {e}")

            planned.append((img_p, ts))

        return planned


class DefaultContextWindowBuilder(ContextWindowBuilder):
    """Assembles prompt detailing video segments, selected keyframes and transcript dialogs."""

    def build_context(
        self,
        shots: List[Shot],
        planned_keyframes: List[Tuple[Path, float]],
        cues: List[TranscriptCue],
        custom_instructions: Optional[str] = None,
    ) -> str:
        lines = [
            "You are analyzing a video timeline reconstructed from keyframes and speech transcripts.",
            "Here is the timeline structured chronologically:",
            "",
        ]

        # Group by shots
        sorted_shots = sorted(shots, key=lambda s: s.start_ms)
        for shot in sorted_shots:
            start_s = shot.start_ms / 1000.0
            end_s = shot.end_ms / 1000.0
            lines.append(f"--- SHOT {shot.id} ({start_s:.2f}s - {end_s:.2f}s) ---")
            
            # Find keyframes inside this shot
            shot_frames = [
                (img_p, ts) for img_p, ts in planned_keyframes
                if shot.start_ms <= int(ts * 1000) <= shot.end_ms
            ]
            if shot_frames:
                lines.append("  Keyframes available at:")
                for img_p, ts in shot_frames:
                    lines.append(f"    - [{ts:.2f}s] File: {img_p.name}")
            else:
                lines.append("  (No keyframes available for this shot)")

            # Find transcript cues inside or overlapping this shot
            shot_cues = [
                cue for cue in cues
                if not ((cue.time_range.end * 1000.0) < shot.start_ms or (cue.time_range.start * 1000.0) > shot.end_ms)
            ]
            if shot_cues:
                lines.append("  Dialogue:")
                for cue in shot_cues:
                    cue_start = cue.time_range.start
                    cue_end = cue.time_range.end
                    lines.append(f"    - [{cue_start:.2f}s - {cue_end:.2f}s] \"{cue.text}\"")
            else:
                lines.append("  (No dialogue/speech detected in this shot)")
            lines.append("")

        lines.append("--- INSTRUCTIONS ---")
        lines.append("1. Ground visual statements strictly in the keyframes.")
        lines.append("2. If a visual action or detail is not present in the keyframe pictures, do not state it.")
        lines.append("3. Ground all audio/speech statements strictly in the dialogue transcript.")
        lines.append("4. Do not hallucinate dialogue or visual events outside the provided data.")
        
        if custom_instructions:
            lines.append(custom_instructions)

        return "\n".join(lines)


class DefaultFrameTranscriptObservationProvider(FrameTranscriptObservationProvider):
    """Fallback observation provider running LLM reasoning over planned context."""

    def __init__(
        self,
        reasoning_provider: TextReasoningProvider,
        planner: FrameBatchPlanner,
        builder: ContextWindowBuilder,
    ) -> None:
        self.reasoning_provider = reasoning_provider
        self.planner = planner
        self.builder = builder

    def observe_fallback(
        self,
        shots: List[Shot],
        keyframes: List[Tuple[Path, float]],
        cues: List[TranscriptCue],
        prompt: str,
        schema_cls: Type[T],
    ) -> Tuple[T, ProviderResponseMetadata]:
        # 1. Plan keyframes (remove duplicates)
        planned_frames = self.planner.plan_keyframes(keyframes)

        # 2. Build context text
        context_text = self.builder.build_context(shots, planned_frames, cues)
        full_prompt = f"{prompt}\n\n{context_text}"

        # 3. Request reasoning output
        request = StructuredGenerationRequest(
            prompt=full_prompt,
            schema_cls=schema_cls,
            temperature=0.0,
        )
        
        raw_result, meta = self.reasoning_provider.generate_structured(request)

        # 4. Map relative outputs / scale confidence / add metadata
        final_result = raw_result

        # Identify coverage gaps (segments >= 5.0 seconds with no keyframes or dialogue)
        gaps = self._detect_coverage_gaps(shots, keyframes, cues)

        # Apply fallback normalization:
        # If result is an ObservationBatch, adjust confidence scores down because of missing direct-video modality.
        if isinstance(final_result, ObservationBatch):
            adjusted_obs = []
            for obs in final_result.observations:
                # Scale confidence down by 20%
                scaled_confidence = max(0.0, min(1.0, obs.confidence * 0.8))
                
                # Make sure modality sources reflect the fallback sources
                adjusted_obs.append(
                    Observation(
                        id=obs.id,
                        timestamp=obs.timestamp,
                        description=obs.description,
                        confidence=scaled_confidence,
                        visual_source=obs.visual_source,
                        audio_source=obs.audio_source,
                    )
                )
            final_result = ObservationBatch(
                observations=adjusted_obs,
                modality_sources=["keyframe", "transcript"],
                coverage_gaps=gaps,
            )

        return final_result, meta

    def _detect_coverage_gaps(
        self,
        shots: List[Shot],
        keyframes: List[Tuple[Path, float]],
        cues: List[TranscriptCue],
    ) -> List[Tuple[float, float]]:
        """Identify intervals >= 5.0 seconds where no keyframes or transcript cues cover the video."""
        if not shots:
            return []

        # Determine total duration
        max_end_ms = max(s.end_ms for s in shots)
        total_duration = max_end_ms / 1000.0

        # Create 1-second interval coverage map
        covered = [False] * int(total_duration + 1)

        # Mark covered seconds
        for sec_idx in range(len(covered)):
            t = float(sec_idx)
            # Covered if a keyframe is within 2.0 seconds
            kf_cover = any(abs(ts - t) <= 2.0 for _, ts in keyframes)
            
            # Covered if a cue covers it
            cue_cover = any(cue.time_range.start <= t <= cue.time_range.end for cue in cues)
            
            if kf_cover or cue_cover:
                covered[sec_idx] = True

        # Find continuous uncovered gaps >= 5 seconds
        gaps = []
        in_gap = False
        gap_start = 0.0

        for sec_idx, is_cov in enumerate(covered):
            t = float(sec_idx)
            if not is_cov:
                if not in_gap:
                    in_gap = True
                    gap_start = t
            else:
                if in_gap:
                    in_gap = False
                    gap_dur = t - gap_start
                    if gap_dur >= 5.0:
                        gaps.append((gap_start, t))

        # Check trailing gap
        if in_gap:
            gap_dur = total_duration - gap_start
            if gap_dur >= 5.0:
                gaps.append((gap_start, total_duration))

        return gaps
