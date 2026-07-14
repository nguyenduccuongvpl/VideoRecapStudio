"""Logging handlers, context propagation, secret redaction, and diagnostic bundling."""

import datetime
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

# --- Thread-local Context Storage ---

_local_context = threading.local()


def get_log_context() -> dict:
    """Retrieve thread-local logging context dictionary."""
    if not hasattr(_local_context, "data"):
        _local_context.data = {}
    return _local_context.data


@contextmanager
def log_context(
    job_id: str | None = None,
    project_id: str | None = None,
    stage: str | None = None,
    operation: str | None = None,
    provider_request_id: str | None = None,
) -> Generator[None, None, None]:
    """Context manager to propagate log metadata fields down the execution tree."""
    ctx = get_log_context()
    original = ctx.copy()

    if job_id is not None:
        ctx["job_id"] = job_id
    if project_id is not None:
        ctx["project_id"] = project_id
    if stage is not None:
        ctx["stage"] = stage
    if operation is not None:
        ctx["operation"] = operation
    if provider_request_id is not None:
        ctx["provider_request_id"] = provider_request_id

    try:
        yield
    finally:
        _local_context.data = original


# --- Secret Redaction Filter ---

# Common API Key regex patterns
GEMINI_KEY_RE = re.compile(r"AIzaSy[a-zA-Z0-9_\-]{30,40}")
OPENAI_KEY_RE = re.compile(r"sk-[a-zA-Z0-9_\-]{30,50}")


def redact_secrets(text: str) -> str:
    """Scan and redact known API secrets from message strings."""
    if not isinstance(text, str):
        return text
    text = GEMINI_KEY_RE.sub("**********", text)
    text = OPENAI_KEY_RE.sub("**********", text)
    return text


class SecretRedactionFilter(logging.Filter):
    """Logging filter that automatically redacts API keys in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            # Redact args if formatting is applied
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(redact_secrets(arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)
        return True


# --- JSON Log Handler ---


class JSONLogHandler(logging.StreamHandler):
    """Outputs structured logs as single-line JSON records."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ctx = get_log_context()

            # Format timestamp
            timestamp = datetime.datetime.fromtimestamp(
                record.created, datetime.timezone.utc
            ).isoformat()

            # Compile log payload
            payload: dict = {
                "timestamp": timestamp,
                "level": record.levelname,
                "job_id": ctx.get("job_id"),
                "project_id": ctx.get("project_id"),
                "stage": ctx.get("stage"),
                "operation": ctx.get("operation"),
                "message": record.getMessage(),
                "error_code": getattr(record, "error_code", None),
                "provider_request_id": ctx.get("provider_request_id"),
            }

            # If there's an exception, attach traceback details
            if record.exc_info:
                import traceback
                payload["exception"] = "".join(traceback.format_exception(*record.exc_info))

            self.stream.write(json.dumps(payload) + "\n")
            self.flush()
        except Exception:
            self.handleError(record)


# --- Human Console Handler ---


class HumanConsoleHandler(logging.StreamHandler):
    """Outputs pretty human-readable log logs to stdout/stderr."""

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_log_context()
        timestamp = datetime.datetime.fromtimestamp(
            record.created, datetime.timezone.utc
        ).strftime("%H:%M:%S")

        level = record.levelname
        stage = ctx.get("stage", "")
        op = ctx.get("operation", "")

        stage_prefix = f" [{stage}:{op}]" if (stage or op) else ""
        msg = record.getMessage()

        exc = ""
        if record.exc_info:
            import traceback
            exc = f"\n" + "".join(traceback.format_exception(*record.exc_info))

        return f"[{timestamp}] [{level}]{stage_prefix} {msg}{exc}"


# --- Sanitized Diagnostic Bundle Service ---


class DiagnosticBundleService:
    """Creates a zip archive of logs, stripping out any secrets first."""

    def create_bundle(self, logs_dir: Path, output_zip_path: Path) -> Path:
        """Collect logs, redact secrets from them, and zip them.

        Args:
            logs_dir: The source directory containing active log files.
            output_zip_path: Destination path for the generated zip bundle.

        Returns:
            The Path to the created zip bundle.
        """
        output_zip_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            # Copy logs to temporary space while redacting keys line-by-line
            if logs_dir.exists():
                for log_file in logs_dir.glob("*.log"):
                    dest_file = temp_dir / log_file.name
                    with open(log_file, "r", encoding="utf-8", errors="ignore") as f_in:
                        with open(dest_file, "w", encoding="utf-8") as f_out:
                            for line in f_in:
                                f_out.write(redact_secrets(line))

            # Zip the temporary directory
            with zipfile.ZipFile(output_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_f:
                for file_path in temp_dir.glob("*"):
                    zip_f.write(file_path, arcname=file_path.name)

        return output_zip_path
