import asyncio
from copy import deepcopy
import inspect
from dataclasses import fields, replace
from types import SimpleNamespace

import pytest
from google.genai.errors import ClientError

import src.ai.llm_client as llm_client_module
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


class _AsyncModelsAdapter:
    def __init__(self, sdk):
        self._sdk = sdk

    async def generate_content(self, **kwargs):
        await asyncio.sleep(0)
        self._sdk.repair_calls.append(deepcopy(kwargs))
        if not self._sdk.repair_responses:
            raise AssertionError("준비된 async 합성 응답이 없습니다.")
        response = self._sdk.repair_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _enable_aio_models(client):
    sdk = client.client
    sync_models = _SyncModelsTrap()
    sdk.models = sync_models
    client.client.aio = SimpleNamespace(
        models=_AsyncModelsAdapter(sdk)
    )
    client._life_test_sync_models = sync_models
    return client


def _life_client(gemini_harness, *args, **kwargs):
    return _enable_aio_models(gemini_harness.client(*args, **kwargs))


class _SyncModelsTrap:
    def __init__(self):
        self.call_count = 0

    def generate_content(self, **_kwargs):
        self.call_count += 1
        raise AssertionError("동기 Gemini transport를 호출하면 안 됩니다.")


class _BlockingAsyncModels:
    def __init__(self, response):
        self.response = response
        self.calls = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate_content(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        self.started.set()
        await self.release.wait()
        return self.response


def test_gemini_life_record_awaits_aio_transport_without_blocking_event_loop(
    gemini_harness,
):
    client = _life_client(gemini_harness, [], repair_responses=[])
    sync_models = _SyncModelsTrap()
    async_models = _BlockingAsyncModels(
        gemini_harness.response("SYNTHETIC-ASYNC-RESULT")
    )
    client.client.models = sync_models
    client.client.aio = SimpleNamespace(models=async_models)

    async def exercise():
        generation = asyncio.create_task(
            client.generate_life_record_once("SYNTHETIC-ASYNC-PROMPT")
        )
        await asyncio.sleep(0)
        assert async_models.started.is_set()
        assert not generation.done()

        event_loop_progress = []

        async def tick():
            await asyncio.sleep(0)
            event_loop_progress.append("advanced")

        await asyncio.create_task(tick())
        assert event_loop_progress == ["advanced"]
        async_models.release.set()
        return await generation

    result = asyncio.run(exercise())

    assert result.text == "SYNTHETIC-ASYNC-RESULT"
    assert len(async_models.calls) == 1
    assert sync_models.call_count == 0


def test_gemini_life_record_cancellation_skips_fallback_cache_and_second_call(
    gemini_harness,
):
    client = _life_client(gemini_harness, [], repair_responses=[])
    sync_models = _SyncModelsTrap()
    async_models = _BlockingAsyncModels(
        gemini_harness.response("SYNTHETIC-CANCELLED-RESULT")
    )
    client.client.models = sync_models
    client.client.aio = SimpleNamespace(models=async_models)

    async def cancel_generation():
        generation = asyncio.create_task(
            client.generate_life_record_once("SYNTHETIC-CANCEL-PROMPT")
        )
        await asyncio.sleep(0)
        assert async_models.started.is_set()
        generation.cancel()
        with pytest.raises(asyncio.CancelledError):
            await generation
        await asyncio.sleep(0)

    asyncio.run(cancel_generation())

    assert len(async_models.calls) == 1
    assert sync_models.call_count == 0

    probe = _life_client(
        gemini_harness,
        [],
        repair_responses=[gemini_harness.response("SYNTHETIC-NATIVE-PROBE")],
    )
    result = asyncio.run(
        probe.generate_life_record_once("SYNTHETIC-NATIVE-PROBE-PROMPT")
    )
    assert result.text == "SYNTHETIC-NATIVE-PROBE"
    assert len(gemini_harness.repair_calls) == 1
    assert "response_json_schema" in gemini_harness.repair_calls[0]["config"]


def test_gemini_life_record_native_call_is_historyless_and_uses_current_contract(
    gemini_harness,
    monkeypatch,
):
    first_response = gemini_harness.response(
        '{"entries":[],"ending_state":{}}',
        input_tokens=5,
        output_tokens=7,
    )
    second_response = gemini_harness.response(
        '{"entries":[{}],"ending_state":{}}',
        input_tokens=2,
        output_tokens=3,
    )
    client = _life_client(
        gemini_harness,
        [],
        repair_responses=[first_response, second_response],
        settings={"life_contract_marker": "first"},
    )
    chat = client.chat
    system_calls = []
    schema_calls = []

    def fake_system_instruction(settings_source):
        marker = settings_source["life_contract_marker"]
        system_calls.append(marker)
        return f"SYNTHETIC-LIFE-SYSTEM-{marker}"

    real_schema_getter = get_life_record_output_schema

    def tracked_schema_getter():
        schema_calls.append(object())
        return real_schema_getter()

    monkeypatch.setattr(
        llm_client_module,
        "build_life_record_system_instruction",
        fake_system_instruction,
        raising=False,
    )
    monkeypatch.setattr(
        llm_client_module,
        "get_life_record_output_schema",
        tracked_schema_getter,
        raising=False,
    )
    monkeypatch.setattr(
        llm_client_module,
        "execute_final_response",
        lambda *_args, **_kwargs: pytest.fail("일반 final pipeline을 호출하면 안 됩니다."),
    )
    monkeypatch.setattr(
        llm_client_module,
        "parse_llm_response",
        lambda *_args, **_kwargs: pytest.fail("일반 parser를 호출하면 안 됩니다."),
    )

    first = asyncio.run(client.generate_life_record_once("SYNTHETIC-LIFE-PROMPT-ONE"))
    client.settings["life_contract_marker"] = "second"
    second = asyncio.run(client.generate_life_record_once("SYNTHETIC-LIFE-PROMPT-TWO"))

    assert first == OneShotGenerationResult(
        text='{"entries":[],"ending_state":{}}',
        status=ResponseStatus.COMPLETE,
        finish_reason="stop",
        token_usage=OneShotTokenUsage(5, 7, 12),
    )
    assert second.token_usage == OneShotTokenUsage(2, 3, 5)
    assert system_calls == ["first", "second"]
    assert len(schema_calls) == 2
    assert client.chat is chat
    assert chat.get_history_calls == []
    assert len(gemini_harness.repair_calls) == 2
    first_call, second_call = gemini_harness.repair_calls
    assert first_call["contents"] == "SYNTHETIC-LIFE-PROMPT-ONE"
    assert second_call["contents"] == "SYNTHETIC-LIFE-PROMPT-TWO"
    assert first_call["config"]["system_instruction"] == "SYNTHETIC-LIFE-SYSTEM-first"
    assert second_call["config"]["system_instruction"] == "SYNTHETIC-LIFE-SYSTEM-second"
    for call in (first_call, second_call):
        config = call["config"]
        assert config["response_mime_type"] == "application/json"
        assert config["response_json_schema"] == get_life_record_output_schema()


@pytest.mark.parametrize(
    ("text", "finish_reason", "expected_status", "expected_reason"),
    [
        ("SYNTHETIC-PARTIAL", "MAX_TOKENS", ResponseStatus.INCOMPLETE, "max_tokens"),
        ("SYNTHETIC-REFUSAL", "SAFETY", ResponseStatus.REFUSAL, "content_filter"),
        (None, "", ResponseStatus.EMPTY, ""),
        ("SYNTHETIC-UNKNOWN", "OTHER_REASON", ResponseStatus.INCOMPLETE, "other"),
    ],
)
def test_gemini_life_record_preserves_non_complete_status_without_retry(
    gemini_harness,
    text,
    finish_reason,
    expected_status,
    expected_reason,
):
    response = gemini_harness.response(text, finish_reason=finish_reason)
    client = _life_client(gemini_harness, [], repair_responses=[response])

    result = asyncio.run(client.generate_life_record_once("SYNTHETIC-STATUS-PROMPT"))

    assert result.status is expected_status
    assert result.finish_reason == expected_reason
    assert len(gemini_harness.repair_calls) == 1


class _SyntheticGeminiCapabilityError(RuntimeError):
    def __init__(self, code, message, usage_metadata=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.usage_metadata = usage_metadata


def test_gemini_life_record_explicit_capability_fallback_accumulates_and_caches(
    gemini_harness,
):
    unsupported = _SyntheticGeminiCapabilityError(
        400,
        "Unknown parameter: response_json_schema is unsupported",
        SimpleNamespace(
            prompt_token_count=2,
            candidates_token_count=1,
            total_token_count=3,
        ),
    )
    fallback = gemini_harness.response(
        "SYNTHETIC-STRICT-JSON-TEXT",
        input_tokens=5,
        output_tokens=4,
    )
    client = _life_client(
        gemini_harness,
        [],
        repair_responses=[unsupported, fallback],
    )

    result = asyncio.run(client.generate_life_record_once("SYNTHETIC-FALLBACK-PROMPT"))

    assert result.text == "SYNTHETIC-STRICT-JSON-TEXT"
    assert result.token_usage == OneShotTokenUsage(7, 5, 12)
    assert len(gemini_harness.repair_calls) == 2
    native_call, fallback_call = gemini_harness.repair_calls
    assert native_call["contents"] == fallback_call["contents"]
    assert (
        native_call["config"]["system_instruction"]
        == fallback_call["config"]["system_instruction"]
    )
    assert "response_json_schema" in native_call["config"]
    assert "response_json_schema" not in fallback_call["config"]
    assert "response_mime_type" not in fallback_call["config"]

    cached = _life_client(
        gemini_harness,
        [],
        repair_responses=[gemini_harness.response("SYNTHETIC-CACHED-STRICT-JSON")],
    )
    assert "response_json_schema" in gemini_harness.created_configs[0]
    cached_result = asyncio.run(
        cached.generate_life_record_once("SYNTHETIC-CACHED-PROMPT")
    )
    assert cached_result.text == "SYNTHETIC-CACHED-STRICT-JSON"
    assert len(gemini_harness.repair_calls) == 1
    assert "response_json_schema" not in gemini_harness.repair_calls[0]["config"]


def test_gemini_life_record_sdk_client_error_falls_back_and_keeps_unknown_usage(
    gemini_harness,
):
    unsupported = ClientError(
        400,
        {
            "error": {
                "code": 400,
                "status": "INVALID_ARGUMENT",
                "message": "Unknown parameter: response_json_schema is unsupported",
            }
        },
    )
    fallback = gemini_harness.response(
        "SYNTHETIC-SDK-FALLBACK",
        input_tokens=3,
        output_tokens=4,
    )
    client = _life_client(
        gemini_harness,
        [],
        repair_responses=[unsupported, fallback],
    )

    result = asyncio.run(client.generate_life_record_once("SYNTHETIC-SDK-PROMPT"))

    assert result.text == "SYNTHETIC-SDK-FALLBACK"
    assert result.token_usage == OneShotTokenUsage(None, None, None)
    assert len(gemini_harness.repair_calls) == 2


def test_gemini_final_reply_fallback_cache_does_not_disable_life_record_native(
    gemini_harness,
):
    unsupported = _SyntheticGeminiCapabilityError(
        400,
        "Unknown parameter: response_json_schema is unsupported",
    )
    final_client = gemini_harness.client([unsupported, "SYNTHETIC FINAL [normal]"])
    assert final_client.send_message("SYNTHETIC-FINAL-PROMPT")[0] == "SYNTHETIC FINAL"

    life_client = _life_client(
        gemini_harness,
        [],
        repair_responses=[gemini_harness.response("SYNTHETIC-LIFE-NATIVE")],
    )
    result = asyncio.run(
        life_client.generate_life_record_once("SYNTHETIC-LIFE-NATIVE-PROMPT")
    )

    assert result.text == "SYNTHETIC-LIFE-NATIVE"
    assert "response_json_schema" in gemini_harness.repair_calls[0]["config"]


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (400, "Invalid schema validation for response_json_schema"),
        (429, "response_json_schema request rate exceeded"),
        (500, "response_json_schema upstream failure"),
    ],
)
def test_gemini_life_record_non_capability_errors_are_not_retried(
    gemini_harness,
    code,
    message,
):
    client = _life_client(
        gemini_harness,
        [],
        repair_responses=[_SyntheticGeminiCapabilityError(code, message)],
    )

    with pytest.raises(RuntimeError, match="^life_record_generation_failed$"):
        asyncio.run(client.generate_life_record_once("SYNTHETIC-ERROR-PROMPT"))

    assert len(gemini_harness.repair_calls) == 1
