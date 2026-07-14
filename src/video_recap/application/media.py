"""Application protocols and ports for subprocess execution and media processing."""

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol
from video_recap.application.pipeline import CancellationToken
from video_recap.domain.media import CommandResult, CommandSpec


class ProcessRunner(Protocol):
    """Protocol for executing subprocess commands securely with monitoring and progress tracking."""

    def run(
        self,
        spec: CommandSpec,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> CommandResult:
        """Run a process command synchronously and return execution details.

        Args:
            spec: Command execution parameters.
            cancellation_token: Token to signal cancellation cooperative halt.
            progress_callback: Callback triggered with execution progress (0.0 to 1.0).

        Returns:
            CommandResult model with stdout, stderr and exit code.

        Raises:
            ProcessExecutionError: If command fails, runs into timeout, or cancels.
        """
        ...


class AudioExtractor(Protocol):
    """Extracts transcription-ready audio track from a media source file."""

    def extract_audio(
        self,
        source_path: Path | str,
        dest_path: Path | str,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> None:
        """Extract audio to a 16kHz mono WAV file.

        Args:
            source_path: Path to the source media file.
            dest_path: Path where the output WAV file should be saved.
            cancellation_token: Optional cancellation token.
        """
        ...


class ProxyGenerator(Protocol):
    """Generates downscaled analysis proxy videos with stable CFR timestamps."""

    def generate_proxy(
        self,
        source_path: Path | str,
        dest_path: Path | str,
        max_width: int,
        max_height: int,
        is_vfr: bool,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> None:
        """Generate a proxy video.

        Args:
            source_path: Path to the source media file.
            dest_path: Output path for the proxy video.
            max_width: Maximum width boundary.
            max_height: Maximum height boundary.
            is_vfr: True if the source is Variable Frame Rate.
            cancellation_token: Optional cancellation token.
            progress_callback: Optional progress feedback callback.
        """
        ...


class ThumbnailGenerator(Protocol):
    """Generates keyframe thumbnails and contact sheet imagery from media inputs."""

    def generate_thumbnails(
        self,
        source_path: Path | str,
        dest_dir: Path | str,
        timestamps: List[float],
        cancellation_token: Optional[CancellationToken] = None,
    ) -> List[Path]:
        """Extract thumbnail images at the requested timestamps.

        Args:
            source_path: Path to the source media file.
            dest_dir: Destination directory to store extracted thumbnails.
            timestamps: List of timestamps in seconds to capture thumbnails.
            cancellation_token: Optional cancellation token.

        Returns:
            List of Paths pointing to the successfully created thumbnail images.
        """
        ...

    def generate_contact_sheet(
        self,
        thumbnail_paths: List[Path | str],
        dest_path: Path | str,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> None:
        """Compile a list of thumbnails into a single contact sheet grid image.

        Args:
            thumbnail_paths: List of thumbnail image paths.
            dest_path: Path to write the output contact sheet image.
            cancellation_token: Optional cancellation token.
        """
        ...


class MediaNormalizer(Protocol):
    """Orchestrates disk checks, media probing, audio/proxy/thumbnail generation and caching."""

    def normalize(
        self,
        source_path: Path | str,
        project_id: str,
        workspace_dir: Path | str,
        settings: Any,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> Dict[str, Any]:
        """Normalize the input media into standardized assets.

        Args:
            source_path: Path to the source media file.
            project_id: Unique project identifier.
            workspace_dir: Project workspace directory path.
            settings: Media normalizer config settings.
            cancellation_token: Optional cancellation token.
            progress_callback: Optional progress feedback callback.

        Returns:
            Dict containing information about generated files (paths, hashes, sizes).
        """
        ...
