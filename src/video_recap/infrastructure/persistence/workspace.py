"""FileSystem persistence implementation for project workspace and artifacts."""

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Dict, Type, TypeVar
from pydantic import BaseModel
from video_recap.application.workspace import ArtifactStore, FileChecksumService, ProjectRepository
from video_recap.domain import (
    BaseArtifact,
    PathTraversalError,
    ProjectAlreadyExistsError,
    ProjectNotFoundError,
)
from video_recap.domain.storage import load_artifact, save_artifact_atomic

T = TypeVar("T", bound=BaseModel)


# --- Path Traversal Protection Helper ---


def safe_resolve_path(base_dir: Path, *subpaths: str | Path) -> Path:
    """Resolve and verify that target path remains inside base directory.

    Args:
        base_dir: Root directory path.
        subpaths: Relative subdirectories or files.

    Returns:
        The fully resolved Path object if safe.

    Raises:
        PathTraversalError: If the target path escapes the base_dir hierarchy.
    """
    resolved_base = base_dir.resolve()
    target = resolved_base.joinpath(*subpaths)
    resolved_target = target.resolve()

    # check if target starts with base_dir path
    try:
        resolved_target.relative_to(resolved_base)
        return resolved_target
    except ValueError:
        raise PathTraversalError(
            f"Path traversal attempt blocked: '{resolved_target}' escapes '{resolved_base}'"
        )


# --- File Checksum Service Implementation ---


class SHA256ChecksumService(FileChecksumService):
    """Calculates file checksums using SHA-256 algorithm in a memory-safe chunked way."""

    def calculate_sha256(self, filepath: Path | str) -> str:
        """Calculate the SHA-256 hash of a file.

        Args:
            filepath: Path to the target file.

        Returns:
            The hex digest string of the SHA-256 hash.
        """
        path = Path(filepath)
        if not path.exists():
            return ""

        sha256 = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        return sha256.hexdigest()


# --- FileSystem Artifact Store Implementation ---


class FileSystemArtifactStore(ArtifactStore):
    """Manages structured JSON artifacts on the local filesystem."""

    def __init__(self, root_dir: Path) -> None:
        """Initialize the store.

        Args:
            root_dir: Root directory of all projects.
        """
        self.root_dir = root_dir

    def _get_artifact_path(self, project_id: str, category: str, filename: str) -> Path:
        """Resolve the path of an artifact and protect against traversal."""
        proj_dir = safe_resolve_path(self.root_dir, project_id)
        if not proj_dir.exists():
            raise ProjectNotFoundError(f"Project workspace '{project_id}' does not exist")
        artifacts_dir = safe_resolve_path(proj_dir, "artifacts")
        category_dir = safe_resolve_path(artifacts_dir, category)
        category_dir.mkdir(parents=True, exist_ok=True)
        return safe_resolve_path(category_dir, filename)

    def save_json(
        self,
        project_id: str,
        category: str,
        filename: str,
        model: BaseModel,
        input_hashes: Dict[str, str],
    ) -> Path:
        """Save a Pydantic model atomically to a versioned JSON artifact on disk."""
        dest_path = self._get_artifact_path(project_id, category, filename)

        # Update input hashes inside the model metadata if it inherits BaseArtifact
        if isinstance(model, BaseArtifact):
            model.input_hashes = input_hashes

        save_artifact_atomic(dest_path, model)
        return dest_path

    def load_json(
        self, project_id: str, category: str, filename: str, model_cls: Type[T]
    ) -> T:
        """Load a JSON artifact from disk and validate it."""
        src_path = self._get_artifact_path(project_id, category, filename)
        if not src_path.exists():
            raise FileNotFoundError(f"Artifact file not found: {src_path}")
        return load_artifact(src_path, model_cls)

    def is_stale(
        self,
        project_id: str,
        category: str,
        filename: str,
        current_input_hashes: Dict[str, str],
    ) -> bool:
        """Determine if an existing artifact is stale (inputs have changed)."""
        try:
            src_path = self._get_artifact_path(project_id, category, filename)
        except ProjectNotFoundError:
            return True

        if not src_path.exists():
            return True

        try:
            # Load the model to inspect its input_hashes
            with open(src_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            saved_hashes = data.get("input_hashes", {})

            # Compare saved hashes with current fresh input hashes
            for key, val in current_input_hashes.items():
                if saved_hashes.get(key) != val:
                    return True  # Stale

            return False  # Up to date (Cache Hit)
        except Exception:
            return True  # Corrupted or unreadable is considered stale


# --- FileSystem Project Repository Implementation ---


class FileSystemProjectRepository(ProjectRepository):
    """Manages workspace lifecycle directories on the local filesystem."""

    def __init__(self, root_dir: Path) -> None:
        """Initialize repository.

        Args:
            root_dir: Root directory where project subfolders are stored.
        """
        self.root_dir = root_dir.resolve()
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def get_project_dir(self, project_id: str) -> Path:
        """Get the absolute root Path of the project workspace."""
        return safe_resolve_path(self.root_dir, project_id)

    def initialize_project(
        self, project_id: str, source_video_path: Path | str, copy_mode: bool
    ) -> Path:
        """Create workspace directory structure and link the source video."""
        proj_dir = safe_resolve_path(self.root_dir, project_id)

        # Raise error if project is already initialized
        if proj_dir.exists() and (proj_dir / "project.json").exists():
            raise ProjectAlreadyExistsError(f"Project '{project_id}' already exists at {proj_dir}")

        # Create workspace folders
        proj_dir.mkdir(parents=True, exist_ok=True)

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
            sub_path = safe_resolve_path(proj_dir, sub)
            sub_path.mkdir(parents=True, exist_ok=True)

        # Link/Copy video source
        src_path = Path(source_video_path)
        if not src_path.exists():
            raise FileNotFoundError(f"Source video file not found: {src_path}")

        dest_video_dir = safe_resolve_path(proj_dir, "source")
        dest_video_path = dest_video_dir / src_path.name

        if copy_mode:
            # Copy file to source/ directory
            shutil.copy2(src_path, dest_video_path)
        else:
            # Create a mock reference file source_reference.json storing original location
            ref_path = dest_video_dir / "source_reference.json"
            with open(ref_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "original_path": str(src_path.resolve()),
                        "referenced_at": str(dest_video_path),
                    },
                    f,
                    indent=2,
                )

        # Write base project.json configuration
        proj_config_path = proj_dir / "project.json"
        project_meta = {
            "project_id": project_id,
            "source_video_path": str(dest_video_path if copy_mode else src_path.resolve()),
            "output_directory": str(safe_resolve_path(proj_dir, "artifacts/renders")),
            "preset_name": "balanced_movie_vi",
            "target_recap_duration": 300.0,
            "voice_name": "vi-VN-HoaiMyNeural",
            "api_keys": {},
        }
        with open(proj_config_path, "w", encoding="utf-8") as f:
            json.dump(project_meta, f, indent=2)

        return proj_dir

    def clean_temp_dir(self, project_id: str) -> None:
        """Safely clean up temporary files in the project workspace."""
        proj_dir = safe_resolve_path(self.root_dir, project_id)
        if not proj_dir.exists():
            raise ProjectNotFoundError(f"Project workspace '{project_id}' does not exist")

        temp_dir = safe_resolve_path(proj_dir, "temp")
        if temp_dir.exists():
            # Delete and recreate empty temp folder safely
            shutil.rmtree(temp_dir)
            temp_dir.mkdir(parents=True, exist_ok=True)
