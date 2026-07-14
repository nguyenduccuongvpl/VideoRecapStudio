"""SQLite repository implementations mapping raw database rows to Pydantic Domain models."""

from typing import List, Optional
from video_recap.application.repository import (
    CostRepository,
    JobRepository,
    ProjectMetadataRepository,
    StageRunRepository,
)
from video_recap.domain import CostRecord, Job, JobState, ProjectConfig, StageName, StageResult
from video_recap.infrastructure.persistence.sqlite_db import DatabaseManager


class SqliteProjectMetadataRepository(ProjectMetadataRepository):
    """SQLite implementation for ProjectMetadataRepository."""

    def __init__(self, db_mgr: DatabaseManager) -> None:
        """Initialize repository.

        Args:
            db_mgr: DatabaseManager instance.
        """
        self.db_mgr = db_mgr

    def save_project_config(self, project_id: str, config: ProjectConfig) -> None:
        """Save project configuration to database (upsert).

        Note: API keys are secrets and are NOT persisted to the database.
        """
        sql = """
            INSERT INTO projects (
                project_id, source_video_path, output_directory, preset_name, 
                target_recap_duration, voice_name
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                source_video_path=excluded.source_video_path,
                output_directory=excluded.output_directory,
                preset_name=excluded.preset_name,
                target_recap_duration=excluded.target_recap_duration,
                voice_name=excluded.voice_name
        """
        with self.db_mgr.transaction() as conn:
            conn.execute(
                sql,
                (
                    project_id,
                    config.source_video_path,
                    config.output_directory,
                    config.preset_name,
                    config.target_recap_duration,
                    config.voice_name,
                ),
            )

    def get_project_config(self, project_id: str) -> Optional[ProjectConfig]:
        """Load project configuration from database."""
        sql = """
            SELECT project_id, source_video_path, output_directory, preset_name, 
                   target_recap_duration, voice_name 
            FROM projects WHERE project_id = ?
        """
        with self.db_mgr.connection() as conn:
            cursor = conn.execute(sql, (project_id,))
            row = cursor.fetchone()

        if row is None:
            return None

        # Reconstruct ProjectConfig with empty api_keys for security
        return ProjectConfig(
            project_id=row["project_id"],
            source_video_path=row["source_video_path"],
            output_directory=row["output_directory"],
            preset_name=row["preset_name"],
            target_recap_duration=row["target_recap_duration"],
            voice_name=row["voice_name"],
            api_keys={},
        )


class SqliteJobRepository(JobRepository):
    """SQLite implementation for JobRepository."""

    def __init__(self, db_mgr: DatabaseManager) -> None:
        """Initialize repository.

        Args:
            db_mgr: DatabaseManager instance.
        """
        self.db_mgr = db_mgr

    def create_job(self, job: Job) -> None:
        """Create a new job record."""
        sql = """
            INSERT INTO jobs (job_id, project_id, state, current_stage, error_details)
            VALUES (?, ?, ?, ?, ?)
        """
        with self.db_mgr.transaction() as conn:
            conn.execute(
                sql,
                (
                    job.job_id,
                    job.project_id,
                    job.state.value,
                    job.current_stage.value if job.current_stage else None,
                    job.error_details,
                ),
            )

    def update_job_state(
        self,
        job_id: str,
        state: JobState,
        current_stage: Optional[StageName] = None,
        error_details: Optional[str] = None,
    ) -> None:
        """Update job status and progress."""
        sql = """
            UPDATE jobs 
            SET state = ?, current_stage = ?, error_details = ?
            WHERE job_id = ?
        """
        with self.db_mgr.transaction() as conn:
            conn.execute(
                sql,
                (
                    state.value,
                    current_stage.value if current_stage else None,
                    error_details,
                    job_id,
                ),
            )

    def get_job(self, job_id: str) -> Optional[Job]:
        """Fetch job details from database."""
        sql = "SELECT job_id, project_id, state, current_stage, error_details FROM jobs WHERE job_id = ?"
        with self.db_mgr.connection() as conn:
            cursor = conn.execute(sql, (job_id,))
            row = cursor.fetchone()

        if row is None:
            return None

        current_stage_val = row["current_stage"]
        stage = StageName(current_stage_val) if current_stage_val else None

        return Job(
            job_id=row["job_id"],
            project_id=row["project_id"],
            state=JobState(row["state"]),
            current_stage=stage,
            error_details=row["error_details"],
        )


class SqliteStageRunRepository(StageRunRepository):
    """SQLite implementation for StageRunRepository."""

    def __init__(self, db_mgr: DatabaseManager) -> None:
        """Initialize repository.

        Args:
            db_mgr: DatabaseManager instance.
        """
        self.db_mgr = db_mgr

    def record_stage_start(self, job_id: str, stage_name: StageName, started_at: str) -> None:
        """Record the start of a pipeline stage execution."""
        sql = """
            INSERT INTO stage_runs (job_id, stage_name, status, started_at, completed_at, error_message)
            VALUES (?, ?, 'RUNNING', ?, '', NULL)
            ON CONFLICT(job_id, stage_name) DO UPDATE SET
                status='RUNNING',
                started_at=excluded.started_at,
                completed_at='',
                error_message=NULL
        """
        with self.db_mgr.transaction() as conn:
            conn.execute(sql, (job_id, stage_name.value, started_at))

    def record_stage_complete(
        self,
        job_id: str,
        stage_name: StageName,
        status: str,
        completed_at: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Record the completion of a pipeline stage execution."""
        sql = """
            UPDATE stage_runs 
            SET status = ?, completed_at = ?, error_message = ?
            WHERE job_id = ? AND stage_name = ?
        """
        with self.db_mgr.transaction() as conn:
            conn.execute(sql, (status, completed_at, error_message, job_id, stage_name.value))

    def get_stage_runs(self, job_id: str) -> List[StageResult]:
        """Get all stage run records for a job."""
        sql = """
            SELECT stage_name, status, started_at, completed_at, error_message 
            FROM stage_runs WHERE job_id = ?
        """
        with self.db_mgr.connection() as conn:
            cursor = conn.execute(sql, (job_id,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append(
                StageResult(
                    stage_name=r["stage_name"],
                    status=r["status"],
                    started_at=r["started_at"],
                    completed_at=r["completed_at"],
                    error_message=r["error_message"],
                )
            )
        return results

    def get_last_successful_stage(self, job_id: str) -> Optional[StageName]:
        """Find the last pipeline stage that completed successfully (ordered by timestamp)."""
        sql = """
            SELECT stage_name FROM stage_runs 
            WHERE job_id = ? AND status = 'SUCCESS' 
            ORDER BY completed_at DESC LIMIT 1
        """
        with self.db_mgr.connection() as conn:
            cursor = conn.execute(sql, (job_id,))
            row = cursor.fetchone()

        if row is None:
            return None

        return StageName(row["stage_name"])


class SqliteCostRepository(CostRepository):
    """SQLite implementation for CostRepository."""

    def __init__(self, db_mgr: DatabaseManager) -> None:
        """Initialize repository.

        Args:
            db_mgr: DatabaseManager instance.
        """
        self.db_mgr = db_mgr

    def record_cost(self, job_id: str, cost: CostRecord) -> None:
        """Record a single provider API call cost record."""
        sql = """
            INSERT INTO cost_records (job_id, service_name, cost_usd, request_count, input_tokens, output_tokens)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        with self.db_mgr.transaction() as conn:
            conn.execute(
                sql,
                (
                    job_id,
                    cost.service_name,
                    cost.cost_usd,
                    cost.request_count,
                    cost.input_tokens,
                    cost.output_tokens,
                ),
            )

    def get_total_costs(self, job_id: str) -> List[CostRecord]:
        """Get all cost records recorded for a job."""
        sql = """
            SELECT service_name, cost_usd, request_count, input_tokens, output_tokens 
            FROM cost_records WHERE job_id = ?
        """
        with self.db_mgr.connection() as conn:
            cursor = conn.execute(sql, (job_id,))
            rows = cursor.fetchall()

        results = []
        for r in rows:
            results.append(
                CostRecord(
                    service_name=r["service_name"],
                    cost_usd=r["cost_usd"],
                    request_count=r["request_count"],
                    input_tokens=r["input_tokens"],
                    output_tokens=r["output_tokens"],
                )
            )
        return results
