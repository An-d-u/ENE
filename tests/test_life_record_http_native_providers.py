import asyncio
import json
import threading

import pytest
import requests

from src.ai.http_llm_clients import (
    AnthropicClient,
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
)
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


def _anthropic():
    return AnthropicClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.anthropic.com/v1/messages",
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
            lambda payload, schema: (
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
                        "schema": schema,
                    }
                }
                and "tools" not in payload
                and "tool_choice" not in payload
            ),
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
    schemas[0]["properties"]["entries"]["maxItems"] = 99
    asyncio.run(client.generate_life_record_once("SYNTHETIC-PROMPT-TWO"))

    assert schemas[0] is not schemas[1]
    assert schemas[1] == get_life_record_output_schema()


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
