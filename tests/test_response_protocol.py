from dataclasses import FrozenInstanceError

import pytest

from src.ai.response_protocol import (
    LLMRequestKind,
    ProviderRefusalError,
    ProviderResponse,
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    ResponseDeliveryMetadata,
    ResponseMode,
    ResponseStatus,
    StructuredOutputUnsupported,
)


def test_response_protocol_uses_content_free_delivery_metadata_defaults():
    metadata = ResponseDeliveryMetadata.empty()

    assert metadata.response_mode == ""
    assert metadata.schema_version == ""
    assert metadata.promises_authoritative is False
    assert metadata.repair_performed is False
    assert not hasattr(metadata, "reply")
    assert not hasattr(metadata, "prompt")

    with pytest.raises(FrozenInstanceError):
        metadata.response_mode = "json_schema"


def test_request_kinds_and_response_modes_are_explicit():
    assert RESPONSE_ENVELOPE_SCHEMA_VERSION == "1"
    assert {item.value for item in LLMRequestKind} == {
        "final_reply", "summary", "decision", "markdown", "plain_text"
    }
    assert {item.value for item in ResponseMode} == {
        "json_schema", "strict_tool", "json_object", "legacy_tags"
    }
    assert {item.value for item in ResponseStatus} == {
        "complete", "incomplete", "refusal", "empty"
    }


def test_provider_response_keeps_carrier_while_errors_omit_raw_body():
    response = ProviderResponse(
        carrier="synthetic carrier",
        status=ResponseStatus.COMPLETE,
        mode=ResponseMode.JSON_SCHEMA,
    )
    error = StructuredOutputUnsupported(ResponseMode.JSON_SCHEMA, provider="openai")

    assert response.carrier == "synthetic carrier"
    assert response.finish_reason == ""
    assert response.usage is None
    with pytest.raises(FrozenInstanceError):
        response.carrier = "changed carrier"
    assert str(error) == "structured_output_unsupported"
    assert error.mode is ResponseMode.JSON_SCHEMA
    assert error.provider == "openai"
    assert not hasattr(error, "response_body")
    assert issubclass(ProviderRefusalError, RuntimeError)

def test_provider_refusal_error_omits_supplied_provider_content():
    error = ProviderRefusalError()

    assert str(error) == "provider_refusal"
    assert error.args == ("provider_refusal",)
    with pytest.raises(TypeError):
        ProviderRefusalError("synthetic raw payload")
