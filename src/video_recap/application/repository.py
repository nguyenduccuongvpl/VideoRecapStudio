"""Protocols for metadata persistence repositories in the database layer."""

from typing import List, Optional, Protocol
from video_recap.domain import CostRecord, Job, JobState, ProjectConfig, StageName, StageResult


class ProjectMetadataRepository(Protocol):
    """Protocol for saving and loading project configurations in database."""

    def save_project_config(self, project_id: str, config: ProjectConfig) -> None:
        """Save project configuration to database (upsert).

        Args:
            project_id: The project identifier.
            config: ProjectConfig domain model.
        """
        ...

    def get_project_config(self, project_id: str) -> Optional[ProjectConfig]:
        """Load project configuration from database.

        Args:
            project_id: The project identifier.

        Returns:
            The ProjectConfig domain model, or None if not found.
        """
        ...


class JobRepository(Protocol):
    """Protocol for managing job lifecycle and execution state in database."""

    def create_job(self, job: Job) -> None:
        """Create a new job record.

        Args:
            job: The Job domain model.
        """
        ...

    def update_job_state(
        self,
        job_id: str,
        state: JobState,
        current_stage: Optional[StageName] = None,
        error_details: Optional[str] = None,
    ) -> None:
        """Update job status and progress.

        Args:
            job_id: The job identifier.
            state: The new JobState.
            current_stage: The active pipeline stage name.
            error_details: Error context if state is FAILED.
        """
        ...

    def get_job(self, job_id: str) -> Optional[Job]:
        """Fetch job details from database.

        Args:
            job_id: The job identifier.

        Returns:
            The Job domain model, or None if not found.
        """
        ...


class StageRunRepository(Protocol):
    """Protocol for logging pipeline stage executions and resume logic."""

    def record_stage_start(self, job_id: str, stage_name: StageName, started_at: str) -> None:
        """Record the start of a pipeline stage execution.

        Args:
            job_id: The execution job identifier.
            stage_name: Name of the stage.
            started_at: UTC timestamp.
        """
        ...

    def record_stage_complete(
        self,
        job_id: str,
        stage_name: StageName,
        status: str,
        completed_at: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Record the completion of a pipeline stage execution.

        Args:
            job_id: The execution job identifier.
            stage_name: Name of the stage.
            status: Status result (SUCCESS, FAILED, SKIPPED).
            completed_at: UTC timestamp.
            error_message: Optional error message if status is FAILED.
        """
        ...

    def get_stage_runs(self, job_id: str) -> List[StageResult]:
        """Get all stage run records for a job.

        Args:
            job_id: The execution job identifier.

        Returns:
            List of StageResult domain models.
        """
        ...

    def get_last_successful_stage(self, job_id: str) -> Optional[StageName]:
        """Find the last pipeline stage that completed successfully.

        Useful for determining the resume point.

        Args:
            job_id: The execution job identifier.

        Returns:
            The StageName of the last successful stage, or None if none succeeded.
        """
        ...


class CostRepository(Protocol):
    """Protocol for logging model API costs."""

    def record_cost(self, job_id: str, cost: CostRecord) -> None:
        """Record a single provider API call cost record.

        Args:
            job_id: The execution job identifier.
            cost: CostRecord domain model.
        """
        ...

    def get_total_costs(self, job_id: str) -> List[CostRecord]:
        """Get all cost records recorded for a job.

        Args:
            job_id: The execution job identifier.

        Returns:
            List of CostRecord domain models.
        """
        ...
