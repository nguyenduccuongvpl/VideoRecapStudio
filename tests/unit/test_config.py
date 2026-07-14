"""Unit tests for project configurations, settings, secrets, and CLI integrations."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pydantic import SecretStr, ValidationError
from video_recap.config import get_config_paths, load_app_settings
from video_recap.config.settings import AppSettings, ProviderSettings, migrate_config_dict
from video_recap.presentation.cli.main import serialize_and_redact


def test_secret_redaction_and_representation() -> None:
    """Test that SecretStr fields are redacted in logs, repr, and dump serialization."""
    prov = ProviderSettings(
        ai_provider="mock",
        ai_model_id="mock-model",
        gemini_api_key=SecretStr("my-gemini-secret-key"),
        openai_api_key=SecretStr("my-openai-secret-key"),
    )

    # 1. Repr and str should hide the secret content
    assert "my-gemini-secret-key" not in repr(prov)
    assert "my-openai-secret-key" not in str(prov)
    assert "**********" in repr(prov.gemini_api_key)

    # 2. Test CLI serialize_and_redact utility
    dumped = prov.model_dump()
    redacted = serialize_and_redact(dumped, redact_flag=True)
    assert redacted["gemini_api_key"] == "**********"
    assert redacted["openai_api_key"] == "**********"

    plain = serialize_and_redact(dumped, redact_flag=False)
    assert plain["gemini_api_key"] == "my-gemini-secret-key"
    assert plain["openai_api_key"] == "my-openai-secret-key"


def test_dependency_validation() -> None:
    """Test validation of dependencies between providers and API keys."""
    # Mock provider requires no keys
    app = AppSettings(provider={"ai_provider": "mock"})
    assert app.provider.ai_provider == "mock"

    # Gemini provider requires gemini_api_key
    with pytest.raises(ValidationError, match="gemini_api_key is required"):
        AppSettings(provider={"ai_provider": "gemini", "gemini_api_key": None})

    # OpenAI provider requires openai_api_key
    with pytest.raises(ValidationError, match="openai_api_key is required"):
        AppSettings(provider={"ai_provider": "openai", "openai_api_key": None})

    # Satisfied dependencies
    app_gemini = AppSettings(
        provider={"ai_provider": "gemini", "gemini_api_key": "gemini-key"}
    )
    assert app_gemini.provider.gemini_api_key.get_secret_value() == "gemini-key"  # type: ignore


def test_env_override_and_precedence() -> None:
    """Test precedence rules and environment overrides."""
    # Check default is mock
    settings = load_app_settings(env_overrides={})
    assert settings.provider.ai_provider == "mock"

    # Override provider via environment variable
    settings_override = load_app_settings(
        env_overrides={
            "PROVIDER__AI_PROVIDER": "gemini",
            "PROVIDER__GEMINI_API_KEY": "my-env-gemini-key",
        }
    )
    assert settings_override.provider.ai_provider == "gemini"
    assert settings_override.provider.gemini_api_key.get_secret_value() == "my-env-gemini-key"  # type: ignore


def test_profile_merge() -> None:
    """Test preset profiles merging into settings."""
    # balanced_movie_vi profile uses default 1920x1080 resolution
    s_balanced = load_app_settings(profile_name="balanced_movie_vi")
    assert s_balanced.media.default_resolution == "1920x1080"
    assert s_balanced.story.pacing == "balanced"

    # fast_preview profile overrides resolution to 854x480 and fps to 15
    s_fast = load_app_settings(profile_name="fast_preview")
    assert s_fast.media.default_resolution == "854x480"
    assert s_fast.media.default_fps == 15.0
    assert s_fast.render.video_bitrate == "1M"


@patch("video_recap.config.settings.keyring")
def test_keyring_integration(mock_keyring: MagicMock) -> None:
    """Test retrieving API keys from system keyring when missing."""
    mock_keyring.get_password.side_effect = lambda service, key: (
        "keyring-gemini-val"
        if key == "gemini_api_key"
        else ("keyring-openai-val" if key == "openai_api_key" else None)
    )

    prov = ProviderSettings(ai_provider="mock")
    assert prov.gemini_api_key is not None
    assert prov.gemini_api_key.get_secret_value() == "keyring-gemini-val"
    assert prov.openai_api_key is not None
    assert prov.openai_api_key.get_secret_value() == "keyring-openai-val"


def test_config_paths() -> None:
    """Test getting configuration folders and file paths."""
    paths = get_config_paths()
    assert "config_dir" in paths
    assert "config_file" in paths
    assert isinstance(paths["config_file"], Path)
    assert paths["config_file"].name == "config.json"


def test_config_migration() -> None:
    """Test config dictionary migration logic."""
    old_config = {"config_version": "0.9.0", "app_name": "VideoRecap"}
    migrated = migrate_config_dict(old_config)
    assert migrated["config_version"] == "1.0.0"


@patch("video_recap.config.settings.get_config_paths")
def test_load_from_disk(mock_get_paths: MagicMock, tmp_path: Path) -> None:
    """Test loading and merging configuration file from disk."""
    config_file = tmp_path / "config.json"
    mock_get_paths.return_value = {"config_dir": tmp_path, "config_file": config_file}

    disk_data = {
        "config_version": "1.0.0",
        "media": {"default_resolution": "2560x1440", "preferred_encoder": "hevc"},
    }
    with open(config_file, "w", encoding="utf-8") as f:
        json.dump(disk_data, f)

    settings = load_app_settings(profile_name="fast_preview")

    # Disk value overrides default and profile defaults
    assert settings.media.default_resolution == "2560x1440"
    assert settings.media.preferred_encoder == "hevc"
    # Profile value remains if not overridden by disk
    assert settings.media.default_fps == 15.0
