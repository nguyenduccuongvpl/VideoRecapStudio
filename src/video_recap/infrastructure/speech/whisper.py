"""Infrastructure implementation of Speech-to-Text using faster-whisper and mock backends."""

import logging
import math
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, List, Optional
from video_recap.application.pipeline import CancellationToken
from video_recap.application.speech import (
    WordTimestamp,
    TranscriptionRequest,
    TranscriptionResult,
    TranscriptionProvider,
)
from video_recap.domain.models import TimeRange, TranscriptCue

logger = logging.getLogger("SpeechWhisper")


class MockTranscriptionProvider(TranscriptionProvider):
    """Mock Speech-to-Text provider for local testing without heavier dependencies."""

    def transcribe(
        self,
        request: TranscriptionRequest,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> TranscriptionResult:
        logger.info(f"Mock transcribing audio file: {request.audio_path}")

        # Simulate progress stages
        stages = [0.1, 0.5, 0.9, 1.0]
        for p in stages:
            if cancellation_token:
                cancellation_token.raise_if_cancelled()
            if progress_callback:
                progress_callback(p)

        # Generate fake cues based on language
        lang = request.language or "en"
        cues = []
        if lang.lower() == "vi":
            cues = [
                TranscriptCue(
                    text="Xin chào và chào mừng bạn đến với VideoRecapStudio.",
                    time_range=TimeRange(start=0.5, end=4.0),
                ),
                TranscriptCue(
                    text="Đây là chặng chuyển giọng nói thành văn bản giả lập.",
                    time_range=TimeRange(start=4.5, end=8.0),
                ),
                TranscriptCue(
                    text="Chúng tôi đang xác thực đường ống xử lý phụ đề.",
                    time_range=TimeRange(start=8.5, end=11.5),
                ),
            ]
        else:
            cues = [
                TranscriptCue(
                    text="Hello and welcome to VideoRecapStudio.",
                    time_range=TimeRange(start=0.5, end=4.0),
                ),
                TranscriptCue(
                    text="This is a mock speech to text transcription process.",
                    time_range=TimeRange(start=4.5, end=8.0),
                ),
                TranscriptCue(
                    text="We are verifying the captioning pipeline correctly.",
                    time_range=TimeRange(start=8.5, end=11.5),
                ),
            ]

        full_text = " ".join(c.text for c in cues)
        
        # Word timestamps
        words = []
        for cue in cues:
            cue_words = cue.text.split()
            word_count = len(cue_words)
            duration = cue.time_range.end - cue.time_range.start
            step = duration / max(1, word_count)
            for idx, w in enumerate(cue_words):
                w_clean = w.strip(".,!?\"'")
                words.append(
                    WordTimestamp(
                        word=w_clean,
                        start=cue.time_range.start + idx * step,
                        end=cue.time_range.start + (idx + 1) * step,
                        probability=0.95,
                    )
                )

        return TranscriptionResult(
            text=full_text,
            language=lang,
            language_probability=1.0,
            cues=cues,
            words=words,
        )

    def is_available(self) -> bool:
        return True


class FasterWhisperProvider(TranscriptionProvider):
    """Transcription provider implementing the faster-whisper local engine."""

    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        self.ffmpeg_path = ffmpeg_path

    def transcribe(
        self,
        request: TranscriptionRequest,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> TranscriptionResult:
        if not self.is_available():
            raise RuntimeError(
                "faster-whisper is not installed. Please install 'faster-whisper' package to run this provider."
            )

        # Dynamic imports
        from faster_whisper import WhisperModel

        model_size = request.preferred_model or "tiny"
        device = request.device or "cpu"
        compute_type = request.compute_type or "default"

        logger.info(f"Loading faster-whisper model '{model_size}' on '{device}'...")

        # Implement CUDA initialization with CPU Fallback
        model = None
        if device == "cuda":
            try:
                model = WhisperModel(model_size, device="cuda", compute_type=compute_type)
            except Exception as e:
                logger.warning(f"Failed to load Whisper on CUDA: {e}. Falling back to CPU...")
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
        else:
            model = WhisperModel(model_size, device="cpu", compute_type="int8")

        # Check audio file exists
        audio_p = Path(request.audio_path)
        if not audio_p.exists():
            raise FileNotFoundError(f"Audio file not found for transcription: {audio_p}")

        # Chunking parameters (e.g. for files longer than 5 mins, we chunk them with overlap)
        # However, faster-whisper natively handles long audios very well.
        # But to satisfy the requirement "chunk audio có overlap" and "merge timestamps", we will chunk if file duration is long.
        # Let's say we check duration first using a simple check or run chunking if requested or if file is > 120s.
        # To test the chunking algorithm itself, we can chunk if file is > 60s.
        # Let's write the chunking orchestrator
        audio_duration = self._get_audio_duration(audio_p)
        
        if audio_duration > 60.0:
            logger.info(f"Audio duration ({audio_duration:.2f}s) is long. Executing chunked transcription.")
            return self._transcribe_chunked(
                model,
                audio_p,
                audio_duration,
                request,
                cancellation_token,
                progress_callback,
            )

        # Non-chunked path
        return self._transcribe_single(
            model,
            audio_p,
            request,
            cancellation_token,
            progress_callback,
            offset=0.0,
            total_duration=audio_duration,
        )

    def is_available(self) -> bool:
        try:
            import faster_whisper
            return True
        except ImportError:
            return False

    def _get_audio_duration(self, audio_path: Path) -> float:
        """Utility to get duration of WAV audio using ffprobe or standard wave parsing."""
        import wave
        try:
            with wave.open(str(audio_path), "rb") as wav:
                frames = wav.getnframes()
                rate = wav.getframerate()
                if rate > 0:
                    return frames / float(rate)
        except Exception:
            pass
        return 0.0

    def _transcribe_single(
        self,
        model: Any,
        audio_path: Path,
        request: TranscriptionRequest,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
        offset: float = 0.0,
        total_duration: float = 0.0,
    ) -> TranscriptionResult:
        """Transcribe a single audio file and map to TranscriptionResult."""
        if cancellation_token:
            cancellation_token.raise_if_cancelled()

        # Run whisper transcribe
        segments, info = model.transcribe(
            str(audio_path),
            language=request.language,
            vad_filter=request.vad_filter,
            word_timestamps=True,
        )

        cues: List[TranscriptCue] = []
        words: List[WordTimestamp] = []
        text_parts: List[str] = []

        duration = total_duration or info.duration or 1.0

        for segment in segments:
            if cancellation_token:
                cancellation_token.raise_if_cancelled()

            # Map segment to TranscriptCue
            cues.append(
                TranscriptCue(
                    text=segment.text.strip(),
                    time_range=TimeRange(
                        start=segment.start + offset,
                        end=segment.end + offset,
                    ),
                )
            )
            text_parts.append(segment.text.strip())

            # Progress callback update
            if progress_callback and duration > 0:
                progress = min(1.0, (segment.end + offset) / duration)
                progress_callback(progress)

            # Word timestamps mapping
            if segment.words:
                for w in segment.words:
                    words.append(
                        WordTimestamp(
                            word=w.word.strip(),
                            start=w.start + offset,
                            end=w.end + offset,
                            probability=w.probability,
                        )
                    )

        if progress_callback:
            progress_callback(1.0)

        return TranscriptionResult(
            text=" ".join(text_parts),
            language=info.language,
            language_probability=info.language_probability,
            cues=cues,
            words=words,
        )

    def _transcribe_chunked(
        self,
        model: Any,
        audio_path: Path,
        total_duration: float,
        request: TranscriptionRequest,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> TranscriptionResult:
        """Slice audio into overlapping chunks, transcribe each, and merge timestamps."""
        chunk_len = 30.0
        overlap = 2.0
        step = chunk_len - overlap

        cues: List[TranscriptCue] = []
        words: List[WordTimestamp] = []
        text_parts: List[str] = []
        detected_lang = request.language or "en"
        detected_prob = 1.0

        num_chunks = int(math.ceil(total_duration / step))
        
        with tempfile.TemporaryDirectory() as temp_dir:
            for i in range(num_chunks):
                if cancellation_token:
                    cancellation_token.raise_if_cancelled()

                start_sec = i * step
                if start_sec >= total_duration:
                    break

                # Extract chunk using FFmpeg
                chunk_path = Path(temp_dir) / f"chunk_{i}.wav"
                from video_recap.domain.media import CommandSpec, FfmpegCommandBuilder
                from video_recap.infrastructure.media.subprocess_runner import SubprocessRunner
                
                builder = (
                    FfmpegCommandBuilder(self.ffmpeg_path)
                    .overwrite()
                    .input(audio_path, seek=start_sec)
                    .output(chunk_path, duration=chunk_len, audio_codec="copy")
                )
                runner = SubprocessRunner()
                runner.run(CommandSpec(args=builder.build()))

                # Transcribe chunk
                chunk_res = self._transcribe_single(
                    model,
                    chunk_path,
                    request,
                    cancellation_token,
                    progress_callback=None,  # Handled below
                    offset=start_sec,
                    total_duration=total_duration,
                )

                # Track language
                if i == 0:
                    detected_lang = chunk_res.language
                    detected_prob = chunk_res.language_probability

                # Merge boundary logic using the overlap split midpoint
                split_mid = start_sec + (overlap / 2.0) if i > 0 else 0.0

                for cue in chunk_res.cues:
                    # Keep cues that fall cleanly within this chunk's timeline domain
                    # Chunk i: only keep if start < split_mid of next chunk
                    # Chunk i+1: only keep if start >= split_mid
                    next_split = start_sec + step + (overlap / 2.0)
                    
                    if i > 0 and cue.time_range.start < split_mid:
                        continue
                    if i < num_chunks - 1 and cue.time_range.start >= next_split:
                        continue

                    cues.append(cue)
                    text_parts.append(cue.text)

                if chunk_res.words:
                    for w in chunk_res.words:
                        if i > 0 and w.start < split_mid:
                            continue
                        next_split = start_sec + step + (overlap / 2.0)
                        if i < num_chunks - 1 and w.start >= next_split:
                            continue
                        words.append(w)

                if progress_callback:
                    progress_callback(min(1.0, (start_sec + chunk_len) / total_duration))

        if progress_callback:
            progress_callback(1.0)

        return TranscriptionResult(
            text=" ".join(text_parts),
            language=detected_lang,
            language_probability=detected_prob,
            cues=cues,
            words=words,
        )
