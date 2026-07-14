"""CLI Entry Point for VideoRecapStudio."""

import argparse
from typing import List, Optional
from video_recap import __version__
from video_recap.application.doctor import run_doctor_checks


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

    parser.print_help()
    return 0

