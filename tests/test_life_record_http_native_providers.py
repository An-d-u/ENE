import asyncio
from copy import deepcopy
import json
import threading
from types import MappingProxyType

import pytest
import requests

from src.ai.http_llm_clients import (
    AnthropicClient,
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
)
from src.ai import http_llm_common
from src.ai.http_llm_common import HTTPStructuredOneShotResponse
from src.ai.response_protocol import (
    LIFE_RECORD_SCHEMA_ID,
    ResponseStatus,
    get_life_record_output_schema,
)


RAW_LIFE_RECORD = '{"entries":[],"ending_state":{}}'
SYSTEM_INSTRUCTION = "SYNTHETIC-BASE-SYSTEM\n\nSYNTHETIC-LIFE-CONTRACT"
HISTORY_SENTINEL = "SYNTHETIC-HISTORY-MUST-NOT-BE-SENT"


class _Response:
    def __init__(self, body):
        self._body = body
        self.status_code = 200
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _openai_chat():
    return OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.openai.com/v1/chat/completions",
        provider_name="openai",
    )


def _openai_responses():
    return OpenAIResponseAPIClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.openai.com/v1/responses",
        provider_name="openai",
    )


def _openai_responses_with_policy(model_name):
    return OpenAIResponseAPIClient(
        api_key="synthetic-key",
        model_name=model_name,
        endpoint="https://api.openai.com/v1/responses",
        provider_name="openai",
        generation_params={
            "temperature": 2.0,
            "top_p": 0.4,
            "max_tokens": 1234,
            "reasoning_effort": " MAX ",
        },
    )


def _anthropic():
    return AnthropicClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.anthropic.com/v1/messages",
    )


def _openai_chat_with_policy(
    *,
    provider_name="openai",
    endpoint="https://api.openai.com/v1/chat/completions",
    model_name="gpt-5.6-sol",
):
    return OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name=model_name,
        endpoint=endpoint,
        provider_name=provider_name,
        generation_params={
            "temperature": 2.0,
            "top_p": 0.4,
            "max_tokens": 1234,
            "reasoning_effort": " XHIGH ",
        },
    )


def _without_max_items(value):
    copied = deepcopy(value)

    def visit(item):
        if isinstance(item, dict):
            item.pop("maxItems", None)
            for nested in item.values():
                visit(nested)
        elif isinstance(item, list):
            for nested in item:
                visit(nested)

    visit(copied)
    return copied


def _anthropic_payload_matches(payload, schema):
    return (
        payload["system"] == SYSTEM_INSTRUCTION
        and payload["messages"]
        == [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "SYNTHETIC-LIFE-PROMPT"}
                ],
            }
        ]
        and payload["output_config"]
        == {
            "format": {
                "type": "json_schema",
                "schema": _without_max_items(schema),
            }
        }
        and "tools" not in payload
        and "tool_choice" not in payload
    )


def _chat_body(
    text=RAW_LIFE_RECORD,
    *,
    finish_reason="stop",
    refusal=None,
    usage=None,
):
    message = {"content": text}
    if refusal is not None:
        message["refusal"] = refusal
    body = {
        "choices": [{"message": message, "finish_reason": finish_reason}],
    }
    if usage is not None:
        body["usage"] = usage
    return body


def _responses_body(
    text=RAW_LIFE_RECORD,
    *,
    status="completed",
    part_type="output_text",
    finish_reason="",
    usage=None,
):
    part = {"type": part_type}
    if part_type == "refusal":
        part["refusal"] = text
    else:
        part["text"] = text
    item = {
        "type": "message",
        "status": status,
        "content": [part],
    }
    body = {"status": status, "output": [item]}
    if finish_reason:
        body["incomplete_details"] = {"reason": finish_reason}
    if usage is not None:
        body["usage"] = usage
    return body


def _anthropic_body(
    text=RAW_LIFE_RECORD,
    *,
    stop_reason="end_turn",
    usage=None,
):
    body = {
        "content": [{"type": "text", "text": text}] if text is not None else [],
        "stop_reason": stop_reason,
    }
    if usage is not None:
        body["usage"] = usage
    return body


@pytest.mark.parametrize(
    ("factory", "body", "assert_payload", "expected_usage"),
    [
        (
            _openai_chat,
            _chat_body(
                usage={
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                }
            ),
            lambda payload, schema: (
                payload["messages"]
                == [
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": "SYNTHETIC-LIFE-PROMPT"},
                ]
                and payload["response_format"]
                == {
                    "type": "json_schema",
                    "json_schema": {
                        "name": LIFE_RECORD_SCHEMA_ID,
                        "strict": True,
                        "schema": schema,
                    },
                }
            ),
            (11, 7, 18),
        ),
        (
            _openai_responses,
            _responses_body(
                usage={
                    "input_tokens": 13,
                    "output_tokens": 5,
                    "total_tokens": 18,
                }
            ),
            lambda payload, schema: (
                payload["instructions"] == SYSTEM_INSTRUCTION
                and payload["input"]
                == [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": "SYNTHETIC-LIFE-PROMPT",
                            }
                        ],
                    }
                ]
                and payload["text"]
                == {
                    "format": {
                        "type": "json_schema",
                        "name": LIFE_RECORD_SCHEMA_ID,
                        "strict": True,
                        "schema": schema,
                    }
                }
                and payload["store"] is False
            ),
            (13, 5, 18),
        ),
        (
            _anthropic,
            _anthropic_body(usage={"input_tokens": 17, "output_tokens": 3}),
            _anthropic_payload_matches,
            (17, 3, None),
        ),
    ],
    ids=("openai-chat", "openai-responses", "anthropic"),
)
def test_native_life_record_payload_is_historyless_strict_and_normalizes_usage(
    monkeypatch,
    factory,
    body,
    assert_payload,
    expected_usage,
):
    captured = []
    main_thread = threading.get_ident()

    monkeypatch.setattr(
        "src.ai.http_llm_common.build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.append((json, threading.get_ident()))
        return _Response(body)

    monkeypatch.setattr(requests, "post", fake_post)
    client = factory()
    client._history = [
        {"role": "user", "content": HISTORY_SENTINEL},
        {"role": "assistant", "content": HISTORY_SENTINEL},
    ]
    monkeypatch.setattr(
        client,
        "_parse_response",
        lambda *_args, **_kwargs: pytest.fail("일반 응답 parser를 호출하면 안 됩니다."),
    )

    result = asyncio.run(
        client.generate_life_record_once("SYNTHETIC-LIFE-PROMPT")
    )

    assert len(captured) == 1
    payload, request_thread = captured[0]
    schema = get_life_record_output_schema()
    assert assert_payload(payload, schema)
    assert request_thread != main_thread
    assert HISTORY_SENTINEL not in json.dumps(payload, ensure_ascii=False)
    assert client.get_conversation_history() == [
        {"role": "user", "content": HISTORY_SENTINEL},
        {"role": "assistant", "content": HISTORY_SENTINEL},
    ]
    assert result.text == RAW_LIFE_RECORD
    assert result.status is ResponseStatus.COMPLETE
    assert result.finish_reason in {"", "stop", "end_turn"}
    assert (
        result.token_usage.input_tokens,
        result.token_usage.output_tokens,
        result.token_usage.total_tokens,
    ) == expected_usage


@pytest.mark.parametrize(
    ("factory", "body"),
    [
        (_openai_chat, _chat_body()),
        (_openai_responses, _responses_body()),
        (_anthropic, _anthropic_body()),
    ],
    ids=("openai-chat", "openai-responses", "anthropic"),
)
def test_native_life_record_uses_a_fresh_schema_for_every_call(
    monkeypatch,
    factory,
    body,
):
    schemas = []
    monkeypatch.setattr(
        "src.ai.http_llm_common.build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )

    def fake_post(url, headers=None, json=None, timeout=None):
        if "response_format" in json:
            schema = json["response_format"]["json_schema"]["schema"]
        elif "text" in json:
            schema = json["text"]["format"]["schema"]
        else:
            schema = json["output_config"]["format"]["schema"]
        schemas.append(schema)
        return _Response(body)

    monkeypatch.setattr(requests, "post", fake_post)
    client = factory()

    asyncio.run(client.generate_life_record_once("SYNTHETIC-PROMPT-ONE"))
    schemas[0]["properties"]["entries"]["minItems"] = 9
    asyncio.run(client.generate_life_record_once("SYNTHETIC-PROMPT-TWO"))

    assert schemas[0] is not schemas[1]
    expected = get_life_record_output_schema()
    if factory is _anthropic:
        expected = _without_max_items(expected)
    assert schemas[1] == expected


def test_life_record_descriptor_defensively_freezes_nested_transport_data(
    monkeypatch,
):
    schema = get_life_record_output_schema()
    usage = {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
    }
    client = _openai_chat()
    client.extra_headers["X-Synthetic-Metadata"] = {"values": ["original"]}
    monkeypatch.setattr(
        http_llm_common,
        "get_life_record_output_schema",
        lambda: schema,
    )

    descriptor = client._build_life_record_request_descriptor("SYNTHETIC-PROMPT")
    response = HTTPStructuredOneShotResponse(
        text=RAW_LIFE_RECORD,
        status=ResponseStatus.COMPLETE,
        usage=usage,
    )

    schema["properties"]["entries"]["minItems"] = 9
    client.generation_params["max_tokens"] = 999
    client.extra_headers["X-Synthetic-Metadata"]["values"].append("mutated")
    usage["input_tokens"] = 99

    assert isinstance(descriptor.request.schema, MappingProxyType)
    assert isinstance(descriptor.request.generation_params, MappingProxyType)
    assert isinstance(descriptor.headers, MappingProxyType)
    assert isinstance(response.usage, MappingProxyType)
    assert descriptor.request.schema["properties"]["entries"]["minItems"] == 1
    assert descriptor.request.generation_params["max_tokens"] != 999
    assert descriptor.headers["X-Synthetic-Metadata"]["values"] == ("original",)
    assert response.usage["input_tokens"] == 3
    with pytest.raises(TypeError):
        descriptor.request.schema["properties"]["entries"]["minItems"] = 7
    with pytest.raises(TypeError):
        descriptor.headers["Authorization"] = "Bearer mutated"
    with pytest.raises(AttributeError):
        descriptor.headers["X-Synthetic-Metadata"]["values"].append("blocked")
    assert "synthetic-key" not in repr(descriptor)


@pytest.mark.parametrize(
    ("factory", "requester_name", "module", "body", "schema_path", "auth_header"),
    [
        (
            _openai_chat,
            "_request_openai_life_record",
            "src.ai.http_llm_openai",
            _chat_body(),
            ("response_format", "json_schema", "schema"),
            "Authorization",
        ),
        (
            _openai_responses,
            "_request_responses_life_record",
            "src.ai.http_llm_openai",
            _responses_body(),
            ("text", "format", "schema"),
            "Authorization",
        ),
        (
            _anthropic,
            "_request_anthropic_life_record",
            "src.ai.http_llm_anthropic",
            _anthropic_body(),
            ("output_config", "format", "schema"),
            "x-api-key",
        ),
    ],
    ids=("openai-chat", "openai-responses", "anthropic"),
)
def test_native_life_record_worker_uses_authoritative_descriptor_snapshot(
    monkeypatch,
    factory,
    requester_name,
    module,
    body,
    schema_path,
    auth_header,
):
    source_schema = get_life_record_output_schema()
    original_schema = deepcopy(source_schema)
    captured = {}
    worker_started = threading.Event()
    worker_release = threading.Event()
    client = factory()
    original_endpoint = client.endpoint
    original_model = client.model_name
    original_provider = client.provider_name
    original_requester = getattr(client, requester_name)

    monkeypatch.setattr(
        http_llm_common,
        "get_life_record_output_schema",
        lambda: source_schema,
    )

    def delayed_requester(descriptor):
        captured["descriptor"] = descriptor
        worker_started.set()
        assert worker_release.wait(2)
        return original_requester(descriptor)

    def fake_post(provider, endpoint, _post, **kwargs):
        captured.update(provider=provider, endpoint=endpoint, **kwargs)
        return _Response(body)

    def fake_raise_for_status(_response, provider):
        captured["status_provider"] = provider

    monkeypatch.setattr(client, requester_name, delayed_requester)
    monkeypatch.setattr(f"{module}._post_with_safe_errors", fake_post)
    monkeypatch.setattr(f"{module}._raise_for_status_with_detail", fake_raise_for_status)

    async def run_competing_mutation():
        task = asyncio.create_task(
            client.generate_life_record_once("SYNTHETIC-PROMPT")
        )
        assert await asyncio.to_thread(worker_started.wait, 2)
        client.endpoint = "https://mutated.invalid/v1/transport"
        client.model_name = "mutated-model"
        client.provider_name = "mutated-provider"
        client.wire_format = "mutated-wire"
        client.api_key = "mutated-key"
        client.generation_params["max_tokens"] = 999
        source_schema["properties"]["entries"]["minItems"] = 9
        worker_release.set()
        await task

    asyncio.run(run_competing_mutation())

    descriptor = captured["descriptor"]
    wire_schema = captured["json"]
    for key in schema_path:
        wire_schema = wire_schema[key]
    expected_schema = (
        _without_max_items(original_schema)
        if factory is _anthropic
        else original_schema
    )
    assert captured["endpoint"] == original_endpoint
    assert captured["provider"] == original_provider
    assert captured["status_provider"] == original_provider
    assert captured["json"]["model"] == original_model
    assert captured["headers"][auth_header].endswith("synthetic-key")
    assert wire_schema == expected_schema
    assert captured["timeout"] == descriptor.timeout_seconds == 60.0
    assert descriptor.capability_key == http_llm_common.build_capability_key(
        descriptor.profile,
        request_kind=descriptor.request.kind,
        schema_id=descriptor.request.schema_id,
        schema_version=descriptor.request.schema_version,
    )
    wire_schema["properties"]["entries"]["minItems"] = 11
    assert descriptor.request.schema["properties"]["entries"]["minItems"] == 1


@pytest.mark.parametrize("worker_fails", [False, True], ids=("success", "error"))
def test_life_record_cancellation_drains_worker_and_preserves_first_cancel(
    worker_fails,
    capsys,
):
    client = _openai_chat()
    original_history = [{"role": "user", "content": "SYNTHETIC-HISTORY"}]
    client._history = deepcopy(original_history)
    worker_started = threading.Event()
    worker_release = threading.Event()
    active_workers = 0
    calls = 0
    state_lock = threading.Lock()
    loop_failures = []
    cancellations = []

    def requester(_descriptor):
        nonlocal active_workers, calls
        with state_lock:
            active_workers += 1
            calls += 1
        worker_started.set()
        try:
            assert worker_release.wait(2)
            if worker_fails:
                raise RuntimeError("SYNTHETIC-WORKER-ERROR-SENTINEL")
            return HTTPStructuredOneShotResponse(
                text=RAW_LIFE_RECORD,
                status=ResponseStatus.COMPLETE,
            )
        finally:
            with state_lock:
                active_workers -= 1

    async def run_cancellation():
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(
            lambda _loop, context: loop_failures.append(context)
        )
        task = asyncio.create_task(
            client._generate_life_record_once("SYNTHETIC-PROMPT", requester)
        )
        assert await asyncio.to_thread(worker_started.wait, 2)
        task.cancel("first-cancel")
        await asyncio.sleep(0)
        assert not task.done()
        assert active_workers == 1
        heartbeat = asyncio.create_task(asyncio.sleep(0))
        await heartbeat
        assert task.cancel("second-cancel")
        await asyncio.sleep(0)
        assert not task.done()
        worker_release.set()
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task
        cancellations.append(exc_info.value)
        assert exc_info.value.args == ("first-cancel",)
        await asyncio.sleep(0)

    asyncio.run(run_cancellation())

    assert calls == 1
    assert active_workers == 0
    assert loop_failures == []
    assert client.get_conversation_history() == original_history
    assert cancellations[0].__cause__ is None
    assert cancellations[0].__context__ is None
    captured = capsys.readouterr()
    assert "SYNTHETIC-WORKER-ERROR-SENTINEL" not in captured.out
    assert "SYNTHETIC-WORKER-ERROR-SENTINEL" not in captured.err


def test_anthropic_wire_schema_removes_only_max_items_from_a_fresh_copy(
    monkeypatch,
):
    captured = {}
    raw_schema = get_life_record_output_schema()
    monkeypatch.setattr(
        "src.ai.http_llm_common.build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["schema"] = json["output_config"]["format"]["schema"]
        return _Response(_anthropic_body())

    monkeypatch.setattr(requests, "post", fake_post)

    asyncio.run(_anthropic().generate_life_record_once("SYNTHETIC-PROMPT"))

    assert raw_schema["properties"]["entries"]["maxItems"] == 24
    assert captured["schema"]["properties"]["entries"]["minItems"] == 1
    assert "maxItems" not in captured["schema"]["properties"]["entries"]
    assert get_life_record_output_schema() == raw_schema


@pytest.mark.parametrize(
    "model_name",
    (
        "claude-sonnet-4-5-synthetic",
        "claude-sonnet-4-6-synthetic",
        "claude-sonnet-4-7-synthetic",
        "claude-sonnet-5-synthetic",
    ),
)
def test_anthropic_life_record_omits_sampling_parameters_for_future_models(
    monkeypatch,
    model_name,
):
    captured = {}
    monkeypatch.setattr(
        "src.ai.http_llm_common.build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: (
            captured.update(payload=kwargs["json"])
            or _Response(_anthropic_body())
        ),
    )
    client = _anthropic()
    client.model_name = model_name

    asyncio.run(client.generate_life_record_once("SYNTHETIC-PROMPT"))

    payload = captured["payload"]
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert payload["max_tokens"] == 2048
    assert payload["output_config"]["format"]["type"] == "json_schema"


@pytest.mark.parametrize(
    ("client", "expected_sampling"),
    [
        (_openai_chat_with_policy(), False),
        (
            _openai_chat_with_policy(
                provider_name="openrouter",
                endpoint="https://openrouter.ai/api/v1/chat/completions",
                model_name="o3-mini",
            ),
            True,
        ),
    ],
    ids=("official-openai-gpt-5.6", "compatible-openrouter-gpt-5.6"),
)
def test_openai_chat_life_record_applies_model_parameter_policy(
    monkeypatch,
    client,
    expected_sampling,
):
    captured = {}
    monkeypatch.setattr(
        "src.ai.http_llm_common.build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: (
            captured.update(payload=kwargs["json"])
            or _Response(_chat_body())
        ),
    )

    asyncio.run(client.generate_life_record_once("SYNTHETIC-PROMPT"))

    payload = captured["payload"]
    if expected_sampling:
        assert payload["messages"] == [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": "SYNTHETIC-PROMPT"},
        ]
        assert payload["temperature"] == 2.0
        assert payload["top_p"] == 0.4
        assert payload["max_tokens"] == 1234
        assert "reasoning_effort" not in payload
        assert "max_completion_tokens" not in payload
    else:
        assert payload["messages"] == [
            {"role": "developer", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": "SYNTHETIC-PROMPT"},
        ]
        assert "temperature" not in payload
        assert "top_p" not in payload
        assert payload["reasoning_effort"] == "xhigh"
        assert payload["max_completion_tokens"] == 1234
        assert "max_tokens" not in payload


@pytest.mark.parametrize("model_name", ("o1-mini", "o3-2025-01-31", "o4"))
def test_openai_chat_life_record_applies_o_series_reasoning_policy(
    monkeypatch,
    model_name,
):
    captured = {}
    monkeypatch.setattr(
        "src.ai.http_llm_common.build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: (
            captured.update(payload=kwargs["json"])
            or _Response(_chat_body())
        ),
    )

    asyncio.run(
        _openai_chat_with_policy(model_name=model_name).generate_life_record_once(
            "SYNTHETIC-PROMPT"
        )
    )

    payload = captured["payload"]
    assert payload["messages"] == [
        {"role": "developer", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": "SYNTHETIC-PROMPT"},
    ]
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "max_tokens" not in payload
    assert payload["reasoning_effort"] == "medium"
    assert payload["max_completion_tokens"] == 1234


@pytest.mark.parametrize("model_name", ("o1-mini", "o3-2025-01-31", "o4"))
def test_openai_responses_life_record_applies_o_series_reasoning_policy(
    monkeypatch,
    model_name,
):
    captured = {}
    monkeypatch.setattr(
        "src.ai.http_llm_common.build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )
    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: (
            captured.update(payload=kwargs["json"])
            or _Response(_responses_body())
        ),
    )

    asyncio.run(
        _openai_responses_with_policy(model_name).generate_life_record_once(
            "SYNTHETIC-PROMPT"
        )
    )

    payload = captured["payload"]
    assert "temperature" not in payload
    assert "top_p" not in payload
    assert payload["reasoning"] == {"effort": "medium"}
    assert payload["max_output_tokens"] == 1234


@pytest.mark.parametrize(
    ("factory", "body", "status", "finish_reason"),
    [
        (_openai_chat, _chat_body(refusal="synthetic refusal"), ResponseStatus.REFUSAL, "stop"),
        (_openai_chat, _chat_body(finish_reason="length"), ResponseStatus.INCOMPLETE, "length"),
        (_openai_chat, _chat_body(text=""), ResponseStatus.EMPTY, "stop"),
        (_openai_responses, _responses_body(text="synthetic refusal", part_type="refusal"), ResponseStatus.REFUSAL, ""),
        (_openai_responses, _responses_body(status="incomplete", finish_reason="max_output_tokens"), ResponseStatus.INCOMPLETE, "max_output_tokens"),
        (_openai_responses, _responses_body(text=""), ResponseStatus.EMPTY, ""),
        (_anthropic, _anthropic_body(stop_reason="refusal"), ResponseStatus.REFUSAL, "refusal"),
        (_anthropic, _anthropic_body(stop_reason="max_tokens"), ResponseStatus.INCOMPLETE, "max_tokens"),
        (_anthropic, _anthropic_body(text=None), ResponseStatus.EMPTY, "end_turn"),
    ],
    ids=(
        "chat-refusal",
        "chat-incomplete",
        "chat-empty",
        "responses-refusal",
        "responses-incomplete",
        "responses-empty",
        "anthropic-refusal",
        "anthropic-incomplete",
        "anthropic-empty",
    ),
)
def test_native_life_record_preserves_status_and_finish_without_retry(
    monkeypatch,
    factory,
    body,
    status,
    finish_reason,
):
    calls = []
    monkeypatch.setattr(
        "src.ai.http_llm_common.build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )

    def fake_post(*args, **kwargs):
        calls.append(kwargs["json"])
        return _Response(body)

    monkeypatch.setattr(requests, "post", fake_post)

    result = asyncio.run(factory().generate_life_record_once("SYNTHETIC-PROMPT"))

    assert len(calls) == 1
    assert result.status is status
    assert result.finish_reason == finish_reason
    assert result.token_usage.input_tokens is None
    assert result.token_usage.output_tokens is None
    assert result.token_usage.total_tokens is None
