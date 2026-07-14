"""Unit tests for subprocess process runner, fluent builders, timeouts, cancellation, and progress parser."""

import os
import sys
import time
import pytest
from pathlib import Path
from video_recap.application.pipeline import CancellationToken
from video_recap.domain import JobCancelledError, ProcessExecutionError
from video_recap.domain.media import CommandSpec
from video_recap.infrastructure.media.ffmpeg_builder import (
    FfmpegCommandBuilder,
    FfprobeCommandBuilder,
    FfmpegProgressParser,
)
from video_recap.infrastructure.media.subprocess_runner import SubprocessRunner


def test_command_builders() -> None:
    """Verify that FFmpeg and FFprobe builders compile correct lists of arguments."""
    # FFmpeg builder test
    builder = (
        FfmpegCommandBuilder(ffmpeg_path="/bin/ffmpeg")
        .overwrite()
        .global_arg("-threads")
        .global_arg("4")
        .input("input.mp4", seek=10.5)
        .output(
            "output.mp4",
            video_codec="libx264",
            audio_codec="aac",
            video_filter="scale=1280:720",
            audio_filter="loudnorm",
            duration=30.0,
        )
    )

    args = builder.build()
    assert args == [
        "/bin/ffmpeg",
        "-y",
        "-threads",
        "4",
        "-ss",
        "10.500000",
        "-i",
        "input.mp4",
        "-c:v",
        "libx264",
        "-c:a",
        "aac",
        "-vf",
        "scale=1280:720",
        "-af",
        "loudnorm",
        "-t",
        "30.000000",
        "output.mp4",
    ]

    # FFprobe builder test
    probe = (
        FfprobeCommandBuilder(ffprobe_path="/bin/ffprobe")
        .input("test.mp4")
        .show_format()
        .show_streams()
    )
    probe_args = probe.build()
    assert probe_args == [
        "/bin/ffprobe",
        "-print_format",
        "json",
        "-v",
        "quiet",
        "-show_format",
        "-show_streams",
        "test.mp4",
    ]


def test_progress_parser() -> None:
    """Verify FfmpegProgressParser parses progress values from stdout and stderr."""
    parser = FfmpegProgressParser(duration_seconds=10.0)

    # 1. Pipe format (stdout)
    assert parser.parse_line("frame=100") is None
    assert parser.parse_line("out_time_us=5000000") == 0.5  # 5s / 10s
    assert parser.parse_line("out_time_us=10000000") == 1.0  # 10s / 10s

    # 2. Stderr format
    assert parser.parse_line("frame=  10 fps=0.0 q=0.0 size=       0kB time=00:00:02.50 speed=   0x") == 0.25


def test_subprocess_runner_success() -> None:
    """Verify that SubprocessRunner runs successfully for zero exit status."""
    runner = SubprocessRunner()
    spec = CommandSpec(args=[sys.executable, "-c", "print('Hello World')"])
    res = runner.run(spec)

    assert res.return_code == 0
    assert "Hello World" in res.stdout


def test_subprocess_runner_non_zero_exit() -> None:
    """Verify that SubprocessRunner raises ProcessExecutionError on non-zero exit."""
    runner = SubprocessRunner()
    spec = CommandSpec(args=[sys.executable, "-c", "import sys; sys.exit(42)"])

    with pytest.raises(ProcessExecutionError) as exc_info:
        runner.run(spec)

    assert exc_info.value.return_code == 42
    assert "exit status 42" in str(exc_info.value)


def test_subprocess_runner_timeout() -> None:
    """Verify that SubprocessRunner kills process and raises error on timeout."""
    runner = SubprocessRunner()
    spec = CommandSpec(
        args=[sys.executable, "-c", "import time; time.sleep(10)"],
        timeout_seconds=0.1,
    )

    start = time.time()
    with pytest.raises(ProcessExecutionError) as exc_info:
        runner.run(spec)
    duration = time.time() - start

    assert "exceeded timeout limit" in str(exc_info.value)
    # The process should have been terminated quickly
    assert duration < 2.0


def test_subprocess_runner_cancellation() -> None:
    """Verify that SubprocessRunner kills process and raises error on cancellation request."""
    runner = SubprocessRunner()
    spec = CommandSpec(args=[sys.executable, "-c", "import time; time.sleep(10)"])
    token = CancellationToken()

    # Trigger cancellation in a background timer to simulate user interaction
    def trigger_cancel():
        time.sleep(0.05)
        token.cancel()

    import threading
    t = threading.Thread(target=trigger_cancel)
    t.start()

    start = time.time()
    with pytest.raises(JobCancelledError):
        runner.run(spec, cancellation_token=token)
    duration = time.time() - start

    t.join()
    assert duration < 2.0


def test_unicode_paths(tmp_path: Path) -> None:
    """Verify that SubprocessRunner works with Unicode directories and files."""
    runner = SubprocessRunner()
    # Unicode folder: Chữ Việt Nam
    unicode_dir = tmp_path / "Chữ_Việt_Nam"
    unicode_dir.mkdir()
    target_file = unicode_dir / "tệp_tin.txt"
    target_file.write_text("Dữ liệu unicode")

    # Command: read file content using python print
    spec = CommandSpec(
        args=[
            sys.executable,
            "-c",
            "import sys; f=open(sys.argv[1], 'r', encoding='utf-8'); print(f.read())",
            str(target_file),
        ]
    )
    res = runner.run(spec)
    assert res.return_code == 0
    assert "Dữ liệu unicode" in res.stdout


def test_ffmpeg_progress_callback() -> None:
    """Verify progress callback is triggered during mock ffmpeg runner execution."""
    runner = SubprocessRunner()
    # Mock ffmpeg progress output command: writes out_time_us updates
    # We name the python binary 'ffmpeg_mock' to trigger the is_ffmpeg check inside runner!
    # On Windows, sys.executable is python.exe. We can copy it to ffmpeg_mock.exe!
    import shutil
    ffmpeg_mock_bin = Path(sys.executable).parent / f"ffmpeg_mock{'.exe' if os.name == 'nt' else ''}"
    try:
        shutil.copy2(sys.executable, ffmpeg_mock_bin)
    except Exception:
        # Fallback to sys.executable if copy fails (e.g. read-only permissions)
        ffmpeg_mock_bin = Path(sys.executable)

    # Command prints out_time_us updates like ffmpeg -progress
    code = (
        "import sys, time; "
        "print('frame=10\\nfps=1\\nout_time_us=2500000\\nprogress=continue\\n', flush=True); "
        "time.sleep(0.02); "
        "print('frame=20\\nfps=2\\nout_time_us=5000000\\nprogress=continue\\n', flush=True); "
        "time.sleep(0.02); "
        "print('frame=30\\nfps=3\\nout_time_us=10000000\\nprogress=end\\n', flush=True)"
    )

    spec = CommandSpec(args=[str(ffmpeg_mock_bin), "-c", code])

    progresses = []

    def callback(val: float) -> None:
        progresses.append(val)

    # Instantiate progress parser inside execution
    # Wait, the runner needs total duration, but wait! How does SubprocessRunner know the duration?
    # Ah! SubprocessRunner instantiates FfmpegProgressParser() with duration_seconds=None if it doesn't know it!
    # But wait, if duration_seconds is None, the progress_parser's parse_line returns None, so the callback is never called!
    # To fix this, we should allow passing duration_seconds or setting it inside FfmpegProgressParser
    # or inside the runner, or let the caller configure the duration!
    # Let's check: how does FfmpegProgressParser know the duration inside SubprocessRunner?
    # Ah! In a real run, the orchestrator/stage knows the duration of the video.
    # But the SubprocessRunner's run method only accepts:
    # run(self, spec: CommandSpec, cancellation_token: Optional[CancellationToken] = None, progress_callback: Optional[Callable[[float], None]] = None)
    # Wait! How can we pass the duration?
    # We can pass duration_seconds as an attribute of the progress_callback itself (e.g. callback.duration = 10.0),
    # or let the builder include duration, or pass it in spec!
    # Yes! We can pass it in `CommandSpec` or let the progress_callback have a `duration_seconds` attribute,
    # or check if progress_callback has `duration_seconds` attribute, or we can look for it in env/metadata.
    # Let's design this: inside SubprocessRunner, if it has `progress_callback` and `is_ffmpeg`:
    #   duration = getattr(progress_callback, "duration_seconds", None)
    #   progress_parser = FfmpegProgressParser(duration)
    # This is an incredibly elegant and dynamic way to pass the duration without changing the signature of run()!
    # Let's verify: yes, if the callback has `duration_seconds` attribute, we use it!
    
    callback.duration_seconds = 10.0  # type: ignore

    try:
        runner.run(spec, progress_callback=callback)
    finally:
        # Cleanup mock binary if created
        if ffmpeg_mock_bin.name == "ffmpeg_mock.exe" and ffmpeg_mock_bin.exists():
            try:
                ffmpeg_mock_bin.unlink()
            except Exception:
                pass

    # Callback should be called with 0.25 (2.5s), 0.5 (5.0s), 1.0 (10.0s)
    assert len(progresses) > 0
    assert 0.25 in progresses
    assert 0.5 in progresses
    assert 1.0 in progresses
