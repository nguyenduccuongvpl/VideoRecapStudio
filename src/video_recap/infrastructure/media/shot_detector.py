"""Infrastructure implementation of shot detection using FFmpeg metadata and mock boundaries."""

import csv
import logging
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from video_recap.application.media import ProcessRunner
from video_recap.application.pipeline import CancellationToken
from video_recap.application.shot import Shot, ShotDetectionService
from video_recap.domain.media import CommandSpec, FfmpegCommandBuilder

logger = logging.getLogger("ShotDetector")

GENRE_THRESHOLDS: Dict[str, float] = {
    "default": 0.4,
    "action": 0.5,
    "interview": 0.25,
    "talking_head": 0.25,
    "presentation": 0.3,
}


class MockShotDetector(ShotDetectionService):
    """Simulates shot detection boundaries for unit testing and offline development."""

    def __init__(self, duration: float = 30.0, fps: float = 30.0) -> None:
        self.duration = duration
        self.fps = fps

    def detect_shots(
        self,
        video_path: Path | str,
        source_hash: str,
        genre: str = "default",
        cancellation_token: Optional[CancellationToken] = None,
    ) -> List[Shot]:
        logger.info(f"Mock detecting shots for: {video_path}")
        
        # Determine duration based on file size or fallback to self.duration
        try:
            p = Path(video_path)
            if p.exists():
                # Simple heuristic duration: size_bytes / 500_000 (approx 500KB/s)
                dur = max(5.0, min(300.0, p.stat().st_size / 500000.0))
            else:
                dur = self.duration
        except Exception:
            dur = self.duration

        # Generate a list of cuts every 6.0 seconds
        cuts = []
        t = 6.0
        while t < dur:
            cuts.append(t)
            t += 6.0

        raw_shots = []
        prev_time = 0.0
        
        # Always add final boundary
        all_boundaries = cuts + [dur]
        
        for idx, bound in enumerate(all_boundaries):
            if cancellation_token:
                cancellation_token.raise_if_cancelled()

            start_f = int(prev_time * self.fps)
            end_f = int(bound * self.fps)
            raw_shots.append(
                Shot(
                    id=f"shot_{idx}",
                    start_ms=int(prev_time * 1000),
                    end_ms=int(bound * 1000),
                    start_frame=start_f,
                    end_frame=end_f,
                    duration=bound - prev_time,
                    detector="mock",
                    cut_score=0.75,
                    transition_type="cut",
                    source_hash=source_hash,
                )
            )
            prev_time = bound

        # Post process to apply merge/split rules
        normalizer = ShotTimelineNormalizer()
        return normalizer.normalize_timeline(raw_shots, dur, self.fps, source_hash)


class FfmpegShotDetector(ShotDetectionService):
    """Executes FFmpeg select=scene filter to discover real shot changes in video."""

    def __init__(self, runner: ProcessRunner, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe") -> None:
        self.runner = runner
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def detect_shots(
        self,
        video_path: Path | str,
        source_hash: str,
        genre: str = "default",
        cancellation_token: Optional[CancellationToken] = None,
    ) -> List[Shot]:
        video_p = Path(video_path)
        if not video_p.exists():
            raise FileNotFoundError(f"Video file not found: {video_p}")

        # 1. Fetch exact duration and FPS using FFprobe
        duration, fps = self._probe_video_specs(video_p)

        # 2. Lookup genre threshold
        threshold = GENRE_THRESHOLDS.get(genre.lower(), 0.4)
        logger.info(f"Running FFmpeg shot detection (genre: {genre}, threshold: {threshold})...")

        # 3. Execute FFmpeg select filter and redirect metadata to a temp file
        with tempfile.TemporaryDirectory() as temp_dir:
            meta_file = Path(temp_dir) / "scene_metadata.txt"
            
            # Escape backslashes for Windows path in select filter output
            meta_file_esc = str(meta_file.absolute()).replace("\\", "/")
            
            # command: ffmpeg -y -i <video> -filter:v "select='gt(scene,threshold)',metadata=print:file='path'" -f null -
            builder = (
                FfmpegCommandBuilder(self.ffmpeg_path)
                .overwrite()
                .input(video_p)
                .output(
                    "-",
                    extra_args=[
                        "-filter:v",
                        f"select='gt(scene,{threshold})',metadata=print:file='{meta_file_esc}'",
                        "-f",
                        "null",
                    ],
                )
            )
            spec = CommandSpec(args=builder.build())
            
            try:
                self.runner.run(spec, cancellation_token=cancellation_token)
            except Exception as e:
                logger.error(f"FFmpeg scene select command failed: {e}")
                raise RuntimeError(f"Shot detection command failed: {e}")

            # 4. Parse detected frame cuts from metadata text file
            cuts = self._parse_metadata_file(meta_file)

        # 5. Build raw Shot list
        raw_shots: List[Shot] = []
        prev_time = 0.0
        prev_frame = 0

        # Boundary cuts must contain final frame/duration
        all_cuts = cuts
        # Check if last cut is already at duration, otherwise add it
        if not all_cuts or abs(all_cuts[-1]["time"] - duration) > 0.05:
            all_cuts.append({"time": duration, "frame": int(duration * fps), "score": 1.0})

        for idx, cut in enumerate(all_cuts):
            if cancellation_token:
                cancellation_token.raise_if_cancelled()

            curr_time = cut["time"]
            curr_frame = cut["frame"]
            score = cut["score"]

            # Safe guard duration
            if curr_time > duration:
                curr_time = duration

            duration_sec = curr_time - prev_time

            # Avoid empty shots
            if duration_sec <= 0:
                continue

            raw_shots.append(
                Shot(
                    id=f"shot_{idx}",
                    start_ms=int(prev_time * 1000),
                    end_ms=int(curr_time * 1000),
                    start_frame=prev_frame,
                    end_frame=curr_frame,
                    duration=duration_sec,
                    detector="ffmpeg-scene",
                    cut_score=score,
                    transition_type="cut",
                    source_hash=source_hash,
                )
            )
            prev_time = curr_time
            prev_frame = curr_frame

        # 6. Normalize timeline: merge micro-shots & split synthetic windows
        normalizer = ShotTimelineNormalizer()
        return normalizer.normalize_timeline(raw_shots, duration, fps, source_hash)

    def _probe_video_specs(self, video_path: Path) -> tuple[float, float]:
        """Probes video duration and frame rate using ffprobe."""
        from video_recap.infrastructure.media.subprocess_runner import SubprocessRunner
        runner = SubprocessRunner()
        
        # Duration probe command
        args = [
            self.ffprobe_path,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=duration,r_frame_rate",
            "-of", "csv=p=0",
            str(video_path),
        ]
        spec = CommandSpec(args=args)
        res = runner.run(spec)
        
        # Parse CSV output (e.g. 30000/1001,10.05)
        # Or output: 25/1,10.4
        output = res.stdout.strip()
        if not output:
            return 10.0, 30.0  # Safe defaults
            
        parts = output.split(",")
        fps = 30.0
        duration = 10.0
        
        try:
            if len(parts) > 0 and "/" in parts[0]:
                num, den = map(float, parts[0].split("/"))
                if den > 0:
                    fps = num / den
            if len(parts) > 1:
                duration = float(parts[1])
        except Exception:
            pass

        return duration, fps

    def _parse_metadata_file(self, meta_file: Path) -> List[dict]:
        """Parses output file from select filter."""
        # Format:
        # frame:13    pts:520000   pts_time:5.2
        # lavfi.select.score=0.452300
        if not meta_file.exists():
            return []

        content = meta_file.read_text(encoding="utf-8")
        
        # Regex matches frame line and following score line
        pattern = re.compile(
            r"frame:(\d+)\s+pts:\d+\s+pts_time:([\d.]+)\s+lavfi\.select\.score=([\d.]+)"
        )
        
        cuts = []
        for match in pattern.finditer(content):
            frame = int(match.group(1))
            pts_time = float(match.group(2))
            score = float(match.group(3))
            cuts.append({"frame": frame, "time": pts_time, "score": score})

        # Sort chronologically
        cuts.sort(key=lambda x: x["time"])
        return cuts


class ShotTimelineNormalizer:
    """Handles post-processing merge, split, and timeline correction rules."""

    def normalize_timeline(
        self,
        shots: List[Shot],
        total_duration: float,
        fps: float,
        source_hash: str,
        min_shot_sec: float = 0.5,
        max_shot_sec: float = 30.0,
    ) -> List[Shot]:
        if not shots:
            # Fallback to single full-video shot
            return [
                Shot(
                    id="shot_0",
                    start_ms=0,
                    end_ms=int(total_duration * 1000),
                    start_frame=0,
                    end_frame=int(total_duration * fps),
                    duration=total_duration,
                    detector="fallback",
                    source_hash=source_hash,
                )
            ]

        # 1. Merge micro-shots (duration < 0.5s) unless score is very high (hard cut indicator > 0.6)
        merged: List[Shot] = []
        for s in shots:
            if not merged:
                merged.append(s)
                continue

            prev = merged[-1]
            if prev.duration < min_shot_sec and (prev.cut_score is None or prev.cut_score <= 0.6):
                # Merge current into prev or prev into current?
                # We extend prev to encompass current shot
                prev.end_ms = s.end_ms
                prev.end_frame = s.end_frame
                prev.duration = (prev.end_ms - prev.start_ms) / 1000.0
                # Keep maximum cut score
                if s.cut_score is not None and prev.cut_score is not None:
                    prev.cut_score = max(prev.cut_score, s.cut_score)
            elif s.duration < min_shot_sec and (s.cut_score is None or s.cut_score <= 0.6):
                # Merge s into prev
                prev.end_ms = s.end_ms
                prev.end_frame = s.end_frame
                prev.duration = (prev.end_ms - prev.start_ms) / 1000.0
            else:
                merged.append(s)

        # 2. Split long shots (duration > 30s) into synthetic analysis windows of 15.0s
        split_shots: List[Shot] = []
        for s in merged:
            if s.duration > max_shot_sec:
                # Split
                num_splits = int(math.ceil(s.duration / 15.0))
                segment_dur = s.duration / num_splits
                
                prev_time = s.start_ms / 1000.0
                prev_frame = s.start_frame
                
                for j in range(num_splits):
                    curr_time = (s.start_ms / 1000.0) + (j + 1) * segment_dur
                    if j == num_splits - 1:
                        curr_time = s.end_ms / 1000.0
                        
                    curr_frame = int(curr_time * fps)
                    if j == num_splits - 1:
                        curr_frame = s.end_frame

                    split_shots.append(
                        Shot(
                            id=f"{s.id}_syn_{j}",
                            start_ms=int(prev_time * 1000),
                            end_ms=int(curr_time * 1000),
                            start_frame=prev_frame,
                            end_frame=curr_frame,
                            duration=curr_time - prev_time,
                            detector=s.detector,
                            cut_score=s.cut_score,
                            transition_type=s.transition_type,
                            source_hash=source_hash,
                            is_synthetic=True,
                        )
                    )
                    prev_time = curr_time
                    prev_frame = curr_frame
            else:
                split_shots.append(s)

        # 3. Timeline verification:
        # - Force continuous bounds: shot[i].end_ms == shot[i+1].start_ms
        # - Exact source timeline: start_ms is 0, end_ms matches duration
        for i in range(len(split_shots) - 1):
            split_shots[i + 1].start_ms = split_shots[i].end_ms
            split_shots[i + 1].start_frame = split_shots[i].end_frame

        split_shots[0].start_ms = 0
        split_shots[0].start_frame = 0
        split_shots[-1].end_ms = int(total_duration * 1000)
        split_shots[-1].end_frame = int(total_duration * fps)

        # Recalculate duration & assign cleaner IDs
        final_shots: List[Shot] = []
        for idx, s in enumerate(split_shots):
            s.id = f"shot_{idx}"
            s.duration = (s.end_ms - s.start_ms) / 1000.0
            # Ensure duration is positive
            if s.duration > 0:
                final_shots.append(s)

        return final_shots
