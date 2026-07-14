"""Configuration models, secret management, profiles, and environment management."""

import json
from pathlib import Path
from typing import Any, Dict, Optional
from platformdirs import PlatformDirs
from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

try:
    import keyring
except ImportError:
    keyring = None  # type: ignore


# --- Settings Sub-Groups ---


class ProviderSettings(BaseModel):
    """Configuration for external AI models and API keys."""

    ai_provider: str = Field("mock", description="AI Provider: mock, gemini, openai")
    ai_model_id: str = Field("mock-model", description="Model ID to use for AI tasks")
    gemini_api_key: Optional[SecretStr] = Field(None, description="API Key for Google Gemini")
    openai_api_key: Optional[SecretStr] = Field(None, description="API Key for OpenAI")

    @model_validator(mode="after")
    def fetch_from_keyring(self) -> "ProviderSettings":
        """Attempt to fetch API Keys from secure system keyring if missing."""
        if keyring is not None:
            if not self.gemini_api_key:
                try:
                    key = keyring.get_password("VideoRecapStudio", "gemini_api_key")
                    if key:
                        self.gemini_api_key = SecretStr(key)
                except Exception:
                    pass

            if not self.openai_api_key:
                try:
                    key = keyring.get_password("VideoRecapStudio", "openai_api_key")
                    if key:
                        self.openai_api_key = SecretStr(key)
                except Exception:
                    pass
        return self


class MediaSettings(BaseModel):
    """Configuration for video probing and extraction."""

    ffmpeg_path: Optional[str] = Field(None, description="Absolute path to ffmpeg executable")
    ffprobe_path: Optional[str] = Field(None, description="Absolute path to ffprobe executable")
    preferred_encoder: str = Field("libx264", description="FFmpeg video encoder")
    default_resolution: str = Field("1920x1080", description="Width x Height")
    default_fps: float = Field(30.0, gt=0.0, description="Default FPS")


class TranscriptionSettings(BaseModel):
    """Configuration for Speech-to-Text backend."""

    language: str = Field("vi", description="Target transcription language")
    transcription_backend: str = Field("mock", description="mock, whisper, google")


class StorySettings(BaseModel):
    """Configuration for narrative design."""

    pacing: str = Field("balanced", description="Fast, balanced, slow pacing")
    outline_prompt_version: str = Field("v1.0", description="Version of the outline prompt")
    narration_prompt_version: str = Field("v1.0", description="Version of the narration prompt")


class TTSSettings(BaseModel):
    """Configuration for Text-to-Speech settings."""

    voice_name: str = Field("vi-VN-HoaiMyNeural", description="Voice profile code")
    tts_backend: str = Field("mock", description="mock, edge-tts")
    speed_modifier: float = Field(1.0, ge=0.5, le=2.0, description="TTS speed multiplier")


class RenderSettings(BaseModel):
    """Configuration for video final rendering options."""

    video_bitrate: str = Field("4M", description="FFmpeg video bit rate (e.g. 4M)")
    enable_subtitles: bool = Field(True, description="Hard-burn subtitles into final render")
    ducking_volume_db: float = Field(-15.0, le=0.0, description="Audio ducking offset in dB")


class QASettings(BaseModel):
    """Threshold checks for QA validation."""

    min_factual_accuracy: float = Field(0.95, ge=0.0, le=1.0)
    min_clip_relevance: float = Field(0.90, ge=0.0, le=1.0)
    max_silence_duration: float = Field(2.0, ge=0.0)


class UISettings(BaseModel):
    """Desktop presentation settings."""

    theme: str = Field("dark", description="light, dark, system")
    font_size: int = Field(12, ge=8, le=24)
    window_width: int = Field(1280, ge=640)
    window_height: int = Field(720, ge=480)


# --- Preset Profiles ---

PROFILES: Dict[str, Dict[str, Any]] = {
    "balanced_movie_vi": {
        "tts": {"voice_name": "vi-VN-HoaiMyNeural"},
        "story": {"pacing": "balanced"},
        "media": {"default_resolution": "1920x1080"},
    },
    "fast_preview": {
        "media": {"default_resolution": "854x480", "default_fps": 15.0},
        "render": {"video_bitrate": "1M"},
    },
    "high_quality_movie_vi": {
        "media": {"default_resolution": "3840x2160"},
        "render": {"video_bitrate": "12M"},
        "tts": {"voice_name": "vi-VN-NamMinhNeural"},
    },
    "silent_video_vi": {
        "render": {"enable_subtitles": True, "ducking_volume_db": 0.0},
        "tts": {"tts_backend": "mock"},
    },
    "esports_vi": {
        "story": {"pacing": "fast"},
        "tts": {"speed_modifier": 1.15, "voice_name": "vi-VN-NamMinhNeural"},
    },
    "short_vertical_vi": {
        "media": {"default_resolution": "1080x1920"},
        "story": {"pacing": "fast"},
    },
}


# --- AppSettings & Version Control ---


class AppSettings(BaseSettings):
    """VideoRecapStudio Global Application Settings."""

    config_version: str = "1.0.0"
    app_name: str = "VideoRecapStudio"

    provider: ProviderSettings = Field(default_factory=ProviderSettings)
    media: MediaSettings = Field(default_factory=MediaSettings)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    story: StorySettings = Field(default_factory=StorySettings)
    tts: TTSSettings = Field(default_factory=TTSSettings)
    render: RenderSettings = Field(default_factory=RenderSettings)
    qa: QASettings = Field(default_factory=QASettings)
    ui: UISettings = Field(default_factory=UISettings)

    # Configuration precedence sources
    model_config = SettingsConfigDict(
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_dependencies(self) -> "AppSettings":
        """Validate settings dependencies (e.g. API keys for providers)."""
        prov = self.provider
        if prov.ai_provider == "gemini":
            if not prov.gemini_api_key:
                raise ValueError("gemini_api_key is required when ai_provider is 'gemini'")
        elif prov.ai_provider == "openai":
            if not prov.openai_api_key:
                raise ValueError("openai_api_key is required when ai_provider is 'openai'")
        return self


# --- Paths Utility ---


def get_config_paths() -> Dict[str, Path]:
    """Get system-specific configuration file and directory paths.

    Returns:
        A dict containing 'config_dir' and 'config_file' Path objects.
    """
    dirs = PlatformDirs("VideoRecapStudio", "CUONGNGUYEN")
    config_dir = Path(dirs.user_config_dir)
    return {
        "config_dir": config_dir,
        "config_file": config_dir / "config.json",
    }


# --- Configuration Loading with Migration ---


def migrate_config_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Migrate configuration dictionaries to newer versions if needed."""
    version = data.get("config_version", "1.0.0")
    if version == "0.9.0":
        # Example migration step
        data["config_version"] = "1.0.0"
    return data


def load_app_settings(
    profile_name: Optional[str] = None, env_overrides: Optional[Dict[str, str]] = None
) -> AppSettings:
    """Load configuration with standard precedence rules:

    Precedence:
      1. Explicit environment overrides (passed in dictionary)
      2. Environment variables / .env file
      3. User configuration file on disk (platformdirs)
      4. Profile-specific overrides
      5. System defaults

    Args:
        profile_name: Optional preset profile name.
        env_overrides: Optional dict of overrides (for testing).

    Returns:
        A fully initialized AppSettings object.
    """
    paths = get_config_paths()
    file_data: Dict[str, Any] = {}

    # 1. Load and migrate from disk if exists
    if paths["config_file"].exists():
        try:
            with open(paths["config_file"], "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                file_data = migrate_config_dict(raw_data)
        except Exception:
            pass

    # 2. Merge profile overrides if requested
    profile_data: Dict[str, Any] = {}
    if profile_name and profile_name in PROFILES:
        profile_data = PROFILES[profile_name]

    # Combine file and profile data (file overrides profile)
    merged_data = {}
    # Deep merge helper for dicts
    def deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> None:
        for k, v in source.items():
            if isinstance(v, dict) and k in target and isinstance(target[k], dict):
                deep_merge(target[k], v)
            else:
                target[k] = v

    deep_merge(merged_data, profile_data)
    deep_merge(merged_data, file_data)

    # 3. Instantiate settings (env vars and .env will naturally override merged_data)
    # If env_overrides are provided (mainly for test isolation), mock environment
    if env_overrides:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, env_overrides):
            settings = AppSettings(**merged_data)
    else:
        settings = AppSettings(**merged_data)

    return settings
