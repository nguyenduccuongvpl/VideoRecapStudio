"""Infrastructure implementation of subprocess process runner with cancellation, timeout and progress parsing."""

import logging
import os
import subprocess
import threading
import time
from queue import Empty, Queue
from typing import Callable, Optional
from video_recap.application.pipeline import CancellationToken
from video_recap.domain import JobCancelledError, ProcessExecutionError
from video_recap.domain.media import CommandResult, CommandSpec
from video_recap.infrastructure.logging import redact_secrets

logger = logging.getLogger("SubprocessRunner")


def _reader_thread_fn(pipe, queue: Queue, max_bytes: int) -> None:
    """Reads lines from a stream and pushes to queue, stopping if byte budget is exceeded."""
    bytes_read = 0
    try:
        while True:
            line = pipe.readline()
            if not line:
                break
            bytes_read += len(line)
            if bytes_read <= max_bytes:
                queue.put(line)
            else:
                queue.put(b"\n<output truncated due to buffer size limit>\n")
                break
    except Exception as e:
        queue.put(f"\n<Error reading process output pipe: {e}>\n".encode("utf-8"))


class SubprocessRunner:
    """Runs shell-less subprocess commands securely with cooperative cancellation and timeouts."""

    def run(
        self,
        spec: CommandSpec,
        cancellation_token: Optional[CancellationToken] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> CommandResult:
        """Run a process command, handling Unicode paths, timeouts, and cancellation."""
        # 1. Redact secrets from command args before logging
        redacted_args = [redact_secrets(arg) for arg in spec.args]
        logger.info(f"Spawning process: {' '.join(redacted_args)}")

        # 2. Launch subprocess
        try:
            proc = subprocess.Popen(
                spec.args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=spec.env,
                cwd=spec.cwd,
                shell=False,
            )
        except Exception as e:
            raise ProcessExecutionError(
                message=f"Failed to start process: {e}",
                command=spec.args,
                return_code=None,
            )

        stdout_queue: Queue = Queue()
        stderr_queue: Queue = Queue()

        stdout_thread = threading.Thread(
            target=_reader_thread_fn,
            args=(proc.stdout, stdout_queue, spec.max_output_size_bytes),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_reader_thread_fn,
            args=(proc.stderr, stderr_queue, spec.max_output_size_bytes),
            daemon=True,
        )

        stdout_thread.start()
        stderr_thread.start()

        # 3. Detect if running FFmpeg to parse progress outputs
        # We dynamic import to avoid circular dependency
        from video_recap.domain.media import FfmpegProgressParser

        is_ffmpeg = len(spec.args) > 0 and "ffmpeg" in os.path.basename(spec.args[0]).lower()
        duration = getattr(progress_callback, "duration_seconds", None) if progress_callback else None
        progress_parser = FfmpegProgressParser(duration) if (is_ffmpeg and progress_callback) else None

        start_time = time.time()
        stdout_lines = []
        stderr_lines = []

        try:
            while proc.poll() is None:
                # Check cancellation
                if cancellation_token and cancellation_token.is_cancelled():
                    proc.terminate()
                    time.sleep(0.05)
                    if proc.poll() is None:
                        proc.kill()
                    raise JobCancelledError("Subprocess cancelled cooperatively.")

                # Check timeout
                if spec.timeout_seconds and (time.time() - start_time) > spec.timeout_seconds:
                    proc.terminate()
                    time.sleep(0.05)
                    if proc.poll() is None:
                        proc.kill()
                    raise ProcessExecutionError(
                        message=f"Subprocess exceeded timeout limit of {spec.timeout_seconds} seconds.",
                        command=spec.args,
                        return_code=-1,
                    )

                # Collect stdout and parse progress
                while not stdout_queue.empty():
                    try:
                        line_bytes = stdout_queue.get_nowait()
                        line = line_bytes.decode("utf-8", errors="ignore")
                        stdout_lines.append(line)

                        if progress_parser and progress_callback:
                            prog = progress_parser.parse_line(line)
                            if prog is not None:
                                progress_callback(prog)
                    except Empty:
                        break

                # Collect stderr
                while not stderr_queue.empty():
                    try:
                        line_bytes = stderr_queue.get_nowait()
                        line = line_bytes.decode("utf-8", errors="ignore")
                        stderr_lines.append(line)

                        # FFmpeg sometimes outputs progress to stderr if no -progress file is set
                        if progress_parser and progress_callback:
                            prog = progress_parser.parse_line(line)
                            if prog is not None:
                                progress_callback(prog)
                    except Empty:
                        break

                time.sleep(0.01)
        except Exception:
            # Guarantee cleanup on cancel or unexpected exceptions
            if proc.poll() is None:
                proc.terminate()
                time.sleep(0.05)
                if proc.poll() is None:
                    proc.kill()
            raise

        # Drain remaining logs
        stdout_thread.join(timeout=0.5)
        stderr_thread.join(timeout=0.5)

        while not stdout_queue.empty():
            try:
                line_bytes = stdout_queue.get_nowait()
                line = line_bytes.decode("utf-8", errors="ignore")
                stdout_lines.append(line)
                if progress_parser and progress_callback:
                    prog = progress_parser.parse_line(line)
                    if prog is not None:
                        progress_callback(prog)
            except Empty:
                break

        while not stderr_queue.empty():
            try:
                line_bytes = stderr_queue.get_nowait()
                line = line_bytes.decode("utf-8", errors="ignore")
                stderr_lines.append(line)
                if progress_parser and progress_callback:
                    prog = progress_parser.parse_line(line)
                    if prog is not None:
                        progress_callback(prog)
            except Empty:
                break

        stdout_str = redact_secrets("".join(stdout_lines))
        stderr_str = redact_secrets("".join(stderr_lines))

        return_code = proc.returncode
        if return_code != 0:
            raise ProcessExecutionError(
                message=f"Command exited with non-zero exit status {return_code}",
                command=spec.args,
                return_code=return_code,
                stdout=stdout_str,
                stderr=stderr_str,
            )

        return CommandResult(
            args=spec.args,
            return_code=return_code,
            stdout=stdout_str,
            stderr=redact_stderr_str if "redact_stderr_str" in locals() else stderr_str,
        )
