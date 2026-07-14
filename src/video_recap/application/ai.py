"""Application protocols and registry for AI providers (Gemini, OpenAI, LLM reasoning)."""

import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Protocol, Tuple, Type, TypeVar
from pydantic import BaseModel, ConfigDict, Field
from video_recap.domain import UnsupportedCapabilityError, InvalidStructuredOutputError

logger = logging.getLogger("AIApplication")

T = TypeVar("T", bound=BaseModel)


class ProviderCapabilities(BaseModel):
    """Supported modalities, token windows and limits for an AI model provider."""

    video_input: bool = Field(False, description="Supports native video ingestion.")
    image_input: bool = Field(False, description="Supports image ingestion.")
    audio_input: bool = Field(False, description="Supports audio ingestion.")
    structured_output: bool = Field(False, description="Supports JSON Schema structured outputs.")
    max_file_size_bytes: int = Field(1024 * 1024 * 1024, description="Maximum file upload size in bytes.")
    max_context_tokens: int = Field(1000000, description="Context window token size limit.")
    supported_mime_types: List[str] = Field(default_factory=list, description="Supported file MIME types.")
    batch_support: bool = Field(False, description="Supports batch requests processing.")


class ModelDescriptor(BaseModel):
    """Metadata describing a specific model registered under a provider."""

    name: str = Field(..., description="The model's API deployment or name.")
    provider_id: str = Field(..., description="Unique provider ID.")
    capabilities: ProviderCapabilities = Field(..., description="Modal capabilities description.")


class StructuredGenerationRequest(BaseModel):
    """Payload parameterizing a structured JSON generation request."""

    prompt: str = Field(..., description="Reasoning prompt instructing the model.")
    schema_cls: Type[BaseModel] = Field(..., description="Pydantic class type mapping expected output.")
    temperature: float = Field(0.0, description="Model generation temperature.")
    max_tokens: Optional[int] = Field(None, description="Completion limit token count.")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ProviderResponseMetadata(BaseModel):
    """API metadata containing request IDs and token usages for billing/metrics."""

    request_id: str = Field(..., description="Unique request identifier logged for tracking.")
    model_name: str = Field(..., description="Actual model executing the request.")
    latency_ms: float = Field(..., description="Call response latency in milliseconds.")
    prompt_tokens: Optional[int] = Field(None, description="Input token usage count.")
    completion_tokens: Optional[int] = Field(None, description="Output token usage count.")


class VideoObservationProvider(Protocol):
    """Protocol for models processing video files to extract visual event observations."""

    def observe_video(
        self,
        video_path: Path | str,
        prompt: str,
        schema_cls: Type[T],
    ) -> Tuple[T, ProviderResponseMetadata]:
        """Scan a video file to generate structured insights.

        Raises:
            UnsupportedCapabilityError: If video or structured output is unsupported.
            InvalidStructuredOutputError: If structured output schema validation fails.
        """
        ...


class TextReasoningProvider(Protocol):
    """Protocol for Large Language Models performing reasoning or text transformations."""

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Tuple[BaseModel, ProviderResponseMetadata]:
        """Process reasoning instructions to output structure.

        Raises:
            UnsupportedCapabilityError: If structured output is unsupported.
            InvalidStructuredOutputError: If structured output schema validation fails.
        """
        ...


class EmbeddingProvider(Protocol):
    """Optional protocol for computing text vector embeddings."""

    def embed_text(self, texts: List[str]) -> List[List[float]]:
        """Calculate embedding vectors for a list of string chunks."""
        ...


class ProviderRegistry:
    """Thread-safe catalog managing registrations of active AI model providers."""

    def __init__(self) -> None:
        self._video_providers: Dict[str, Tuple[VideoObservationProvider, ModelDescriptor]] = {}
        self._text_providers: Dict[str, Tuple[TextReasoningProvider, ModelDescriptor]] = {}

    def register_video_provider(
        self,
        provider_id: str,
        provider: VideoObservationProvider,
        descriptor: ModelDescriptor,
    ) -> None:
        """Register a video observation engine."""
        if not descriptor.capabilities.video_input:
            raise UnsupportedCapabilityError(f"Model {descriptor.name} does not support video inputs.")
        self._video_providers[provider_id] = (provider, descriptor)

    def register_text_provider(
        self,
        provider_id: str,
        provider: TextReasoningProvider,
        descriptor: ModelDescriptor,
    ) -> None:
        """Register a text reasoning engine."""
        self._text_providers[provider_id] = (provider, descriptor)

    def get_video_provider(self, provider_id: str) -> Tuple[VideoObservationProvider, ModelDescriptor]:
        """Lookup a registered video provider by identifier."""
        if provider_id not in self._video_providers:
            raise KeyError(f"Video provider '{provider_id}' is not registered.")
        return self._video_providers[provider_id]

    def get_text_provider(self, provider_id: str) -> Tuple[TextReasoningProvider, ModelDescriptor]:
        """Lookup a registered text provider by identifier."""
        if provider_id not in self._text_providers:
            raise KeyError(f"Text provider '{provider_id}' is not registered.")
        return self._text_providers[provider_id]


def repair_json_output(raw_text: str) -> str:
    """Clean markdown wraps and locate JSON block bounds in unstructured text.

    Args:
        raw_text: The dirty model output string.

    Returns:
        A cleaned JSON string substring ready to be parsed.
    """
    cleaned = raw_text.strip()
    
    # 1. Strip markdown ```json / ``` wraps if present
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if match:
        cleaned = match.group(1).strip()

    # 2. Extract substring between first '{' or '[' and last '}' or ']'
    # We look for '{' or '[' to handle lists/objects
    first_brace = cleaned.find("{")
    first_bracket = cleaned.find("[")
    
    start_idx = -1
    end_char = ""
    
    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        start_idx = first_brace
        end_char = "}"
    elif first_bracket != -1:
        start_idx = first_bracket
        end_char = "]"
        
    if start_idx != -1:
        end_idx = cleaned.rfind(end_char)
        if end_idx != -1 and end_idx > start_idx:
            cleaned = cleaned[start_idx : end_idx + 1]

    return cleaned


def parse_and_validate_json(raw_text: str, schema_cls: Type[T]) -> T:
    """Robust parser that applies JSON cleaning and repairs before Pydantic validation."""
    cleaned = repair_json_output(raw_text)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise InvalidStructuredOutputError(
            f"Failed to decode repaired JSON content: {e}. Raw content: {raw_text}",
            raw_output=raw_text,
        )

    try:
        return schema_cls.model_validate(data)
    except Exception as e:
        raise InvalidStructuredOutputError(
            f"Pydantic schema validation failed: {e}",
            raw_output=raw_text,
        )
