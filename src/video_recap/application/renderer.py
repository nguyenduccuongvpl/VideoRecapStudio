"""Application protocols and models for deterministic video timeline rendering."""

from pathlib import Path
from typing import List, Optional, Protocol
from pydantic import BaseModel, Field


class NarrationOverlay(BaseModel):
    """Audio narration overlay payload config."""

    audio_path: str = Field(..., description="Absolute path to the narration WAV file.")
    start_time_in_clip: float = Field(0.0, description="Start time offset in seconds relative to this clip.")
    duration: float = Field(..., description="Duration of the narration audio in seconds.")


class TimelineClip(BaseModel):
    """Configuration representing a source video segment slice with audio overlays."""

    id: str = Field(..., description="Unique clip segment identifier.")
    source_start: float = Field(..., description="Source video start time in seconds.")
    source_end: float = Field(..., description="Source video end time in seconds.")
    original_audio_volume: float = Field(1.0, description="Volume level for original audio (0.0 to 1.0).")
    narrations: List[NarrationOverlay] = Field(default_factory=list, description="Narration audio overlays.")


class RenderTimeline(BaseModel):
    """Unified timeline configuration to be rendered."""

    clips: List[TimelineClip] = Field(..., description="Chronological sequence of video segments.")
    output_width: int = Field(1280, description="Width resolution of output video.")
    output_height: int = Field(720, description="Height resolution of output video.")
    output_fps: float = Field(30.0, description="Frame rate of output video.")


class RenderManifest(BaseModel):
    """Details and logs describing a completed render process."""

    timeline: RenderTimeline = Field(..., description="The timeline configuration that was rendered.")
    output_path: str = Field(..., description="Target output path where file was saved.")
    rendered_at: str = Field(..., description="ISO 8601 UTC timestamp of rendering.")
    duration: float = Field(..., description="Total duration of output video in seconds.")
    ffmpeg_commands: List[List[str]] = Field(default_factory=list, description="Executed FFmpeg commands list.")


class PreviewRenderer(Protocol):
    """Protocol for rendering manual preview videos from a timeline config."""

    def render_preview(
        self,
        video_path: Path | str,
        timeline: RenderTimeline,
        dest_path: Path | str,
        cancellation_token: Optional[object] = None,
    ) -> RenderManifest:
        """Process video segments, scale/pad, delay and mix narration, then concatenate them.

        Args:
            video_path: Source video path.
            timeline: The timeline configuration.
            dest_path: Destination path for the rendered MP4 file.
            cancellation_token: Optional cancellation token.

        Returns:
            RenderManifest with results.

        Raises:
            AudioDurationOverflowError: If narration overlays exceed clip segment length.
        """
        ...
