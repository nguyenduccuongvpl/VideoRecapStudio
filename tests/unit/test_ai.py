"""Unit tests for AI Provider Registry, capability validation, and JSON Repairing/Schema verification."""

import pytest
from pydantic import BaseModel, Field
from video_recap.application.ai import (
    ProviderCapabilities,
    ModelDescriptor,
    StructuredGenerationRequest,
    ProviderRegistry,
    repair_json_output,
    parse_and_validate_json,
)
from video_recap.infrastructure.ai.mock_provider import (
    MockVideoObservationProvider,
    MockTextReasoningProvider,
)
from video_recap.domain import UnsupportedCapabilityError, InvalidStructuredOutputError


# Simple schema for testing
class DummyOutputSchema(BaseModel):
    name: str = Field(..., description="Test name.")
    score: int = Field(..., description="Test score.")


def test_provider_registry_valid_registration() -> None:
    """Verify registry accepts valid provider capability profiles and allows retrieval."""
    registry = ProviderRegistry()

    # 1. Video Provider
    video_caps = ProviderCapabilities(video_input=True, structured_output=True)
    video_desc = ModelDescriptor(name="gemini-video", provider_id="gemini", capabilities=video_caps)
    video_prov = MockVideoObservationProvider(video_desc)

    registry.register_video_provider("gemini-vid", video_prov, video_desc)
    prov, desc = registry.get_video_provider("gemini-vid")
    assert prov == video_prov
    assert desc.name == "gemini-video"

    # 2. Text Provider
    text_caps = ProviderCapabilities(structured_output=True)
    text_desc = ModelDescriptor(name="gpt-4", provider_id="openai", capabilities=text_caps)
    text_prov = MockTextReasoningProvider(text_desc)

    registry.register_text_provider("openai-text", text_prov, text_desc)
    prov_t, desc_t = registry.get_text_provider("openai-text")
    assert prov_t == text_prov
    assert desc_t.name == "gpt-4"


def test_provider_registry_unsupported_capability_raises_error() -> None:
    """Verify registry raises UnsupportedCapabilityError if descriptor has incorrect modality flags."""
    registry = ProviderRegistry()
    
    # Model does NOT support video_input but we try to register as video provider
    invalid_caps = ProviderCapabilities(video_input=False)
    invalid_desc = ModelDescriptor(name="gpt-plain", provider_id="openai", capabilities=invalid_caps)
    video_prov = MockVideoObservationProvider(invalid_desc)

    with pytest.raises(UnsupportedCapabilityError):
        registry.register_video_provider("gpt-vid", video_prov, invalid_desc)


def test_provider_missing_lookup_raises_key_error() -> None:
    """Verify registry raises KeyError when querying unregistered provider IDs."""
    registry = ProviderRegistry()
    with pytest.raises(KeyError):
        registry.get_video_provider("nonexistent")


def test_mock_provider_unsupported_capability_call_raises_error(tmp_path) -> None:
    """Verify that calling an unsupported API capability on the provider adapter throws error."""
    # Video provider with video_input=False
    caps = ProviderCapabilities(video_input=False)
    desc = ModelDescriptor(name="text-only", provider_id="test", capabilities=caps)
    prov = MockVideoObservationProvider(desc)

    fake_file = tmp_path / "vid.mp4"
    fake_file.write_text("fake video file content")

    with pytest.raises(UnsupportedCapabilityError):
        prov.observe_video(fake_file, "what is this?", DummyOutputSchema)


def test_repair_json_output_markdown_blocks() -> None:
    """Verify regex-based JSON extractor successfully cleans markdown syntax."""
    # Wrapped JSON
    dirty_json = "```json\n{\n  \"name\": \"Test\",\n  \"score\": 10\n}\n```"
    repaired = repair_json_output(dirty_json)
    assert repaired == "{\n  \"name\": \"Test\",\n  \"score\": 10\n}"

    # Extra pre/post texts
    extra_text = "Here is the response:\n{\n  \"name\": \"Alice\",\n  \"score\": 95\n} hope you enjoy!"
    repaired = repair_json_output(extra_text)
    assert repaired == "{\n  \"name\": \"Alice\",\n  \"score\": 95\n}"

    # Repaired list json
    list_json = "Some list: [1, 2, 3] end."
    repaired = repair_json_output(list_json)
    assert repaired == "[1, 2, 3]"


def test_parse_and_validate_json_valid_data() -> None:
    """Verify valid parsed fields load correctly into Pydantic schema."""
    raw = "```json\n{\"name\": \"Success\", \"score\": 100}\n```"
    result = parse_and_validate_json(raw, DummyOutputSchema)
    assert result.name == "Success"
    assert result.score == 100


def test_parse_and_validate_json_invalid_json_raises_error() -> None:
    """Verify broken syntax throws InvalidStructuredOutputError."""
    broken = "{\"name\": \"Success\", \"score\": "  # Mismatched brace & cut-off
    with pytest.raises(InvalidStructuredOutputError) as exc_info:
        parse_and_validate_json(broken, DummyOutputSchema)
    assert exc_info.value.raw_output == broken


def test_parse_and_validate_json_missing_fields_raises_error() -> None:
    """Verify type validation failures throw InvalidStructuredOutputError."""
    # Missing required field "score"
    invalid_data = "{\"name\": \"Success\"}"
    with pytest.raises(InvalidStructuredOutputError) as exc_info:
        parse_and_validate_json(invalid_data, DummyOutputSchema)
    assert "validation failed" in str(exc_info.value)
