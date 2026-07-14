"""Subprocess command specifications and results domain models."""

from typing import Dict, List, Optional
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
