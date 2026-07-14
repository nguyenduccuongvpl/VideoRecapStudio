"""Unit tests for SQLite database connection, transactions, migrations, and repositories."""

import sqlite3
from pathlib import Path
import pytest
from video_recap.domain import CostRecord, Job, JobState, ProjectConfig, StageName
from video_recap.infrastructure.persistence.sqlite_db import DatabaseManager, run_migrations
from video_recap.infrastructure.persistence.sqlite_repo import (
    SqliteCostRepository,
    SqliteJobRepository,
    SqliteProjectMetadataRepository,
    SqliteStageRunRepository,
)


@pytest.fixture
def db_mgr(tmp_path: Path) -> DatabaseManager:
    """Fixture that initializes DatabaseManager with auto-run migrations."""
    db_file = tmp_path / "test_metadata.sqlite"
    mgr = DatabaseManager(db_file)
    run_migrations(mgr)
    return mgr


def test_sqlite_migrations_execution(db_mgr: DatabaseManager) -> None:
    """Test that all tables are correctly created after migrations."""
    with db_mgr.connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_migrations'"
        )
        assert cursor.fetchone() is not None

        # Verify other tables exist
        for table in ["projects", "jobs", "stage_runs", "cost_records"]:
            cursor = conn.execute(
                f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'"
            )
            assert cursor.fetchone() is not None


def test_sqlite_transaction_rollback(db_mgr: DatabaseManager) -> None:
    """Test that failed transaction operations are rolled back completely."""
    repo = SqliteProjectMetadataRepository(db_mgr)
    config = ProjectConfig(
        project_id="proj_roll",
        source_video_path="v.mp4",
        output_directory="out",
        preset_name="balanced_movie_vi",
        target_recap_duration=300.0,
        voice_name="HoaiMy",
        api_keys={"openai": "secret-key-must-not-be-in-db"},
    )

    # 1. Successful save
    repo.save_project_config("proj_roll", config)
    assert repo.get_project_config("proj_roll") is not None

    # 2. Try an operation inside transaction that fails
    with pytest.raises(sqlite3.IntegrityError):
        with db_mgr.transaction() as conn:
            # Modify output directory successfully
            conn.execute(
                "UPDATE projects SET output_directory = 'new_out' WHERE project_id = 'proj_roll'"
            )
            # This will fail unique/non-null constraint
            conn.execute("INSERT INTO projects (project_id) VALUES (NULL)")

    # 3. Verify rollback: output_directory should STILL be 'out', not 'new_out'!
    proj = repo.get_project_config("proj_roll")
    assert proj is not None
    assert proj.output_directory == "out"


def test_project_metadata_repository_secret_exclusion(db_mgr: DatabaseManager) -> None:
    """Test saving/loading configs and verifying secrets are excluded from DB."""
    repo = SqliteProjectMetadataRepository(db_mgr)
    config = ProjectConfig(
        project_id="proj_01",
        source_video_path="input.mp4",
        output_directory="out",
        preset_name="balanced_movie_vi",
        target_recap_duration=300.0,
        voice_name="vi-VN-HoaiMy",
        api_keys={"gemini": "secret-gemini-key", "openai": "secret-openai-key"},
    )

    # Save config
    repo.save_project_config("proj_01", config)

    # Load config
    loaded = repo.get_project_config("proj_01")
    assert loaded is not None
    assert loaded.project_id == "proj_01"
    assert loaded.preset_name == "balanced_movie_vi"
    # Ensure api_keys dictionary is loaded empty (secrets excluded from database)
    assert len(loaded.api_keys) == 0

    # Ensure no secrets leak in projects table
    with db_mgr.connection() as conn:
        cursor = conn.execute("SELECT * FROM projects WHERE project_id = 'proj_01'")
        row = cursor.fetchone()
        for col in row.keys():
            assert "secret" not in str(row[col])


def test_job_repository_status_transitions(db_mgr: DatabaseManager) -> None:
    """Test job state transitions and querying in database."""
    proj_repo = SqliteProjectMetadataRepository(db_mgr)
    job_repo = SqliteJobRepository(db_mgr)

    # Create dummy project for foreign key constraints
    config = ProjectConfig(
        project_id="p_job",
        source_video_path="v.mp4",
        output_directory="out",
        preset_name="balanced",
        target_recap_duration=120.0,
        voice_name="HoaiMy",
        api_keys={},
    )
    proj_repo.save_project_config("p_job", config)

    # Create job
    job = Job(
        job_id="j_01",
        project_id="p_job",
        state=JobState.CREATED,
        current_stage=None,
    )
    job_repo.create_job(job)

    # Verify initial state
    loaded = job_repo.get_job("j_01")
    assert loaded is not None
    assert loaded.state == JobState.CREATED
    assert loaded.current_stage is None

    # Transition 1: CREATED -> VALIDATING
    job_repo.update_job_state("j_01", JobState.VALIDATING, StageName.VALIDATING)
    loaded = job_repo.get_job("j_01")
    assert loaded.state == JobState.VALIDATING
    assert loaded.current_stage == StageName.VALIDATING

    # Transition 2: VALIDATING -> INGESTING
    job_repo.update_job_state("j_01", JobState.INGESTING, StageName.INGESTING)
    loaded = job_repo.get_job("j_01")
    assert loaded.state == JobState.INGESTING
    assert loaded.current_stage == StageName.INGESTING

    # Transition 3: FAILED
    job_repo.update_job_state(
        "j_01", JobState.FAILED, StageName.INGESTING, error_details="Disk Full Error"
    )
    loaded = job_repo.get_job("j_01")
    assert loaded.state == JobState.FAILED
    assert loaded.error_details == "Disk Full Error"


def test_stage_run_repository_resume_logic(db_mgr: DatabaseManager) -> None:
    """Test logging stages and finding the last successful stage to resume."""
    proj_repo = SqliteProjectMetadataRepository(db_mgr)
    job_repo = SqliteJobRepository(db_mgr)
    stage_repo = SqliteStageRunRepository(db_mgr)

    # Set up project and job
    proj_config = ProjectConfig(
        project_id="p_stages",
        source_video_path="v.mp4",
        output_directory="out",
        preset_name="balanced",
        target_recap_duration=120.0,
        voice_name="HoaiMy",
        api_keys={},
    )
    proj_repo.save_project_config("p_stages", proj_config)
    job = Job(job_id="j_stages", project_id="p_stages", state=JobState.CREATED)
    job_repo.create_job(job)

    # Ensure no successful stage yet
    assert stage_repo.get_last_successful_stage("j_stages") is None

    # Run INGESTING stage - SUCCESS
    stage_repo.record_stage_start("j_stages", StageName.INGESTING, "2026-07-14T10:00:00Z")
    stage_repo.record_stage_complete(
        "j_stages", StageName.INGESTING, "SUCCESS", "2026-07-14T10:05:00Z"
    )
    assert stage_repo.get_last_successful_stage("j_stages") == StageName.INGESTING

    # Run TRANSCRIBING stage - SUCCESS
    stage_repo.record_stage_start("j_stages", StageName.TRANSCRIBING, "2026-07-14T10:06:00Z")
    stage_repo.record_stage_complete(
        "j_stages", StageName.TRANSCRIBING, "SUCCESS", "2026-07-14T10:10:00Z"
    )
    assert stage_repo.get_last_successful_stage("j_stages") == StageName.TRANSCRIBING

    # Run DETECTING_SHOTS stage - FAILED
    stage_repo.record_stage_start("j_stages", StageName.DETECTING_SHOTS, "2026-07-14T10:11:00Z")
    stage_repo.record_stage_complete(
        "j_stages",
        StageName.DETECTING_SHOTS,
        "FAILED",
        "2026-07-14T10:12:00Z",
        error_message="ffmpeg process crashed",
    )

    # Last successful stage should STILL be TRANSCRIBING!
    assert stage_repo.get_last_successful_stage("j_stages") == StageName.TRANSCRIBING

    # Verify stage_run list
    runs = stage_repo.get_stage_runs("j_stages")
    assert len(runs) == 3
    ingest_run = next(r for r in runs if r.stage_name == "INGESTING")
    assert ingest_run.status == "SUCCESS"
    assert ingest_run.completed_at == "2026-07-14T10:05:00Z"

    fail_run = next(r for r in runs if r.stage_name == "DETECTING_SHOTS")
    assert fail_run.status == "FAILED"
    assert fail_run.error_message == "ffmpeg process crashed"


def test_cost_repository_logging(db_mgr: DatabaseManager) -> None:
    """Test logging provider usage costs in database."""
    proj_repo = SqliteProjectMetadataRepository(db_mgr)
    job_repo = SqliteJobRepository(db_mgr)
    cost_repo = SqliteCostRepository(db_mgr)

    # Set up project and job
    proj_config = ProjectConfig(
        project_id="p_costs",
        source_video_path="v.mp4",
        output_directory="out",
        preset_name="balanced",
        target_recap_duration=120.0,
        voice_name="HoaiMy",
        api_keys={},
    )
    proj_repo.save_project_config("p_costs", proj_config)
    job = Job(job_id="j_costs", project_id="p_costs", state=JobState.CREATED)
    job_repo.create_job(job)

    # Add cost records
    c1 = CostRecord(
        service_name="Gemini-Pro-Vision",
        cost_usd=0.0125,
        request_count=1,
        input_tokens=1000,
        output_tokens=250,
    )
    c2 = CostRecord(
        service_name="Whisper-API",
        cost_usd=0.0060,
        request_count=1,
        input_tokens=0,
        output_tokens=0,
    )

    cost_repo.record_cost("j_costs", c1)
    cost_repo.record_cost("j_costs", c2)

    # Fetch and verify
    costs = cost_repo.get_total_costs("j_costs")
    assert len(costs) == 2
    assert sum(c.cost_usd for c in costs) == pytest.approx(0.0185)
    assert any(c.service_name == "Whisper-API" for c in costs)
