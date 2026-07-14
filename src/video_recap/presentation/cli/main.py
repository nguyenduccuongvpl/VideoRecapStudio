"""CLI Entry Point for VideoRecapStudio."""

import argparse
import datetime
import json
import uuid
from pathlib import Path
from typing import Any, List, Optional
from pydantic import SecretStr
from video_recap import __version__
from video_recap.application.doctor import run_doctor_checks
from video_recap.application.pipeline import (
    CancellationToken,
    JobOrchestrator,
    PipelineDefinition,
    StageContext,
)
from video_recap.config import get_config_paths, load_app_settings
from video_recap.domain import Job, JobState, ProjectConfig, StageName
from video_recap.domain.events import StageProgress
from video_recap.infrastructure.logging import InProcessEventBus
from video_recap.infrastructure.persistence import (
    DatabaseManager,
    FileSystemArtifactStore,
    FileSystemProjectRepository,
    SHA256ChecksumService,
    SqliteCostRepository,
    SqliteJobRepository,
    SqliteProjectMetadataRepository,
    SqliteStageRunRepository,
    run_migrations,
)


def serialize_and_redact(data: Any, redact_flag: bool) -> Any:
    """Recursively dump model dictionary and redact SecretStr if requested."""
    if isinstance(data, dict):
        return {k: serialize_and_redact(v, redact_flag) for k, v in data.items()}
    if isinstance(data, list):
        return [serialize_and_redact(v, redact_flag) for v in data]
    if isinstance(data, SecretStr):
        return "**********" if redact_flag else data.get_secret_value()
    return data


class FakeStage:
    """Simulated pipeline stage for CLI execution and integration testing."""

    def __init__(self, name: StageName) -> None:
        self._name = name

    @property
    def name(self) -> StageName:
        return self._name

    def execute(self, context: StageContext) -> None:
        import time

        for i in range(1, 4):
            progress_val = i / 3.0
            # Cooperative cancellation check
            context.cancellation_token.raise_if_cancelled()

            # Check if cancelled in DB (external cooperative cancel)
            db_job = context.job_repo.get_job(context.job_id)
            if db_job and db_job.state == JobState.CANCELLED:
                context.cancellation_token.cancel()
                context.cancellation_token.raise_if_cancelled()

            context.event_bus.publish(
                StageProgress(
                    job_id=context.job_id,
                    project_id=context.project_id,
                    stage=self.name,
                    progress=progress_val,
                    message=f"Working... {int(progress_val * 100)}%",
                    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                )
            )
            time.sleep(0.01)


def cli_main(args: Optional[List[str]] = None) -> int:
    """Entry point for the CLI tool.

    Args:
        args: List of command line arguments. If None, sys.argv is used.

    Returns:
        Exit status code (0 for success, non-zero for failure).
    """
    parser = argparse.ArgumentParser(
        prog="video_recap",
        description="VideoRecapStudio: Desktop & CLI Video Recap Generator",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Subcommand: version
    subparsers.add_parser("version", help="Show version information")

    # Subcommand: doctor
    doctor_parser = subparsers.add_parser(
        "doctor", help="Check system capabilities and dependencies"
    )
    doctor_parser.add_argument("--json", action="store_true", help="Output doctor report as JSON")

    # Subcommand: config
    config_parser = subparsers.add_parser("config", help="Manage application configurations")
    config_subparsers = config_parser.add_subparsers(dest="config_command", help="Config commands")

    # config show
    show_parser = config_subparsers.add_parser("show", help="Show current config settings")
    show_parser.add_argument(
        "--redacted", action="store_true", default=False, help="Redact secrets"
    )

    # config validate
    config_subparsers.add_parser("validate", help="Validate current config settings")

    # config paths
    config_subparsers.add_parser("paths", help="Show config directory and file paths")

    # Subcommand: project
    project_parser = subparsers.add_parser("project", help="Manage project workspaces")
    project_subparsers = project_parser.add_subparsers(
        dest="project_command", help="Project commands"
    )

    # project init
    init_parser = project_subparsers.add_parser(
        "init", help="Initialize a new project workspace"
    )
    init_parser.add_argument("--project-id", required=True, help="Unique project identifier")
    init_parser.add_argument("--source", required=True, help="Path to the source video file")
    init_parser.add_argument(
        "--copy",
        action="store_true",
        default=False,
        help="Copy source video into workspace instead of referencing it",
    )

    # project inspect
    inspect_parser = project_subparsers.add_parser(
        "inspect", help="Inspect an existing project workspace"
    )
    inspect_parser.add_argument("--project-id", required=True, help="Unique project identifier")

    # project verify
    verify_parser = project_subparsers.add_parser(
        "verify", help="Verify integrity of project workspace files"
    )
    verify_parser.add_argument("--project-id", required=True, help="Unique project identifier")

    # project clean-temp
    clean_parser = project_subparsers.add_parser(
        "clean-temp", help="Clean up temporary files in project workspace"
    )
    clean_parser.add_argument("--project-id", required=True, help="Unique project identifier")

    # Subcommand: job
    job_parser = subparsers.add_parser("job", help="Manage pipeline execution jobs")
    job_subparsers = job_parser.add_subparsers(dest="job_command", help="Job subcommands")

    # job create
    job_create = job_subparsers.add_parser("create", help="Create a new job for a project")
    job_create.add_argument("--project-id", required=True, help="The project ID")

    # job run
    job_run = job_subparsers.add_parser("run", help="Run a created job")
    job_run.add_argument("--job-id", required=True, help="The job ID to run")

    # job resume
    job_resume = job_subparsers.add_parser("resume", help="Resume a paused/failed job")
    job_resume.add_argument("--job-id", required=True, help="The job ID to resume")

    # job cancel
    job_cancel = job_subparsers.add_parser("cancel", help="Cancel a running job")
    job_cancel.add_argument("--job-id", required=True, help="The job ID to cancel")

    # job status
    job_status = job_subparsers.add_parser("status", help="Get status of a job")
    job_status.add_argument("--job-id", required=True, help="The job ID")

    # Subcommand: media
    media_parser = subparsers.add_parser("media", help="Media utilities")
    media_subparsers = media_parser.add_subparsers(dest="media_command", help="Media subcommands")

    # media probe
    probe_parser = media_subparsers.add_parser("probe", help="Probe metadata from a media file")
    probe_parser.add_argument("file", help="Path to the media file to probe")

    # Subcommand: obs-review
    obs_review_parser = subparsers.add_parser("obs-review", help="Generate interactive human review dashboard for VLM observations")
    obs_review_parser.add_argument("observations_file", help="Path to JSON file containing list of observations")
    obs_review_parser.add_argument("video_file", help="Path to the source video file")
    obs_review_parser.add_argument("--output", default="observation_review.html", help="Path to output HTML file")
    obs_review_parser.add_argument("--sample-size", type=int, default=20, help="Number of observations to sample")

    parsed_args = parser.parse_args(args)

    if parsed_args.command == "version":
        print(f"VideoRecapStudio version {__version__}")
        return 0

    if parsed_args.command == "doctor":
        report = run_doctor_checks()
        if parsed_args.json:
            print(report.model_dump_json(indent=2))
            return 0 if report.is_valid else 1
        else:
            print("=" * 60)
            print("VideoRecapStudio Capability Doctor Check")
            print("=" * 60)
            for item in report.items:
                status_icon = {
                    "SUCCESS": "[  OK  ]",
                    "WARNING": "[ WARN ]",
                    "FAILED": "[ FAIL ]",
                }.get(item.status, "[ ???? ]")
                print(f"{status_icon} {item.name}: {item.details}")
            print("=" * 60)

            if report.is_valid:
                print("SUCCESS: System meets all required capabilities!")
                return 0
            else:
                print("ERROR: System is missing required capabilities. Check docs/installation.md.")
                return 1

    if parsed_args.command == "config":
        if parsed_args.config_command == "paths":
            paths = get_config_paths()
            print(f"Config Directory: {paths['config_dir']}")
            print(f"Config File:      {paths['config_file']}")
            return 0

        if parsed_args.config_command == "validate":
            try:
                load_app_settings()
                print("SUCCESS: Configuration is valid.")
                return 0
            except Exception as e:
                print(f"ERROR: Configuration validation failed: {e}")
                return 1

        if parsed_args.config_command == "show":
            try:
                settings = load_app_settings()
                dumped = settings.model_dump()
                redacted_data = serialize_and_redact(dumped, parsed_args.redacted)
                print(json.dumps(redacted_data, indent=2))
                return 0
            except Exception as e:
                print(f"ERROR: Failed to load config: {e}")
                return 1

    # SQLite DB Setup
    projects_dir = Path.cwd() / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    db_path = projects_dir / "metadata.sqlite"
    db_mgr = DatabaseManager(db_path)
    run_migrations(db_mgr)

    if parsed_args.command == "project":
        repo = FileSystemProjectRepository(projects_dir)

        if parsed_args.project_command == "init":
            try:
                proj_dir = repo.initialize_project(
                    parsed_args.project_id, parsed_args.source, parsed_args.copy
                )
                print(
                    f"SUCCESS: Project '{parsed_args.project_id}' successfully "
                    f"initialized at '{proj_dir.resolve()}'."
                )
                return 0
            except Exception as e:
                print(f"ERROR: Failed to initialize project: {e}")
                return 1

        if parsed_args.project_command == "inspect":
            try:
                proj_dir = repo.get_project_dir(parsed_args.project_id)
                if not proj_dir.exists():
                    print(f"ERROR: Project directory '{proj_dir}' does not exist.")
                    return 1

                config_path = proj_dir / "project.json"
                config_data = {}
                if config_path.exists():
                    with open(config_path, "r", encoding="utf-8") as f:
                        config_data = json.load(f)

                print("=" * 60)
                print(f"Project Inspection: {parsed_args.project_id}")
                print("=" * 60)
                print(f"Directory:       {proj_dir.resolve()}")
                print(f"Source Video:    {config_data.get('source_video_path')}")
                print(f"Voice Name:      {config_data.get('voice_name')}")
                print(f"Preset Profile:  {config_data.get('preset_name')}")
                print("=" * 60)
                return 0
            except Exception as e:
                print(f"ERROR: Failed to inspect project: {e}")
                return 1

        if parsed_args.project_command == "verify":
            try:
                proj_dir = repo.get_project_dir(parsed_args.project_id)
                if not proj_dir.exists():
                    print(f"ERROR: Project directory '{proj_dir}' does not exist.")
                    return 1

                config_path = proj_dir / "project.json"
                if not config_path.exists():
                    print("ERROR: project.json missing.")
                    return 1

                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)

                video_path = Path(config_data.get("source_video_path", ""))
                checksum_svc = SHA256ChecksumService()
                sha_val = checksum_svc.calculate_sha256(video_path)

                print("=" * 60)
                print(f"Project Integrity Verification: {parsed_args.project_id}")
                print("=" * 60)
                print(f"Source Video Path: {video_path}")
                print(f"SHA-256 Checksum:  {sha_val or 'Not Found/Readable'}")
                print("=" * 60)
                return 0
            except Exception as e:
                print(f"ERROR: Verification failed: {e}")
                return 1

        if parsed_args.project_command == "clean-temp":
            try:
                repo.clean_temp_dir(parsed_args.project_id)
                print(
                    f"SUCCESS: Temp directory cleaned successfully for project "
                    f"'{parsed_args.project_id}'."
                )
                return 0
            except Exception as e:
                print(f"ERROR: Cleaning temp failed: {e}")
                return 1

    if parsed_args.command == "job":
        job_repo = SqliteJobRepository(db_mgr)
        proj_meta_repo = SqliteProjectMetadataRepository(db_mgr)
        stage_run_repo = SqliteStageRunRepository(db_mgr)
        cost_repo = SqliteCostRepository(db_mgr)

        if parsed_args.job_command == "create":
            try:
                # 1. Upsert project metadata to SQLite if not already there
                project_id = parsed_args.project_id
                proj_dir = projects_dir / project_id
                if not proj_dir.exists():
                    print(f"ERROR: Project directory '{proj_dir}' not found. Run project init first.")
                    return 1

                config_path = proj_dir / "project.json"
                if not config_path.exists():
                    print(f"ERROR: project.json missing in '{proj_dir}'.")
                    return 1

                with open(config_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)

                proj_config = ProjectConfig(
                    project_id=project_id,
                    source_video_path=meta.get("source_video_path", ""),
                    output_directory=meta.get("output_directory", ""),
                    preset_name=meta.get("preset_name", "balanced_movie_vi"),
                    target_recap_duration=meta.get("target_recap_duration", 300.0),
                    voice_name=meta.get("voice_name", "vi-VN-HoaiMyNeural"),
                    api_keys={},
                )
                proj_meta_repo.save_project_config(project_id, proj_config)

                # 2. Create Job
                job_id = str(uuid.uuid4())
                job = Job(
                    job_id=job_id,
                    project_id=project_id,
                    state=JobState.CREATED,
                )
                job_repo.create_job(job)
                print(f"SUCCESS: Job '{job_id}' created successfully for project '{project_id}'.")
                return 0
            except Exception as e:
                print(f"ERROR: Job creation failed: {e}")
                return 1

        if parsed_args.job_command in ("run", "resume"):
            job_id = parsed_args.job_id
            job = job_repo.get_job(job_id)
            if not job:
                print(f"ERROR: Job '{job_id}' not found.")
                return 1

            config = proj_meta_repo.get_project_config(job.project_id)
            if not config:
                print(f"ERROR: Project config for job '{job_id}' not found.")
                return 1

            # Setup stage context
            cancellation_token = CancellationToken()
            artifact_store = FileSystemArtifactStore(projects_dir)
            project_repo = FileSystemProjectRepository(projects_dir)
            event_bus = InProcessEventBus()

            # Subscribe logging outputs
            event_bus.subscribe(
                StageProgress, lambda e: print(f"[{e.stage.value}] Progress: {int(e.progress * 100)}% - {e.message}")
            )

            # Build pipeline of fake stages
            fake_stages = [FakeStage(name) for name in StageName]
            pipeline = PipelineDefinition(fake_stages)
            orchestrator = JobOrchestrator(pipeline)

            context = StageContext(
                job_id=job_id,
                project_id=job.project_id,
                config=config,
                artifact_store=artifact_store,
                project_repo=project_repo,
                job_repo=job_repo,
                stage_run_repo=stage_run_repo,
                cost_repo=cost_repo,
                event_bus=event_bus,
                cancellation_token=cancellation_token,
            )

            is_resume = parsed_args.job_command == "resume"
            try:
                print(f"Starting pipeline execution for Job '{job_id}' (resume={is_resume})...")
                orchestrator.execute_job(job, context, resume=is_resume)
                print(f"SUCCESS: Job '{job_id}' execution completed. State: {job.state.value}")
                return 0
            except Exception as e:
                print(f"ERROR: Pipeline execution failed: {e}")
                return 1

        if parsed_args.job_command == "cancel":
            job_id = parsed_args.job_id
            job = job_repo.get_job(job_id)
            if not job:
                print(f"ERROR: Job '{job_id}' not found.")
                return 1

            # In thread-based runs, setting status in DB cooperative aborts.
            # Whitelist check: ensure CANCELLED transition is valid.
            try:
                # Mock context to transition
                event_bus = InProcessEventBus()
                context = StageContext(
                    job_id=job_id,
                    project_id=job.project_id,
                    config=None,  # type: ignore
                    artifact_store=None,  # type: ignore
                    project_repo=None,  # type: ignore
                    job_repo=job_repo,
                    stage_run_repo=stage_run_repo,
                    cost_repo=cost_repo,
                    event_bus=event_bus,
                    cancellation_token=CancellationToken(),
                )
                orchestrator = JobOrchestrator(PipelineDefinition([]))
                orchestrator._transition_job_state(job, JobState.CANCELLED, context)
                print(f"SUCCESS: Job '{job_id}' marked as CANCELLED.")
                return 0
            except Exception as e:
                print(f"ERROR: Failed to cancel job: {e}")
                return 1

        if parsed_args.job_command == "status":
            job_id = parsed_args.job_id
            job = job_repo.get_job(job_id)
            if not job:
                print(f"ERROR: Job '{job_id}' not found.")
                return 1

            # Get stage runs
            runs = stage_run_repo.get_stage_runs(job_id)

            print("=" * 60)
            print(f"Job Status: {job_id}")
            print("=" * 60)
            print(f"Project ID:      {job.project_id}")
            print(f"Current State:   {job.state.value}")
            print(f"Current Stage:   {job.current_stage.value if job.current_stage else 'None'}")
            print(f"Error Details:   {job.error_details or 'None'}")
            print("-" * 60)
            print("Pipeline Stages:")
            for r in runs:
                err_msg = f" - Error: {r.error_message}" if r.error_message else ""
                print(f"  - {r.stage_name}: {r.status} (Started: {r.started_at}, Completed: {r.completed_at}){err_msg}")
            print("=" * 60)
            return 0

    if parsed_args.command == "media":
        if parsed_args.media_command == "probe":
            from video_recap.infrastructure.media.subprocess_runner import SubprocessRunner
            from video_recap.application.probe import MediaProbeService, MediaProbeError

            runner = SubprocessRunner()
            try:
                settings = load_app_settings()
                ffprobe_path = settings.media.ffprobe_path or "ffprobe"
            except Exception:
                ffprobe_path = "ffprobe"

            service = MediaProbeService(runner, ffprobe_path=ffprobe_path)
            try:
                info = service.probe(parsed_args.file)
                print(info.model_dump_json(indent=2))
                return 0
            except MediaProbeError as e:
                print(f"ERROR: Probing failed: {e}")
                return 1
            except Exception as e:
                print(f"ERROR: Unexpected error: {e}")
                return 1

    if parsed_args.command == "obs-review":
        from video_recap.domain.models import Observation
        from video_recap.application.review import StratifiedObservationSampler
        from video_recap.presentation.cli.review_tool import generate_review_html

        obs_path = Path(parsed_args.observations_file)
        if not obs_path.exists():
            print(f"ERROR: Observations file not found at {obs_path}")
            return 1

        try:
            with open(obs_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            
            if isinstance(raw_data, dict) and "observations" in raw_data:
                obs_list_raw = raw_data["observations"]
            elif isinstance(raw_data, list):
                obs_list_raw = raw_data
            else:
                print("ERROR: Invalid observations JSON format.")
                return 1

            observations = [Observation.model_validate(item) for item in obs_list_raw]
        except Exception as e:
            print(f"ERROR: Failed to parse observations file: {e}")
            return 1

        sampler = StratifiedObservationSampler()
        sampled = sampler.sample(observations, target_size=parsed_args.sample_size)
        
        output_path = Path(parsed_args.output)
        try:
            generate_review_html(sampled, parsed_args.video_file, output_path)
            print(f"SUCCESS: Generated observation review tool at: {output_path.absolute()}")
            print(f"Sampled {len(sampled)} observations for review.")
            return 0
        except Exception as e:
            print(f"ERROR: Failed to generate HTML: {e}")
            return 1

    parser.print_help()
    return 0
