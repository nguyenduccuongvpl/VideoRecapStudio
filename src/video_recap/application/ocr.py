"""Application protocols and models for OCR (Optical Character Recognition) text detection."""

from pathlib import Path
from typing import List, Optional, Protocol, Tuple
from pydantic import BaseModel, Field, field_validator


class OCRObservation(BaseModel):
    """Normalized metadata representing a detected snippet of text on screen."""

    text: str = Field(..., description="The detected text content.")
    confidence: float = Field(..., description="Detector confidence score between 0.0 and 1.0.")
    bounding_box: Tuple[float, float, float, float] = Field(
        ...,
        description="Normalized bounding box coordinates (x_min, y_min, x_max, y_max) between 0.0 and 1.0.",
    )
    timestamp: float = Field(..., description="Video timeline timestamp in seconds when frame was sampled.")
    language_hint: Optional[str] = Field(None, description="Optional language code hint.")
    evidence_frame: str = Field(..., description="Path to the keyframe image file containing the text.")

    @field_validator("bounding_box")
    @classmethod
    def validate_bounding_box(cls, v: Tuple[float, float, float, float]) -> Tuple[float, float, float, float]:
        """Verify coordinates are normalized and mathematically valid."""
        x_min, y_min, x_max, y_max = v
        for val in (x_min, y_min, x_max, y_max):
            if not (0.0 <= val <= 1.0):
                raise ValueError("Bounding box coordinates must be normalized between 0.0 and 1.0.")
        if x_min > x_max:
            raise ValueError("Bounding box coordinate x_min must be <= x_max.")
        if y_min > y_max:
            raise ValueError("Bounding box coordinate y_min must be <= y_max.")
        return v


class OCRProvider(Protocol):
    """Protocol for OCR engines analyzing text in image frames."""

    def detect_text(
        self,
        image_path: Path | str,
        timestamp: float,
        language_hint: Optional[str] = None,
    ) -> List[OCRObservation]:
        """Scan an image and return detected text occurrences.

        Args:
            image_path: Path to the image file on disk.
            timestamp: Timeline timestamp of this frame.
            language_hint: Optional language code hint.

        Returns:
            List of OCRObservation items.
        """
        ...

    def is_available(self) -> bool:
        """Return True if the OCR dependencies are installed on the local system."""
        ...


class OCRPostProcessor:
    """Performs filtering and temporal deduplication on OCR observations."""

    @staticmethod
    def filter_and_deduplicate(
        observations: List[OCRObservation],
        min_confidence: float = 0.6,
        dedupe_window_sec: float = 2.0,
    ) -> List[OCRObservation]:
        """Filter out low confidence detections and deduplicate consecutive matching texts.

        Args:
            observations: List of raw OCR observations.
            min_confidence: Threshold below which detections are discarded.
            dedupe_window_sec: Window in seconds within which identical texts are merged.

        Returns:
            A cleaned list of OCRObservation items.
        """
        # 1. Filter by confidence
        filtered = [obs for obs in observations if obs.confidence >= min_confidence]
        if not filtered:
            return []

        # 2. Sort chronologically by timestamp
        filtered.sort(key=lambda o: o.timestamp)

        # 3. Temporal deduplication
        # If identical text occurs within dedupe_window_sec, we keep only the one with higher confidence
        deduplicated: List[OCRObservation] = []
        
        for obs in filtered:
            # Check if we already have this text within the window
            duplicate_found = False
            for idx, existing in enumerate(deduplicated):
                # Case-insensitive comparison of stripped text
                if existing.text.strip().lower() == obs.text.strip().lower():
                    if abs(obs.timestamp - existing.timestamp) <= dedupe_window_sec:
                        duplicate_found = True
                        # If current has higher confidence, replace the existing one
                        if obs.confidence > existing.confidence:
                            deduplicated[idx] = obs
                        break
            
            if not duplicate_found:
                deduplicated.append(obs)

        return deduplicated
