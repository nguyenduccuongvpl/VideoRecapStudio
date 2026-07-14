"""Infrastructure implementation of OCR providers (Mock and Local easyocr/pytesseract fallback)."""

import logging
from pathlib import Path
from typing import List, Optional
from video_recap.application.ocr import OCRObservation, OCRProvider

logger = logging.getLogger("OCRProvider")


class MockOCRProvider(OCRProvider):
    """Mock OCR provider allowing pre-seeded test observations or dummy detections."""

    def __init__(self) -> None:
        self._preset_observations: List[OCRObservation] = []

    def set_preset_observations(self, observations: List[OCRObservation]) -> None:
        """Inject preset observations for unit testing."""
        self._preset_observations = observations

    def detect_text(
        self,
        image_path: Path | str,
        timestamp: float,
        language_hint: Optional[str] = None,
    ) -> List[OCRObservation]:
        logger.info(f"Mock OCR processing image: {image_path}")

        # If preset observations exist, return them
        if self._preset_observations:
            return self._preset_observations

        # Generate a dummy observation based on filename
        img_p = Path(image_path)
        stem = img_p.stem.upper()
        
        # Return a single mock detection
        return [
            OCRObservation(
                text=f"DETECTED TEXT ON {stem}",
                confidence=0.85,
                bounding_box=(0.1, 0.2, 0.9, 0.4),
                timestamp=timestamp,
                language_hint=language_hint,
                evidence_frame=str(img_p.absolute()),
            )
        ]

    def is_available(self) -> bool:
        return True


class LocalOcrProvider(OCRProvider):
    """Local OCR provider using pytesseract or easyocr if available."""

    def detect_text(
        self,
        image_path: Path | str,
        timestamp: float,
        language_hint: Optional[str] = None,
    ) -> List[OCRObservation]:
        if not self.is_available():
            logger.warning("Local OCR libraries (pytesseract/easyocr) are not available. Skipping OCR.")
            return []

        # Placeholder local OCR execution logic
        # (This is disabled by default and handles local privacy/offline constraints gracefully)
        return []

    def is_available(self) -> bool:
        # Check pytesseract or easyocr imports
        try:
            import pytesseract  # type: ignore
            return True
        except ImportError:
            try:
                import easyocr  # type: ignore
                return True
            except ImportError:
                return False
