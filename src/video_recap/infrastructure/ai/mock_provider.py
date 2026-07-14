"""Infrastructure mock implementation of AI providers for unit testing."""

import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Type
from pydantic import BaseModel
from video_recap.application.ai import (
    VideoObservationProvider,
    TextReasoningProvider,
    StructuredGenerationRequest,
    ProviderResponseMetadata,
    ModelDescriptor,
)
from video_recap.domain import UnsupportedCapabilityError, InvalidStructuredOutputError

# A helper mapping to automatically instantiate schemas with dummy data for mock testing
def populate_mock_schema(schema_cls: Type[BaseModel]) -> BaseModel:
    """Recursively instantiate a Pydantic schema class with default or empty field values."""
    fields = {}
    for name, field in schema_cls.model_fields.items():
        # Retrieve field type or default
        field_type = field.annotation
        
        # Check defaults
        if field.default is not None and str(field.default) != "PydanticUndefined":
            fields[name] = field.default
            continue
        if field.default_factory is not None:
            fields[name] = field.default_factory()
            continue

        # Handle simple types
        if field_type is int:
            fields[name] = 0
        elif field_type is float:
            fields[name] = 0.0
        elif field_type is str:
            fields[name] = "mock_value"
        elif field_type is bool:
            fields[name] = False
        elif getattr(field_type, "__origin__", None) is list:
            fields[name] = []
        elif getattr(field_type, "__origin__", None) is dict:
            fields[name] = {}
        elif issubclass(field_type, BaseModel):
            fields[name] = populate_mock_schema(field_type)
        else:
            fields[name] = None
    return schema_cls.model_validate(fields)


class MockVideoObservationProvider(VideoObservationProvider):
    """Simulates video understanding models with configurable mock outputs and capability checks."""

    def __init__(self, descriptor: ModelDescriptor) -> None:
        self.descriptor = descriptor
        self._preset_response: Optional[BaseModel] = None
        self._preset_raw_json: Optional[str] = None

    def set_preset_response(self, response: BaseModel) -> None:
        self._preset_response = response

    def set_preset_raw_json(self, raw_json: str) -> None:
        self._preset_raw_json = raw_json

    def observe_video(
        self,
        video_path: Path | str,
        prompt: str,
        schema_cls: Type[BaseModel],
    ) -> Tuple[BaseModel, ProviderResponseMetadata]:
        # 1. Capability check
        if not self.descriptor.capabilities.video_input:
            raise UnsupportedCapabilityError(
                f"Model {self.descriptor.name} does not support video modality."
            )

        # 2. Log request details without secret tokens or actual video payload
        req_id = str(uuid.uuid4())
        file_size = Path(video_path).stat().st_size if Path(video_path).exists() else 0
        print(f"[AI Observation Input Log] Request ID: {req_id} | File Size: {file_size} bytes")

        # 3. Handle preset raw JSON parsing (testing invalid outputs)
        if self._preset_raw_json is not None:
            from video_recap.application.ai import parse_and_validate_json
            result = parse_and_validate_json(self._preset_raw_json, schema_cls)
            meta = ProviderResponseMetadata(
                request_id=req_id,
                model_name=self.descriptor.name,
                latency_ms=100.0,
                prompt_tokens=500,
                completion_tokens=200,
            )
            return result, meta

        # 4. Return preset response or generate mock
        response = self._preset_response or populate_mock_schema(schema_cls)
        meta = ProviderResponseMetadata(
            request_id=req_id,
            model_name=self.descriptor.name,
            latency_ms=250.0,
            prompt_tokens=1000,
            completion_tokens=350,
        )
        return response, meta


class MockTextReasoningProvider(TextReasoningProvider):
    """Simulates text reasoning LLMs with configuration checks and mock outputs."""

    def __init__(self, descriptor: ModelDescriptor) -> None:
        self.descriptor = descriptor
        self._preset_response: Optional[BaseModel] = None
        self._preset_raw_json: Optional[str] = None

    def set_preset_response(self, response: BaseModel) -> None:
        self._preset_response = response

    def set_preset_raw_json(self, raw_json: str) -> None:
        self._preset_raw_json = raw_json

    def generate_structured(
        self,
        request: StructuredGenerationRequest,
    ) -> Tuple[BaseModel, ProviderResponseMetadata]:
        # 1. Capability check
        if not self.descriptor.capabilities.structured_output:
            raise UnsupportedCapabilityError(
                f"Model {self.descriptor.name} does not support structured outputs."
            )

        req_id = str(uuid.uuid4())
        print(f"[AI Reasoning Input Log] Request ID: {req_id} | Prompt length: {len(request.prompt)}")

        # 2. Handle preset raw JSON parsing (testing invalid outputs)
        if self._preset_raw_json is not None:
            from video_recap.application.ai import parse_and_validate_json
            result = parse_and_validate_json(self._preset_raw_json, request.schema_cls)
            meta = ProviderResponseMetadata(
                request_id=req_id,
                model_name=self.descriptor.name,
                latency_ms=50.0,
                prompt_tokens=150,
                completion_tokens=80,
            )
            return result, meta

        # 3. Return preset response or generate mock
        response = self._preset_response or populate_mock_schema(request.schema_cls)
        meta = ProviderResponseMetadata(
            request_id=req_id,
            model_name=self.descriptor.name,
            latency_ms=120.0,
            prompt_tokens=400,
            completion_tokens=150,
        )
        return response, meta
