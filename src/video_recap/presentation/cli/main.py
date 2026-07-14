"""CLI Entry Point for VideoRecapStudio."""

import argparse
import json
from typing import Any, List, Optional
from pydantic import SecretStr
from video_recap import __version__
from video_recap.application.doctor import run_doctor_checks
from video_recap.config import get_config_paths, load_app_settings


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
                # Load settings, validating them
                load_app_settings()
                print("SUCCESS: Configuration is valid.")
                return 0
            except Exception as e:
                print(f"ERROR: Configuration validation failed: {e}")
                return 1

        if parsed_args.config_command == "show":
            try:
                # Load settings, but allow invalid API keys for display if mock is chosen
                # To prevent validate_dependencies from crashing during show command if keys are missing,
                # we load settings. If validation fails, we print the validation error details.
                settings = load_app_settings()
                dumped = settings.model_dump()
                redacted_data = serialize_and_redact(dumped, parsed_args.redacted)
                print(json.dumps(redacted_data, indent=2))
                return 0
            except Exception as e:
                print(f"ERROR: Failed to load config: {e}")
                return 1

    parser.print_help()
    return 0
