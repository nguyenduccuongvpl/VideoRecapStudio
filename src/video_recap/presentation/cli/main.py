"""CLI Entry Point for VideoRecapStudio."""

import argparse
from typing import List, Optional
from video_recap import __version__


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

    parser.add_argument(
        "command",
        nargs="?",
        choices=["version"],
        help="Subcommand to execute (e.g., 'version')",
    )

    parsed_args = parser.parse_args(args)

    if parsed_args.command == "version":
        print(f"VideoRecapStudio version {__version__}")
        return 0

    parser.print_help()
    return 0
