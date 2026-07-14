import sys
from unittest.mock import MagicMock

# Mock faster_whisper module before imports
sys.modules["faster_whisper"] = MagicMock()

import pytest
from pathlib import Path
from unittest.mock import patch
from video_recap.application.pipeline import CancellationToken
from video_recap.application.speech import (
    TranscriptionRegistry,
    TranscriptionRequest,
    TranscriptionResult,
)
from video_recap.domain import JobCancelledError
from video_recap.domain.models import TimeRange, TranscriptCue
from video_recap.infrastructure.speech.whisper import (
    MockTranscriptionProvider,
    FasterWhisperProvider,
)


@pytest.fixture
def mock_wav(tmp_path: Path) -> Path:
    f = tmp_path / "audio.wav"
    f.write_text("fake WAV audio content")
    return f


def test_provider_registry() -> None:
    """Verify registry resolves, lists, and raises KeyErrors for STT providers."""
    # Ensure default mock and whisper are registered
    import video_recap.infrastructure.speech  # triggers auto-register
    
    assert "mock" in TranscriptionRegistry.list_providers()
    assert "whisper" in TranscriptionRegistry.list_providers()

    mock_prov = TranscriptionRegistry.get("mock")
    assert isinstance(mock_prov, MockTranscriptionProvider)

    with pytest.raises(KeyError):
        TranscriptionRegistry.get("unknown_provider")


def test_mock_transcription_provider(mock_wav: Path) -> None:
    """Verify MockTranscriptionProvider generates cues, supports languages, and tracks progress."""
    provider = MockTranscriptionProvider()
    assert provider.is_available() is True

    # 1. Test english
    req = TranscriptionRequest(audio_path=str(mock_wav), language="en")
    progresses = []

    def progress(p: float) -> None:
        progresses.append(p)

    res = provider.transcribe(req, progress_callback=progress)

    assert isinstance(res, TranscriptionResult)
    assert res.language == "en"
    assert len(res.cues) == 3
    assert len(res.words) > 0
    assert "welcome" in res.text.lower()
    assert progresses == [0.1, 0.5, 0.9, 1.0]

    # 2. Test vietnamese
    req_vi = TranscriptionRequest(audio_path=str(mock_wav), language="vi")
    res_vi = provider.transcribe(req_vi)
    assert res_vi.language == "vi"
    assert "chào mừng" in res_vi.text.lower()


def test_mock_transcription_cancellation(mock_wav: Path) -> None:
    """Verify MockTranscriptionProvider raises JobCancelledError if token is cancelled."""
    provider = MockTranscriptionProvider()
    token = CancellationToken()
    token.cancel()

    req = TranscriptionRequest(audio_path=str(mock_wav))
    with pytest.raises(JobCancelledError):
        provider.transcribe(req, cancellation_token=token)


def test_whisper_unavailable_raises_runtime_error(mock_wav: Path) -> None:
    """Verify FasterWhisperProvider throws clean message if library is not available."""
    provider = FasterWhisperProvider()
    
    with patch.object(FasterWhisperProvider, "is_available", return_value=False):
        req = TranscriptionRequest(audio_path=str(mock_wav))
        with pytest.raises(RuntimeError) as exc_info:
            provider.transcribe(req)
        assert "faster-whisper is not installed" in str(exc_info.value)


@patch("faster_whisper.WhisperModel")
def test_whisper_cpu_fallback(mock_model_class: MagicMock, mock_wav: Path) -> None:
    """Verify FasterWhisperProvider falls back to CPU if CUDA fails to initialize."""
    mock_cpu_model = MagicMock()
    mock_cpu_model.transcribe.return_value = ([], MagicMock(language="en", language_probability=1.0))

    def mock_init(model_size, device, compute_type=None):
        if device == "cuda":
            raise RuntimeError("CUDA out of memory")
        return mock_cpu_model

    mock_model_class.side_effect = mock_init

    provider = FasterWhisperProvider()
    
    with patch.object(FasterWhisperProvider, "is_available", return_value=True):
        with patch.object(FasterWhisperProvider, "_get_audio_duration", return_value=10.0):
            req = TranscriptionRequest(audio_path=str(mock_wav), device="cuda")
            # This should invoke CPU fallback, load CPU model, and transcribe successfully
            res = provider.transcribe(req)
            assert res is not None
            assert mock_model_class.call_count >= 2  # once with cuda, once with cpu


def test_whisper_chunking_overlap_merge(mock_wav: Path) -> None:
    """Verify that chunking overlap split merges duplicate cues at boundary midpoints correctly."""
    # We will test the _transcribe_chunked method of FasterWhisperProvider
    provider = FasterWhisperProvider()
    
    # Mock model
    mock_model = MagicMock()
    
    # 2 chunks will be transcribed.
    # Chunk 0 (starts at 0.0s): cues: 0.5->4.0, 25.0->29.5 (spans into overlap 28.0->30.0)
    # Chunk 1 (starts at 28.0s): cues: 28.5->32.0 (equivalent to 0.5->4.0 relative), 35.0->38.0
    # Overlap midpoint is at 29.0s.
    # Chunk 0 cue (25.0->29.5) starts at 25.0 < 29.0, so it's kept.
    # Chunk 1 cue (28.5->32.0) starts at 28.5 < 29.0, so it's discarded (duplicate of the overlap region).
    # Chunk 1 cue (35.0->38.0) starts at 35.0 >= 29.0, so it's kept.
    
    chunk_0_result = (
        [
            MagicMock(start=0.5, end=4.0, text="Hello"),
            MagicMock(start=25.0, end=29.5, text="Overlap boundary"),
        ],
        MagicMock(language="en", language_probability=1.0),
    )
    # Chunk 1 starts at 28.0.
    # Inside model.transcribe, the timestamps returned by whisper are local to the chunk (relative to 0.0).
    # Inside _transcribe_single, they are offset by 28.0.
    # So a segment from 0.5 to 4.0 becomes 28.5 to 32.0.
    chunk_1_result = (
        [
            MagicMock(start=0.5, end=4.0, text="Overlap boundary duplicate"),
            MagicMock(start=7.0, end=10.0, text="World"),
        ],
        MagicMock(language="en", language_probability=1.0),
    )

    call_count = 0
    def mock_transcribe(audio_path, **kwargs):
        nonlocal call_count
        res = chunk_0_result if call_count == 0 else chunk_1_result
        call_count += 1
        return res

    mock_model.transcribe.side_effect = mock_transcribe

    req = TranscriptionRequest(audio_path=str(mock_wav))
    
    # Mock get_audio_duration to return 45 seconds (so it fits in 2 chunks of 30s with 2s overlap: chunk 0: 0->30, chunk 1: 28->45)
    # Mock SubprocessRunner to do nothing
    with patch.object(FasterWhisperProvider, "_get_audio_duration", return_value=45.0):
        with patch("video_recap.infrastructure.media.subprocess_runner.SubprocessRunner.run") as mock_run:
            res = provider._transcribe_chunked(
                model=mock_model,
                audio_path=mock_wav,
                total_duration=45.0,
                request=req,
            )

            # We should get exactly 3 merged cues:
            # 1. Hello (0.5 -> 4.0)
            # 2. Overlap boundary (25.0 -> 29.5)
            # 3. World (35.0 -> 38.0) - Note: 28.0 + 7.0 = 35.0
            # "Overlap boundary duplicate" (28.5 -> 32.0) should be discarded because start 28.5 < midpoint 29.0
            assert len(res.cues) == 3
            assert res.cues[0].text == "Hello"
            assert res.cues[1].text == "Overlap boundary"
            assert res.cues[2].text == "World"
            assert res.cues[2].time_range.start == 35.0
            assert res.cues[2].time_range.end == 38.0
