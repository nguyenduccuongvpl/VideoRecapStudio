"""Speech infrastructure implementations and registry initialization."""

from video_recap.application.speech import TranscriptionRegistry
from video_recap.infrastructure.speech.whisper import (
    MockTranscriptionProvider,
    FasterWhisperProvider,
)

# Initialize and register default providers
_mock = MockTranscriptionProvider()
_whisper = FasterWhisperProvider()

TranscriptionRegistry.register("mock", _mock)
TranscriptionRegistry.register("whisper", _whisper)

__all__ = [
    "MockTranscriptionProvider",
    "FasterWhisperProvider",
]
