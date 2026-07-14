"""Application service for probing media metadata using FFprobe."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from video_recap.application.media import ProcessRunner
from video_recap.domain import ProcessExecutionError
from video_recap.domain.models import MediaInfo, MediaStreamInfo, StageName
from video_recap.domain.media import FfprobeCommandBuilder
from video_recap.domain.errors import DomainError

logger = logging.getLogger("MediaProbeService")


class MediaProbeError(DomainError):
    """Raised when media probe validation or execution fails."""
    pass


class MediaProbeService:
    """Probes media files using ffprobe and maps results to domain MediaInfo models."""

    def __init__(self, runner: ProcessRunner, ffprobe_path: str = "ffprobe") -> None:
        """Initialize MediaProbeService.

        Args:
            runner: The process runner implementation.
            ffprobe_path: Path/command name for ffprobe.
        """
        self.runner = runner
        self.ffprobe_path = ffprobe_path

    def probe(self, file_path: Path | str) -> MediaInfo:
        """Probe a media file using ffprobe and construct a validated MediaInfo instance.

        Args:
            file_path: The file path to probe.

        Returns:
            A MediaInfo object with parsed metadata.

        Raises:
            MediaProbeError: If validation fails or ffprobe fails.
        """
        path_obj = Path(file_path)
        if not path_obj.exists():
            raise MediaProbeError(f"Media file not found: {path_obj}")

        # Build ffprobe command
        builder = (
            FfprobeCommandBuilder(self.ffprobe_path)
            .input(path_obj)
            .show_format()
            .show_streams()
        )

        from video_recap.domain.media import CommandSpec
        spec = CommandSpec(args=builder.build())

        try:
            result = self.runner.run(spec)
        except ProcessExecutionError as e:
            raise MediaProbeError(f"ffprobe execution failed: {e}") from e

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise MediaProbeError(f"Failed to parse ffprobe JSON output: {e}") from e

        # Extract format and streams info
        format_data = data.get("format", {})
        streams_data = data.get("streams", [])

        # Parse streams
        streams: List[MediaStreamInfo] = []
        has_video = False
        has_audio = False
        vfr_detected = False
        main_video_width = 0
        main_video_height = 0
        main_video_fps = 0.0

        for i, s in enumerate(streams_data):
            stream_type = s.get("codec_type", "unknown")
            codec = s.get("codec_name", "unknown")
            
            # Rotation normalization
            rotation = self._extract_rotation(s)

            # Frame rate parsing
            fps = self._parse_frame_rate(s.get("r_frame_rate", ""))
            avg_fps = self._parse_frame_rate(s.get("avg_frame_rate", ""))

            # VFR detection heuristic: avg_frame_rate != r_frame_rate
            if stream_type == "video" and fps and avg_fps and abs(fps - avg_fps) > 0.05:
                vfr_detected = True

            # Disposition
            disposition = {k: int(v) for k, v in s.get("disposition", {}).items() if isinstance(v, (int, str)) and str(v).isdigit()}

            # Duration & Bit rate parsing
            stream_duration = self._float_or_none(s.get("duration"))
            stream_bit_rate = self._int_or_none(s.get("bit_rate"))
            start_time = self._float_or_none(s.get("start_time"))

            # Construct stream info
            stream_info = MediaStreamInfo(
                index=int(s.get("index", i)),
                stream_type=stream_type,
                codec=codec,
                codec_long_name=s.get("codec_long_name"),
                profile=s.get("profile"),
                width=self._int_or_none(s.get("width")),
                height=self._int_or_none(s.get("height")),
                display_aspect_ratio=s.get("display_aspect_ratio"),
                pix_fmt=s.get("pix_fmt"),
                color_space=s.get("color_space"),
                color_transfer=s.get("color_transfer"),
                color_primaries=s.get("color_primaries"),
                fps=fps,
                avg_frame_rate=s.get("avg_frame_rate"),
                r_frame_rate=s.get("r_frame_rate"),
                rotation=rotation,
                sample_rate=self._int_or_none(s.get("sample_rate")),
                channels=self._int_or_none(s.get("channels")),
                channel_layout=s.get("channel_layout"),
                language=s.get("tags", {}).get("language"),
                disposition=disposition,
                duration=stream_duration,
                bit_rate=stream_bit_rate,
                start_time=start_time,
                tags={str(k): str(v) for k, v in s.get("tags", {}).items()},
            )
            streams.append(stream_info)

            # Record stats of main video stream
            if stream_type == "video" and not has_video:
                has_video = True
                main_video_width = stream_info.width or 0
                main_video_height = stream_info.height or 0
                main_video_fps = fps or 25.0

            if stream_type == "audio":
                has_audio = True

        # Validation: check for video stream
        if not has_video:
            raise MediaProbeError("Validation failed: media file has no video stream.")

        # Duration validation
        duration = self._float_or_none(format_data.get("duration"))
        if duration is None or duration <= 0:
            raise MediaProbeError(f"Validation failed: media duration '{duration}' is invalid.")

        # Size validation
        size_bytes = self._int_or_none(format_data.get("size")) or 0

        # Construct and validate final MediaInfo
        resolution = f"{main_video_width}x{main_video_height}"
        
        # Warnings
        if not has_audio:
            logger.warning(f"Media file '{path_obj.name}' contains no audio track.")
        if vfr_detected:
            logger.warning(f"Media file '{path_obj.name}' uses Variable Frame Rate (VFR) which may cause sync issues.")

        return MediaInfo(
            schema_version="1.0.0",
            producer_stage=StageName.INGESTING,  # Probing happens as part of INGESTING
            input_hashes={},
            format_name=format_data.get("format_name", "unknown"),
            duration=duration,
            size_bytes=size_bytes,
            bit_rate=self._int_or_none(format_data.get("bit_rate")),
            streams=streams,
            tags={str(k): str(v) for k, v in format_data.get("tags", {}).items()},
            resolution=resolution,
            fps=main_video_fps,
            has_video=has_video,
            has_audio=has_audio,
            vfr_detected=vfr_detected,
        )

    def _extract_rotation(self, stream: Dict[str, Any]) -> Optional[float]:
        """Extract and normalize rotation information from side data or tags."""
        # 1. Check side data list
        side_data_list = stream.get("side_data_list", [])
        for side in side_data_list:
            if side.get("side_data_type") == "Display Matrix":
                rotation = side.get("rotation")
                if rotation is not None:
                    try:
                        return float(rotation) % 360.0
                    except (ValueError, TypeError):
                        pass

        # 2. Check tags (e.g. rotate)
        tags = stream.get("tags", {})
        rotate_tag = tags.get("rotate") or tags.get("rotation")
        if rotate_tag is not None:
            try:
                return float(rotate_tag) % 360.0
            except (ValueError, TypeError):
                pass

        return None

    def _parse_frame_rate(self, rate_str: str) -> Optional[float]:
        """Parse frame rate division strings (e.g., '30000/1001', '25/1')."""
        if not rate_str:
            return None
        if "/" in rate_str:
            try:
                num, den = rate_str.split("/")
                d_val = float(den)
                if d_val != 0:
                    return float(num) / d_val
            except (ValueError, ZeroDivisionError):
                pass
        else:
            try:
                return float(rate_str)
            except ValueError:
                pass
        return None

    def _float_or_none(self, val: Any) -> Optional[float]:
        if val is None:
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    def _int_or_none(self, val: Any) -> Optional[int]:
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None
