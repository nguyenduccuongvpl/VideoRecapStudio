"""Infrastructure Gemini Direct-Video Observation adapter using google-generativeai."""

import hashlib
import logging
import random
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple, Type, TypeVar
from pydantic import BaseModel
from video_recap.application.ai import (
    VideoObservationProvider,
    ModelDescriptor,
    ProviderResponseMetadata,
    parse_and_validate_json,
)
from video_recap.domain import (
    UnsupportedCapabilityError,
    InvalidStructuredOutputError,
)

logger = logging.getLogger("GeminiAdapter")

T = TypeVar("T", bound=BaseModel)


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA-256 hash of a file for upload deduplication."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            sha256.update(chunk)
    return sha256.hexdigest()


def adjust_timestamps_recursive(obj: Any, source_offset: float) -> Any:
    """Recursively traverse pydantic models or collections to map relative time to absolute timeline."""
    if isinstance(obj, BaseModel):
        updates = {}
        for name, value in obj:
            if name in ["timestamp", "start_time", "end_time"] and isinstance(value, (int, float)):
                updates[name] = value + source_offset
            elif name in ["start_ms", "end_ms"] and isinstance(value, (int, float)):
                updates[name] = value + (source_offset * 1000.0)
            else:
                updates[name] = adjust_timestamps_recursive(value, source_offset)
        # Avoid validation issues with config by constructing dump
        dump = obj.model_dump()
        dump.update(updates)
        return obj.__class__.model_validate(dump)
    elif isinstance(obj, list):
        return [adjust_timestamps_recursive(item, source_offset) for item in obj]
    elif isinstance(obj, dict):
        return {k: adjust_timestamps_recursive(v, source_offset) for k, v in obj.items()}
    return obj


class GeminiVideoObservationAdapter(VideoObservationProvider):
    """Google GenAI VLM provider adapter with automated file lifecycle and rate-limit backoff."""

    def __init__(
        self,
        descriptor: ModelDescriptor,
        api_key: Optional[str] = None,
        max_retries: int = 5,
        poll_interval_sec: float = 2.0,
        poll_timeout_sec: float = 300.0,
    ) -> None:
        self.descriptor = descriptor
        self.max_retries = max_retries
        self.poll_interval_sec = poll_interval_sec
        self.poll_timeout_sec = poll_timeout_sec

        import google.generativeai as genai  # type: ignore
        if api_key:
            genai.configure(api_key=api_key)

    def observe_video(
        self,
        video_path: Path | str,
        prompt: str,
        schema_cls: Type[T],
        source_offset: float = 0.0,
    ) -> Tuple[T, ProviderResponseMetadata]:
        """Upload video file to Gemini, poll status, run structured reasoning, map times, then cleanup."""
        import google.generativeai as genai
        from google.api_core.exceptions import GoogleAPIError, ResourceExhausted

        p = Path(video_path)
        if not p.exists():
            raise FileNotFoundError(f"Video file not found: {p}")

        # 1. Capability Verification
        if not self.descriptor.capabilities.video_input:
            raise UnsupportedCapabilityError(
                f"Model {self.descriptor.name} does not support video inputs."
            )

        # 2. Duplicate Check / Upload file
        file_hash = calculate_sha256(p)
        target_display_name = f"recap_hash_{file_hash}"
        
        # Check remote files cache list
        video_file = None
        try:
            for f in genai.list_files():
                if f.display_name == target_display_name and f.state.name in ["ACTIVE", "PROCESSING"]:
                    video_file = f
                    logger.info(f"Re-using cached video upload: {f.name}")
                    break
        except Exception as e:
            logger.warning(f"Failed to query existing remote files: {e}")

        # Upload if not cached
        if not video_file:
            logger.info(f"Uploading video {p.name} (size: {p.stat().st_size} bytes)...")
            video_file = genai.upload_file(path=str(p.absolute()), display_name=target_display_name)

        # 3. Poll processing status
        start_poll = time.time()
        while video_file.state.name == "PROCESSING":
            if time.time() - start_poll > self.poll_timeout_sec:
                # Cleanup and raise
                try:
                    genai.delete_file(video_file.name)
                except Exception:
                    pass
                raise TimeoutError(f"Video processing on Gemini server timed out after {self.poll_timeout_sec}s.")

            logger.info(f"Waiting for video processing... state: {video_file.state.name}")
            time.sleep(self.poll_interval_sec)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise RuntimeError(f"Video file processing failed on Gemini server: {video_file.state.name}")

        # 4. Generate structured content with retry backoff
        latency_start = time.perf_counter()
        
        def call_gemini() -> Any:
            model = genai.GenerativeModel(model_name=self.descriptor.name)
            # Instruct model to return JSON schema format
            return model.generate_content(
                [video_file, prompt],
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    response_schema=schema_cls,
                ),
            )

        # Retry loop for rate limits
        response = None
        delay = 2.0
        for attempt in range(self.max_retries):
            try:
                response = call_gemini()
                break
            except ResourceExhausted as re_err:
                if attempt == self.max_retries - 1:
                    raise re_err
                sleep_time = delay + random.uniform(0, 1.0)
                logger.warning(f"Gemini API rate limit hit. Retrying in {sleep_time:.2f}s...")
                time.sleep(sleep_time)
                delay *= 2.0
            except GoogleAPIError as api_err:
                if attempt == self.max_retries - 1:
                    raise api_err
                time.sleep(delay)
                delay *= 2.0

        if not response:
            raise RuntimeError("Gemini content generation failed with empty response.")

        latency_ms = (time.perf_counter() - latency_start) * 1000.0

        # 5. Clean up remote file
        try:
            logger.info(f"Cleaning up remote Gemini file: {video_file.name}")
            genai.delete_file(video_file.name)
        except Exception as cleanup_err:
            logger.warning(f"Failed to delete remote Gemini file: {cleanup_err}")

        # 6. Parse and Validate Output JSON
        raw_text = response.text
        parsed_result = parse_and_validate_json(raw_text, schema_cls)

        # 7. Map Relative -> Absolute Timestamps
        if source_offset > 0.0:
            parsed_result = adjust_timestamps_recursive(parsed_result, source_offset)

        # 8. Extract Token Metadata if available
        # Usage metadata may be present on the response object
        prompt_tokens = getattr(response.usage_metadata, "prompt_token_count", None)
        completion_tokens = getattr(response.usage_metadata, "candidates_token_count", None)

        req_id = getattr(response, "request_id", None)
        if not isinstance(req_id, str):
            req_id = "gemini-req-" + str(uuid_mock())

        meta = ProviderResponseMetadata(
            request_id=req_id,
            model_name=self.descriptor.name,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

        return parsed_result, meta


def uuid_mock() -> str:
    """Mock uuid generator fallback."""
    import uuid
    return str(uuid.uuid4())
