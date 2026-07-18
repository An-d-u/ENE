from __future__ import annotations

import pytest
import requests

from src.ai.http_llm_clients import OpenAIResponseAPIClient
from src.ai.response_envelope import (
    RESPONSE_ENVELOPE_SCHEMA_NAME,
    RESPONSE_ENVELOPE_V1_SCHEMA,
    RESPONSE_REPAIR_SCHEMA_NAME,
    get_response_repair_schema,
)
from src.ai.response_protocol import ProviderRefusalError
from tests.http_structured_fixtures import (
    DummyHTTPResponse,
    legacy_final_reply,
    structured_settings,
)
from tests.structured_response_fixtures import valid_envelope_json


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
