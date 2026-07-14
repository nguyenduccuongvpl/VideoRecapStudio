"""Domain event definitions and logging context models."""

from typing import List, Optional
from pydantic import BaseModel, Field
from video_recap.domain.models import JobState, StageName


class LogContext(BaseModel):
    """Contextual fields injected into every log message."""

    job_id: Optional[str] = None
    project_id: Optional[str] = None
    stage: Optional[str] = None
    operation: Optional[str] = None
    provider_request_id: Optional[str] = None


class ProgressEvent(BaseModel):
    """Event triggered for generic pipeline progress updates."""

    job_id: str
    project_id: str
    progress: float = Field(..., ge=0.0, le=1.0, description="Progress from 0.0 to 1.0")
    message: str


class StageStarted(BaseModel):
    """Event triggered when a pipeline stage begins execution."""

    job_id: str
    project_id: str
    stage: StageName
    started_at: str


class StageProgress(BaseModel):
    """Event triggered to track detailed progress inside a stage."""

    job_id: str
    project_id: str
    stage: StageName
    progress: float = Field(..., ge=0.0, le=1.0, description="Progress from 0.0 to 1.0")
    message: str
    timestamp: str


class StageCompleted(BaseModel):
    """Event triggered when a pipeline stage completes successfully."""

    job_id: str
    project_id: str
    stage: StageName
    completed_at: str
    status: str = "SUCCESS"


class StageFailed(BaseModel):
    """Event triggered when a pipeline stage fails execution."""

    job_id: str
    project_id: str
    stage: StageName
    failed_at: str
    error_code: str
    error_message: str
    stack_trace: Optional[str] = None


class JobStateChanged(BaseModel):
    """Event triggered when a top-level job state changes."""

    job_id: str
    project_id: str
    old_state: JobState
    new_state: JobState
    timestamp: str


class UserActionRequired(BaseModel):
    """Event triggered when execution pauses and requires manual review."""

    job_id: str
    project_id: str
    stage: StageName
    action_type: str  # e.g., "NEEDS_REVIEW", "CORRECTION"
    prompt_message: str
    options: List[str]
