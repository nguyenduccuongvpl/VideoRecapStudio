"""Unit tests for TTS speech providers, catalog caching, pronunciation dictionary replacements, and request-hash caching."""

import time
import wave
import pytest
from pathlib import Path
from video_recap.application.tts import (
    VoiceDescriptor,
    ProsodySettings,
    PronunciationDictionary,
    SpeechRequest,
    MockSpeechProvider,
    EdgeSpeechProvider,
    VoiceCatalogCache,
    SpeechProviderRegistry,
)


def test_pronunciation_dictionary() -> None:
    """Verify abbreviation replacement replaces text mapping keys phonetic spellings."""
    dictionary = PronunciationDictionary(phrases={"TTS": "ti ti ét", "AI": "ay ai"})
    text = "Hệ thống TTS sử dụng AI"
    assert dictionary.apply(text) == "Hệ thống ti ti ét sử dụng ay ai"


def test_voice_catalog_cache() -> None:
    """Verify voice catalog cache TTL expiration behavior."""
    cache = VoiceCatalogCache(ttl_seconds=0.5)
    voices = [
        VoiceDescriptor(
            voice_id="v1", display_name="V1", gender="female", language="vi-VN", provider="mock"
        )
    ]

    cache.set("key", voices)
    assert cache.get("key") == voices

    # Sleep to expire cache TTL
    time.sleep(0.6)
    assert cache.get("key") is None


def test_mock_speech_provider_synthesis(tmp_path: Path) -> None:
    """Verify mock provider generates valid wav files and throws on unsupported voices."""
    provider = MockSpeechProvider()
    
    # Supported voice request
    req = SpeechRequest(
        text="Đây là lời thoại.",
        voice_id="vi-VN-HoaiMyNeural",
        prosody=ProsodySettings(speed=1.0),
        pronunciation_dict=PronunciationDictionary(),
        output_format="wav"
    )
    
    out_file = tmp_path / "test.wav"
    res = provider.synthesize(req, out_file)

    assert out_file.exists()
    assert res.audio_path == str(out_file.resolve())
    assert res.duration_ms > 0
    assert res.character_count == len("Đây là lời thoại.")
    assert len(res.request_hash) > 0

    # Verify wave file header is valid
    with wave.open(str(out_file), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 16000

    # Unsupported voice request
    req_bad = SpeechRequest(
        text="Text",
        voice_id="en-US-UnknownVoice",
        prosody=ProsodySettings(),
        pronunciation_dict=PronunciationDictionary(),
        output_format="wav"
    )
    with pytest.raises(ValueError, match="is not supported"):
        provider.synthesize(req_bad, out_file)


def test_edge_speech_provider_fallback(tmp_path: Path) -> None:
    """Verify edge provider defaults to mock provider if library is missing."""
    provider = EdgeSpeechProvider()
    
    # If not available (i.e. edge_tts not installed in virtual environment), must fallback to mock
    if not provider.is_available():
        req = SpeechRequest(
            text="Lời thoại tiếng Việt.",
            voice_id="vi-VN-HoaiMyNeural",
            prosody=ProsodySettings(speed=1.0),
            pronunciation_dict=PronunciationDictionary(),
            output_format="wav"
        )
        out_file = tmp_path / "edge.wav"
        res = provider.synthesize(req, out_file)
        assert out_file.exists()
        assert res.duration_ms > 0


def test_speech_provider_registry() -> None:
    """Verify speech provider registry can register and retrieve providers."""
    SpeechProviderRegistry.clear()
    provider = MockSpeechProvider()

    SpeechProviderRegistry.register("mock", provider)
    assert SpeechProviderRegistry.get("mock") == provider
    assert "mock" in SpeechProviderRegistry.list_providers()

    with pytest.raises(KeyError):
        SpeechProviderRegistry.get("unknown_provider")
