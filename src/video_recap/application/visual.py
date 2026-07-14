"""Application protocols and models for Keyframe extraction and visual signals analysis."""

from pathlib import Path
from typing import List, Optional, Protocol, Tuple
from pydantic import BaseModel, Field
from video_recap.application.pipeline import CancellationToken
from video_recap.application.shot import Shot


class VisualSignals(BaseModel):
    """Aggregate payload containing calculated visual quality and motion metrics for a shot."""

    shot_id: str = Field(..., description="The corresponding shot identifier.")
    motion_score: float = Field(0.0, description="Movement activity level within the shot (0.0 to 1.0).")
    black_ratio: float = Field(0.0, description="Percentage of dark or black frames in the shot.")
    freeze_similarity: float = Field(0.0, description="Temporal similarity metric indicating still or frozen frames.")
    sharpness_score: float = Field(0.0, description="Image focus sharpness value (0.0 to 1.0).")
    brightness: float = Field(0.0, description="Mean brightness level of the keyframe (0.0 to 1.0).")
    subject_presence: bool = Field(False, description="True if a primary subject/face is detected in keyframes.")
    subject_description: Optional[str] = Field(None, description="Optional description of key subjects/faces.")
    keyframe_paths: List[str] = Field(default_factory=list, description="List of generated keyframe paths.")


class KeyframeExtractor(Protocol):
    """Protocol for extracting specific video frames as JPEG images."""

    def extract_keyframes(
        self,
        video_path: Path | str,
        shot: Shot,
        dest_dir: Path | str,
        motion_score: float = 0.0,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> List[Path]:
        """Extract representative frames for a shot based on duration and motion.

        Args:
            video_path: Source video path.
            shot: The Shot domain model.
            dest_dir: Destination folder to write keyframe JPEGs.
            motion_score: Calculated motion of the shot to influence sampling density.
            cancellation_token: Optional cancellation token.

        Returns:
            List of absolute paths to the extracted keyframe files.
        """
        ...


class MotionAnalyzer(Protocol):
    """Protocol for analyzing temporal motion velocity in video segments."""

    def analyze_motion(
        self,
        video_path: Path | str,
        shot: Shot,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> float:
        """Compute visual motion score between 0.0 and 1.0 for the shot duration."""
        ...


class BlackFrameAnalyzer(Protocol):
    """Protocol for detecting black frames or dark ratios in images."""

    def analyze_black_ratio(self, image_path: Path | str) -> float:
        """Compute the ratio of black pixels (value < threshold) in the keyframe."""
        ...


class FreezeFrameAnalyzer(Protocol):
    """Protocol for detecting still or frozen frame sequences."""

    def analyze_freeze_similarity(self, image_path_1: Path | str, image_path_2: Path | str) -> float:
        """Calculate the structural or pixel similarity score (0.0 to 1.0) between two keyframes."""
        ...


class SharpnessAnalyzer(Protocol):
    """Protocol for computing focus sharpness and blur level of frames."""

    def analyze_sharpness(self, image_path: Path | str) -> float:
        """Compute a sharpness score between 0.0 (very blurry) and 1.0 (extremely sharp)."""
        ...


class FacePresenceAnalyzer(Protocol):
    """Protocol for analyzing if subjects or human faces are present in the shot."""

    def analyze_face_presence(self, image_path: Path | str) -> Tuple[bool, str]:
        """Detect faces or objects, returning a presence flag and textual description."""
        ...
