"""Application protocols and models for Shot and Scene boundary detection."""

from pathlib import Path
from typing import List, Optional, Protocol
from pydantic import BaseModel, Field
from video_recap.application.pipeline import CancellationToken


class Shot(BaseModel):
    """Metadata representing a single detected camera shot."""

    id: str = Field(..., description="Unique shot identifier.")
    start_ms: int = Field(..., description="Start timestamp of the shot in milliseconds.")
    end_ms: int = Field(..., description="End timestamp of the shot in milliseconds.")
    start_frame: int = Field(..., description="Start video frame index (0-indexed).")
    end_frame: int = Field(..., description="End video frame index.")
    duration: float = Field(..., description="Duration of the shot in seconds.")
    detector: str = Field(..., description="Detector engine used (e.g. ffmpeg-scene, mock).")
    cut_score: Optional[float] = Field(None, description="Optional confidence cut score (0.0 to 1.0).")
    transition_type: str = Field("cut", description="Transition type: 'cut', 'fade', 'black'.")
    source_hash: str = Field(..., description="Checksum hash of the source video file.")
    is_synthetic: bool = Field(False, description="True if this was artificially split from a very long shot.")


class ShotDetectionService(Protocol):
    """Protocol for boundary shot detection services."""

    def detect_shots(
        self,
        video_path: Path | str,
        source_hash: str,
        genre: str = "default",
        cancellation_token: Optional[CancellationToken] = None,
    ) -> List[Shot]:
        """Analyze a video file and segment it into contiguous camera shots.

        Args:
            video_path: Path to the video on disk.
            source_hash: Checksum hash of the video.
            genre: Threshold profile name (e.g. default, action, interview).
            cancellation_token: Optional cancellation token.

        Returns:
            List of detected Shot models.
        """
        ...
