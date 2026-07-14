"""Infrastructure implementation of the video timeline renderer using FFmpeg."""

import datetime
import logging
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
from video_recap.application.media import ProcessRunner
from video_recap.application.pipeline import CancellationToken
from video_recap.application.renderer import (
    NarrationOverlay,
    TimelineClip,
    RenderTimeline,
    RenderManifest,
    PreviewRenderer,
)
from video_recap.domain import AudioDurationOverflowError
from video_recap.domain.media import CommandSpec, FfmpegCommandBuilder

logger = logging.getLogger("TimelineRenderer")


class FfmpegPreviewRenderer(PreviewRenderer):
    """Orchestrates deterministic rendering of a timeline sequence into an MP4 video using FFmpeg."""

    def __init__(self, runner: ProcessRunner, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe") -> None:
        self.runner = runner
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def render_preview(
        self,
        video_path: Path | str,
        timeline: RenderTimeline,
        dest_path: Path | str,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> RenderManifest:
        src = Path(video_path)
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)

        if not src.exists():
            raise FileNotFoundError(f"Source video file not found: {src}")

        # 1. Validation: Verify narration overlay durations
        total_output_duration = 0.0
        for clip in timeline.clips:
            clip_dur = clip.source_end - clip.source_start
            if clip_dur <= 0:
                raise ValueError(f"Clip {clip.id} has invalid source boundaries: {clip.source_start} -> {clip.source_end}")
            
            total_output_duration += clip_dur

            for narr in clip.narrations:
                if narr.start_time_in_clip + narr.duration > clip_dur:
                    raise AudioDurationOverflowError(
                        f"Narration overlay {narr.audio_path} (starts at {narr.start_time_in_clip}s, duration {narr.duration}s) "
                        f"exceeds the video clip {clip.id} duration ({clip_dur}s)."
                    )

        # 2. Probe source audio stream presence
        has_audio = self._probe_has_audio(src)

        ffmpeg_commands: List[List[str]] = []

        # 3. Render individual clips to temp files
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_clips = []
            
            for idx, clip in enumerate(timeline.clips):
                if cancellation_token:
                    cancellation_token.raise_if_cancelled()

                clip_dur = clip.source_end - clip.source_start
                temp_output = Path(temp_dir) / f"clip_{idx}_{clip.id}.mp4"
                temp_clips.append(temp_output)

                cmd_args = self._build_clip_render_command(
                    src,
                    clip,
                    clip_dur,
                    has_audio,
                    timeline.output_width,
                    timeline.output_height,
                    timeline.output_fps,
                    temp_output,
                )
                
                ffmpeg_commands.append(cmd_args)
                
                spec = CommandSpec(args=cmd_args)
                logger.info(f"Rendering temporary clip {clip.id}...")
                self.runner.run(spec, cancellation_token=cancellation_token)

            # 4. Generate concat demuxer text file
            concat_txt = Path(temp_dir) / "concat_list.txt"
            with open(concat_txt, "w", encoding="utf-8") as f:
                for temp_p in temp_clips:
                    # Escape backslashes for FFmpeg concat demuxer on Windows
                    escaped_path = str(temp_p.absolute()).replace("\\", "/")
                    f.write(f"file '{escaped_path}'\n")

            # 5. Concatenate all processed temp clips
            if cancellation_token:
                cancellation_token.raise_if_cancelled()

            concat_builder = (
                FfmpegCommandBuilder(self.ffmpeg_path)
                .overwrite()
                .global_arg("-f")
                .global_arg("concat")
                .global_arg("-safe")
                .global_arg("0")
                .input(concat_txt)
                .output(dest, extra_args=["-c", "copy"])
            )
            concat_cmd = concat_builder.build()
            ffmpeg_commands.append(concat_cmd)

            logger.info("Concatenating temporary clips into final output...")
            self.runner.run(CommandSpec(args=concat_cmd), cancellation_token=cancellation_token)

        # 6. Save Manifest
        manifest = RenderManifest(
            timeline=timeline,
            output_path=str(dest.absolute()),
            rendered_at=datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
            duration=total_output_duration,
            ffmpeg_commands=ffmpeg_commands,
        )

        return manifest

    def _probe_has_audio(self, path: Path) -> bool:
        """Query ffprobe to detect presence of audio stream."""
        from video_recap.infrastructure.media.subprocess_runner import SubprocessRunner
        runner = SubprocessRunner()
        args = [
            self.ffprobe_path,
            "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=index",
            "-of", "csv=p=0",
            str(path),
        ]
        try:
            res = runner.run(CommandSpec(args=args))
            return len(res.stdout.strip()) > 0
        except Exception:
            return False

    def _build_clip_render_command(
        self,
        source_video: Path,
        clip: TimelineClip,
        duration: float,
        has_audio: bool,
        width: int,
        height: int,
        fps: float,
        output_path: Path,
    ) -> List[str]:
        # base builder
        builder = FfmpegCommandBuilder(self.ffmpeg_path).overwrite()
        
        # Input 0: Trimmed video
        builder.input(source_video, seek=clip.source_start)
        
        # Audio inputs setup:
        # If we need silent audio fallback (either because source has no audio, or volume is 0.0),
        # we append anullsrc filter input.
        use_silent_base = not has_audio or clip.original_audio_volume == 0.0
        
        # Append narration audios as extra inputs
        for narr in clip.narrations:
            builder.input(narr.audio_path)
            
        if use_silent_base:
            # Append silent audio input generator using lavfi
            # ffmpeg -f lavfi -i anullsrc=r=48000:cl=stereo
            builder.global_arg("-f").global_arg("lavfi")
            builder.input("anullsrc=r=48000:cl=stereo")

        # Video filter: Scale and pad to destination resolution preserving aspect ratio
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
            f"fps={fps},"
            f"format=yuv420p"
        )

        # Audio mixing filtergraph:
        audio_filter = ""
        narr_count = len(clip.narrations)
        
        # Input index mappings:
        # Video is always input 0.
        # Narrations are input 1, 2, ..., N.
        # Silent base input (if added) is input N+1.
        
        # Delays list:
        # Delay original volume or silent audio, and then delay/mix all narrations.
        if use_silent_base:
            # Silent base input is index N+1
            silent_idx = narr_count + 1
            audio_inputs = [f"[{silent_idx}:a]"]
        else:
            # Original audio input is index 0
            audio_inputs = [f"[0:a]volume={clip.original_audio_volume}"]

        # Apply adelay filter to all narrations
        for j, narr in enumerate(clip.narrations):
            delay_ms = int(narr.start_time_in_clip * 1000)
            # FFmpeg adelay filter requires delay per channel: e.g. delay|delay
            audio_inputs.append(f"[{j+1}:a]adelay={delay_ms}|{delay_ms}")

        # amix filtergraph compilation
        # [0:a]volume=1.0[a0]; [1:a]adelay=3000|3000[a1]; [a0][a1]amix=inputs=2:duration=first[a]
        mix_inputs = []
        filter_lines = []
        
        for idx, inp in enumerate(audio_inputs):
            # assign intermediate tags
            tag = f"[mix_{idx}]"
            if idx == 0 and not use_silent_base:
                # original audio volume adjustment
                filter_lines.append(f"{inp}{tag}")
            elif idx == 0 and use_silent_base:
                # silent base
                filter_lines.append(f"{inp}apadsamples=size=0{tag}")  # bypass filter syntax
            else:
                # delayed narration
                filter_lines.append(f"{inp}{tag}")
            mix_inputs.append(tag)

        # Merge mix
        filter_lines.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first[a]")
        audio_filter = ";".join(filter_lines)

        # Compilation of output options
        extra_args = [
            "-to", f"{duration}",
            "-filter_complex", f"[0:v]{video_filter}[v];{audio_filter}",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", "libx264",
            "-profile:v", "high",
            "-level", "4.1",
            "-c:a", "aac",
            "-b:a", "192k",
        ]
        
        builder.output(output_path, extra_args=extra_args)
        return builder.build()
