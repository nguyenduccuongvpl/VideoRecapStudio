"""CLI Entry Point for VideoRecapStudio."""

import argparse
import json
from pathlib import Path
from typing import Any, List, Optional
from pydantic import SecretStr
from video_recap import __version__
from video_recap.application.doctor import run_doctor_checks
from video_recap.config import get_config_paths, load_app_settings
from video_recap.infrastructure.persistence import (
    FileSystemProjectRepository,
    SHA256ChecksumService,
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

    if parsed_args.command == "project":
        repo = FileSystemProjectRepository(Path.cwd() / "projects")

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

                # Read project config
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

                # Calculate SHA-256 for video source
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

    parser.print_help()
    return 0
