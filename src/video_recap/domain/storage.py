"""Atomic file loading and saving with schema migration for artifacts."""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, Type, TypeVar
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

# Registry for schema migrations: model_class -> from_version -> migration_fn
_MIGRATORS: Dict[Type[Any], Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]] = {}


def register_migrator(
    model_cls: Type[Any],
    from_version: str,
    migrator_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
) -> None:
    """Register a migration function for a specific model class and version.

    Args:
        model_cls: The Pydantic model class to migrate.
        from_version: The version string to migrate FROM.
        migrator_fn: A function that takes a dict and returns a migrated dict.
    """
    if model_cls not in _MIGRATORS:
        _MIGRATORS[model_cls] = {}
    _MIGRATORS[model_cls][from_version] = migrator_fn


def save_artifact_atomic(filepath: Path | str, model: BaseModel) -> None:
    """Save a Pydantic model to a JSON file atomically.

    Writes to a temp file in the same folder first, then replaces the target file.

    Args:
        filepath: Destination path of the JSON file.
        model: The Pydantic model to write.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create temporary file in the same directory to ensure atomic replace on Windows/Linux
    fd, temp_path_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(model.model_dump_json(indent=2))
        # Atomic file replacement
        os.replace(temp_path, path)
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise e


def load_artifact(filepath: Path | str, model_cls: Type[T]) -> T:
    """Load and validate a Pydantic model from a JSON file with version migration.

    Args:
        filepath: Source path of the JSON file.
        model_cls: The Pydantic model class to load.

    Returns:
        The validated Pydantic model instance.
    """
    path = Path(filepath)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Read artifact schema version (default to 1.0.0 if not found)
    current_version = data.get("schema_version", "1.0.0")

    # Read expected default version from target model fields
    schema_field = model_cls.model_fields.get("schema_version")
    target_version = "1.0.0"
    if schema_field is not None and schema_field.default is not None:
        target_version = str(schema_field.default)

    # Run migration steps if versions mismatch
    if current_version != target_version:
        migrators = _MIGRATORS.get(model_cls, {})
        visited = set()

        while current_version != target_version and current_version in migrators:
            if current_version in visited:
                raise RuntimeError(f"Circular migration path detected for version {current_version}")
            visited.add(current_version)

            migration_fn = migrators[current_version]
            data = migration_fn(data)
            current_version = data.get("schema_version", "1.0.0")

    return model_cls.model_validate(data)
