"""Subprocess command specifications, results, and builders domain models."""

import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field


class CommandSpec(BaseModel):
    """Configuration schema for executing a subprocess command."""

    args: List[str] = Field(..., description="The command arguments (first item is the executable).")
    env: Optional[Dict[str, str]] = Field(
        None, description="Optional dictionary of environment variables."
    )
    cwd: Optional[str] = Field(None, description="Optional working directory to run in.")
    timeout_seconds: Optional[float] = Field(
        None, description="Timeout limit in seconds before terminating the subprocess."
    )
    max_output_size_bytes: int = Field(
        10 * 1024 * 1024,
        description="Maximum size of stdout/stderr buffers in bytes to prevent memory issues.",
    )


class CommandResult(BaseModel):
    """The result output of a subprocess execution."""

    args: List[str] = Field(..., description="The executed command arguments.")
    return_code: int = Field(..., description="The return code of the subprocess execution.")
    stdout: str = Field(..., description="Captured standard output content.")
    stderr: str = Field(..., description="Captured standard error content.")


class FfmpegProgressParser:
    """Parses progress from FFmpeg execution outputs (both -progress pipe lines and stderr)."""

    def __init__(self, duration_seconds: Optional[float] = None) -> None:
        """Initialize parser.

        Args:
            duration_seconds: The total video/audio duration to calculate float progress.
        """
        self.duration_seconds = duration_seconds
        # Keep track of parsed values
        self._last_progress = 0.0

        # Pattern for stderr time update: time=00:00:05.12
        self._time_re = re.compile(r"time=(\d+):(\d+):(\d+)\.(\d+)")

    def parse_line(self, line: str) -> Optional[float]:
        """Parse a line of FFmpeg stdout/stderr and return progress (0.0 to 1.0).

        Args:
            line: Single output line string.

        Returns:
            Float progress or None if progress could not be calculated.
        """
        if not self.duration_seconds or self.duration_seconds <= 0:
            return None

        # 1. Parse pipe format: out_time_us=5000000
        if "out_time_us=" in line:
            try:
                parts = line.strip().split("=")
                if len(parts) == 2:
                    us = int(parts[1])
                    secs = us / 1_000_000.0
                    progress = min(1.0, max(0.0, secs / self.duration_seconds))
                    self._last_progress = progress
                    return progress
            except Exception:
                pass

        # 2. Parse fallback stderr format: time=00:00:05.12
        match = self._time_re.search(line)
        if match:
            try:
                h, m, s, ms = map(int, match.groups())
                # Centiseconds vs Milliseconds parsing
                sec_val = h * 3600 + m * 60 + s + (ms / 100.0)
                progress = min(1.0, max(0.0, sec_val / self.duration_seconds))
                self._last_progress = progress
                return progress
            except Exception:
                pass

        return None


class FfmpegCommandBuilder:
    """Fluent API builder for compiling FFmpeg command arguments."""

    def __init__(self, ffmpeg_path: str = "ffmpeg") -> None:
        self.ffmpeg_path = ffmpeg_path
        self._inputs: List[Tuple[Union[str, Path], Optional[float]]] = []
        self._outputs: List[Dict[str, Optional[Union[str, Path, float]]]] = []
        self._global_args: List[str] = []
        self._overwrite = False

    def input(self, path: Union[str, Path], seek: Optional[float] = None) -> "FfmpegCommandBuilder":
        """Add input file, optionally seeking to a start position."""
        self._inputs.append((path, seek))
        return self

    def output(
        self,
        path: Union[str, Path],
        video_codec: Optional[str] = None,
        audio_codec: Optional[str] = None,
        video_filter: Optional[str] = None,
        audio_filter: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> "FfmpegCommandBuilder":
        """Add output destination with encoding settings."""
        self._outputs.append(
            {
                "path": path,
                "video_codec": video_codec,
                "audio_codec": audio_codec,
                "video_filter": video_filter,
                "audio_filter": audio_filter,
                "duration": duration,
            }
        )
        return self

    def overwrite(self) -> "FfmpegCommandBuilder":
        """Add -y argument to overwrite existing files."""
        self._overwrite = True
        return self

    def global_arg(self, arg: str) -> "FfmpegCommandBuilder":
        """Add an ad-hoc global argument."""
        self._global_args.append(arg)
        return self

    def build(self) -> List[str]:
        """Compile and return the complete arguments list."""
        args = [self.ffmpeg_path]
        if self._overwrite:
            args.append("-y")

        args.extend(self._global_args)

        # Append Inputs
        for path, seek in self._inputs:
            if seek is not None:
                args.extend(["-ss", f"{seek:.6f}"])
            args.extend(["-i", str(path)])

        # Append Outputs
        for out in self._outputs:
            if out["video_codec"]:
                args.extend(["-c:v", str(out["video_codec"])])
            if out["audio_codec"]:
                args.extend(["-c:a", str(out["audio_codec"])])
            if out["video_filter"]:
                args.extend(["-vf", str(out["video_filter"])])
            if out["audio_filter"]:
                args.extend(["-af", str(out["audio_filter"])])
            if out["duration"] is not None:
                args.extend(["-t", f"{out['duration']:.6f}"])

            args.append(str(out["path"]))

        return args


class FfprobeCommandBuilder:
    """Fluent API builder for compiling FFprobe command arguments."""

    def __init__(self, ffprobe_path: str = "ffprobe") -> None:
        self.ffprobe_path = ffprobe_path
        self._input_path: Optional[Union[str, Path]] = None
        self._show_format = False
        self._show_streams = False

    def input(self, path: Union[str, Path]) -> "FfprobeCommandBuilder":
        """Set the target input media file."""
        self._input_path = path
        return self

    def show_format(self) -> "FfprobeCommandBuilder":
        """Add format metadata extraction."""
        self._show_format = True
        return self

    def show_streams(self) -> "FfprobeCommandBuilder":
        """Add streams metadata extraction."""
        self._show_streams = True
        return self

    def build(self) -> List[str]:
        """Compile and return the complete ffprobe command list."""
        args = [self.ffprobe_path]
        # Always read in quiet, JSON formatted mode
        args.extend(["-print_format", "json", "-v", "quiet"])

        if self._show_format:
            args.append("-show_format")
        if self._show_streams:
            args.append("-show_streams")

        if self._input_path:
            args.append(str(self._input_path))

        return args
