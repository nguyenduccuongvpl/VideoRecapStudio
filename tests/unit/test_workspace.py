"""Unit tests for workspace directory structure, path traversal, checksums, and artifact storage."""

import json
from pathlib import Path
import pytest
from video_recap.domain import (
    MediaInfo,
    PathTraversalError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from video_recap.infrastructure.persistence.workspace import (
    FileSystemArtifactStore,
    FileSystemProjectRepository,
    SHA256ChecksumService,
    safe_resolve_path,
)


def test_safe_resolve_path(tmp_path: Path) -> None:
    """Test safe_resolve_path traversal validation."""
    base = tmp_path / "workspace"
    base.mkdir()

    # Safe subpath
    safe = safe_resolve_path(base, "project_1", "file.json")
    assert safe.parent.name == "project_1"

    # Traversal attempt
    with pytest.raises(PathTraversalError):
        safe_resolve_path(base, "../outside.json")

    with pytest.raises(PathTraversalError):
        safe_resolve_path(base, "project_1", "..", "..", "outside.json")


def test_sha256_checksum_service(tmp_path: Path) -> None:
    """Test SHA-256 calculation for files."""
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"hello world")

    svc = SHA256ChecksumService()
    checksum = svc.calculate_sha256(test_file)

    # Expected SHA-256 of b"hello world"
    expected = "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    assert checksum == expected

    # Non-existent file should return empty string
    assert svc.calculate_sha256(tmp_path / "missing.txt") == ""


def test_project_initialization_copy_mode(tmp_path: Path) -> None:
    """Test project initialization folder structures in copy mode."""
    root = tmp_path / "projects"
    repo = FileSystemProjectRepository(root)

    # Source video file
    video_source = tmp_path / "input.mp4"
    video_source.write_bytes(b"dummy video data")

    # Initialize project
    proj_dir = repo.initialize_project("proj_01", video_source, copy_mode=True)

    # Check root exists
    assert proj_dir.exists()

    # Check project.json
    assert (proj_dir / "project.json").exists()

    # Check video source is copied
    copied_video = proj_dir / "source" / "input.mp4"
    assert copied_video.exists()
    assert copied_video.read_bytes() == b"dummy video data"

    # Verify subfolders are created
    subfolders = [
        "source",
        "artifacts/media",
        "artifacts/transcript",
        "artifacts/observations",
        "artifacts/events",
        "artifacts/story",
        "artifacts/timeline",
        "artifacts/speech",
        "artifacts/renders",
        "artifacts/qa",
        "cache",
        "logs",
        "temp",
    ]
    for sub in subfolders:
        assert (proj_dir / sub).exists()


def test_project_initialization_reference_mode(tmp_path: Path) -> None:
    """Test project initialization folder structures in reference mode."""
    root = tmp_path / "projects"
    repo = FileSystemProjectRepository(root)

    video_source = tmp_path / "input.mp4"
    video_source.write_bytes(b"dummy video data")

    # Reference mode (copy_mode=False)
    proj_dir = repo.initialize_project("proj_02", video_source, copy_mode=False)

    # Check referenced video link file is created
    ref_file = proj_dir / "source" / "source_reference.json"
    assert ref_file.exists()

    with open(ref_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["original_path"] == str(video_source.resolve())

    # Source video itself should not be copied
    copied_video = proj_dir / "source" / "input.mp4"
    assert not copied_video.exists()


def test_project_already_exists_error(tmp_path: Path) -> None:
    """Test that initializing an already existing project raises an error."""
    root = tmp_path / "projects"
    repo = FileSystemProjectRepository(root)

    video_source = tmp_path / "input.mp4"
    video_source.write_bytes(b"dummy video")

    repo.initialize_project("proj_dup", video_source, copy_mode=False)

    with pytest.raises(ProjectAlreadyExistsError):
        repo.initialize_project("proj_dup", video_source, copy_mode=False)


def test_artifact_store_stale_and_cache_hit(tmp_path: Path) -> None:
    """Test ArtifactStore stale check and cache hits."""
    root = tmp_path / "projects"
    repo = FileSystemProjectRepository(root)

    video_source = tmp_path / "input.mp4"
    video_source.write_bytes(b"dummy video")

    repo.initialize_project("proj_cache", video_source, copy_mode=False)

    store = FileSystemArtifactStore(root)

    model = MediaInfo(
        producer_stage="INGESTING",
        resolution="1920x1080",
        fps=30.0,
        duration=120.0,
        size_bytes=102400,
        streams=[],
    )

    # Initial input hashes
    input_hashes = {"input.mp4": "hash_aaa"}

    # Save
    store.save_json("proj_cache", "media", "media_info.json", model, input_hashes)

    # Load and verify
    loaded = store.load_json("proj_cache", "media", "media_info.json", MediaInfo)
    assert loaded.resolution == "1920x1080"
    assert loaded.input_hashes == input_hashes

    # Cache Hit (Unchanged hashes)
    assert not store.is_stale("proj_cache", "media", "media_info.json", {"input.mp4": "hash_aaa"})

    # Stale (Changed hash)
    assert store.is_stale("proj_cache", "media", "media_info.json", {"input.mp4": "hash_bbb"})

    # Stale (Added new input hash dependency)
    assert store.is_stale(
        "proj_cache",
        "media",
        "media_info.json",
        {"input.mp4": "hash_aaa", "extra.mp4": "hash_ccc"},
    )


def test_clean_temp_dir(tmp_path: Path) -> None:
    """Test safely cleaning the temporary directory."""
    root = tmp_path / "projects"
    repo = FileSystemProjectRepository(root)

    video_source = tmp_path / "input.mp4"
    video_source.write_bytes(b"dummy video")

    proj_dir = repo.initialize_project("proj_clean", video_source, copy_mode=False)

    # Write dummy file inside temp folder
    temp_file = proj_dir / "temp" / "scratch.tmp"
    temp_file.write_bytes(b"scratch data")
    assert temp_file.exists()

    # Clean
    repo.clean_temp_dir("proj_clean")

    # Temp folder should be empty but still exist
    assert not temp_file.exists()
    assert (proj_dir / "temp").exists()


def test_missing_project_errors(tmp_path: Path) -> None:
    """Test raising errors for missing projects."""
    root = tmp_path / "projects"
    store = FileSystemArtifactStore(root)
    repo = FileSystemProjectRepository(root)

    # Missing project for store loading
    with pytest.raises(ProjectNotFoundError):
        store.load_json("missing_project", "media", "info.json", MediaInfo)

    # Missing project for cleaning temp
    with pytest.raises(ProjectNotFoundError):
        repo.clean_temp_dir("missing_project")
