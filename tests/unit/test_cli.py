"""CLI unit tests."""

import io
from pathlib import Path
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


def test_cli_project_commands(tmp_path: Path) -> None:
    """Test project init, inspect, verify, and clean-temp CLI flows."""
    dummy_video = tmp_path / "video.mp4"
    dummy_video.write_bytes(b"dummy metadata")

    # Override project repository path inside main to point to tmp_path
    with patch("video_recap.presentation.cli.main.FileSystemProjectRepository") as mock_repo_cls:
        from video_recap.infrastructure.persistence.workspace import FileSystemProjectRepository
        real_repo = FileSystemProjectRepository(tmp_path / "projects")
        mock_repo_cls.return_value = real_repo

        # 1. Project Init
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            code = cli_main(["project", "init", "--project-id", "cli_proj", "--source", str(dummy_video)])
            assert code == 0
            assert "successfully initialized" in mock_stdout.getvalue()

        # 2. Project Inspect
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            code = cli_main(["project", "inspect", "--project-id", "cli_proj"])
            assert code == 0
            assert "Project Inspection: cli_proj" in mock_stdout.getvalue()

        # 3. Project Verify
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            code = cli_main(["project", "verify", "--project-id", "cli_proj"])
            assert code == 0
            assert "Project Integrity Verification: cli_proj" in mock_stdout.getvalue()

        # 4. Project Clean-temp
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            code = cli_main(["project", "clean-temp", "--project-id", "cli_proj"])
            assert code == 0
            assert "Temp directory cleaned successfully" in mock_stdout.getvalue()


