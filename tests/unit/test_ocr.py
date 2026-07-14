"""Unit tests for OCRObservation bounding box validators, confidence filtering, and temporal deduplication."""

import pytest
from pydantic import ValidationError
from video_recap.application.ocr import OCRObservation, OCRPostProcessor


def test_ocr_observation_valid_coordinates() -> None:
    """Verify valid normalized coordinates pass Pydantic validation."""
    obs = OCRObservation(
        text="Hello",
        confidence=0.85,
        bounding_box=(0.1, 0.2, 0.8, 0.9),
        timestamp=2.5,
        evidence_frame="frame.jpg",
    )
    assert obs.bounding_box == (0.1, 0.2, 0.8, 0.9)


def test_ocr_observation_invalid_range() -> None:
    """Verify coordinates outside [0.0, 1.0] raise ValidationError."""
    with pytest.raises(ValidationError):
        OCRObservation(
            text="Hello",
            confidence=0.85,
            bounding_box=(-0.1, 0.2, 0.8, 0.9),  # x_min negative
            timestamp=2.5,
            evidence_frame="frame.jpg",
        )

    with pytest.raises(ValidationError):
        OCRObservation(
            text="Hello",
            confidence=0.85,
            bounding_box=(0.1, 0.2, 1.5, 0.9),  # x_max > 1.0
            timestamp=2.5,
            evidence_frame="frame.jpg",
        )


def test_ocr_observation_invalid_dimensions() -> None:
    """Verify min > max coordinates raise ValidationError."""
    with pytest.raises(ValidationError):
        OCRObservation(
            text="Hello",
            confidence=0.85,
            bounding_box=(0.8, 0.2, 0.1, 0.9),  # x_min > x_max
            timestamp=2.5,
            evidence_frame="frame.jpg",
        )

    with pytest.raises(ValidationError):
        OCRObservation(
            text="Hello",
            confidence=0.85,
            bounding_box=(0.1, 0.9, 0.8, 0.2),  # y_min > y_max
            timestamp=2.5,
            evidence_frame="frame.jpg",
        )


def test_ocr_post_processor_filtering() -> None:
    """Verify confidence filtering discards low confidence detections."""
    observations = [
        OCRObservation(
            text="Keep Me",
            confidence=0.9,
            bounding_box=(0.1, 0.1, 0.5, 0.5),
            timestamp=1.0,
            evidence_frame="frame1.jpg",
        ),
        OCRObservation(
            text="Discard Me",
            confidence=0.45,  # below 0.6
            bounding_box=(0.1, 0.1, 0.5, 0.5),
            timestamp=2.0,
            evidence_frame="frame2.jpg",
        ),
    ]

    cleaned = OCRPostProcessor.filter_and_deduplicate(observations, min_confidence=0.6)
    assert len(cleaned) == 1
    assert cleaned[0].text == "Keep Me"


def test_ocr_post_processor_deduplication() -> None:
    """Verify temporal deduplication merges identical texts inside the window, preserving higher confidence."""
    observations = [
        # Match 1: lower confidence first, within window
        OCRObservation(
            text="Duplicate",
            confidence=0.7,
            bounding_box=(0.1, 0.1, 0.5, 0.5),
            timestamp=1.0,
            evidence_frame="frame1.jpg",
        ),
        OCRObservation(
            text="Duplicate",
            confidence=0.9,  # higher confidence
            bounding_box=(0.1, 0.1, 0.5, 0.5),
            timestamp=2.0,  # delta = 1.0s <= dedupe_window_sec (2.0s)
            evidence_frame="frame2.jpg",
        ),
        # Match 2: same text but outside the 2s window (from 2.0s to 5.0s delta is 3.0s)
        OCRObservation(
            text="Duplicate",
            confidence=0.8,
            bounding_box=(0.1, 0.1, 0.5, 0.5),
            timestamp=5.0,
            evidence_frame="frame3.jpg",
        ),
        # Match 3: different text in the same window
        OCRObservation(
            text="Unique",
            confidence=0.85,
            bounding_box=(0.1, 0.1, 0.5, 0.5),
            timestamp=1.5,
            evidence_frame="frame4.jpg",
        ),
    ]

    cleaned = OCRPostProcessor.filter_and_deduplicate(
        observations,
        min_confidence=0.6,
        dedupe_window_sec=2.0,
    )

    # Expected:
    # 1. "Duplicate" at 2.0s kept (replaces 1.0s one because of higher confidence).
    # 2. "Unique" at 1.5s kept.
    # 3. "Duplicate" at 5.0s kept (outside window of 2.0s one).
    assert len(cleaned) == 3
    
    texts = [c.text for c in cleaned]
    assert "Unique" in texts
    
    dup_obs = [c for c in cleaned if c.text == "Duplicate"]
    assert len(dup_obs) == 2
    # Check that the one at 2.0s has confidence 0.9 (meaning it successfully replaced the 0.7 one)
    assert any(d.timestamp == 2.0 and d.confidence == 0.9 for d in dup_obs)
    assert any(d.timestamp == 5.0 and d.confidence == 0.8 for d in dup_obs)
