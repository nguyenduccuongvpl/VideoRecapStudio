"""Main entry point for running the package via python -m video_recap."""

import sys
from video_recap.presentation.cli.main import cli_main

if __name__ == "__main__":
    sys.exit(cli_main())
