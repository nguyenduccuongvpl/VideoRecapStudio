"""Unit tests for the pipeline stage execution, orchestration, cancellation, retries, and resume planning."""

import time
from pathlib import Path
import pytest
from video_recap.application.pipeline import (
    CancellationToken,
    CheckpointPolicy,
    JobOrchestrator,
    PipelineDefinition,
    RetryPolicy,
    Stage,
    StageContext,
)
from video_recap.domain import Job, JobCancelledError, JobState, ProjectConfig, StageName
from video_recap.infrastructure.logging import InProcessEventBus
from video_recap.infrastructure.persistence import (
    DatabaseManager,
    FileSystemArtifactStore,
    FileSystemProjectRepository,
    SqliteCostRepository,
    SqliteJobRepository,
    SqliteProjectMetadataRepository,
    SqliteStageRunRepository,
)


class DummyStage(Stage):
    """A dummy pipeline stage for testing execution and errors."""

    def __init__(self, name: StageName, execute_fn=None) -> None:
        self._name = name
        self.execute_fn = execute_fn
        self.call_count = 0

    @property
    def name(self) -> StageName:
        return self._name

    def execute(self, context: StageContext) -> None:
        self.call_count += 1
        if self.execute_fn:
            self.execute_fn(context)


@pytest.fixture
def db_mgr(tmp_path: Path) -> DatabaseManager:
    """Setup a temporary in-memory database."""
    from video_recap.infrastructure.persistence import run_migrations

    db_path = tmp_path / "metadata.sqlite"
    mgr = DatabaseManager(db_path)
    run_migrations(mgr)
    return mgr


@pytest.fixture
def stage_context(db_mgr: DatabaseManager, tmp_path: Path) -> StageContext:
    """Construct a StageContext fixture with mock databases and repositories."""
    job_repo = SqliteJobRepository(db_mgr)
    proj_meta_repo = SqliteProjectMetadataRepository(db_mgr)
    stage_run_repo = SqliteStageRunRepository(db_mgr)
    cost_repo = SqliteCostRepository(db_mgr)

    project_repo = FileSystemProjectRepository(tmp_path / "projects")
    artifact_store = FileSystemArtifactStore(tmp_path / "projects")

    # Initialize projects
    project_id = "test_project"
    video_src = tmp_path / "dummy.mp4"
    video_src.write_text("dummy contents")
    project_repo.initialize_project(project_id, str(video_src), copy_mode=True)

    config = ProjectConfig(
        project_id=project_id,
        source_video_path=str(video_src),
        output_directory=str(tmp_path / "projects" / project_id),
        preset_name="balanced_movie_vi",
        target_recap_duration=300.0,
        voice_name="hoaimy",
        api_keys={},
    )
    proj_meta_repo.save_project_config(project_id, config)

    cancellation_token = CancellationToken()
    event_bus = InProcessEventBus()

    return StageContext(
        job_id="test_job",
        project_id=project_id,
        config=config,
        artifact_store=artifact_store,
        project_repo=project_repo,
        job_repo=job_repo,
        stage_run_repo=stage_run_repo,
        cost_repo=cost_repo,
        event_bus=event_bus,
        cancellation_token=cancellation_token,
    )


def test_transition_whitelist(stage_context: StageContext) -> None:
    """Verify that JobOrchestrator rejects invalid state transitions."""
    job = Job(job_id="job_1", project_id="test_project", state=JobState.CREATED)
    stage_context.job_repo.create_job(job)

    orchestrator = JobOrchestrator(PipelineDefinition([]))

    # Allowed: CREATED -> VALIDATING
    orchestrator._transition_job_state(job, JobState.VALIDATING, stage_context)
    assert job.state == JobState.VALIDATING

    # Disallowed: VALIDATING -> COMPLETED directly
    with pytest.raises(ValueError) as exc_info:
        orchestrator._transition_job_state(job, JobState.COMPLETED, stage_context)
    assert "Invalid job state transition" in str(exc_info.value)


def test_successful_pipeline_execution(stage_context: StageContext) -> None:
    """Verify happy-path execution of a pipeline with multiple stages."""
    # Create job in database
    job = Job(job_id="test_job", project_id="test_project", state=JobState.CREATED)
    stage_context.job_repo.create_job(job)

    # Build stage pipeline
    stage_1 = DummyStage(StageName.VALIDATING)
    stage_2 = DummyStage(StageName.INGESTING)
    pipeline = PipelineDefinition([stage_1, stage_2])

    orchestrator = JobOrchestrator(pipeline)
    orchestrator.execute_job(job, stage_context)

    # Check status transitions and calls
    assert stage_1.call_count == 1
    assert stage_2.call_count == 1
    assert job.state == JobState.COMPLETED

    # Check database records
    db_job = stage_context.job_repo.get_job("test_job")
    assert db_job is not None
    assert db_job.state == JobState.COMPLETED

    runs = stage_context.stage_run_repo.get_stage_runs("test_job")
    assert len(runs) == 2
    runs_map = {r.stage_name: r for r in runs}
    assert "VALIDATING" in runs_map
    assert runs_map["VALIDATING"].status == "SUCCESS"
    assert "INGESTING" in runs_map
    assert runs_map["INGESTING"].status == "SUCCESS"


def test_cooperative_cancellation(stage_context: StageContext) -> None:
    """Verify that cancelling the token interrupts execution and marks CANCELLED."""
    job = Job(job_id="test_job", project_id="test_project", state=JobState.CREATED)
    stage_context.job_repo.create_job(job)

    def cancel_execution(context: StageContext) -> None:
        # Trigger cancellation during first stage execution
        context.cancellation_token.cancel()

    stage_1 = DummyStage(StageName.VALIDATING, execute_fn=cancel_execution)
    stage_2 = DummyStage(StageName.INGESTING)
    pipeline = PipelineDefinition([stage_1, stage_2])

    orchestrator = JobOrchestrator(pipeline)

    with pytest.raises(JobCancelledError):
        orchestrator.execute_job(job, stage_context)

    assert stage_1.call_count == 1
    assert stage_2.call_count == 0  # Cancelled before stage 2
    assert job.state == JobState.CANCELLED

    # Check database state
    db_job = stage_context.job_repo.get_job("test_job")
    assert db_job is not None
    assert db_job.state == JobState.CANCELLED


def test_retry_policy_on_recoverable_error(stage_context: StageContext) -> None:
    """Verify that a stage retries on recoverable exceptions before failing."""
    job = Job(job_id="test_job", project_id="test_project", state=JobState.CREATED)
    stage_context.job_repo.create_job(job)

    def fail_with_rate_limit(context: StageContext) -> None:
        raise RuntimeError("API Rate Limit Exceeded")

    stage_1 = DummyStage(StageName.VALIDATING, execute_fn=fail_with_rate_limit)
    pipeline = PipelineDefinition([stage_1])

    # Faster retry interval for testing
    retry_policy = RetryPolicy(max_attempts=2, backoff_factor=0.01)
    orchestrator = JobOrchestrator(pipeline, retry_policy=retry_policy)

    with pytest.raises(RuntimeError) as exc_info:
        orchestrator.execute_job(job, stage_context)

    assert "API Rate Limit" in str(exc_info.value)
    # Stage should run exactly 3 times (1 initial + 2 retries)
    assert stage_1.call_count == 3
    assert job.state == JobState.FAILED


def test_immediate_failure_on_permanent_error(stage_context: StageContext) -> None:
    """Verify that permanent errors immediately fail without retry."""
    job = Job(job_id="test_job", project_id="test_project", state=JobState.CREATED)
    stage_context.job_repo.create_job(job)

    def fail_permanent(context: StageContext) -> None:
        raise ValueError("Permanent configuration error")

    stage_1 = DummyStage(StageName.VALIDATING, execute_fn=fail_permanent)
    pipeline = PipelineDefinition([stage_1])

    retry_policy = RetryPolicy(max_attempts=5, backoff_factor=0.01)
    orchestrator = JobOrchestrator(pipeline, retry_policy=retry_policy)

    with pytest.raises(ValueError):
        orchestrator.execute_job(job, stage_context)

    assert stage_1.call_count == 1  # Should fail immediately
    assert job.state == JobState.FAILED


def test_preview_validation_fails_transitions_to_needs_review(stage_context: StageContext) -> None:
    """Verify that VALIDATING_PREVIEW failures transition job to NEEDS_REVIEW state."""
    job = Job(job_id="test_job", project_id="test_project", state=JobState.CREATED)
    stage_context.job_repo.create_job(job)

    # Force transition job state sequentially to VALIDATING_PREVIEW first to bypass whitelist
    orchestrator = JobOrchestrator(PipelineDefinition([]))
    orchestrator._transition_job_state(job, JobState.VALIDATING, stage_context)
    orchestrator._transition_job_state(job, JobState.INGESTING, stage_context)
    orchestrator._transition_job_state(job, JobState.TRANSCRIBING, stage_context)
    orchestrator._transition_job_state(job, JobState.DETECTING_SHOTS, stage_context)
    orchestrator._transition_job_state(job, JobState.OBSERVING, stage_context)
    orchestrator._transition_job_state(job, JobState.BUILDING_EVENTS, stage_context)
    orchestrator._transition_job_state(job, JobState.PLANNING_STORY, stage_context)
    orchestrator._transition_job_state(job, JobState.WRITING_NARRATION, stage_context)
    orchestrator._transition_job_state(job, JobState.PLANNING_TIMELINE, stage_context)
    orchestrator._transition_job_state(job, JobState.GENERATING_SPEECH, stage_context)
    orchestrator._transition_job_state(job, JobState.RENDERING_PREVIEW, stage_context)

    # Execute VALIDATING_PREVIEW stage which fails
    def fail_qa(context: StageContext) -> None:
        raise ValueError("QA threshold not met")

    stage = DummyStage(StageName.VALIDATING_PREVIEW, execute_fn=fail_qa)
    pipeline = PipelineDefinition([stage])

    orchestrator = JobOrchestrator(pipeline)

    with pytest.raises(ValueError):
        orchestrator.execute_job(job, stage_context)

    # Validating preview stage failed -> transitioned to NEEDS_REVIEW
    assert job.state == JobState.NEEDS_REVIEW


def test_plan_resume_logic(stage_context: StageContext) -> None:
    """Verify resume planning checks and stale artifact skip/execution planning."""
    job = Job(job_id="test_job", project_id="test_project", state=JobState.CREATED)
    stage_context.job_repo.create_job(job)

    stage_1 = DummyStage(StageName.VALIDATING)
    stage_2 = DummyStage(StageName.INGESTING)
    pipeline = PipelineDefinition([stage_1, stage_2])

    orchestrator = JobOrchestrator(pipeline)

    # 1. No stage runs completed -> runs all
    remaining = orchestrator.plan_resume("test_job", stage_context)
    assert remaining == [StageName.VALIDATING, StageName.INGESTING]

    # 2. Complete VALIDATING stage
    stage_context.stage_run_repo.record_stage_start(stage_context.job_id, StageName.VALIDATING, "2026-07-14")
    checkpoint = CheckpointPolicy()
    checkpoint.record_checkpoint(stage_context, StageName.VALIDATING, "2026-07-14")

    # Save artifact to prevent stale detection triggering resume
    from video_recap.domain import BaseArtifact
    artifact = BaseArtifact(schema_version="1.0.0", producer_stage=StageName.VALIDATING, input_hashes={})
    stage_context.artifact_store.save_json(
        stage_context.project_id, "validating", "validating_artifact.json", artifact, input_hashes={}
    )

    # Now should resume from INGESTING
    remaining_resumed = orchestrator.plan_resume("test_job", stage_context)
    assert remaining_resumed == [StageName.INGESTING]
