"""CLI unit tests."""

import io
from unittest.mock import patch
import pytest
from video_recap.presentation.cli.main import cli_main


def test_cli_version() -> None:
    """Test the CLI version command."""
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        code = cli_main(["version"])
        assert code == 0
        assert "VideoRecapStudio version" in mock_stdout.getvalue()


def test_cli_help() -> None:
    """Test that CLI displays help text."""
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        with pytest.raises(SystemExit) as exc_info:
            cli_main(["--help"])
        assert exc_info.value.code == 0
        assert "video_recap" in mock_stdout.getvalue()


def test_cli_config_paths() -> None:
    """Test the CLI config paths command."""
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        code = cli_main(["config", "paths"])
        assert code == 0
        assert "Config Directory" in mock_stdout.getvalue()
        assert "Config File" in mock_stdout.getvalue()


def test_cli_config_validate() -> None:
    """Test the CLI config validate command."""
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        code = cli_main(["config", "validate"])
        assert code == 0
        assert "Configuration is valid" in mock_stdout.getvalue()


def test_cli_config_show() -> None:
    """Test the CLI config show command."""
    with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
        code = cli_main(["config", "show", "--redacted"])
        assert code == 0
        assert "config_version" in mock_stdout.getvalue()
        assert "app_name" in mock_stdout.getvalue()

