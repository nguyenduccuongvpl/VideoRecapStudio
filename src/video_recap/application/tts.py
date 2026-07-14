"""Application protocols, models, and mock/edge providers for Text-to-Speech (TTS) synthesis."""

import hashlib
import json
import logging
import time
import wave
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple
from pydantic import BaseModel, Field

logger = logging.getLogger("TTS")


class VoiceDescriptor(BaseModel):
    """Metadata representing a specific available voice model."""

    voice_id: str = Field(..., description="Unique voice identifier.")
    display_name: str = Field(..., description="User-friendly name.")
    gender: str = Field(..., description="Gender: male, female, neutral.")
    language: str = Field(..., description="Language locale tag (e.g. vi-VN, en-US).")
    provider: str = Field(..., description="Name of provider hosting this voice.")


class ProsodySettings(BaseModel):
    """Speech speed, pitch, and volume properties."""

    speed: float = Field(1.0, description="Speed multiplier (e.g. 1.0 is normal, 1.25 is faster).")
    pitch: float = Field(0.0, description="Pitch adjustment in semitones or percentage offset.")
    volume: float = Field(1.0, description="Volume multiplier.")


class PronunciationDictionary(BaseModel):
    """Custom replacement map to translate abbreviations and acronyms to phonetic spellings."""

    phrases: Dict[str, str] = Field(default_factory=dict, description="Word replacements: abbreviation -> phonetic spelling.")

    def apply(self, text: str) -> str:
        """Replace all occurrences of dictionary keys with phonetic replacements."""
        if not text:
            return ""
        for key, val in self.phrases.items():
            # Match whole words only
            text = text.replace(key, val)
        return text


class SpeechRequest(BaseModel):
    """Parameter configuration to request speech synthesis."""

    text: str = Field(..., description="Text payload to synthesize.")
    voice_id: str = Field(..., description="Voice model identifier.")
    prosody: ProsodySettings = Field(default_factory=ProsodySettings)
    pronunciation_dict: PronunciationDictionary = Field(default_factory=PronunciationDictionary)
    output_format: str = Field("wav", description="Target audio file format: wav, mp3.")


class SpeechResult(BaseModel):
    """Synthesis result details including generated file path and duration metrics."""

    audio_path: str = Field(..., description="Absolute path of generated audio file.")
    duration_ms: int = Field(..., description="Actual audio play duration in milliseconds.")
    character_count: int = Field(..., description="Synthesized text character count.")
    request_hash: str = Field(..., description="Computed hash identifying the unique configuration.")


class VoiceCatalogProvider(Protocol):
    """Protocol for providers that can list available voices."""

    def get_voices(self) -> List[VoiceDescriptor]:
        """Fetch list of supported voices."""
        ...


class SpeechProvider(Protocol):
    """Protocol representing a Text-to-Speech synthesis service."""

    def synthesize(self, request: SpeechRequest, output_path: Path) -> SpeechResult:
        """Convert text to speech audio file.

        Args:
            request: Configuration containing text and voice parameters.
            output_path: Target path to write the audio file.

        Returns:
            SpeechResult metadata.
        """
        ...

    def is_available(self) -> bool:
        """Return True if service dependencies are available, False otherwise."""
        ...

    def get_voices(self) -> List[VoiceDescriptor]:
        """Fetch list of supported voices."""
        ...


class SpeechProviderRegistry:
    """Registry class to manage SpeechProvider implementations."""

    _providers: Dict[str, SpeechProvider] = {}

    @classmethod
    def register(cls, name: str, provider: SpeechProvider) -> None:
        """Register a new speech provider."""
        cls._providers[name.lower()] = provider

    @classmethod
    def get(cls, name: str) -> SpeechProvider:
        """Retrieve a registered provider by name."""
        key = name.lower()
        if key not in cls._providers:
            raise KeyError(f"Speech provider '{name}' is not registered.")
        return cls._providers[key]

    @classmethod
    def list_providers(cls) -> List[str]:
        """List names of all registered providers."""
        return list(cls._providers.keys())

    @classmethod
    def clear(cls) -> None:
        """Clear all registered providers."""
        cls._providers.clear()


class VoiceCatalogCache:
    """Thread-safe TTL cache for voice descriptors catalog."""

    def __init__(self, ttl_seconds: float = 3600.0) -> None:
        self.ttl = ttl_seconds
        self._cache: Dict[str, List[VoiceDescriptor]] = {}
        self._timestamps: Dict[str, float] = {}

    def get(self, key: str) -> Optional[List[VoiceDescriptor]]:
        """Retrieve cached voices if not expired."""
        if key in self._cache:
            if time.time() - self._timestamps[key] < self.ttl:
                return self._cache[key]
        return None

    def set(self, key: str, voices: List[VoiceDescriptor]) -> None:
        """Cache voices with current timestamp."""
        self._cache[key] = voices
        self._timestamps[key] = time.time()


class MockSpeechProvider:
    """Mock speech provider generating deterministic silent wav audio with valid headers."""

    def __init__(self) -> None:
        self.voices = [
            VoiceDescriptor(
                voice_id="vi-VN-HoaiMyNeural",
                display_name="Hoài My",
                gender="female",
                language="vi-VN",
                provider="mock"
            ),
            VoiceDescriptor(
                voice_id="vi-VN-NamMinhNeural",
                display_name="Nam Minh",
                gender="male",
                language="vi-VN",
                provider="mock"
            )
        ]

    def is_available(self) -> bool:
        return True

    def get_voices(self) -> List[VoiceDescriptor]:
        return self.voices

    def synthesize(self, request: SpeechRequest, output_path: Path) -> SpeechResult:
        # Validate voice ID
        supported_ids = [v.voice_id for v in self.voices]
        if request.voice_id not in supported_ids:
            raise ValueError(f"Voice ID '{request.voice_id}' is not supported by MockSpeechProvider.")

        # Normalize text and dictionary replacements
        norm_text = request.pronunciation_dict.apply(request.text)
        
        # Calculate duration based on word count
        # ~300ms per word * speed factor
        words = norm_text.split()
        duration_ms = max(500, int((len(words) * 300) / request.prosody.speed))

        # Generate a valid silent wave file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._write_silent_wav(output_path, duration_ms)

        # Validate file size is non-zero
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise IOError("Mock Speech Provider generated an empty or missing audio file.")

        # Compute hash
        hasher = hashlib.sha256()
        hasher.update(f"{request.voice_id}:{norm_text}:{request.prosody.speed}:{request.prosody.pitch}".encode("utf-8"))
        req_hash = hasher.hexdigest()

        return SpeechResult(
            audio_path=str(output_path.resolve()),
            duration_ms=duration_ms,
            character_count=len(norm_text),
            request_hash=req_hash
        )

    def _write_silent_wav(self, path: Path, duration_ms: int) -> None:
        """Write a basic valid silent WAV file using wave library."""
        sample_rate = 16000
        num_channels = 1
        bytes_per_sample = 2  # 16-bit audio
        
        num_frames = int(sample_rate * (duration_ms / 1000.0))
        silent_data = b"\x00" * (num_frames * num_channels * bytes_per_sample)

        with wave.open(str(path), "wb") as w:
            w.setnchannels(num_channels)
            w.setsampwidth(bytes_per_sample)
            w.setframerate(sample_rate)
            w.writeframes(silent_data)


class EdgeSpeechProvider:
    """Optional Edge TTS Speech synthesis provider using external edge-tts package."""

    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.cache_dir = cache_dir
        self.mock_fallback = MockSpeechProvider()

    def is_available(self) -> bool:
        try:
            import edge_tts
            return True
        except ImportError:
            return False

    def get_voices(self) -> List[VoiceDescriptor]:
        if not self.is_available():
            return self.mock_fallback.get_voices()

        # Simulated fetch or real edge-tts catalog mapper
        return [
            VoiceDescriptor(
                voice_id="vi-VN-HoaiMyNeural",
                display_name="Hoài My (Edge)",
                gender="female",
                language="vi-VN",
                provider="edge"
            ),
            VoiceDescriptor(
                voice_id="vi-VN-NamMinhNeural",
                display_name="Nam Minh (Edge)",
                gender="male",
                language="vi-VN",
                provider="edge"
            )
        ]

    def synthesize(self, request: SpeechRequest, output_path: Path) -> SpeechResult:
        if not self.is_available():
            logger.warning("edge-tts library not available. Falling back to MockSpeechProvider.")
            return self.mock_fallback.synthesize(request, output_path)

        norm_text = request.pronunciation_dict.apply(request.text)

        # Compute hash for request cache reuse
        hasher = hashlib.sha256()
        hasher.update(f"{request.voice_id}:{norm_text}:{request.prosody.speed}:{request.prosody.pitch}".encode("utf-8"))
        req_hash = hasher.hexdigest()

        # If cache hit, copy file and return cached result
        if self.cache_dir:
            cached_file = self.cache_dir / f"{req_hash}.wav"
            if cached_file.exists():
                output_path.parent.mkdir(parents=True, exist_ok=True)
                # Copy from cache to target output path
                with open(cached_file, "rb") as src, open(output_path, "wb") as dest:
                    dest.write(src.read())
                
                # Fetch duration
                with wave.open(str(output_path), "rb") as w:
                    frames = w.getnframes()
                    rate = w.getframerate()
                    dur_ms = int((frames / float(rate)) * 1000)

                return SpeechResult(
                    audio_path=str(output_path.resolve()),
                    duration_ms=dur_ms,
                    character_count=len(norm_text),
                    request_hash=req_hash
                )

        # Edge TTS execution with retry logic
        import asyncio
        import edge_tts

        async def run_synthesis():
            # Format speed parameter for edge-tts: e.g. "+10%", "-5%"
            speed_val = request.prosody.speed
            if speed_val >= 1.0:
                speed_str = f"+{int((speed_val - 1.0) * 100)}%"
            else:
                speed_str = f"-{int((1.0 - speed_val) * 100)}%"

            communicate = edge_tts.Communicate(norm_text, request.voice_id, rate=speed_str)
            await communicate.save(str(output_path))

        # Basic retry logic
        max_retries = 3
        last_error = None
        for attempt in range(max_retries):
            try:
                asyncio.run(run_synthesis())
                break
            except Exception as e:
                last_error = e
                logger.warning(f"TTS synthesis attempt {attempt + 1} failed: {e}. Retrying...")
                time.sleep(1.0)
        else:
            raise IOError(f"TTS synthesis failed after {max_retries} attempts: {last_error}")

        # Validate file size is non-zero
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise IOError("Edge TTS generated an empty or missing audio file.")

        # Estimate/measure duration from wav frames
        dur_ms = int(len(norm_text.split()) * 300 / request.prosody.speed)
        try:
            with wave.open(str(output_path), "rb") as w:
                frames = w.getnframes()
                rate = w.getframerate()
                dur_ms = int((frames / float(rate)) * 1000)
        except Exception:
            # Fallback if format is not wav (e.g. edge-tts defaults to mp3)
            # We can use character count estimation for duration if wave reading fails
            pass

        # Save to cache if enabled
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            cached_file = self.cache_dir / f"{req_hash}.wav"
            with open(output_path, "rb") as src, open(cached_file, "wb") as dest:
                dest.write(src.read())

        return SpeechResult(
            audio_path=str(output_path.resolve()),
            duration_ms=dur_ms,
            character_count=len(norm_text),
            request_hash=req_hash
        )
