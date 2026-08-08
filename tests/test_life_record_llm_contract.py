import inspect
from dataclasses import fields, replace

import pytest

import src.ai.prompt as prompt_module
from src.ai.llm_provider import LLMClientProtocol
from src.ai.response_protocol import (
    LIFE_RECORD_OUTPUT_SCHEMA,
    LIFE_RECORD_SCHEMA_ID,
    LIFE_RECORD_SCHEMA_VERSION,
    LLMRequestKind,
    MAX_SAFE_TOKEN_COUNT,
    OneShotGenerationResult,
    OneShotTokenUsage,
    ResponseCapabilityKey,
    ResponseStatus,
    get_life_record_output_schema,
)


def test_life_record_request_kind_and_protocol_are_provider_neutral():
    method = LLMClientProtocol.generate_life_record_once

    assert LLMRequestKind.LIFE_RECORD.value == "life_record"
    assert inspect.iscoroutinefunction(method)
    assert inspect.signature(method).parameters["prompt"].annotation is str
    assert inspect.signature(method).return_annotation is OneShotGenerationResult


def test_life_record_schema_allows_only_the_exact_output_contract():
    schema = LIFE_RECORD_OUTPUT_SCHEMA

    assert schema["type"] == "object"
    assert list(schema["required"]) == ["entries", "ending_state"]
    assert schema["additionalProperties"] is False
    assert list(schema["properties"]) == ["entries", "ending_state"]

    entries = schema["properties"]["entries"]
    assert entries["type"] == "array"
    assert entries["minItems"] == 1
    assert entries["maxItems"] == 24
    assert list(entries["items"]["required"]) == [
        "started_at",
        "ended_at",
        "place",
        "activity",
    ]
    assert entries["items"]["additionalProperties"] is False
    assert list(entries["items"]["properties"]) == [
        "started_at",
        "ended_at",
        "place",
        "activity",
    ]
    assert all(
        value == {"type": "string"}
        for value in entries["items"]["properties"].values()
    )

    ending_state = schema["properties"]["ending_state"]
    assert list(ending_state["required"]) == ["place", "summary"]
    assert ending_state["additionalProperties"] is False
    assert list(ending_state["properties"]) == ["place", "summary"]
    assert all(
        value == {"type": "string"}
        for value in ending_state["properties"].values()
    )


def test_life_record_schema_export_is_read_only_and_getter_returns_fresh_dicts():
    with pytest.raises(TypeError):
        LIFE_RECORD_OUTPUT_SCHEMA["properties"]["entries"]["maxItems"] = 99

    first = get_life_record_output_schema()
    second = get_life_record_output_schema()
    first["properties"]["entries"]["maxItems"] = 99
    first["required"].append("synthetic_extra")

    assert first is not second
    assert second["properties"]["entries"]["maxItems"] == 24
    assert second["required"] == ["entries", "ending_state"]
    assert list(LIFE_RECORD_OUTPUT_SCHEMA["required"]) == [
        "entries",
        "ending_state",
    ]


def test_response_capability_key_requires_request_and_schema_identity():
    field_names = [field.name for field in fields(ResponseCapabilityKey)]
    assert field_names == [
        "provider",
        "wire_format",
        "endpoint_fingerprint",
        "model",
        "request_kind",
        "schema_id",
        "schema_version",
    ]

    required_prefix = {
        "provider": "gemini",
        "wire_format": "gemini",
        "endpoint_fingerprint": "synthetic-endpoint",
        "model": "synthetic-model",
    }
    with pytest.raises(TypeError):
        ResponseCapabilityKey(**required_prefix)

    final_key = ResponseCapabilityKey(
        **required_prefix,
        request_kind=LLMRequestKind.FINAL_REPLY,
        schema_id="response_envelope",
        schema_version="1",
    )
    life_key = ResponseCapabilityKey(
        **required_prefix,
        request_kind=LLMRequestKind.LIFE_RECORD,
        schema_id=LIFE_RECORD_SCHEMA_ID,
        schema_version=LIFE_RECORD_SCHEMA_VERSION,
    )

    cache = {final_key: "legacy", life_key: "strict_json"}
    assert cache[final_key] == "legacy"
    assert cache[life_key] == "strict_json"
    assert final_key != life_key
    assert replace(life_key, request_kind=LLMRequestKind.FINAL_REPLY) != life_key
    assert replace(life_key, schema_id="other_output") != life_key
    assert replace(life_key, schema_version="2") != life_key


def test_life_record_system_instruction_is_base_first_and_contract_last(monkeypatch):
    base = (
        "SYNTHETIC-BASE-SYSTEM-SENTINEL\n"
        "일반 대화 말투로 답하고 JSON을 사용하지 마세요."
    )
    settings = {"synthetic": True}
    captured = {}

    def fake_runtime_config(*, settings_source=None, base_path=None):
        captured["settings_source"] = settings_source
        captured["base_path"] = base_path
        return {
            "base_system_prompt": base,
            "sub_prompt_body": "SYNTHETIC-SUB-PROMPT-SENTINEL",
            "emotions": ["normal"],
            "emotion_guides": {"normal": "SYNTHETIC-EMOTION-SENTINEL"},
        }

    monkeypatch.setattr(prompt_module, "load_runtime_prompt_config", fake_runtime_config)
    monkeypatch.setattr(
        prompt_module,
        "build_analysis_system_appendix",
        lambda **_kwargs: "SYNTHETIC-ANALYSIS-SENTINEL",
    )
    monkeypatch.setattr(
        prompt_module,
        "build_legacy_response_contract_appendix",
        lambda **_kwargs: "SYNTHETIC-LEGACY-CONTRACT-SENTINEL",
    )
    monkeypatch.setattr(
        prompt_module,
        "build_structured_response_contract_appendix",
        lambda **_kwargs: "SYNTHETIC-STRUCTURED-CONTRACT-SENTINEL",
    )

    instruction = prompt_module.build_life_record_system_instruction(settings)

    assert captured == {"settings_source": settings, "base_path": None}
    assert instruction.startswith(base + "\n\n")
    assert instruction.rfind("생활 기록 전용 계약") > instruction.rfind(base)
    assert "충돌" in instruction
    assert "JSON" in instruction
    assert "entries" in instruction
    assert "ending_state" in instruction
    assert "SYNTHETIC-SUB-PROMPT-SENTINEL" not in instruction
    assert "SYNTHETIC-EMOTION-SENTINEL" not in instruction
    assert "SYNTHETIC-ANALYSIS-SENTINEL" not in instruction
    assert "SYNTHETIC-LEGACY-CONTRACT-SENTINEL" not in instruction
    assert "SYNTHETIC-STRUCTURED-CONTRACT-SENTINEL" not in instruction


def test_one_shot_result_preserves_status_finish_reason_and_normalized_usage():
    result = OneShotGenerationResult(
        text='{"entries": [], "ending_state": {}}',
        status=ResponseStatus.INCOMPLETE,
        finish_reason="max_tokens",
        token_usage=OneShotTokenUsage(
            input_tokens=5,
            output_tokens=7,
            total_tokens=12,
        ),
    )

    assert result.text
    assert result.status is ResponseStatus.INCOMPLETE
    assert result.finish_reason == "max_tokens"
    assert result.token_usage.total_tokens == 12


def test_one_shot_token_usage_preserves_none_and_safe_integer_boundaries():
    usage = OneShotTokenUsage(
        input_tokens=None,
        output_tokens=0,
        total_tokens=MAX_SAFE_TOKEN_COUNT,
    )

    assert usage.input_tokens is None
    assert usage.output_tokens == 0
    assert usage.total_tokens == MAX_SAFE_TOKEN_COUNT


@pytest.mark.parametrize("field_name", ["input_tokens", "output_tokens", "total_tokens"])
@pytest.mark.parametrize("invalid_value", [True, -1, MAX_SAFE_TOKEN_COUNT + 1])
def test_one_shot_token_usage_rejects_invalid_counts(field_name, invalid_value):
    values = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
    values[field_name] = invalid_value

    with pytest.raises(ValueError, match="^invalid_token_usage$"):
        OneShotTokenUsage(**values)
