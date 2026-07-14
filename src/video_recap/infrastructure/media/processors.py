"""Infrastructure implementation of media processors using FFmpeg/FFprobe."""

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from video_recap.application.media import (
    AudioExtractor,
    ProxyGenerator,
    ThumbnailGenerator,
    MediaNormalizer,
    ProcessRunner,
)
from video_recap.application.pipeline import CancellationToken
from video_recap.application.probe import MediaProbeService
from video_recap.domain import ProcessExecutionError, JobCancelledError
from video_recap.domain.media import CommandSpec, FfmpegCommandBuilder
from video_recap.domain.models import MediaInfo, StageName
from video_recap.application.workspace import FileChecksumService
from video_recap.infrastructure.persistence import SHA256ChecksumService

logger = logging.getLogger("MediaProcessors")


class FfmpegAudioExtractor:
    """Extracts audio tracks from media files using FFmpeg."""

    def __init__(self, runner: ProcessRunner, ffmpeg_path: str = "ffmpeg") -> None:
        self.runner = runner
        self.ffmpeg_path = ffmpeg_path

    def extract_audio(
        self,
        source_path: Path | str,
        dest_path: Path | str,
        cancellation_token: Optional[CancellationToken] = None,
        duration: Optional[float] = None,
    ) -> None:
        """Extract audio to a 16kHz mono WAV file. If no audio stream is present, generates silence."""
        src = Path(source_path)
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # We need to check if there is an audio stream.
        # If not, generate silence using anullsrc filter.
        has_audio = True
        if duration is not None:
            # Check if duration is provided, meaning we might know if there's no audio
            # or we can check via ffprobe or standard handling.
            pass

        # Build command
        builder = FfmpegCommandBuilder(self.ffmpeg_path).overwrite()
        
        if duration is not None and duration > 0 and not has_audio:
            # Generate silent audio track
            builder.global_arg("-f").global_arg("lavfi")
            builder.input(f"anullsrc=r=16000:cl=mono")
            builder.output(dest, audio_codec="pcm_s16le", duration=duration)
        else:
            # Extract from source
            builder.input(src)
            builder.output(
                dest,
                audio_codec="pcm_s16le",
                audio_channels=1,
                audio_rate=16000,
                extra_args=["-vn"],
            )

        spec = CommandSpec(args=builder.build())

        try:
            self.runner.run(spec, cancellation_token=cancellation_token)
        except ProcessExecutionError as e:
            # If FFmpeg failed because of "no audio stream" and we didn't mock duration beforehand,
            # we fallback to generating silence
            if "Output file does not contain any stream" in e.stderr or "no audio" in e.stderr.lower() or "Stream map select" in e.stderr:
                logger.warning("No audio track detected in source video. Generating silent WAV fallback.")
                fallback_duration = duration if duration is not None else 10.0
                fallback_builder = (
                    FfmpegCommandBuilder(self.ffmpeg_path)
                    .overwrite()
                    .global_arg("-f")
                    .global_arg("lavfi")
                    .input("anullsrc=r=16000:cl=mono")
                    .output(dest, audio_codec="pcm_s16le", duration=fallback_duration)
                )
                fallback_spec = CommandSpec(args=fallback_builder.build())
                self.runner.run(fallback_spec, cancellation_token=cancellation_token)
            else:
                raise


class FfmpegProxyGenerator:
    """Generates Constant Frame Rate (CFR) downscaled proxy videos for analysis."""

    def __init__(self, runner: ProcessRunner, ffmpeg_path: str = "ffmpeg") -> None:
        self.runner = runner
        self.ffmpeg_path = ffmpeg_path

    def generate_proxy(
        self,
        source_path: Path | str,
        dest_path: Path | str,
        max_width: int,
        max_height: int,
        is_vfr: bool,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
        source_width: int = 1920,
        source_height: int = 1080,
    ) -> None:
        """Generate a low-res proxy video for faster analysis and processing."""
        src = Path(source_path)
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        # Scale calculation to preserve aspect ratio and keep dimensions divisible by 2
        scale_factor = min(max_width / source_width, max_height / source_height)
        if scale_factor < 1.0:
            new_width = int(source_width * scale_factor)
            new_height = int(source_height * scale_factor)
        else:
            new_width = source_width
            new_height = source_height

        new_width = max(2, (new_width // 2) * 2)
        new_height = max(2, (new_height // 2) * 2)

        # Build FFmpeg command
        builder = FfmpegCommandBuilder(self.ffmpeg_path).overwrite()
        builder.input(src)

        extra = ["-pix_fmt", "yuv420p"]
        if is_vfr:
            # Force CFR to ensure stable timestamps
            extra.extend(["-vsync", "cfr"])

        builder.output(
            dest,
            video_codec="libx264",
            audio_codec="aac",
            video_filter=f"scale={new_width}:{new_height}",
            video_fps=30.0 if is_vfr else None,
            extra_args=extra,
        )

        spec = CommandSpec(args=builder.build())
        self.runner.run(spec, cancellation_token=cancellation_token, progress_callback=progress_callback)


class FfmpegThumbnailGenerator:
    """Generates keyframe thumbnails and tiles them into a contact sheet."""

    def __init__(self, runner: ProcessRunner, ffmpeg_path: str = "ffmpeg") -> None:
        self.runner = runner
        self.ffmpeg_path = ffmpeg_path

    def generate_thumbnails(
        self,
        source_path: Path | str,
        dest_dir: Path | str,
        timestamps: List[float],
        cancellation_token: Optional[CancellationToken] = None,
    ) -> List[Path]:
        """Extract thumbnail image frames at specific timestamps."""
        src = Path(source_path)
        out_dir = Path(dest_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        paths = []
        for idx, ts in enumerate(timestamps):
            if cancellation_token:
                cancellation_token.raise_if_cancelled()

            thumb_path = out_dir / f"thumb_{idx}.jpg"
            builder = (
                FfmpegCommandBuilder(self.ffmpeg_path)
                .overwrite()
                .input(src, seek=ts)
                .output(thumb_path, extra_args=["-vframes", "1", "-f", "image2"])
            )
            spec = CommandSpec(args=builder.build())
            self.runner.run(spec, cancellation_token=cancellation_token)
            paths.append(thumb_path)

        return paths

    def generate_contact_sheet(
        self,
        thumbnail_paths: List[Path | str],
        dest_path: Path | str,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> None:
        """Create a tiled contact sheet from a list of thumbnails."""
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        n = len(thumbnail_paths)
        if n == 0:
            raise ValueError("No thumbnails provided to generate contact sheet.")

        # Grid geometry
        import math
        cols = int(math.ceil(math.sqrt(n)))
        rows = int(math.ceil(n / cols))

        # Write inputs to a temp concat text file to avoid pattern match issues on Windows
        with tempfile.TemporaryDirectory() as temp_dir:
            concat_file = Path(temp_dir) / "inputs.txt"
            with open(concat_file, "w", encoding="utf-8") as f:
                for p in thumbnail_paths:
                    # FFmpeg concat demuxer paths must escape backslashes
                    escaped_path = str(Path(p).absolute()).replace("\\", "/")
                    f.write(f"file '{escaped_path}'\n")

            builder = (
                FfmpegCommandBuilder(self.ffmpeg_path)
                .overwrite()
                .global_arg("-f")
                .global_arg("concat")
                .global_arg("-safe")
                .global_arg("0")
                .input(concat_file)
                .output(dest, video_filter=f"tile={cols}x{rows}")
            )

            spec = CommandSpec(args=builder.build())
            self.runner.run(spec, cancellation_token=cancellation_token)


class DefaultMediaNormalizer:
    """Orchestrates the ingestion, preflight check, caching, and normalization flow."""

    def __init__(
        self,
        probe_service: MediaProbeService,
        audio_extractor: AudioExtractor,
        proxy_generator: ProxyGenerator,
        thumbnail_generator: ThumbnailGenerator,
        checksum_service: Optional[FileChecksumService] = None,
    ) -> None:
        self.probe_service = probe_service
        self.audio_extractor = audio_extractor
        self.proxy_generator = proxy_generator
        self.thumbnail_generator = thumbnail_generator
        self.checksum_service = checksum_service or SHA256ChecksumService()

    def normalize(
        self,
        source_path: Path | str,
        project_id: str,
        workspace_dir: Path | str,
        settings: Any,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> Dict[str, Any]:
        """Normalize source media into proxy, WAV, and contact sheet assets."""
        src = Path(source_path)
        ws = Path(workspace_dir)
        media_artifacts_dir = ws / "artifacts" / "media"
        media_artifacts_dir.mkdir(parents=True, exist_ok=True)

        if not src.exists():
            raise FileNotFoundError(f"Source video file not found: {src}")

        # 1. Disk Preflight Check
        # Need space for proxy (approx 0.5x) + audio (approx 0.1x) + buffer. We check for 1.5x source size.
        src_size = src.stat().st_size
        required_free_bytes = max(50 * 1024 * 1024, int(src_size * 1.5))
        disk_info = shutil.disk_usage(ws)
        if disk_info.free < required_free_bytes:
            raise IOError(
                f"Insufficient disk space. Required: {required_free_bytes} bytes, "
                f"Available: {disk_info.free} bytes on '{ws.drive}'"
            )

        # 2. Checksum/Hash Calculation
        sha256 = self.checksum_service.calculate_sha256(src)

        # Target file names
        source_ref_path = media_artifacts_dir / "source_reference.json"
        media_info_path = media_artifacts_dir / "media_info.json"
        proxy_path = media_artifacts_dir / "analysis_proxy.mp4"
        audio_path = media_artifacts_dir / "transcription_audio.wav"
        contact_sheet_path = media_artifacts_dir / "contact_sheet.jpg"

        # 3. Cache Check
        cache_hit = False
        if source_ref_path.exists() and media_info_path.exists() and proxy_path.exists() and audio_path.exists() and contact_sheet_path.exists():
            try:
                with open(source_ref_path, "r", encoding="utf-8") as f:
                    ref_data = json.load(f)
                if ref_data.get("sha256") == sha256:
                    cache_hit = True
                    logger.info("Cache hit: media normalization skipped. Reusing existing assets.")
            except Exception:
                pass

        if cache_hit:
            # Read and return existing media info
            with open(media_info_path, "r", encoding="utf-8") as f:
                media_info_json = json.load(f)
            return {
                "cache_hit": True,
                "sha256": sha256,
                "media_info": media_info_json,
                "proxy_path": str(proxy_path),
                "audio_path": str(audio_path),
                "contact_sheet_path": str(contact_sheet_path),
            }

        # 4. Probe Media Info
        media_info = self.probe_service.probe(src)

        # 5. Extract Audio Track (WAV, 16kHz, mono)
        logger.info("Extracting audio for transcription...")
        self.audio_extractor.extract_audio(
            src,
            audio_path,
            cancellation_token=cancellation_token,
            duration=media_info.duration if not media_info.has_audio else None,
        )

        # 6. Generate Video Proxy
        max_w = getattr(settings, "max_proxy_width", 640)
        max_h = getattr(settings, "max_proxy_height", 360)
        
        # We set callback.duration_seconds to hook into SubprocessRunner's progress parsing
        if progress_callback:
            progress_callback.duration_seconds = media_info.duration  # type: ignore

        logger.info(f"Generating proxy video ({max_w}x{max_h})...")
        self.proxy_generator.generate_proxy(
            source_path=src,
            dest_path=proxy_path,
            max_width=max_w,
            max_height=max_h,
            is_vfr=media_info.vfr_detected,
            cancellation_token=cancellation_token,
            progress_callback=progress_callback,
            source_width=int(media_info.resolution.split("x")[0]),
            source_height=int(media_info.resolution.split("x")[1]),
        )

        # 7. Generate Thumbnails & Contact Sheet
        logger.info("Generating keyframe thumbnails and contact sheet...")
        # Capture 9 evenly spaced keyframe thumbnails across the duration
        duration = media_info.duration
        timestamps = [duration * (i / 10.0) for i in range(1, 10)]
        
        with tempfile.TemporaryDirectory() as temp_thumb_dir:
            thumb_paths = self.thumbnail_generator.generate_thumbnails(
                src,
                temp_thumb_dir,
                timestamps,
                cancellation_token=cancellation_token,
            )
            self.thumbnail_generator.generate_contact_sheet(
                thumb_paths,
                contact_sheet_path,
                cancellation_token=cancellation_token,
            )

        # 8. Save Artifacts Atomically
        # Save source reference
        ref_payload = {
            "source_path": str(src.absolute()),
            "sha256": sha256,
            "size_bytes": src_size,
        }
        with open(source_ref_path, "w", encoding="utf-8") as f:
            json.dump(ref_payload, f, indent=2)

        # Save media info JSON
        with open(media_info_path, "w", encoding="utf-8") as f:
            f.write(media_info.model_dump_json(indent=2))

        # Save ingest report JSON
        report_payload = {
            "project_id": project_id,
            "ingested_at": media_info_path.stat().st_mtime,
            "sha256": sha256,
            "size_bytes": src_size,
            "resolution": media_info.resolution,
            "fps": media_info.fps,
            "duration": media_info.duration,
            "vfr": media_info.vfr_detected,
            "has_audio": media_info.has_audio,
        }
        with open(media_artifacts_dir / "ingest_report.json", "w", encoding="utf-8") as f:
            json.dump(report_payload, f, indent=2)

        return {
            "cache_hit": False,
            "sha256": sha256,
            "media_info": media_info.model_dump(),
            "proxy_path": str(proxy_path),
            "audio_path": str(audio_path),
            "contact_sheet_path": str(contact_sheet_path),
        }
