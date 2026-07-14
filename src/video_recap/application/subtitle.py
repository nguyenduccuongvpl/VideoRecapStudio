"""Application protocols and ports for subtitle discovery, parsing, and normalization."""

from pathlib import Path
from typing import List, Optional, Protocol
from pydantic import BaseModel, Field
from video_recap.domain.models import MediaInfo, TranscriptCue


class SubtitleCandidate(BaseModel):
    """Metadata schema representing a discovered subtitle candidate track."""

    source_type: str = Field(..., description="'sidecar' or 'embedded'")
    path: Optional[str] = Field(None, description="Absolute file path for sidecar subtitle files.")
    stream_index: Optional[int] = Field(None, description="Stream index for embedded subtitles.")
    language: Optional[str] = Field(None, description="ISO language identifier if available.")
    codec: Optional[str] = Field(None, description="Subtitle codec name (e.g. mov_text, srt, subrip).")
    is_default: bool = Field(False, description="True if the stream has the default disposition set.")


class SubtitleDiscoveryService(Protocol):
    """Protocol for scanning and discovering sidecar and embedded subtitle tracks."""

    def discover_subtitles(
        self,
        source_video_path: Path | str,
        media_info: MediaInfo,
        user_selected_path: Optional[Path | str] = None,
    ) -> List[SubtitleCandidate]:
        """Scan sidecar folders and inspect embedded video streams for subtitle tracks.

        Args:
            source_video_path: Path to the main source video.
            media_info: Probed MediaInfo metadata of the source video.
            user_selected_path: Optional user-specified subtitle file.

        Returns:
            A list of discovered SubtitleCandidate tracks.
        """
        ...


class SubtitleParser(Protocol):
    """Parses subtitle track files (SRT, VTT, ASS/SSA) into standardized TranscriptCues."""

    def parse(self, filepath: Path | str, encoding: Optional[str] = None) -> List[TranscriptCue]:
        """Parse a subtitle file.

        Args:
            filepath: Path to the subtitle file on disk.
            encoding: Optional encoding override, otherwise auto-detected.

        Returns:
            List of parsed TranscriptCue items.
        """
        ...


class SubtitleNormalizer(Protocol):
    """Cleans up transcription cues, strips tags, solves overlaps and bilingual duplicates."""

    def normalize_cues(self, cues: List[TranscriptCue]) -> List[TranscriptCue]:
        """Normalize raw subtitle cues: strip HTML/ASS tags, fix overlaps, deduplicate tracks.

        Args:
            cues: List of raw cues parsed from subtitles.

        Returns:
            Cleaned and normalized TranscriptCue list.
        """
        ...


class SubtitleSelectionPolicy(Protocol):
    """Applies ranking rules to select the best subtitle candidate."""

    def select_best(
        self,
        candidates: List[SubtitleCandidate],
        preferred_language: Optional[str] = None,
    ) -> Optional[SubtitleCandidate]:
        """Rank and select the optimal subtitle candidate based on priority rules.

        Args:
            candidates: Discovered subtitle candidates.
            preferred_language: Language code preferred for the project.

        Returns:
            The selected SubtitleCandidate, or None if no subtitles are available.
        """
        ...
