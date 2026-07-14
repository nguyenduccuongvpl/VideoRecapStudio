"""Infrastructure implementation of Keyframe extraction and NumPy-based visual analysis."""

import logging
import math
import os
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple
import numpy as np
from video_recap.application.media import ProcessRunner
from video_recap.application.pipeline import CancellationToken
from video_recap.application.shot import Shot
from video_recap.application.visual import (
    VisualSignals,
    KeyframeExtractor,
    MotionAnalyzer,
    BlackFrameAnalyzer,
    FreezeFrameAnalyzer,
    SharpnessAnalyzer,
    FacePresenceAnalyzer,
)
from video_recap.domain.media import CommandSpec, FfmpegCommandBuilder

logger = logging.getLogger("VisualAnalyzer")


class FfmpegKeyframeExtractor(KeyframeExtractor):
    """Extracts keyframes from video at specific timestamps using FFmpeg."""

    def __init__(self, runner: ProcessRunner, ffmpeg_path: str = "ffmpeg") -> None:
        self.runner = runner
        self.ffmpeg_path = ffmpeg_path

    def extract_keyframes(
        self,
        video_path: Path | str,
        shot: Shot,
        dest_dir: Path | str,
        motion_score: float = 0.0,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> List[Path]:
        src = Path(video_path)
        out_dir = Path(dest_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # 1. Determine sampling timestamps
        # Always sample midpoint
        mid_time = (shot.start_ms + shot.end_ms) / 2.0 / 1000.0
        
        timestamps = []
        if motion_score > 0.5:
            # High motion: dense sampling (10%, 30%, 50%, 70%, 90%)
            timestamps = [shot.start_ms / 1000.0 + (shot.duration * p) for p in [0.1, 0.3, 0.5, 0.7, 0.9]]
        elif shot.duration > 10.0:
            # Long shot: multi-sampling (25%, 50%, 75%)
            timestamps = [shot.start_ms / 1000.0 + (shot.duration * p) for p in [0.25, 0.5, 0.75]]
        else:
            timestamps = [mid_time]

        # Filter duplicates and ensure within bounds
        unique_ts = sorted(list(set(timestamps)))
        extracted_paths = []

        for ts in unique_ts:
            if cancellation_token:
                cancellation_token.raise_if_cancelled()

            # Format name: keyframe_<shot_id>_<timestamp_ms>.jpg
            ts_ms = int(ts * 1000)
            dest_file = out_dir / f"keyframe_{shot.id}_{ts_ms}.jpg"

            # FFmpeg seek and extract single frame
            builder = (
                FfmpegCommandBuilder(self.ffmpeg_path)
                .overwrite()
                .input(src, seek=ts)
                .output(dest_file, extra_args=["-vframes", "1", "-f", "image2"])
            )
            spec = CommandSpec(args=builder.build())
            
            try:
                self.runner.run(spec, cancellation_token=cancellation_token)
                if dest_file.exists():
                    extracted_paths.append(dest_file.absolute())
            except Exception as e:
                logger.warning(f"Failed to extract keyframe at {ts}s: {e}")

        return extracted_paths


class NumpyVisualAnalyzer(
    MotionAnalyzer,
    BlackFrameAnalyzer,
    FreezeFrameAnalyzer,
    SharpnessAnalyzer,
    FacePresenceAnalyzer,
):
    """Analyzes image focus, brightness, darkness and frame differences using NumPy and FFmpeg."""

    def __init__(self, runner: ProcessRunner, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe") -> None:
        self.runner = runner
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def _load_frame_numpy(self, image_path: Path | str) -> Tuple[np.ndarray, int, int]:
        """Convert a JPEG image to raw RGB24 bytes via FFmpeg and load into NumPy."""
        img_p = Path(image_path)
        if not img_p.exists():
            raise FileNotFoundError(f"Image not found: {img_p}")

        # Probe resolution using ffprobe
        width, height = self._probe_resolution(img_p)

        with tempfile.TemporaryDirectory() as temp_dir:
            raw_bin = Path(temp_dir) / "frame.bin"
            
            # Command: ffmpeg -y -i <image> -f rawvideo -pix_fmt rgb24 <raw_bin>
            builder = (
                FfmpegCommandBuilder(self.ffmpeg_path)
                .overwrite()
                .input(img_p)
                .output(raw_bin, extra_args=["-f", "rawvideo", "-pix_fmt", "rgb24"])
            )
            spec = CommandSpec(args=builder.build())
            self.runner.run(spec)

            if not raw_bin.exists():
                raise IOError(f"Failed to decode image using FFmpeg: {img_p}")

            raw_bytes = raw_bin.read_bytes()
            arr = np.frombuffer(raw_bytes, dtype=np.uint8)
            
            # Try to reshape to 3D array
            try:
                arr = arr.reshape((height, width, 3))
            except ValueError:
                # If shape mismatch, return flat array
                pass
            return arr, width, height

    def _probe_resolution(self, path: Path) -> Tuple[int, int]:
        """Probe image dimensions using ffprobe."""
        from video_recap.infrastructure.media.subprocess_runner import SubprocessRunner
        runner = SubprocessRunner()
        args = [
            self.ffprobe_path,
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "csv=p=0",
            str(path),
        ]
        res = runner.run(CommandSpec(args=args))
        output = res.stdout.strip()
        if not output:
            return 640, 360  # Default fallback
        try:
            w, h = map(int, output.split(","))
            return w, h
        except Exception:
            return 640, 360

    def analyze_black_ratio(self, image_path: Path | str) -> float:
        """Compute the ratio of black pixels (value < 15) in the keyframe."""
        try:
            arr, _, _ = self._load_frame_numpy(image_path)
            # Calculate proportion of dark pixels
            dark_pixels = np.mean(arr < 15)
            return float(dark_pixels)
        except Exception as e:
            logger.warning(f"Error calculating black ratio: {e}")
            return 0.0

    def analyze_brightness(self, image_path: Path | str) -> float:
        """Compute the average brightness of the keyframe."""
        try:
            arr, _, _ = self._load_frame_numpy(image_path)
            mean_val = np.mean(arr) / 255.0
            return float(mean_val)
        except Exception as e:
            logger.warning(f"Error calculating brightness: {e}")
            return 0.0

    def analyze_sharpness(self, image_path: Path | str) -> float:
        """Compute image focus sharpness using gradient variance."""
        try:
            arr, w, h = self._load_frame_numpy(image_path)
            if len(arr.shape) < 3:
                return 0.5

            # Convert to grayscale first
            gray = arr.mean(axis=-1)
            # Compute spatial gradients
            gy, gx = np.gradient(gray)
            gnorm = np.sqrt(gx**2 + gy**2)
            
            # Sharpness score normalized between 0.0 and 1.0 (heuristic based on average gradient)
            mean_grad = np.mean(gnorm)
            # Map average gradient to 0..1 using sigmoid-like scaling
            score = 1.0 - (1.0 / (1.0 + math.exp(mean_grad / 10.0 - 1.5)))
            return float(score)
        except Exception as e:
            logger.warning(f"Error calculating sharpness: {e}")
            return 0.5

    def analyze_freeze_similarity(self, image_path_1: Path | str, image_path_2: Path | str) -> float:
        """Compute pixel similarity between two keyframes."""
        try:
            arr1, _, _ = self._load_frame_numpy(image_path_1)
            arr2, _, _ = self._load_frame_numpy(image_path_2)

            # Ensure same shape
            if arr1.shape != arr2.shape:
                return 0.0

            diff = np.abs(arr1.astype(float) - arr2.astype(float))
            mean_diff = np.mean(diff) / 255.0
            similarity = 1.0 - mean_diff
            return float(similarity)
        except Exception as e:
            logger.warning(f"Error calculating similarity: {e}")
            return 0.0

    def analyze_motion(
        self,
        video_path: Path | str,
        shot: Shot,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> float:
        """Calculate motion score by comparing frames sampled at 25%, 50% and 75%."""
        src = Path(video_path)
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Extract 3 frames
            t1 = shot.start_ms / 1000.0 + shot.duration * 0.25
            t2 = shot.start_ms / 1000.0 + shot.duration * 0.50
            t3 = shot.start_ms / 1000.0 + shot.duration * 0.75

            img1 = temp_path / "f1.jpg"
            img2 = temp_path / "f2.jpg"
            img3 = temp_path / "f3.jpg"

            # Run extractions
            for t, img in [(t1, img1), (t2, img2), (t3, img3)]:
                if cancellation_token:
                    cancellation_token.raise_if_cancelled()
                builder = (
                    FfmpegCommandBuilder(self.ffmpeg_path)
                    .overwrite()
                    .input(src, seek=t)
                    .output(img, extra_args=["-vframes", "1", "-f", "image2"])
                )
                self.runner.run(CommandSpec(args=builder.build()))

            if not (img1.exists() and img2.exists() and img3.exists()):
                return 0.1  # Fallback

            # Compute similarities
            sim1 = self.analyze_freeze_similarity(img1, img2)
            sim2 = self.analyze_freeze_similarity(img2, img3)

            mean_sim = (sim1 + sim2) / 2.0
            motion = 1.0 - mean_sim
            return max(0.0, min(1.0, float(motion)))

    def analyze_face_presence(self, image_path: Path | str) -> Tuple[bool, str]:
        """Optional/mocked face presence analyzer (non-OCR)."""
        # Return False by default for simplicity without specialized neural nets
        return False, "No human face detected"


class MockVisualAnalyzer(
    MotionAnalyzer,
    BlackFrameAnalyzer,
    FreezeFrameAnalyzer,
    SharpnessAnalyzer,
    FacePresenceAnalyzer,
):
    """Mock visual analyzer returning standard simulated metrics."""

    def analyze_black_ratio(self, image_path: Path | str) -> float:
        return 0.05

    def analyze_brightness(self, image_path: Path | str) -> float:
        return 0.65

    def analyze_sharpness(self, image_path: Path | str) -> float:
        return 0.82

    def analyze_freeze_similarity(self, image_path_1: Path | str, image_path_2: Path | str) -> float:
        return 0.98

    def analyze_motion(
        self,
        video_path: Path | str,
        shot: Shot,
        cancellation_token: Optional[CancellationToken] = None,
    ) -> float:
        return 0.35

    def analyze_face_presence(self, image_path: Path | str) -> Tuple[bool, str]:
        return True, "Detected one talking-head subject"
