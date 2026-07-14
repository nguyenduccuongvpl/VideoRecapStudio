"""Infrastructure implementation of subtitle parsing, extraction, and discovery."""

import logging
import re
from pathlib import Path
from typing import Any, List, Optional, Tuple
from video_recap.application.media import ProcessRunner
from video_recap.application.pipeline import CancellationToken
from video_recap.application.subtitle import (
    SubtitleCandidate,
    SubtitleDiscoveryService,
    SubtitleParser,
    SubtitleNormalizer,
    SubtitleSelectionPolicy,
)
from video_recap.domain import ProcessExecutionError
from video_recap.domain.media import CommandSpec, FfmpegCommandBuilder
from video_recap.domain.models import MediaInfo, TimeRange, TranscriptCue

logger = logging.getLogger("SubtitlePipeline")


class FfmpegSubtitleExtractor:
    """Helper service to extract embedded subtitle streams to disk using FFmpeg."""

    def __init__(self, runner: ProcessRunner, ffmpeg_path: str = "ffmpeg") -> None:
        self.runner = runner
        self.ffmpeg_path = ffmpeg_path

    def extract(
        self,
        video_path: Path | str,
        stream_index: int,
        dest_path: Path | str,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> None:
        """Run FFmpeg to extract subtitle stream at stream_index to dest_path."""
        builder = (
            FfmpegCommandBuilder(self.ffmpeg_path)
            .overwrite()
            .input(video_path)
            .output(
                dest_path,
                extra_args=["-map", f"0:{stream_index}", "-c:s", "copy"],
            )
        )
        # Fallback: if 'copy' codec fails (e.g. conversion needed), let FFmpeg auto-transcode
        spec = CommandSpec(args=builder.build())
        try:
            self.runner.run(spec, cancellation_token=cancellation_token)
        except ProcessExecutionError as e:
            logger.warning(f"Direct stream copy of subtitle failed: {e}. Retrying with transcoding...")
            fallback_builder = (
                FfmpegCommandBuilder(self.ffmpeg_path)
                .overwrite()
                .input(video_path)
                .output(
                    dest_path,
                    extra_args=["-map", f"0:{stream_index}"],
                )
            )
            fallback_spec = CommandSpec(args=fallback_builder.build())
            self.runner.run(fallback_spec, cancellation_token=cancellation_token)


class SubtitleDiscoveryServiceImpl(SubtitleDiscoveryService):
    """Scans for sidecar subtitle files and parses embedded video streams."""

    def discover_subtitles(
        self,
        source_video_path: Path | str,
        media_info: MediaInfo,
        user_selected_path: Optional[Path | str] = None,
    ) -> List[SubtitleCandidate]:
        candidates: List[SubtitleCandidate] = []
        video_p = Path(source_video_path)

        # 1. User selected
        if user_selected_path:
            user_p = Path(user_selected_path)
            if user_p.exists():
                candidates.append(
                    SubtitleCandidate(
                        source_type="user_selected",
                        path=str(user_p.absolute()),
                        codec=user_p.suffix.strip(".").lower(),
                    )
                )

        # 2. Sidecar subtitles (same basename next to video)
        video_dir = video_p.parent
        video_stem = video_p.stem
        # Scan for matching stems, e.g. source.srt, source.en.srt
        if video_dir.exists():
            for p in video_dir.iterdir():
                if p.is_file() and p.stem.startswith(video_stem):
                    ext = p.suffix.strip(".").lower()
                    if ext in ("srt", "vtt", "ass", "ssa"):
                        # Extract language suffix if present, e.g. "en" from "video.en.srt"
                        lang = None
                        suffix = p.stem[len(video_stem) :].strip(".")
                        if suffix and len(suffix) <= 3:
                            lang = suffix

                        # Avoid duplication of user_selected
                        if user_selected_path and Path(user_selected_path).resolve() == p.resolve():
                            continue

                        candidates.append(
                            SubtitleCandidate(
                                source_type="sidecar",
                                path=str(p.absolute()),
                                language=lang,
                                codec=ext,
                            )
                        )

        # 3. Embedded subtitle streams
        for stream in media_info.streams:
            if stream.stream_type == "subtitle":
                is_def = stream.disposition.get("default", 0) == 1 if stream.disposition else False
                candidates.append(
                    SubtitleCandidate(
                        source_type="embedded",
                        stream_index=stream.index,
                        language=stream.language,
                        codec=stream.codec,
                        is_default=is_def,
                    )
                )

        return candidates


class SubtitleSelectionPolicyImpl(SubtitleSelectionPolicy):
    """Ranks and selects the best subtitle candidate."""

    def select_best(
        self,
        candidates: List[SubtitleCandidate],
        preferred_language: Optional[str] = None,
    ) -> Optional[SubtitleCandidate]:
        if not candidates:
            return None

        # 1. Check user selected
        for c in candidates:
            if c.source_type == "user_selected":
                return c

        # 2. Rank sidecar subtitles
        sidecars = [c for c in candidates if c.source_type == "sidecar"]
        if sidecars:
            if preferred_language:
                # Prefer sidecar matching preferred language (e.g. source.en.srt)
                for s in sidecars:
                    if s.language and s.language.lower() == preferred_language.lower():
                        return s
            # Default to first sidecar
            return sidecars[0]

        # 3. Rank embedded default
        embedded = [c for c in candidates if c.source_type == "embedded"]
        if embedded:
            # Check default embedded matching preferred language
            if preferred_language:
                for e in embedded:
                    if e.is_default and e.language and e.language.lower() == preferred_language.lower():
                        return e
                # Check any embedded matching preferred language
                for e in embedded:
                    if e.language and e.language.lower() == preferred_language.lower():
                        return e
            # Default to default embedded stream
            for e in embedded:
                if e.is_default:
                    return e
            # Default to first embedded stream
            return embedded[0]

        return None


class SubtitleParserImpl(SubtitleParser):
    """Parses SRT, VTT, and ASS subtitle formats with character encoding auto-detection."""

    def parse(self, filepath: Path | str, encoding: Optional[str] = None) -> List[TranscriptCue]:
        path = Path(filepath)
        if not path.exists():
            raise FileNotFoundError(f"Subtitle file not found: {path}")

        # Auto-detect encoding
        encodings_to_try = [encoding] if encoding else ["utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"]
        content = ""
        success_encoding = None

        for enc in encodings_to_try:
            try:
                content = path.read_text(encoding=enc)
                success_encoding = enc
                break
            except (UnicodeDecodeError, TypeError):
                continue

        if success_encoding is None:
            raise UnicodeDecodeError("Failed to decode subtitle file with standard encodings.")

        # Determine parser from format
        suffix = path.suffix.lower().strip(".")
        if suffix == "vtt":
            return self._parse_vtt(content)
        elif suffix in ("ass", "ssa"):
            return self._parse_ass(content)
        else:
            return self._parse_srt(content)

    def _parse_srt(self, content: str) -> List[TranscriptCue]:
        cues: List[TranscriptCue] = []
        # Split into blocks by blank lines
        blocks = re.split(r"\n\s*\n", content.strip().replace("\r\n", "\n"))

        time_pattern = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})")

        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 2:
                continue

            # Find line with timestamp arrow
            time_line_idx = -1
            time_match = None
            for idx, line in enumerate(lines):
                m = time_pattern.search(line)
                if m:
                    time_line_idx = idx
                    time_match = m
                    break

            if time_line_idx == -1 or not time_match:
                continue

            # Parse start and end times
            start_sec = self._parse_time_groups(time_match.groups()[:4])
            end_sec = self._parse_time_groups(time_match.groups()[4:])

            # Text is everything after the timeline
            text_lines = lines[time_line_idx + 1 :]
            text = " ".join(t.strip() for t in text_lines if t.strip())

            if text and start_sec < end_sec:
                cues.append(
                    TranscriptCue(
                        text=text,
                        time_range=TimeRange(start=start_sec, end=end_sec),
                    )
                )

        return cues

    def _parse_vtt(self, content: str) -> List[TranscriptCue]:
        cues: List[TranscriptCue] = []
        # Strip WEBVTT header and metadata
        lines = content.replace("\r\n", "\n").split("\n")
        
        # Heuristic to find first cue
        time_pattern = re.compile(
            r"(?:(\d{2}):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->\s*(?:(\d{2}):)?(\d{2}):(\d{2})[.,](\d{3})"
        )

        current_text: List[str] = []
        current_times: Optional[Tuple[float, float]] = None

        for line in lines:
            line = line.strip()
            if not line or line.lower().startswith("webvtt") or line.lower().startswith("note"):
                if current_times and current_text:
                    start_sec, end_sec = current_times
                    text = " ".join(current_text)
                    if text and start_sec < end_sec:
                        cues.append(TranscriptCue(text=text, time_range=TimeRange(start=start_sec, end=end_sec)))
                    current_text = []
                    current_times = None
                continue

            m = time_pattern.search(line)
            if m:
                # Flush previous cue
                if current_times and current_text:
                    start_sec, end_sec = current_times
                    text = " ".join(current_text)
                    if text and start_sec < end_sec:
                        cues.append(TranscriptCue(text=text, time_range=TimeRange(start=start_sec, end=end_sec)))
                    current_text = []
                
                # Parse groups
                g = m.groups()
                # Start
                h1 = int(g[0]) if g[0] else 0
                m1, s1, ms1 = int(g[1]), int(g[2]), int(g[3])
                start_sec = h1 * 3600 + m1 * 60 + s1 + (ms1 / 1000.0)
                # End
                h2 = int(g[4]) if g[4] else 0
                m2, s2, ms2 = int(g[5]), int(g[6]), int(g[7])
                end_sec = h2 * 3600 + m2 * 60 + s2 + (ms2 / 1000.0)

                current_times = (start_sec, end_sec)
            else:
                if current_times:
                    # Ignore VTT cue identifiers (numbers or labels before timeline) if we don't have timeline yet
                    current_text.append(line)

        # Flush final cue
        if current_times and current_text:
            start_sec, end_sec = current_times
            text = " ".join(current_text)
            if text and start_sec < end_sec:
                cues.append(TranscriptCue(text=text, time_range=TimeRange(start=start_sec, end=end_sec)))

        return cues

    def _parse_ass(self, content: str) -> List[TranscriptCue]:
        cues: List[TranscriptCue] = []
        lines = content.replace("\r\n", "\n").split("\n")
        
        # Dialogue line format: Dialogue: Marked=0,0:02:40.65,0:02:41.79,Default,,0,0,0,,Text
        # We need to find format fields if possible, but standard layout is:
        # dialogue_re matches Dialogue: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
        dialogue_re = re.compile(r"^Dialogue:\s*[^,]+,([^,]+),([^,]+),[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,?(.*)$")

        for line in lines:
            line = line.strip()
            m = dialogue_re.match(line)
            if m:
                start_str, end_str, text = m.groups()
                start_sec = self._parse_ass_time(start_str)
                end_sec = self._parse_ass_time(end_str)
                if text.strip() and start_sec < end_sec:
                    cues.append(
                        TranscriptCue(
                            text=text.strip(),
                            time_range=TimeRange(start=start_sec, end=end_sec),
                        )
                    )
        return cues

    def _parse_time_groups(self, groups: Tuple[str, ...]) -> float:
        h, m, s, ms = map(int, groups)
        return h * 3600 + m * 60 + s + (ms / 1000.0)

    def _parse_ass_time(self, time_str: str) -> float:
        # Format: h:mm:ss.cs (centiseconds)
        try:
            parts = time_str.split(":")
            h = int(parts[0])
            m = int(parts[1])
            s_parts = parts[2].split(".")
            s = int(s_parts[0])
            cs = int(s_parts[1]) if len(s_parts) > 1 else 0
            return h * 3600 + m * 60 + s + (cs / 100.0)
        except Exception:
            return 0.0


class SubtitleNormalizerImpl(SubtitleNormalizer):
    """Normalizes formatting, solves overlaps, and filters bilingual duplicates."""

    def normalize_cues(self, cues: List[TranscriptCue]) -> List[TranscriptCue]:
        if not cues:
            return []

        # 1. Clean formatting tags
        cleaned_cues: List[TranscriptCue] = []
        for cue in cues:
            text = self._strip_formatting(cue.text)
            if text:
                cleaned_cues.append(
                    TranscriptCue(
                        text=text,
                        time_range=TimeRange(start=cue.time_range.start, end=cue.time_range.end),
                    )
                )

        if not cleaned_cues:
            return []

        # 2. Sort chronologically by start time
        cleaned_cues.sort(key=lambda c: (c.time_range.start, c.time_range.end))

        # 3. Resolve overlaps and bilingual duplicates
        normalized: List[TranscriptCue] = []
        
        for next_cue in cleaned_cues:
            if not normalized:
                normalized.append(next_cue)
                continue

            prev_cue = normalized[-1]

            # Duplicate bilingual track check
            # Heuristic: if timestamps match exactly or have >95% overlap, and texts match or have duplicate pattern
            time_overlap = min(prev_cue.time_range.end, next_cue.time_range.end) - max(
                prev_cue.time_range.start, next_cue.time_range.start
            )
            duration = max(0.01, prev_cue.time_range.end - prev_cue.time_range.start)
            
            # If timestamps match exactly or are highly overlapping
            if abs(prev_cue.time_range.start - next_cue.time_range.start) < 0.05 and abs(prev_cue.time_range.end - next_cue.time_range.end) < 0.05:
                # Same timeline. If they are bilingual, combine or keep one.
                # Let's combine if text is different, or skip if duplicate
                if prev_cue.text.lower() == next_cue.text.lower():
                    # Exact duplicate, skip next
                    continue
                else:
                    # Bilingual pair, keep both or merge? Let's merge them with a separator
                    prev_cue.text = f"{prev_cue.text} | {next_cue.text}"
                    continue

            # Standard overlap resolution: clip prev_cue.end to next_cue.start if overlapping
            if prev_cue.time_range.end > next_cue.time_range.start:
                # If they overlap chronologically
                if next_cue.time_range.start > prev_cue.time_range.start:
                    prev_cue.time_range.end = next_cue.time_range.start
                else:
                    # Out of order or bad timestamps, just enforce minimum duration
                    prev_cue.time_range.end = prev_cue.time_range.start + 0.01

            # Validate range integrity
            if prev_cue.time_range.end > prev_cue.time_range.start:
                normalized.append(next_cue)
            else:
                # Replace last one if it got squashed
                normalized[-1] = next_cue

        # Ensure final cue is valid
        if normalized and normalized[-1].time_range.end <= normalized[-1].time_range.start:
            normalized.pop()

        return normalized

    def _strip_formatting(self, text: str) -> str:
        # Strip HTML-like tags, e.g. <i>, <b>, </i>, </font>
        text = re.sub(r"<[^>]*>", "", text)
        # Strip ASS style format overrides, e.g. {\pos(400,570)}, {\i1}
        text = re.sub(r"\{[^}]*\}", "", text)
        # Clean double spaces/newlines
        text = re.sub(r"\s+", " ", text)
        return text.strip()
