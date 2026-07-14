"""Application logic for capability verification (Doctor check)."""

import importlib.util
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional
from video_recap.domain.capability import CapabilityItem, CapabilityReport


def check_module_available(name: str) -> Optional[str]:
    """Check if a Python module is available and return its version if possible.

    Args:
        name: The name of the module.

    Returns:
        Version string if found, empty string if available but no version, None if not found.
    """
    try:
        spec = importlib.util.find_spec(name)
        if spec is None:
            return None
        module = importlib.import_module(name)
        return str(getattr(module, "__version__", ""))
    except Exception:
        return None


def get_ffmpeg_path() -> Optional[str]:
    """Get the path to ffmpeg executable."""
    env_path = os.environ.get("FFMPEG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    return shutil.which("ffmpeg")


def get_ffprobe_path() -> Optional[str]:
    """Get the path to ffprobe executable."""
    env_path = os.environ.get("FFPROBE_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    return shutil.which("ffprobe")


def run_command(cmd: List[str]) -> Optional[str]:
    """Run a command and return stdout. Returns None if it fails."""
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout
        return result.stdout + result.stderr
    except Exception:
        return None


def run_doctor_checks() -> CapabilityReport:
    """Execute all capability checks and return a CapabilityReport.

    Returns:
        A CapabilityReport containing results of all checks.
    """
    items: List[CapabilityItem] = []

    # 1. Python Version Check
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 12):
        items.append(
            CapabilityItem(
                name="Python Version",
                status="SUCCESS",
                required=True,
                details=f"Python {py_ver} matches required version >= 3.12",
            )
        )
    else:
        items.append(
            CapabilityItem(
                name="Python Version",
                status="FAILED",
                required=True,
                details=f"Python {py_ver} is installed, but version >= 3.12 is required",
            )
        )

    # 2. PySide6 Check
    pyside_ver = check_module_available("PySide6")
    if pyside_ver is not None:
        items.append(
            CapabilityItem(
                name="PySide6 Library",
                status="SUCCESS",
                required=True,
                details=f"PySide6 version {pyside_ver or 'unknown'} is installed",
            )
        )
    else:
        items.append(
            CapabilityItem(
                name="PySide6 Library",
                status="FAILED",
                required=True,
                details="PySide6 is not installed. Run 'pip install PySide6'",
            )
        )

    # 3. Pydantic Check
    pydantic_ver = check_module_available("pydantic")
    if pydantic_ver is not None:
        items.append(
            CapabilityItem(
                name="Pydantic Library",
                status="SUCCESS",
                required=True,
                details=f"Pydantic version {pydantic_ver} is installed",
            )
        )
    else:
        items.append(
            CapabilityItem(
                name="Pydantic Library",
                status="FAILED",
                required=True,
                details="Pydantic is not installed. Run 'pip install pydantic'",
            )
        )

    # 4. Scene Detection Check
    sd_ver = check_module_available("scenedetect")
    if sd_ver is not None:
        items.append(
            CapabilityItem(
                name="Scene Detection Library",
                status="SUCCESS",
                required=True,
                details=f"scenedetect version {sd_ver or 'unknown'} is installed",
            )
        )
    else:
        items.append(
            CapabilityItem(
                name="Scene Detection Library",
                status="FAILED",
                required=True,
                details="scenedetect is not installed. Run 'pip install scenedetect'",
            )
        )

    # 5. Optional AI SDKs Checks
    openai_ver = check_module_available("openai")
    if openai_ver is not None:
        items.append(
            CapabilityItem(
                name="OpenAI AI SDK (Optional)",
                status="SUCCESS",
                required=False,
                details=f"openai SDK version {openai_ver or 'unknown'} is installed",
            )
        )
    else:
        items.append(
            CapabilityItem(
                name="OpenAI AI SDK (Optional)",
                status="WARNING",
                required=False,
                details="openai SDK is not installed. Will not be able to use OpenAI models",
            )
        )

    gemini_ver = check_module_available("google.generativeai")
    if gemini_ver is not None:
        items.append(
            CapabilityItem(
                name="Google Gemini AI SDK (Optional)",
                status="SUCCESS",
                required=False,
                details="google-generativeai SDK is installed",
            )
        )
    else:
        items.append(
            CapabilityItem(
                name="Google Gemini AI SDK (Optional)",
                status="WARNING",
                required=False,
                details="google-generativeai SDK is not installed. Cannot use Gemini models",
            )
        )

    # 6. Optional Transcription Backend Check
    tts_ver = check_module_available("edge_tts")
    if tts_ver is not None:
        items.append(
            CapabilityItem(
                name="Edge TTS Library (Optional)",
                status="SUCCESS",
                required=False,
                details=f"edge-tts version {tts_ver or 'unknown'} is installed",
            )
        )
    else:
        items.append(
            CapabilityItem(
                name="Edge TTS Library (Optional)",
                status="WARNING",
                required=False,
                details="edge-tts is not installed. Will not be able to generate local TTS audio",
            )
        )

    # 7. FFmpeg CLI Path Check
    ffmpeg_path = get_ffmpeg_path()
    if ffmpeg_path:
        # Run -version to get version info
        ver_output = run_command([ffmpeg_path, "-version"])
        if ver_output:
            first_line = ver_output.splitlines()[0]
            items.append(
                CapabilityItem(
                    name="FFmpeg Executable",
                    status="SUCCESS",
                    required=True,
                    details=f"FFmpeg found at '{ffmpeg_path}'. Info: {first_line}",
                )
            )

            # Check H.264 encoder availability
            enc_output = run_command([ffmpeg_path, "-encoders"])
            h264_ok = False
            if enc_output:
                for line in enc_output.splitlines():
                    if "264" in line or "h264" in line:
                        h264_ok = True
                        break
            if h264_ok:
                items.append(
                    CapabilityItem(
                        name="FFmpeg H.264 Encoder",
                        status="SUCCESS",
                        required=True,
                        details="H.264 video encoder is available in FFmpeg",
                    )
                )
            else:
                items.append(
                    CapabilityItem(
                        name="FFmpeg H.264 Encoder",
                        status="FAILED",
                        required=True,
                        details="H.264 video encoder (e.g. libx264) not found in FFmpeg build",
                    )
                )

            # Check required filters
            filter_output = run_command([ffmpeg_path, "-filters"])
            required_filters = ["loudnorm", "sidechaincompress", "silencedetect"]
            filter_status: Dict[str, bool] = {f: False for f in required_filters}

            if filter_output:
                for line in filter_output.splitlines():
                    for filt in required_filters:
                        if filt in line:
                            filter_status[filt] = True

            missing_filters = [f for f, ok in filter_status.items() if not ok]
            if not missing_filters:
                items.append(
                    CapabilityItem(
                        name="FFmpeg Filters",
                        status="SUCCESS",
                        required=True,
                        details="All required filters (loudnorm, sidechaincompress, silencedetect) are available",
                    )
                )
            else:
                items.append(
                    CapabilityItem(
                        name="FFmpeg Filters",
                        status="FAILED",
                        required=True,
                        details=f"Missing required filters: {', '.join(missing_filters)}",
                    )
                )
        else:
            items.append(
                CapabilityItem(
                    name="FFmpeg Executable",
                    status="FAILED",
                    required=True,
                    details=f"FFmpeg found at '{ffmpeg_path}', but failed to execute check version",
                )
            )
    else:
        items.append(
            CapabilityItem(
                name="FFmpeg Executable",
                status="FAILED",
                required=True,
                details="ffmpeg executable not found in PATH or environment FFMPEG_PATH",
            )
        )

    # 8. ffprobe CLI Path Check
    ffprobe_path = get_ffprobe_path()
    if ffprobe_path:
        probe_ver = run_command([ffprobe_path, "-version"])
        if probe_ver:
            first_line = probe_ver.splitlines()[0]
            items.append(
                CapabilityItem(
                    name="FFprobe Executable",
                    status="SUCCESS",
                    required=True,
                    details=f"FFprobe found at '{ffprobe_path}'. Info: {first_line}",
                )
            )
        else:
            items.append(
                CapabilityItem(
                    name="FFprobe Executable",
                    status="FAILED",
                    required=True,
                    details=f"FFprobe found at '{ffprobe_path}', but failed to execute check version",
                )
            )
    else:
        items.append(
            CapabilityItem(
                name="FFprobe Executable",
                status="FAILED",
                required=True,
                details="ffprobe executable not found in PATH or environment FFPROBE_PATH",
            )
        )

    return CapabilityReport(items=items)
