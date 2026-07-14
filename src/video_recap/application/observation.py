"""Application protocols and models for keyframe-and-transcript fallback observation processing."""

from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple, Type, TypeVar
from pydantic import BaseModel, Field
from video_recap.application.ai import ProviderResponseMetadata
from video_recap.application.shot import Shot
from video_recap.domain.models import Observation, TranscriptCue

T = TypeVar("T", bound=BaseModel)


class ObservationBatch(BaseModel):
    """Aggregate payload containing a list of mapped factual observations."""

    observations: List[Observation] = Field(default_factory=list, description="Collection of observations.")
    modality_sources: List[str] = Field(
        default_factory=lambda: ["keyframe", "transcript"],
        description="The media modalities used to generate these observations (e.g., direct_video, keyframe, transcript).",
    )
    coverage_gaps: List[Tuple[float, float]] = Field(
        default_factory=list,
        description="Time segments (start_sec, end_sec) lacking both keyframe images and transcript dialogue.",
    )


class FrameBatchPlanner(Protocol):
    """Protocol for selecting representative keyframes while weeding out near-duplicates."""

    def plan_keyframes(
        self,
        keyframes: List[Tuple[Path, float]],
        similarity_threshold: float = 0.95,
    ) -> List[Tuple[Path, float]]:
        """Filter out keyframes that look too similar to preserve context window space.

        Args:
            keyframes: List of (image_path, absolute_timestamp_sec).
            similarity_threshold: Structural similarity threshold above which a frame is skipped.

        Returns:
            Filtered list of unique keyframes with absolute timestamps.
        """
        ...


class ContextWindowBuilder(Protocol):
    """Protocol for assembling a VLM/LLM prompt with shot, frame, and audio timelines."""

    def build_context(
        self,
        shots: List[Shot],
        planned_keyframes: List[Tuple[Path, float]],
        cues: List[TranscriptCue],
        custom_instructions: Optional[str] = None,
    ) -> str:
        """Generate structured contextual text prompt combining shots, frames, and dialogue.

        Args:
            shots: List of video shots.
            planned_keyframes: Selected keyframe paths and their absolute timestamps.
            cues: Audio speech transcription cues.
            custom_instructions: Extra instructions for the reasoning model.

        Returns:
            Assembled prompt string.
        """
        ...


class FrameTranscriptObservationProvider(Protocol):
    """Protocol for observation providers executing VLM/LLM reasoning over keyframes and transcript."""

    def observe_fallback(
        self,
        shots: List[Shot],
        keyframes: List[Tuple[Path, float]],
        cues: List[TranscriptCue],
        prompt: str,
        schema_cls: Type[T],
    ) -> Tuple[T, ProviderResponseMetadata]:
        """Perform multimodal or context-based reasoning fallback to generate observations.

        Args:
            shots: Chronological list of Shots.
            keyframes: List of all extracted keyframes with absolute timestamps.
            cues: Chronological speech transcript cues.
            prompt: Text prompt guiding observation target parameters.
            schema_cls: Target Pydantic model for validation (e.g. ObservationBatch).

        Returns:
            Validated output model and provider metadata.
        """
        ...
