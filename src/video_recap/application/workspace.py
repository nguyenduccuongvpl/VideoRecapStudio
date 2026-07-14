"""Protocols and interfaces for Workspace and Artifact Storage management."""

from pathlib import Path
from typing import Dict, Protocol, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class FileChecksumService(Protocol):
    """Protocol for calculating file checksums (SHA-256)."""

    def calculate_sha256(self, filepath: Path | str) -> str:
        """Calculate the SHA-256 hash of a file.

        Args:
            filepath: Path to the target file.

        Returns:
            The hex digest string of the SHA-256 hash.
        """
        ...


class ArtifactStore(Protocol):
    """Protocol for storing and validating structured and binary artifacts."""

    def save_json(
        self,
        project_id: str,
        category: str,
        filename: str,
        model: BaseModel,
        input_hashes: Dict[str, str],
    ) -> Path:
        """Save a Pydantic model atomically to a versioned JSON artifact on disk.

        Args:
            project_id: The ID of the project.
            category: Subfolder category (e.g. 'transcript', 'media').
            filename: Target file name (e.g. 'transcript.json').
            model: Pydantic model to save.
            input_hashes: Dict of input files hashes that this artifact relies on.

        Returns:
            The resolved absolute Path to the saved artifact.
        """
        ...

    def load_json(
        self, project_id: str, category: str, filename: str, model_cls: Type[T]
    ) -> T:
        """Load a JSON artifact from disk and validate it.

        Args:
            project_id: The ID of the project.
            category: Subfolder category.
            filename: File name.
            model_cls: Pydantic model class to validate against.

        Returns:
            The validated Pydantic model instance.
        """
        ...

    def is_stale(
        self,
        project_id: str,
        category: str,
        filename: str,
        current_input_hashes: Dict[str, str],
    ) -> bool:
        """Determine if an existing artifact is stale (inputs have changed).

        Args:
            project_id: The ID of the project.
            category: Subfolder category.
            filename: File name.
            current_input_hashes: Fresh input hashes to compare against.

        Returns:
            True if the artifact is stale or missing, False if it is valid (cache hit).
        """
        ...


class ProjectRepository(Protocol):
    """Protocol for managing project workspace directories and lifecycles."""

    def initialize_project(
        self, project_id: str, source_video_path: Path | str, copy_mode: bool
    ) -> Path:
        """Create workspace directory structure and link the source video.

        Args:
            project_id: Unique ID of the project.
            source_video_path: Path to the original video file.
            copy_mode: If True, copy video to source/. If False, reference it.

        Returns:
            The root Path of the initialized project directory.
        """
        ...

    def get_project_dir(self, project_id: str) -> Path:
        """Get the absolute root Path of the project workspace.

        Args:
            project_id: Unique ID of the project.

        Returns:
            The project root directory Path.
        """
        ...

    def clean_temp_dir(self, project_id: str) -> None:
        """Safely clean up temporary files in the project workspace.

        Args:
            project_id: Unique ID of the project.
        """
        ...
