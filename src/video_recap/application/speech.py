"""Application protocols, registry, and models for Speech-to-Text translation."""

from typing import Callable, Dict, List, Optional, Protocol
from pydantic import BaseModel, Field
from video_recap.application.pipeline import CancellationToken
from video_recap.domain.models import TranscriptCue


class WordTimestamp(BaseModel):
    """Word-level alignment metadata."""

    word: str = Field(..., description="The spoken word text.")
    start: float = Field(..., description="Start timestamp of the word in seconds.")
    end: float = Field(..., description="End timestamp of the word in seconds.")
    probability: float = Field(..., description="Confidence probability between 0.0 and 1.0.")


class TranscriptionRequest(BaseModel):
    """Request payload configuration for Speech-to-Text conversion."""

    audio_path: str = Field(..., description="Absolute path to the audio WAV file.")
    language: Optional[str] = Field(None, description="ISO code to force language selection.")
    preferred_model: Optional[str] = Field(None, description="Model ID/size (e.g. base, tiny, small).")
    device: Optional[str] = Field(None, description="Execution device (e.g. cpu, cuda).")
    compute_type: Optional[str] = Field(None, description="Computation precision (e.g. int8, float16).")
    vad_filter: bool = Field(False, description="True to enable Voice Activity Detection filter.")


class TranscriptionResult(BaseModel):
    """Outcome payload containing parsed cues and metadata from transcription."""

    text: str = Field(..., description="Full combined transcription text.")
    language: str = Field(..., description="Detected or forced language ISO code.")
    language_probability: float = Field(..., description="Probability of language detection.")
    cues: List[TranscriptCue] = Field(..., description="Standardized cues with timestamps.")
    words: Optional[List[WordTimestamp]] = Field(None, description="Optional word-level details.")


class TranscriptionProvider(Protocol):
    """Protocol representing a backend provider for Speech-to-Text conversion."""

    def transcribe(
        self,
        request: TranscriptionRequest,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> TranscriptionResult:
        """Transcribe an audio file.

        Args:
            request: Transcription settings and file path.
            cancellation_token: Optional cancellation token.
            progress_callback: Optional progress percentage callback.

        Returns:
            TranscriptionResult object with text and cues.
        """
        ...

    def is_available(self) -> bool:
        """Return True if the underlying model/dependencies are available, False otherwise."""
        ...


class TranscriptionRegistry:
    """Registry class to manage and resolve multiple TranscriptionProvider implementations."""

    _providers: Dict[str, TranscriptionProvider] = {}

    @classmethod
    def register(cls, name: str, provider: TranscriptionProvider) -> None:
        """Register a new transcription provider."""
        cls._providers[name.lower()] = provider

    @classmethod
    def get(cls, name: str) -> TranscriptionProvider:
        """Retrieve a registered provider by name.

        Raises:
            KeyError: If the provider name is not registered.
        """
        key = name.lower()
        if key not in cls._providers:
            raise KeyError(f"Transcription provider '{name}' is not registered.")
        return cls._providers[key]

    @classmethod
    def list_providers(cls) -> List[str]:
        """List names of all registered providers."""
        return list(cls._providers.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered providers (mostly for tests)."""
        cls._providers.clear()
