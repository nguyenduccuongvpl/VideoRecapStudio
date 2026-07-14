"""Pipeline stage protocols, contexts, orchestrator, and resume policies."""

import datetime
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Type, TypeVar
from pydantic import BaseModel
from video_recap.application.events import EventPublisher
from video_recap.application.repository import (
    CostRepository,
    JobRepository,
    ProjectMetadataRepository,
    StageRunRepository,
)
from video_recap.application.workspace import ArtifactStore, ProjectRepository as ProjectRepoPort
from video_recap.domain import (
    Job,
    JobCancelledError,
    JobState,
    ProjectConfig,
    StageName,
    StageResult,
)
from video_recap.domain.events import JobStateChanged, StageCompleted, StageFailed, StageStarted

T = TypeVar("T", bound=BaseModel)
logger = logging.getLogger("Pipeline")


# --- State Transition Whitelist ---

TRANSITION_WHITELIST: Dict[JobState, Set[JobState]] = {
    JobState.CREATED: {JobState.VALIDATING, JobState.FAILED, JobState.CANCELLED},
    JobState.VALIDATING: {JobState.INGESTING, JobState.FAILED, JobState.CANCELLED},
    JobState.INGESTING: {JobState.TRANSCRIBING, JobState.FAILED, JobState.CANCELLED},
    JobState.TRANSCRIBING: {JobState.DETECTING_SHOTS, JobState.FAILED, JobState.CANCELLED},
    JobState.DETECTING_SHOTS: {JobState.OBSERVING, JobState.FAILED, JobState.CANCELLED},
    JobState.OBSERVING: {JobState.BUILDING_EVENTS, JobState.FAILED, JobState.CANCELLED},
    JobState.BUILDING_EVENTS: {JobState.PLANNING_STORY, JobState.FAILED, JobState.CANCELLED},
    JobState.PLANNING_STORY: {JobState.WRITING_NARRATION, JobState.FAILED, JobState.CANCELLED},
    JobState.WRITING_NARRATION: {JobState.PLANNING_TIMELINE, JobState.FAILED, JobState.CANCELLED},
    JobState.PLANNING_TIMELINE: {JobState.GENERATING_SPEECH, JobState.FAILED, JobState.CANCELLED},
    JobState.GENERATING_SPEECH: {JobState.RENDERING_PREVIEW, JobState.FAILED, JobState.CANCELLED},
    JobState.RENDERING_PREVIEW: {JobState.VALIDATING_PREVIEW, JobState.FAILED, JobState.CANCELLED},
    JobState.VALIDATING_PREVIEW: {
        JobState.NEEDS_REVIEW,
        JobState.RENDERING_FINAL,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    JobState.NEEDS_REVIEW: {
        JobState.PLANNING_STORY,
        JobState.WRITING_NARRATION,
        JobState.PLANNING_TIMELINE,
        JobState.RENDERING_FINAL,
        JobState.FAILED,
        JobState.CANCELLED,
    },
    JobState.RENDERING_FINAL: {JobState.VALIDATING_FINAL, JobState.FAILED, JobState.CANCELLED},
    JobState.VALIDATING_FINAL: {JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED},
    JobState.COMPLETED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}

# --- Cooperative Cancellation Token ---


class CancellationToken:
    """Token to signal cooperative cancellation across threads and pipeline stages."""

    def __init__(self) -> None:
        self._is_cancelled = False
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Signal cancellation."""
        with self._lock:
            self._is_cancelled = True

    def is_cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        with self._lock:
            return self._is_cancelled

    def raise_if_cancelled(self) -> None:
        """Raise JobCancelledError if cancellation was requested."""
        if self.is_cancelled():
            raise JobCancelledError("Job execution was cooperatively cancelled.")


# --- Stage Context ---


class StageContext:
    """Unified runtime context passed to every pipeline stage."""

    def __init__(
        self,
        job_id: str,
        project_id: str,
        config: ProjectConfig,
        artifact_store: ArtifactStore,
        project_repo: ProjectRepoPort,
        job_repo: JobRepository,
        stage_run_repo: StageRunRepository,
        cost_repo: CostRepository,
        event_bus: EventPublisher,
        cancellation_token: CancellationToken,
    ) -> None:
        self.job_id = job_id
        self.project_id = project_id
        self.config = config
        self.artifact_store = artifact_store
        self.project_repo = project_repo
        self.job_repo = job_repo
        self.stage_run_repo = stage_run_repo
        self.cost_repo = cost_repo
        self.event_bus = event_bus
        self.cancellation_token = cancellation_token


# --- Stage Protocol ---


class Stage(Protocol):
    """Protocol defining a single pipeline stage execution block."""

    @property
    def name(self) -> StageName:
        """The logical StageName of this block."""
        ...

    def execute(self, context: StageContext) -> None:
        """Execute the stage work.

        Args:
            context: Runtime StageContext with ports and cancellation.
        """
        ...


# --- Policies ---


class RetryPolicy:
    """Determines whether transient errors should trigger retries."""

    def __init__(self, max_attempts: int = 3, backoff_factor: float = 0.5) -> None:
        self.max_attempts = max_attempts
        self.backoff_factor = backoff_factor

    def is_recoverable(self, exception: Exception) -> bool:
        """Determine if an exception is transient/recoverable."""
        # RateLimitError, connection errors, or simulated transient exceptions
        msg = str(exception).lower()
        if "rate limit" in msg or "timeout" in msg or "transient" in msg:
            return True
        return False

    def wait_time(self, attempt: int) -> float:
        """Calculate wait time with backoff."""
        return self.backoff_factor * (2 ** (attempt - 1))


class CheckpointPolicy:
    """Manages recording successful checkpoints to the metadata store."""

    def record_checkpoint(
        self, context: StageContext, stage_name: StageName, started_at: str
    ) -> None:
        """Record a successful checkpoint of a stage execution in database."""
        completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        context.stage_run_repo.record_stage_complete(
            job_id=context.job_id,
            stage_name=stage_name,
            status="SUCCESS",
            completed_at=completed_at,
        )
        context.event_bus.publish(
            StageCompleted(
                job_id=context.job_id,
                project_id=context.project_id,
                stage=stage_name,
                completed_at=completed_at,
            )
        )


# --- Pipeline Definition ---


class PipelineDefinition:
    """Defines the order of stages in the execution pipeline."""

    def __init__(self, stages: List[Stage]) -> None:
        self.stages = stages
        self._stage_map = {s.name: s for s in stages}

    def get_stage(self, name: StageName) -> Optional[Stage]:
        """Fetch Stage implementation by name."""
        return self._stage_map.get(name)

    @property
    def stage_names(self) -> List[StageName]:
        """Ordered list of stages in this pipeline."""
        return [s.name for s in self.stages]


# --- Job Orchestrator ---


class JobOrchestrator:
    """Coordinates execution of the pipeline stages, state transitions, and resume logic."""

    def __init__(
        self,
        pipeline: PipelineDefinition,
        retry_policy: Optional[RetryPolicy] = None,
        checkpoint_policy: Optional[CheckpointPolicy] = None,
    ) -> None:
        self.pipeline = pipeline
        self.retry_policy = retry_policy or RetryPolicy()
        self.checkpoint_policy = checkpoint_policy or CheckpointPolicy()

    def _transition_job_state(
        self, job: Job, new_state: JobState, context: StageContext, force: bool = False
    ) -> None:
        """Safely transition job status verifying against whitelist."""
        old_state = job.state
        allowed = TRANSITION_WHITELIST.get(old_state, set())

        if not force and new_state not in allowed:
            raise ValueError(
                f"Invalid job state transition: cannot transition from {old_state} to {new_state}"
            )

        job.state = new_state
        context.job_repo.update_job_state(job.job_id, new_state, job.current_stage)
        context.event_bus.publish(
            JobStateChanged(
                job_id=job.job_id,
                project_id=job.project_id,
                old_state=old_state,
                new_state=new_state,
                timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            )
        )

    def plan_resume(self, job_id: str, context: StageContext) -> List[StageName]:
        """Identify which stages must be run/rerun.

        Stale detection:
          - If a stage is not logged as SUCCESS, start from there.
          - If a stage is SUCCESS, check its artifact inputs. If changed (stale),
            invalidate all downstream stages and resume from here.

        Args:
            job_id: ID of the execution job.
            context: Runtime context.

        Returns:
            List of StageNames remaining to be executed.
        """
        stage_runs = {run.stage_name: run for run in context.stage_run_repo.get_stage_runs(job_id)}
        resume_index = 0

        # Scan stages sequentially to find the first incomplete or stale stage
        for i, stage_name in enumerate(self.pipeline.stage_names):
            run = stage_runs.get(stage_name.value)
            if not run or run.status != "SUCCESS":
                resume_index = i
                break

            # Check if artifact exists and is stale
            # For simplicity, if we don't have explicit inputs for stale check yet,
            # we check the artifact metadata via is_stale in the artifact store.
            # We assume category matches the stage name in lowercase
            category = stage_name.value.lower()
            filename = f"{category}_artifact.json"  # standard naming convention

            # If the artifact is stale, we must resume from this stage
            # We pass empty dict as current hashes by default (meaning we rely on file existence)
            # but subclasses/usecases can override.
            if context.artifact_store.is_stale(
                context.project_id, category, filename, current_input_hashes={}
            ):
                resume_index = i
                break
        else:
            # All stages completed and fresh
            return []

        return self.pipeline.stage_names[resume_index:]

    def execute_job(self, job: Job, context: StageContext, resume: bool = False) -> None:
        """Run the pipeline stages for the given job.

        Args:
            job: The Job model.
            context: The StageContext.
            resume: If True, plan resume and execute remaining stages.
        """
        try:
            # Determine stages to run
            if resume:
                stages_to_run = self.plan_resume(job.job_id, context)
                if not stages_to_run:
                    logger.info(f"Job {job.job_id} is already up to date.")
                    return
            else:
                stages_to_run = self.pipeline.stage_names

            # We map StageName to JobState (mapping matches enum names)
            # StageName has corresponding state with same name
            for stage_name in stages_to_run:
                context.cancellation_token.raise_if_cancelled()

                stage_impl = self.pipeline.get_stage(stage_name)
                if not stage_impl:
                    raise ValueError(f"No implementation found for stage: {stage_name}")

                # Transition state to active stage state
                stage_state = JobState(stage_name.value)
                job.current_stage = stage_name
                self._transition_job_state(job, stage_state, context)

                started_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                context.stage_run_repo.record_stage_start(job.job_id, stage_name, started_at)
                context.event_bus.publish(
                    StageStarted(
                        job_id=job.job_id,
                        project_id=job.project_id,
                        stage=stage_name,
                        started_at=started_at,
                    )
                )

                # Execute stage with retry policy
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        context.cancellation_token.raise_if_cancelled()
                        stage_impl.execute(context)
                        break
                    except JobCancelledError as e:
                        # Transition to CANCELLED and raise
                        completed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        context.stage_run_repo.record_stage_complete(
                            job.job_id, stage_name, "CANCELLED", completed_at, str(e)
                        )
                        raise e
                    except Exception as e:
                        if self.retry_policy.is_recoverable(e) and attempt <= self.retry_policy.max_attempts:
                            wait = self.retry_policy.wait_time(attempt)
                            logger.warning(
                                f"Stage {stage_name.value} failed with recoverable error: {e}. "
                                f"Retrying in {wait} seconds (attempt {attempt}/{self.retry_policy.max_attempts})."
                            )
                            time.sleep(wait)
                            continue

                        # Permanent failure or max attempts reached
                        failed_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
                        context.stage_run_repo.record_stage_complete(
                            job.job_id, stage_name, "FAILED", failed_at, str(e)
                        )
                        context.event_bus.publish(
                            StageFailed(
                                job_id=job.job_id,
                                project_id=job.project_id,
                                stage=stage_name,
                                failed_at=failed_at,
                                error_code="E-STAGE-FAIL",
                                error_message=str(e),
                            )
                        )

                        # Determine if it should transition to NEEDS_REVIEW or FAILED
                        # Quality gate failure transitions to NEEDS_REVIEW, others to FAILED
                        # For simplicity, we check if the stage is VALIDATING_PREVIEW
                        if stage_name == StageName.VALIDATING_PREVIEW:
                            self._transition_job_state(job, JobState.NEEDS_REVIEW, context)
                        else:
                            self._transition_job_state(job, JobState.FAILED, context)
                        raise e

                # Record successful checkpoint
                self.checkpoint_policy.record_checkpoint(context, stage_name, started_at)

            # Transition job to COMPLETED
            self._transition_job_state(job, JobState.COMPLETED, context, force=True)
        except JobCancelledError as e:
            self._transition_job_state(job, JobState.CANCELLED, context, force=True)
            raise e
        except Exception as e:
            # Fallback for unhandled exceptions in the loop body
            if job.state not in (JobState.FAILED, JobState.NEEDS_REVIEW, JobState.CANCELLED):
                self._transition_job_state(job, JobState.FAILED, context, force=True)
            raise e
