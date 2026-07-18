from __future__ import annotations

import pytest
import requests

from src.ai.http_llm_clients import (
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
)
from src.ai.response_envelope import (
    RESPONSE_ENVELOPE_SCHEMA_NAME,
    RESPONSE_ENVELOPE_V1_SCHEMA,
    RESPONSE_REPAIR_SCHEMA_NAME,
    get_response_repair_schema,
)
from src.ai.response_protocol import (
    LLMRequestKind,
    ProviderRefusalError,
)
from tests.http_structured_fixtures import (
    DummyHTTPResponse,
    legacy_final_reply,
    structured_settings,
)
from tests.structured_response_fixtures import valid_envelope_json


_JSON_OBJECT_SYSTEM_INSTRUCTION = (
    "Return the final response as a valid JSON object."
)


def _openai_output_text_body(carrier: str, *, status: str = "completed") -> dict:
    return {
        "id": "resp_synthetic",
        "status": status,
        "output": [
            {
                "id": "msg_synthetic",
                "type": "message",
                "status": status,
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": carrier,
                        "annotations": [],
                    }
                ],
            }
        ],
    }


def _install_http_sequence(monkeypatch, responses):
    captured = []
    queue = list(responses)

    def fake_post(_url, *, headers=None, json=None, timeout=None):
        captured.append(
            {
                "url": _url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        outcome = queue.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr("src.ai.http_llm_openai.requests.post", fake_post)
    return captured


def _client(**overrides) -> OpenAIResponseAPIClient:
    values = {
        "api_key": "synthetic-key",
        "model_name": "gpt-4o-mini",
        "endpoint": "https://api.openai.com/v1/responses",
        "provider_name": "openai",
        "settings": structured_settings(),
    }
    values.update(overrides)
    return OpenAIResponseAPIClient(**values)


def test_openai_responses_final_reply_uses_strict_json_schema(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(reply="Synthetic structured reply.")
                )
            )
        ],
    )
    client = _client()

    payload = client.send_message("Synthetic neutral input.")

    assert payload[0] == "Synthetic structured reply."
    fmt = captured[0]["json"]["text"]["format"]
    assert fmt == {
        "type": "json_schema",
        "name": RESPONSE_ENVELOPE_SCHEMA_NAME,
        "strict": True,
        "schema": RESPONSE_ENVELOPE_V1_SCHEMA,
    }




def _openai_refusal_body() -> dict:
    return {
        "id": "resp_refusal_synthetic",
        "status": "completed",
        "output": [
            {
                "id": "msg_refusal_synthetic",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "refusal",
                        "refusal": "Synthetic refusal text.",
                    }
                ],
            }
        ],
    }


def test_openai_responses_refusal_is_not_parsed_or_downgraded(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(_openai_refusal_body()),
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(reply="Synthetic reply after refusal.")
                )
            ),
        ],
    )
    client = _client()

    with pytest.raises(ProviderRefusalError):
        client.send_message("Synthetic refusal request.")

    assert client.get_conversation_history() == []
    assert client.send_message("Synthetic request after refusal.")[0] == (
        "Synthetic reply after refusal."
    )
    assert len(captured) == 2
    assert all("text" in request["json"] for request in captured)


def test_openai_responses_incomplete_length_expands_budget_within_cap(monkeypatch):
    incomplete = _openai_output_text_body('{"reply":')
    incomplete_item = incomplete["output"][0]
    incomplete_item["status"] = "incomplete"
    incomplete_item["incomplete_details"] = {
        "reason": "max_output_tokens"
    }
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(incomplete),
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(reply="Regenerated synthetic reply.")
                )
            ),
        ],
    )
    client = _client(generation_params={"max_tokens": 1024})
    monkeypatch.setattr(client, "_response_output_token_cap", lambda: 1536, raising=False)

    payload = client.send_message("Synthetic length request.")

    assert payload[0] == "Regenerated synthetic reply."
    assert [request["json"]["max_output_tokens"] for request in captured] == [
        1024,
        1536,
    ]
    assert all("text" in request["json"] for request in captured)


@pytest.mark.parametrize(
    ("current_tokens", "expected_primary", "expected_retry"),
    [
        (0, None, 1536),
        (2048, 2048, 2048),
        (256, 256, 768),
    ],
)
def test_openai_responses_regeneration_budget_boundaries_preserve_snapshot(
    monkeypatch,
    current_tokens,
    expected_primary,
    expected_retry,
):
    incomplete = _openai_output_text_body('{"reply":')
    incomplete["output"][0]["status"] = "incomplete"
    incomplete["output"][0]["incomplete_details"] = {
        "reason": "max_output_tokens"
    }
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(incomplete),
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(
                        reply="Synthetic boundary retry reply."
                    )
                )
            ),
        ],
    )
    client = _client(generation_params={"max_tokens": current_tokens})
    monkeypatch.setattr(
        client,
        "_response_output_token_cap",
        lambda: 1536,
        raising=False,
    )
    original_generation_params = dict(client.generation_params)
    seen_generation_snapshots = []
    original_request = client._request_responses

    def recording_request(user_content, *, request_descriptor=None):
        if request_descriptor is not None:
            seen_generation_snapshots.append(
                request_descriptor.context.generation_params
            )
        return original_request(
            user_content,
            request_descriptor=request_descriptor,
        )

    monkeypatch.setattr(client, "_request_responses", recording_request)

    assert client.send_message("Synthetic budget boundary request.")[0] == (
        "Synthetic boundary retry reply."
    )
    assert [
        request["json"].get("max_output_tokens") for request in captured
    ] == [expected_primary, expected_retry]
    assert client.generation_params == original_generation_params
    assert seen_generation_snapshots
    assert all(
        snapshot == original_generation_params
        for snapshot in seen_generation_snapshots
    )


def test_openai_responses_repair_uses_repair_schema(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(reply="Synthetic reply needing repair.")
                )
            ),
            DummyHTTPResponse(
                _openai_output_text_body(
                    '{"thought":"Synthetic repaired thought."}'
                )
            ),
        ],
    )
    client = _client(settings=structured_settings(enable_ene_thoughts=True))

    payload = client.send_message("Synthetic repair request.")

    assert payload[6] == "Synthetic repaired thought."
    primary_format = captured[0]["json"]["text"]["format"]
    repair_format = captured[1]["json"]["text"]["format"]
    assert primary_format["name"] == RESPONSE_ENVELOPE_SCHEMA_NAME
    assert repair_format == {
        "type": "json_schema",
        "name": RESPONSE_REPAIR_SCHEMA_NAME,
        "strict": True,
        "schema": get_response_repair_schema(("thought",)),
    }


def test_openai_responses_explicit_format_unsupported_downgrades_and_caches(
    monkeypatch,
):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                {"error": {"message": "Unknown parameter: text.format"}},
                status_code=400,
            ),
            DummyHTTPResponse(
                _openai_output_text_body(
                    legacy_final_reply("Synthetic legacy fallback.")
                )
            ),
            DummyHTTPResponse(
                _openai_output_text_body(
                    legacy_final_reply("Synthetic cached legacy reply.")
                )
            ),
        ],
    )
    client = _client()

    assert client.send_message("Synthetic unsupported request.")[0] == (
        "Synthetic legacy fallback."
    )
    assert client.send_message("Synthetic cached request.")[0] == (
        "Synthetic cached legacy reply."
    )

    assert "text" in captured[0]["json"]
    assert "text" not in captured[1]["json"]
    assert "text" not in captured[2]["json"]


def test_openai_responses_timeout_keeps_native_capability(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            requests.Timeout("synthetic timeout"),
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(reply="Synthetic response after timeout.")
                )
            ),
        ],
    )
    client = _client()

    with pytest.raises(requests.Timeout, match="synthetic timeout"):
        client.send_message("Synthetic timeout request.")

    assert client.get_conversation_history() == []
    assert client.send_message("Synthetic retry after timeout.")[0] == (
        "Synthetic response after timeout."
    )
    assert all("text" in request["json"] for request in captured)


def test_openai_responses_prefers_output_item_carrier_over_compatibility_field(
    monkeypatch,
):
    body = _openai_output_text_body(
        valid_envelope_json(reply="Synthetic actual output carrier.")
    )
    body["output_text"] = valid_envelope_json(
        reply="Synthetic compatibility fallback."
    )
    _install_http_sequence(monkeypatch, [DummyHTTPResponse(body)])
    client = _client()

    payload = client.send_message("Synthetic carrier request.")

    assert payload[0] == "Synthetic actual output carrier."


def test_openai_responses_failed_item_status_is_not_treated_as_complete(
    monkeypatch,
):
    failed = _openai_output_text_body(
        valid_envelope_json(reply="Synthetic failed carrier.")
    )
    failed["output"][0]["status"] = "failed"
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(failed),
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(reply="Synthetic recovered carrier.")
                )
            ),
        ],
    )
    client = _client()

    payload = client.send_message("Synthetic failed-status request.")

    assert payload[0] == "Synthetic recovered carrier."
    assert len(captured) == 2


@pytest.mark.parametrize("status_code", [429, 503], ids=["rate_limit", "server_error"])
def test_openai_responses_http_failures_keep_native_capability(
    monkeypatch,
    status_code,
):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                {"error": {"message": "Synthetic transient failure."}},
                status_code=status_code,
            ),
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(reply="Synthetic response after failure.")
                )
            ),
        ],
    )
    client = _client()

    with pytest.raises(requests.HTTPError):
        client.send_message("Synthetic transient request.")

    assert client.get_conversation_history() == []
    assert client.send_message("Synthetic request after failure.")[0] == (
        "Synthetic response after failure."
    )
    assert all("text" in request["json"] for request in captured)


@pytest.mark.parametrize(
    ("model_name", "expected_cap"),
    [
        ("gpt-4o", 16384),
        ("gpt-4o-mini", 16384),
        ("gpt-4o-realtime-preview", 8192),
        ("synthetic-unknown-model", 8192),
    ],
)
def test_openai_responses_output_token_cap_uses_exact_known_models(
    model_name,
    expected_cap,
):
    client = _client(model_name=model_name)

    assert client._response_output_token_cap() == expected_cap


def test_openai_responses_content_filter_is_terminal_and_keeps_native(
    monkeypatch,
):
    filtered = _openai_output_text_body(
        '{"reply":"Synthetic filtered fragment."}',
        status="incomplete",
    )
    filtered["incomplete_details"] = {"reason": "content_filter"}
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(filtered),
            DummyHTTPResponse(
                _openai_output_text_body(
                    valid_envelope_json(reply="Synthetic reply after filter.")
                )
            ),
        ],
    )
    client = _client()

    with pytest.raises(ProviderRefusalError):
        client.send_message("Synthetic filtered request.")

    assert client.get_conversation_history() == []
    assert client.send_message("Synthetic request after filter.")[0] == (
        "Synthetic reply after filter."
    )
    assert all("text" in request["json"] for request in captured)


def _openai_chat_body(carrier: str, *, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl_synthetic",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": carrier,
                },
                "finish_reason": finish_reason,
            }
        ],
    }


def _openai_tool_body(
    *,
    function_name: str,
    arguments: str,
    content: str | None = None,
    finish_reason: str = "tool_calls",
) -> dict:
    return {
        "id": "chatcmpl_tool_synthetic",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": [
                        {
                            "id": "call_synthetic",
                            "type": "function",
                            "function": {
                                "name": function_name,
                                "arguments": arguments,
                            },
                        }
                    ],
                },
                "finish_reason": finish_reason,
            }
        ],
    }


def _compatible_client(*, provider_name: str, endpoint: str, **overrides):
    values = {
        "api_key": "synthetic-key",
        "model_name": "synthetic-model",
        "endpoint": endpoint,
        "provider_name": provider_name,
        "settings": structured_settings(),
    }
    values.update(overrides)
    return OpenAICompatibleClient(**values)


def _capture_compatible_payload(
    monkeypatch,
    *,
    provider_name: str,
    endpoint: str,
    response_body: dict | None = None,
):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                response_body
                or _openai_chat_body(
                    valid_envelope_json(reply="Synthetic compatible reply.")
                )
            )
        ],
    )
    client = _compatible_client(
        provider_name=provider_name,
        endpoint=endpoint,
    )

    assert client.send_message("Synthetic compatible request.")[0] == (
        "Synthetic compatible reply."
    )
    return captured[0]["json"]


def _system_content(payload: dict) -> str:
    return next(
        str(message.get("content", ""))
        for message in payload["messages"]
        if isinstance(message, dict) and message.get("role") == "system"
    )


def test_openrouter_final_reply_requires_json_schema_supporting_route(monkeypatch):
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
    )

    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": RESPONSE_ENVELOPE_SCHEMA_NAME,
            "strict": True,
            "schema": RESPONSE_ENVELOPE_V1_SCHEMA,
        },
    }
    assert payload["provider"] == {"require_parameters": True}
    assert _JSON_OBJECT_SYSTEM_INSTRUCTION not in _system_content(payload)


def test_deepseek_stable_final_reply_uses_json_object(monkeypatch):
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
    )

    assert payload["response_format"] == {"type": "json_object"}
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert _system_content(payload).count(
        _JSON_OBJECT_SYSTEM_INSTRUCTION
    ) == 1


def test_explicit_deepseek_beta_uses_forced_strict_tool(monkeypatch):
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name="custom_api",
        endpoint="https://api.deepseek.com/beta/chat/completions",
        response_body=_openai_tool_body(
            function_name=f"emit_{RESPONSE_ENVELOPE_SCHEMA_NAME}",
            arguments=valid_envelope_json(reply="Synthetic compatible reply."),
            content=valid_envelope_json(reply="Synthetic compatible reply."),
        ),
    )

    function = payload["tools"][0]["function"]
    assert function["name"] == f"emit_{RESPONSE_ENVELOPE_SCHEMA_NAME}"
    assert function["strict"] is True
    assert function["parameters"] == RESPONSE_ENVELOPE_V1_SCHEMA
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": function["name"]},
    }
    assert "response_format" not in payload
    assert _JSON_OBJECT_SYSTEM_INSTRUCTION not in _system_content(payload)


@pytest.mark.parametrize("provider_name", ["openai", "custom_api"])
def test_openai_chat_official_endpoint_uses_schema_without_router_key(
    monkeypatch,
    provider_name,
):
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name=provider_name,
        endpoint="https://api.openai.com/v1/chat/completions",
    )

    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["schema"] == (
        RESPONSE_ENVELOPE_V1_SCHEMA
    )
    assert "provider" not in payload
    assert _JSON_OBJECT_SYSTEM_INSTRUCTION not in _system_content(payload)


def test_deepseek_v1_stable_final_reply_uses_json_object(monkeypatch):
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name="deepseek",
        endpoint="https://api.deepseek.com/v1/chat/completions",
    )

    assert payload["response_format"] == {"type": "json_object"}
    assert "tools" not in payload
    assert _system_content(payload).count(
        _JSON_OBJECT_SYSTEM_INSTRUCTION
    ) == 1


def test_deepseek_json_object_instruction_copies_system_message(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(reply="Synthetic copied reply.")
                )
            )
        ],
    )
    client = _compatible_client(
        provider_name="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
    )
    source_messages = [
        {"role": "system", "content": "Synthetic frozen system."},
        {"role": "user", "content": "Synthetic frozen user input."},
    ]
    original_source_messages = [dict(message) for message in source_messages]
    monkeypatch.setattr(
        client,
        "_messages_for_openai",
        lambda *_args, **_kwargs: source_messages,
    )

    assert client.send_message("Synthetic copy request.")[0] == (
        "Synthetic copied reply."
    )

    payload_messages = captured[0]["json"]["messages"]
    assert source_messages == original_source_messages
    assert payload_messages is not source_messages
    assert payload_messages[0] is not source_messages[0]
    assert str(payload_messages[0]["content"]).count(
        _JSON_OBJECT_SYSTEM_INSTRUCTION
    ) == 1


def test_unknown_openai_compatible_endpoint_keeps_legacy_wire(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body(
                    legacy_final_reply("Synthetic unknown-endpoint reply.")
                )
            )
        ],
    )
    client = _compatible_client(
        provider_name="custom_api",
        endpoint="https://synthetic.invalid/v1/chat/completions",
    )

    assert client.send_message("Synthetic legacy request.")[0] == (
        "Synthetic unknown-endpoint reply."
    )
    payload = captured[0]["json"]
    assert "response_format" not in payload
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert "provider" not in payload
    assert _JSON_OBJECT_SYSTEM_INSTRUCTION not in _system_content(payload)


@pytest.mark.parametrize(
    ("provider_name", "endpoint"),
    [
        ("openrouter", "https://openrouter.ai/api/v1/chat/completions"),
        ("deepseek", "https://api.deepseek.com/chat/completions"),
        ("custom_api", "https://api.deepseek.com/beta/chat/completions"),
    ],
)
def test_openai_compatible_one_shot_has_no_native_response_contract(
    monkeypatch,
    provider_name,
    endpoint,
):
    captured = _install_http_sequence(
        monkeypatch,
        [DummyHTTPResponse(_openai_chat_body("Synthetic plain one-shot."))],
    )
    client = _compatible_client(
        provider_name=provider_name,
        endpoint=endpoint,
    )

    assert client._request_one_shot_raw(
        "Synthetic summary input.",
        request_kind=LLMRequestKind.SUMMARY,
    ) == "Synthetic plain one-shot."
    payload = captured[0]["json"]
    assert "response_format" not in payload
    assert "tools" not in payload
    assert "tool_choice" not in payload
    assert "provider" not in payload
    assert _JSON_OBJECT_SYSTEM_INSTRUCTION not in _system_content(payload)


def test_deepseek_strict_tool_uses_arguments_not_content(monkeypatch):
    _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_tool_body(
                    function_name=f"emit_{RESPONSE_ENVELOPE_SCHEMA_NAME}",
                    arguments=valid_envelope_json(
                        reply="Synthetic tool-argument reply."
                    ),
                    content=valid_envelope_json(
                        reply="Synthetic forbidden content reply."
                    ),
                )
            )
        ],
    )
    client = _compatible_client(
        provider_name="custom_api",
        endpoint="https://api.deepseek.com/beta/chat/completions",
    )

    payload = client.send_message("Synthetic tool carrier request.")

    assert payload[0] == "Synthetic tool-argument reply."


@pytest.mark.parametrize(
    ("function_name", "arguments"),
    [
        ("emit_wrong_schema", valid_envelope_json(reply="Synthetic wrong tool.")),
        (f"emit_{RESPONSE_ENVELOPE_SCHEMA_NAME}", ""),
    ],
    ids=["wrong_name", "empty_arguments"],
)
def test_deepseek_invalid_tool_call_does_not_fallback_to_content(
    monkeypatch,
    function_name,
    arguments,
):
    expected_name = f"emit_{RESPONSE_ENVELOPE_SCHEMA_NAME}"
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_tool_body(
                    function_name=function_name,
                    arguments=arguments,
                    content=valid_envelope_json(
                        reply="Synthetic forbidden fallback."
                    ),
                )
            ),
            DummyHTTPResponse(
                _openai_tool_body(
                    function_name=expected_name,
                    arguments=valid_envelope_json(
                        reply="Synthetic regenerated tool reply."
                    ),
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="custom_api",
        endpoint="https://api.deepseek.com/beta/chat/completions",
    )

    payload = client.send_message("Synthetic invalid tool request.")

    assert payload[0] == "Synthetic regenerated tool reply."
    assert len(captured) == 2
    assert all(request["json"]["tools"][0]["function"]["name"] == expected_name for request in captured)


def test_deepseek_malformed_json_retries_same_mode_and_endpoint(monkeypatch):
    endpoint = "https://api.deepseek.com/chat/completions"
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(_openai_chat_body("not-json")),
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(
                        reply="Synthetic regenerated JSON-object reply."
                    )
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="deepseek",
        endpoint=endpoint,
        generation_params={"max_tokens": 1024},
    )

    payload = client.send_message("Synthetic malformed JSON request.")

    assert payload[0] == "Synthetic regenerated JSON-object reply."
    assert [request["url"] for request in captured] == [endpoint, endpoint]
    assert [request["json"]["response_format"] for request in captured] == [
        {"type": "json_object"},
        {"type": "json_object"},
    ]
    assert [request["json"]["max_tokens"] for request in captured] == [
        1024,
        1024,
    ]
    assert all(
        _system_content(request["json"]).count(
            _JSON_OBJECT_SYSTEM_INSTRUCTION
        ) == 1
        for request in captured
    )


def test_openai_compatible_length_retry_expands_budget_within_cap(monkeypatch):
    endpoint = "https://api.deepseek.com/chat/completions"
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body('{"reply":', finish_reason="length")
            ),
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(reply="Synthetic length retry reply.")
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="deepseek",
        endpoint=endpoint,
        generation_params={"max_tokens": 1024},
    )
    monkeypatch.setattr(
        client,
        "_response_output_token_cap",
        lambda: 1536,
        raising=False,
    )

    payload = client.send_message("Synthetic length request.")

    assert payload[0] == "Synthetic length retry reply."
    assert [request["json"]["max_tokens"] for request in captured] == [
        1024,
        1536,
    ]
    assert all(request["url"] == endpoint for request in captured)


@pytest.mark.parametrize(
    ("current_tokens", "expected_primary", "expected_retry"),
    [
        (0, None, 1536),
        (2048, 2048, 2048),
        (256, 256, 768),
    ],
)
def test_openai_compatible_regeneration_budget_boundaries_preserve_snapshot(
    monkeypatch,
    current_tokens,
    expected_primary,
    expected_retry,
):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body('{"reply":', finish_reason="length")
            ),
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(
                        reply="Synthetic compatible boundary retry."
                    )
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
        generation_params={"max_tokens": current_tokens},
    )
    monkeypatch.setattr(
        client,
        "_response_output_token_cap",
        lambda: 1536,
        raising=False,
    )
    original_generation_params = dict(client.generation_params)
    seen_generation_snapshots = []
    original_request = client._request_openai

    def recording_request(
        user_content,
        include_sub_prompt=True,
        *,
        request_descriptor=None,
    ):
        if request_descriptor is not None:
            seen_generation_snapshots.append(
                request_descriptor.context.generation_params
            )
        return original_request(
            user_content,
            include_sub_prompt,
            request_descriptor=request_descriptor,
        )

    monkeypatch.setattr(client, "_request_openai", recording_request)

    assert client.send_message("Synthetic compatible budget boundary.")[0] == (
        "Synthetic compatible boundary retry."
    )
    assert [request["json"].get("max_tokens") for request in captured] == [
        expected_primary,
        expected_retry,
    ]
    assert client.generation_params == original_generation_params
    assert seen_generation_snapshots
    assert all(
        snapshot == original_generation_params
        for snapshot in seen_generation_snapshots
    )


def test_deepseek_json_object_instruction_is_applied_to_repair(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(
                        reply="Synthetic stable reply needing repair."
                    )
                )
            ),
            DummyHTTPResponse(
                _openai_chat_body(
                    '{"thought":"Synthetic stable repaired thought."}'
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
        settings=structured_settings(enable_ene_thoughts=True),
    )

    payload = client.send_message("Synthetic stable repair request.")

    assert payload[6] == "Synthetic stable repaired thought."
    assert [request["json"]["response_format"] for request in captured] == [
        {"type": "json_object"},
        {"type": "json_object"},
    ]
    assert all(
        _system_content(request["json"]).count(
            _JSON_OBJECT_SYSTEM_INSTRUCTION
        ) == 1
        for request in captured
    )


def test_openrouter_repair_uses_descriptor_repair_schema(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(reply="Synthetic reply needing repair.")
                )
            ),
            DummyHTTPResponse(
                _openai_chat_body('{"thought":"Synthetic repaired thought."}')
            ),
        ],
    )
    client = _compatible_client(
        provider_name="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        settings=structured_settings(enable_ene_thoughts=True),
    )

    payload = client.send_message("Synthetic OpenRouter repair request.")

    assert payload[6] == "Synthetic repaired thought."
    primary_schema = captured[0]["json"]["response_format"]["json_schema"]
    repair_schema = captured[1]["json"]["response_format"]["json_schema"]
    assert primary_schema["name"] == RESPONSE_ENVELOPE_SCHEMA_NAME
    assert repair_schema == {
        "name": RESPONSE_REPAIR_SCHEMA_NAME,
        "strict": True,
        "schema": get_response_repair_schema(("thought",)),
    }
    assert all(request["json"]["provider"] == {"require_parameters": True} for request in captured)


def test_deepseek_beta_repair_uses_descriptor_function(monkeypatch):
    primary_name = f"emit_{RESPONSE_ENVELOPE_SCHEMA_NAME}"
    repair_name = f"emit_{RESPONSE_REPAIR_SCHEMA_NAME}"
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_tool_body(
                    function_name=primary_name,
                    arguments=valid_envelope_json(
                        reply="Synthetic beta reply needing repair."
                    ),
                )
            ),
            DummyHTTPResponse(
                _openai_tool_body(
                    function_name=repair_name,
                    arguments='{"thought":"Synthetic beta repaired thought."}',
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="custom_api",
        endpoint="https://api.deepseek.com/beta/chat/completions",
        settings=structured_settings(enable_ene_thoughts=True),
    )

    payload = client.send_message("Synthetic beta repair request.")

    assert payload[6] == "Synthetic beta repaired thought."
    primary_function = captured[0]["json"]["tools"][0]["function"]
    repair_function = captured[1]["json"]["tools"][0]["function"]
    assert primary_function["name"] == primary_name
    assert primary_function["parameters"] == RESPONSE_ENVELOPE_V1_SCHEMA
    assert repair_function["name"] == repair_name
    assert repair_function["parameters"] == get_response_repair_schema(("thought",))


def test_deepseek_missing_tool_call_does_not_fallback_to_content(monkeypatch):
    expected_name = f"emit_{RESPONSE_ENVELOPE_SCHEMA_NAME}"
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(reply="Synthetic forbidden content."),
                    finish_reason="tool_calls",
                )
            ),
            DummyHTTPResponse(
                _openai_tool_body(
                    function_name=expected_name,
                    arguments=valid_envelope_json(
                        reply="Synthetic recovery after missing tool."
                    ),
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="custom_api",
        endpoint="https://api.deepseek.com/beta/chat/completions",
    )

    payload = client.send_message("Synthetic missing-tool request.")

    assert payload[0] == "Synthetic recovery after missing tool."
    assert len(captured) == 2


def test_openai_chat_refusal_is_terminal_without_capability_downgrade(monkeypatch):
    refusal = _openai_chat_body(
        valid_envelope_json(reply="Synthetic forbidden refusal content.")
    )
    refusal["choices"][0]["message"]["refusal"] = "Synthetic refusal."
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(refusal),
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(reply="Synthetic reply after refusal.")
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
    )

    with pytest.raises(ProviderRefusalError):
        client.send_message("Synthetic refusal request.")

    assert client.get_conversation_history() == []
    assert client.send_message("Synthetic request after refusal.")[0] == (
        "Synthetic reply after refusal."
    )
    assert all("response_format" in request["json"] for request in captured)


def test_openai_chat_content_filter_is_terminal_without_downgrade(monkeypatch):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body(
                    '{"reply":"Synthetic filtered fragment."}',
                    finish_reason="content_filter",
                )
            ),
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(reply="Synthetic reply after filter.")
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
    )

    with pytest.raises(ProviderRefusalError):
        client.send_message("Synthetic filtered request.")

    assert client.get_conversation_history() == []
    assert client.send_message("Synthetic request after filter.")[0] == (
        "Synthetic reply after filter."
    )
    assert all("response_format" in request["json"] for request in captured)


@pytest.mark.parametrize(
    "failure_kind",
    ["rate_limit", "timeout", "server_error"],
)
def test_openrouter_transient_failures_keep_native_capability(
    monkeypatch,
    failure_kind,
):
    if failure_kind == "timeout":
        first_outcome = requests.Timeout("synthetic timeout")
        expected_error = requests.Timeout
    else:
        status_code = 429 if failure_kind == "rate_limit" else 503
        first_outcome = DummyHTTPResponse(
            {"error": {"message": "Synthetic transient failure."}},
            status_code=status_code,
        )
        expected_error = requests.HTTPError
    captured = _install_http_sequence(
        monkeypatch,
        [
            first_outcome,
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(reply="Synthetic reply after failure.")
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
    )

    with pytest.raises(expected_error):
        client.send_message("Synthetic transient request.")

    assert client.get_conversation_history() == []
    assert client.send_message("Synthetic request after failure.")[0] == (
        "Synthetic reply after failure."
    )
    assert all("response_format" in request["json"] for request in captured)
    assert all(
        request["json"]["provider"] == {"require_parameters": True}
        for request in captured
    )


def test_openrouter_explicit_unsupported_downgrades_and_isolates_model_key(
    monkeypatch,
):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                {"error": {"message": "Unknown parameter: response_format"}},
                status_code=400,
            ),
            DummyHTTPResponse(
                _openai_chat_body(
                    legacy_final_reply("Synthetic legacy route fallback.")
                )
            ),
            DummyHTTPResponse(
                _openai_chat_body(
                    legacy_final_reply("Synthetic cached legacy route.")
                )
            ),
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(reply="Synthetic other-model native route.")
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="openrouter",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        model_name="synthetic-model-a",
    )

    assert client.send_message("Synthetic unsupported route request.")[0] == (
        "Synthetic legacy route fallback."
    )
    assert client.send_message("Synthetic cached route request.")[0] == (
        "Synthetic cached legacy route."
    )
    client.model_name = "synthetic-model-b"
    assert client.send_message("Synthetic other-model route request.")[0] == (
        "Synthetic other-model native route."
    )

    assert "response_format" in captured[0]["json"]
    assert "response_format" not in captured[1]["json"]
    assert "response_format" not in captured[2]["json"]
    assert "response_format" in captured[3]["json"]
    assert "provider" in captured[0]["json"]
    assert "provider" not in captured[1]["json"]
    assert "provider" not in captured[2]["json"]
    assert "provider" in captured[3]["json"]


@pytest.mark.parametrize(
    ("model_name", "expected_cap"),
    [
        ("synthetic-model", 8192),
        ("deepseek-v4-synthetic", 8192),
    ],
)
def test_openai_compatible_unknown_output_cap_is_conservative(
    model_name,
    expected_cap,
):
    client = _compatible_client(
        provider_name="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
        model_name=model_name,
    )

    assert client._response_output_token_cap() == expected_cap


def test_custom_exact_openrouter_endpoint_requires_supported_route(monkeypatch):
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name="custom_api",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
    )

    assert payload["response_format"]["type"] == "json_schema"
    assert payload["provider"] == {"require_parameters": True}


def test_custom_uppercase_openrouter_host_keeps_routing_requirement(monkeypatch):
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name="custom_api",
        endpoint="https://OPENROUTER.ai/api/v1/chat/completions",
    )

    assert payload["response_format"]["type"] == "json_schema"
    assert payload["provider"] == {"require_parameters": True}


def test_custom_uppercase_deepseek_stable_host_keeps_json_object(monkeypatch):
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name="custom_api",
        endpoint="https://API.DEEPSEEK.com/chat/completions",
    )

    assert payload["response_format"] == {"type": "json_object"}


def test_custom_uppercase_deepseek_beta_host_keeps_strict_tool(monkeypatch):
    function_name = f"emit_{RESPONSE_ENVELOPE_SCHEMA_NAME}"
    payload = _capture_compatible_payload(
        monkeypatch,
        provider_name="custom_api",
        endpoint="https://API.DEEPSEEK.com/beta/chat/completions",
        response_body=_openai_tool_body(
            function_name=function_name,
            arguments=valid_envelope_json(reply="Synthetic compatible reply."),
        ),
    )

    assert payload["tools"][0]["function"]["name"] == function_name
    assert payload["tool_choice"] == {
        "type": "function",
        "function": {"name": function_name},
    }


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://openrouter.ai/api/v1/chat/completions/extra",
        "https://openrouter.ai/api/v1/chat/completions?route=synthetic",
        "https://api.deepseek.com/chat/completions/extra",
        "https://api.deepseek.com/beta/chat/completions?mode=synthetic",
    ],
)
def test_custom_openai_compatible_near_miss_endpoint_stays_legacy(
    monkeypatch,
    endpoint,
):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body(
                    legacy_final_reply("Synthetic near-miss legacy reply.")
                )
            )
        ],
    )
    client = _compatible_client(
        provider_name="custom_api",
        endpoint=endpoint,
    )

    assert client.send_message("Synthetic near-miss request.")[0] == (
        "Synthetic near-miss legacy reply."
    )
    payload = captured[0]["json"]
    assert "response_format" not in payload
    assert "provider" not in payload
    assert "tools" not in payload
    assert "tool_choice" not in payload


@pytest.mark.parametrize(
    "finish_reason",
    ["error", "insufficient_system_resource"],
)
def test_openai_compatible_noncomplete_finish_reason_regenerates_without_expansion(
    monkeypatch,
    finish_reason,
):
    captured = _install_http_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(
                        reply="Synthetic carrier from incomplete response."
                    ),
                    finish_reason=finish_reason,
                )
            ),
            DummyHTTPResponse(
                _openai_chat_body(
                    valid_envelope_json(
                        reply="Synthetic regenerated complete response."
                    )
                )
            ),
        ],
    )
    client = _compatible_client(
        provider_name="deepseek",
        endpoint="https://api.deepseek.com/chat/completions",
        generation_params={"max_tokens": 1024},
    )

    payload = client.send_message("Synthetic incomplete-reason request.")

    assert payload[0] == "Synthetic regenerated complete response."
    assert [request["json"]["response_format"] for request in captured] == [
        {"type": "json_object"},
        {"type": "json_object"},
    ]
    assert [request["json"]["max_tokens"] for request in captured] == [
        1024,
        1024,
    ]
