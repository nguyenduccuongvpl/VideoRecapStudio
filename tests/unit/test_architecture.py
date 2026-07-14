"""Architecture boundaries smoke tests."""

import ast
import os
from pathlib import Path


def test_domain_import_boundaries() -> None:
    """Test that domain layer does not import from infrastructure or presentation layers."""
    src_dir = Path(__file__).parent.parent.parent / "src" / "video_recap"
    domain_dir = src_dir / "domain"

    if not domain_dir.exists():
        return

    for root, _, files in os.walk(domain_dir):
        for file in files:
            if file.endswith(".py"):
                path = Path(root) / file
                with open(path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=str(path))

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            assert "infrastructure" not in name.name, (
                                f"Domain layer {file} imports from infrastructure: {name.name}"
                            )
                            assert "presentation" not in name.name, (
                                f"Domain layer {file} imports from presentation: {name.name}"
                            )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        assert "infrastructure" not in node.module, (
                                f"Domain layer {file} imports from infrastructure: {node.module}"
                            )
                        assert "presentation" not in node.module, (
                                f"Domain layer {file} imports from presentation: {node.module}"
                            )


def test_application_import_boundaries() -> None:
    """Test that application layer does not import from infrastructure or presentation layers."""
    src_dir = Path(__file__).parent.parent.parent / "src" / "video_recap"
    app_dir = src_dir / "application"

    if not app_dir.exists():
        return

    for root, _, files in os.walk(app_dir):
        for file in files:
            if file.endswith(".py"):
                path = Path(root) / file
                with open(path, "r", encoding="utf-8") as f:
                    tree = ast.parse(f.read(), filename=str(path))

                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        for name in node.names:
                            assert "infrastructure" not in name.name, (
                                f"Application layer {file} imports "
                                f"from infrastructure: {name.name}"
                            )
                            assert "presentation" not in name.name, (
                                f"Application layer {file} imports "
                                f"from presentation: {name.name}"
                            )
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        assert "infrastructure" not in node.module, (
                                f"Application layer {file} imports "
                                f"from infrastructure: {node.module}"
                            )
                        assert "presentation" not in node.module, (
                                f"Application layer {file} imports "
                                f"from presentation: {node.module}"
                            )
