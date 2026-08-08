from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
import inspect
import json as json_module
import threading
from typing import get_type_hints

import pytest
import requests

from src.ai import http_llm_common
from src.ai.http_llm_anthropic import AnthropicClient
from src.ai.http_llm_custom_providers import CohereClient, GoogleCloudClient
from src.ai.http_llm_ollama import OllamaClient
from src.ai.http_llm_openai import (
    MistralClient,
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
)
from src.ai.response_protocol import (
    LIFE_RECORD_SCHEMA_ID,
    LIFE_RECORD_SCHEMA_VERSION,
    LLMRequestKind,
    OneShotGenerationResult,
    ResponseMode,
    ResponseStatus,
    get_life_record_output_schema,
)
from tests.http_structured_fixtures import DummyHTTPResponse


SYSTEM_INSTRUCTION = "SYNTHETIC-BASE-FIRST\n\nSYNTHETIC-LIFE-CONTRACT-LAST"
PROMPT = "SYNTHETIC-LIFE-RECORD-PROMPT"
RAW_LIFE_RECORD = '{"entries":[],"ending_state":{}}'
EXCLUDED_SENTINELS = (
    "SYNTHETIC-SUB-PROMPT-SENTINEL",
    "SYNTHETIC-RESPONSE-CONTRACT-SENTINEL",
    "SYNTHETIC-ANALYSIS-SENTINEL",
    "SYNTHETIC-MEMORY-SENTINEL",
)


def _client(
    *,
    endpoint: str = "http://127.0.0.1:11434/api/chat",
) -> OllamaClient:
    client = OllamaClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint=endpoint,
        generation_params={
            "temperature": 0.4,
            "top_p": 0.8,
            "max_tokens": 321,
        },
    )
    client._history = [
        {"role": "user", "content": EXCLUDED_SENTINELS[-1]},
        {"role": "assistant", "content": EXCLUDED_SENTINELS[-1]},
    ]
    return client


def _ollama_body(
    text: str = RAW_LIFE_RECORD,
    *,
    done: bool = True,
    done_reason: str = "stop",
    prompt_eval_count: object = None,
    eval_count: object = None,
    total_tokens: object = None,
) -> dict:
    body = {
        "message": {"content": text},
        "done": done,
        "done_reason": done_reason,
    }
    if prompt_eval_count is not None:
        body["prompt_eval_count"] = prompt_eval_count
    if eval_count is not None:
        body["eval_count"] = eval_count
    if total_tokens is not None:
        body["total_tokens"] = total_tokens
    return body


def _install_sequence(monkeypatch, responses):
    captured = []
    queue = list(responses)

    def fake_post(url, *, headers=None, json=None, timeout=None):
        captured.append(
            {
                "url": url,
                "headers": deepcopy(headers),
                "json": deepcopy(json),
                "timeout": timeout,
            }
        )
        return queue.pop(0)

    monkeypatch.setattr("src.ai.http_llm_ollama.requests.post", fake_post)
    return captured


def _capture_single_post(monkeypatch, target: str, body: dict):
    captured = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        captured.append(
            {
                "url": url,
                "headers": deepcopy(headers),
                "json": deepcopy(json),
                "timeout": timeout,
            }
        )
        return DummyHTTPResponse(body)

    monkeypatch.setattr(target, fake_post)
    return captured


def _payload_contains_value(value, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(
            _payload_contains_value(nested, expected)
            for nested in value.values()
        )
    if isinstance(value, list):
        return any(
            _payload_contains_value(nested, expected)
            for nested in value
        )
    return False


def _patch_system_instruction(monkeypatch):
    monkeypatch.setattr(
        http_llm_common,
        "build_life_record_system_instruction",
        lambda _settings: SYSTEM_INSTRUCTION,
    )


def _openai_chat_client() -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.openai.com/v1/chat/completions",
        provider_name="openai",
    )


def _openai_responses_client() -> OpenAIResponseAPIClient:
    return OpenAIResponseAPIClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.openai.com/v1/responses",
        provider_name="openai",
    )


def _anthropic_client() -> AnthropicClient:
    return AnthropicClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.anthropic.com/v1/messages",
    )


def _mistral_client(
    endpoint: str = "https://api.mistral.ai/v1/chat/completions",
) -> MistralClient:
    return MistralClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint=endpoint,
        provider_name="custom_api",
        generation_params={
            "temperature": 0.4,
            "top_p": 0.8,
            "max_tokens": 321,
        },
    )


def _google_client(
    endpoint: str = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/{model}:generateContent"
    ),
) -> GoogleCloudClient:
    return GoogleCloudClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint=endpoint,
        generation_params={
            "temperature": 0.4,
            "top_p": 0.8,
            "max_tokens": 321,
        },
    )


def _cohere_client(
    endpoint: str = "https://api.cohere.com/v1/chat",
) -> CohereClient:
    return CohereClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint=endpoint,
        generation_params={
            "temperature": 0.4,
            "top_p": 0.8,
            "max_tokens": 321,
        },
    )


def _openai_chat_body() -> dict:
    return {
        "choices": [
            {
                "message": {"content": RAW_LIFE_RECORD},
                "finish_reason": "stop",
            }
        ]
    }


def _openai_responses_body() -> dict:
    return {
        "status": "completed",
        "output": [
            {
                "type": "message",
                "status": "completed",
                "content": [
                    {"type": "output_text", "text": RAW_LIFE_RECORD}
                ],
            }
        ],
    }


def _anthropic_body() -> dict:
    return {
        "content": [{"type": "text", "text": RAW_LIFE_RECORD}],
        "stop_reason": "end_turn",
    }


@pytest.mark.parametrize(
    (
        "factory",
        "post_target",
        "unsupported_parameter",
        "success_body",
        "native_carrier",
        "content_snapshot",
    ),
    [
        (
            _openai_chat_client,
            "src.ai.http_llm_openai.requests.post",
            "response_format",
            _openai_chat_body(),
            "response_format",
            lambda payload: (payload["messages"][0], payload["messages"][-1]),
        ),
        (
            _openai_responses_client,
            "src.ai.http_llm_openai.requests.post",
            "text.format",
            _openai_responses_body(),
            "text",
            lambda payload: (payload["instructions"], payload["input"]),
        ),
        (
            _anthropic_client,
            "src.ai.http_llm_anthropic.requests.post",
            "output_config.format",
            _anthropic_body(),
            "output_config",
            lambda payload: (payload["system"], payload["messages"]),
        ),
    ],
    ids=("openai-chat", "openai-responses", "anthropic"),
)
def test_native_http_serializers_remove_schema_carrier_for_strict_fallback(
    monkeypatch,
    factory,
    post_target,
    unsupported_parameter,
    success_body,
    native_carrier,
    content_snapshot,
):
    _patch_system_instruction(monkeypatch)
    captured = []
    responses = [
        DummyHTTPResponse(
            status_code=400,
            text=f"Unknown parameter: {unsupported_parameter}",
        ),
        DummyHTTPResponse(success_body),
    ]

    def fake_post(url, *, headers=None, json=None, timeout=None):
        captured.append(deepcopy(json))
        return responses.pop(0)

    monkeypatch.setattr(post_target, fake_post)

    result = asyncio.run(factory().generate_life_record_once(PROMPT))

    assert result.text == RAW_LIFE_RECORD
    assert len(captured) == 2
    assert native_carrier in captured[0]
    assert native_carrier not in captured[1]
    assert content_snapshot(captured[0]) == content_snapshot(captured[1])


def test_life_record_descriptor_resolves_verified_and_unknown_profiles_by_life_key(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    native = _client()
    strict = _client(endpoint="https://ollama.example.invalid/api/chat")
    non_schema_native = OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.deepseek.com/v1/chat/completions",
        provider_name="deepseek",
    )

    native_descriptor = native._build_life_record_request_descriptor(PROMPT)
    strict_descriptor = strict._build_life_record_request_descriptor(PROMPT)
    non_schema_descriptor = (
        non_schema_native._build_life_record_request_descriptor(PROMPT)
    )
    final_key = http_llm_common.build_capability_key(native_descriptor.profile)
    http_llm_common._HTTP_RESPONSE_CAPABILITY_REGISTRY.mark_legacy(final_key)
    native_after_final_downgrade = native._build_life_record_request_descriptor(
        PROMPT
    )

    assert native_descriptor.response_mode is ResponseMode.JSON_SCHEMA
    assert native_after_final_downgrade.response_mode is ResponseMode.JSON_SCHEMA
    assert strict_descriptor.response_mode is ResponseMode.LEGACY_TAGS
    assert non_schema_descriptor.response_mode is ResponseMode.LEGACY_TAGS
    assert native_descriptor.capability_key.request_kind is LLMRequestKind.LIFE_RECORD
    assert native_descriptor.capability_key.schema_id == LIFE_RECORD_SCHEMA_ID
    assert native_descriptor.capability_key.schema_version == LIFE_RECORD_SCHEMA_VERSION
    assert native_descriptor.request.system_instruction == SYSTEM_INSTRUCTION


@pytest.mark.parametrize(
    ("key_field", "other_value"),
    [
        ("request_kind", LLMRequestKind.DECISION),
        ("schema_id", "synthetic_other_schema"),
        ("schema_version", "synthetic-v2"),
    ],
    ids=("request-kind", "schema-id", "schema-version"),
)
def test_life_record_capability_cache_isolated_by_complete_key(
    monkeypatch,
    key_field,
    other_value,
):
    _patch_system_instruction(monkeypatch)
    client = _client()
    descriptor = client._build_life_record_request_descriptor(PROMPT)
    other_key = replace(
        descriptor.capability_key,
        **{key_field: other_value},
    )

    http_llm_common._HTTP_RESPONSE_CAPABILITY_REGISTRY.mark_legacy(other_key)

    current = client._build_life_record_request_descriptor(PROMPT)
    assert current.response_mode is ResponseMode.JSON_SCHEMA
    assert (
        http_llm_common._HTTP_RESPONSE_CAPABILITY_REGISTRY.resolve(
            descriptor.profile,
            capability_key=other_key,
        )
        is ResponseMode.LEGACY_TAGS
    )

    http_llm_common.clear_http_response_capability_cache()
    http_llm_common._HTTP_RESPONSE_CAPABILITY_REGISTRY.mark_legacy(
        descriptor.capability_key
    )

    current = client._build_life_record_request_descriptor(PROMPT)
    assert current.response_mode is ResponseMode.LEGACY_TAGS
    assert (
        http_llm_common._HTTP_RESPONSE_CAPABILITY_REGISTRY.resolve(
            descriptor.profile,
            capability_key=other_key,
        )
        is ResponseMode.JSON_SCHEMA
    )


@pytest.mark.parametrize(
    "factory",
    [_mistral_client, _google_client, _cohere_client],
    ids=("mistral", "google-cloud", "cohere"),
)
def test_remaining_http_clients_expose_async_life_record_generation(factory):
    client = factory()

    assert inspect.iscoroutinefunction(client.generate_life_record_once)
    assert (
        get_type_hints(client.generate_life_record_once).get("return")
        is OneShotGenerationResult
    )


@pytest.mark.parametrize(
    ("factory", "expected_mode"),
    [
        (_mistral_client, ResponseMode.JSON_SCHEMA),
        (_google_client, ResponseMode.JSON_SCHEMA),
        (_cohere_client, ResponseMode.JSON_SCHEMA),
        (
            lambda: _cohere_client("https://api.cohere.ai/v1/chat"),
            ResponseMode.JSON_SCHEMA,
        ),
        (
            lambda: _mistral_client(
                "https://gateway.example.invalid/v1/chat/completions"
            ),
            ResponseMode.LEGACY_TAGS,
        ),
        (
            lambda: _google_client(
                "https://gateway.example.invalid/v1beta/models/"
                "{model}:generateContent"
            ),
            ResponseMode.LEGACY_TAGS,
        ),
        (
            lambda: _cohere_client("https://gateway.example.invalid/v1/chat"),
            ResponseMode.LEGACY_TAGS,
        ),
    ],
    ids=(
        "mistral-official",
        "google-official",
        "cohere-official",
        "cohere-official-ai-host",
        "mistral-unverified",
        "google-unverified",
        "cohere-unverified",
    ),
)
def test_remaining_life_record_profiles_require_verified_official_endpoint(
    monkeypatch,
    factory,
    expected_mode,
):
    _patch_system_instruction(monkeypatch)

    descriptor = factory()._build_life_record_request_descriptor(PROMPT)

    assert descriptor.response_mode is expected_mode
    assert descriptor.capability_key.request_kind is LLMRequestKind.LIFE_RECORD
    assert descriptor.capability_key.schema_id == LIFE_RECORD_SCHEMA_ID
    assert descriptor.capability_key.schema_version == LIFE_RECORD_SCHEMA_VERSION


def test_custom_anthropic_requires_exact_official_endpoint_for_native(monkeypatch):
    _patch_system_instruction(monkeypatch)
    official = _anthropic_client()
    official.provider_name = "custom_api"
    arbitrary = _anthropic_client()
    arbitrary.provider_name = "custom_api"
    arbitrary.endpoint = "https://gateway.example.invalid/v1/messages"

    assert (
        official._build_life_record_request_descriptor(PROMPT).response_mode
        is ResponseMode.JSON_SCHEMA
    )
    assert (
        arbitrary._build_life_record_request_descriptor(PROMPT).response_mode
        is ResponseMode.LEGACY_TAGS
    )


@pytest.mark.parametrize(
    ("factory", "official_endpoint", "arbitrary_endpoint"),
    [
        (
            lambda endpoint: OpenAICompatibleClient(
                api_key="synthetic-key",
                model_name="synthetic-model",
                endpoint=endpoint,
                provider_name="custom_api",
            ),
            "https://api.openai.com/v1/chat/completions",
            "https://gateway.example.invalid/v1/chat/completions",
        ),
        (
            lambda endpoint: OpenAIResponseAPIClient(
                api_key="synthetic-key",
                model_name="synthetic-model",
                endpoint=endpoint,
                provider_name="custom_api",
            ),
            "https://api.openai.com/v1/responses",
            "https://gateway.example.invalid/v1/responses",
        ),
    ],
    ids=("openai-chat", "openai-responses"),
)
def test_custom_openai_wire_name_does_not_elevate_arbitrary_endpoint(
    monkeypatch,
    factory,
    official_endpoint,
    arbitrary_endpoint,
):
    _patch_system_instruction(monkeypatch)

    official_mode = factory(
        official_endpoint
    )._build_life_record_request_descriptor(PROMPT).response_mode
    arbitrary_mode = factory(
        arbitrary_endpoint
    )._build_life_record_request_descriptor(PROMPT).response_mode

    assert official_mode is ResponseMode.JSON_SCHEMA
    assert arbitrary_mode is ResponseMode.LEGACY_TAGS


def test_mistral_official_life_record_uses_native_schema_without_history(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    captured = _capture_single_post(
        monkeypatch,
        "src.ai.http_llm_openai.requests.post",
        {
            "choices": [
                {
                    "message": {"content": RAW_LIFE_RECORD},
                    "finish_reason": "length",
                }
            ],
            "usage": {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
            },
        },
    )
    client = _mistral_client()
    client._history = [{"role": "user", "content": EXCLUDED_SENTINELS[-1]}]

    result = asyncio.run(client.generate_life_record_once(PROMPT))

    payload = captured[0]["json"]
    assert payload["messages"] == [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": PROMPT},
    ]
    assert payload["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": LIFE_RECORD_SCHEMA_ID,
            "strict": True,
            "schema": get_life_record_output_schema(),
        },
    }
    assert "tools" not in payload
    assert all(
        sentinel not in json_module.dumps(payload, ensure_ascii=False)
        for sentinel in EXCLUDED_SENTINELS
    )
    assert result.status is ResponseStatus.INCOMPLETE
    assert result.finish_reason == "length"
    assert (
        result.token_usage.input_tokens,
        result.token_usage.output_tokens,
        result.token_usage.total_tokens,
    ) == (5, 3, 8)


def test_google_official_life_record_uses_native_schema_without_history(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    captured = _capture_single_post(
        monkeypatch,
        "src.ai.http_llm_custom_providers.requests.post",
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": RAW_LIFE_RECORD}],
                    },
                    "finishReason": "MAX_TOKENS",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 7,
                "candidatesTokenCount": 4,
                "totalTokenCount": 11,
            },
        },
    )
    client = _google_client()
    client._history = [{"role": "user", "content": EXCLUDED_SENTINELS[-1]}]

    result = asyncio.run(client.generate_life_record_once(PROMPT))

    payload = captured[0]["json"]
    assert payload["systemInstruction"] == {
        "parts": [{"text": SYSTEM_INSTRUCTION}]
    }
    assert payload["contents"] == [
        {"role": "user", "parts": [{"text": PROMPT}]}
    ]
    assert payload["generationConfig"]["responseFormat"] == {
        "text": {
            "mimeType": "application/json",
            "schema": get_life_record_output_schema(),
        }
    }
    assert "tools" not in payload
    assert all(
        sentinel not in json_module.dumps(payload, ensure_ascii=False)
        for sentinel in EXCLUDED_SENTINELS
    )
    assert result.status is ResponseStatus.INCOMPLETE
    assert result.finish_reason == "max_tokens"
    assert (
        result.token_usage.input_tokens,
        result.token_usage.output_tokens,
        result.token_usage.total_tokens,
    ) == (7, 4, 11)


@pytest.mark.parametrize(
    "finish_reason",
    (
        "SAFETY",
        "RECITATION",
        "BLOCKLIST",
        "PROHIBITED_CONTENT",
        "SPII",
        "IMAGE_SAFETY",
        "IMAGE_PROHIBITED_CONTENT",
        "IMAGE_RECITATION",
    ),
)
def test_google_life_record_maps_filtered_finish_reasons_like_gemini_sdk(
    monkeypatch,
    finish_reason,
):
    _patch_system_instruction(monkeypatch)
    _capture_single_post(
        monkeypatch,
        "src.ai.http_llm_custom_providers.requests.post",
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": RAW_LIFE_RECORD}]},
                    "finishReason": finish_reason,
                }
            ]
        },
    )

    result = asyncio.run(_google_client().generate_life_record_once(PROMPT))

    assert result.status is ResponseStatus.REFUSAL
    assert result.finish_reason == "content_filter"


def test_google_life_record_treats_unspecified_finish_reason_as_normal(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    _capture_single_post(
        monkeypatch,
        "src.ai.http_llm_custom_providers.requests.post",
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": RAW_LIFE_RECORD}]},
                    "finishReason": "FINISH_REASON_UNSPECIFIED",
                }
            ]
        },
    )

    result = asyncio.run(_google_client().generate_life_record_once(PROMPT))

    assert result.status is ResponseStatus.COMPLETE
    assert result.finish_reason == "finish_reason_unspecified"


def test_google_unknown_non_structured_field_never_falls_back(monkeypatch):
    _patch_system_instruction(monkeypatch)
    calls = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        calls.append(deepcopy(json))
        return DummyHTTPResponse(
            {
                "error": {
                    "message": (
                        'Unknown name "candidateCount" at '
                        "'generationConfig': Cannot find field."
                    )
                }
            },
            status_code=400,
        )

    monkeypatch.setattr(
        "src.ai.http_llm_custom_providers.requests.post",
        fake_post,
    )
    client = _google_client()

    with pytest.raises(RuntimeError, match="life_record_generation_failed"):
        asyncio.run(client.generate_life_record_once(PROMPT))

    assert len(calls) == 1
    assert "responseFormat" in calls[0]["generationConfig"]
    assert client._build_life_record_request_descriptor(PROMPT).response_mode is (
        ResponseMode.JSON_SCHEMA
    )


def test_cohere_official_life_record_uses_native_schema_without_history(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    captured = _capture_single_post(
        monkeypatch,
        "src.ai.http_llm_custom_providers.requests.post",
        {
            "text": RAW_LIFE_RECORD,
            "finish_reason": "COMPLETE",
            "meta": {
                "billed_units": {
                    "input_tokens": 6,
                    "output_tokens": 2,
                }
            },
        },
    )
    client = _cohere_client()
    client._history = [{"role": "user", "content": EXCLUDED_SENTINELS[-1]}]

    result = asyncio.run(client.generate_life_record_once(PROMPT))

    payload = captured[0]["json"]
    assert payload["preamble"] == SYSTEM_INSTRUCTION
    assert payload["message"] == PROMPT
    assert payload["chat_history"] == []
    assert payload["response_format"] == {
        "type": "json_object",
        "schema": get_life_record_output_schema(),
    }
    assert "tools" not in payload
    assert all(
        sentinel not in json_module.dumps(payload, ensure_ascii=False)
        for sentinel in EXCLUDED_SENTINELS
    )
    assert result.status is ResponseStatus.COMPLETE
    assert result.finish_reason == "complete"
    assert (
        result.token_usage.input_tokens,
        result.token_usage.output_tokens,
        result.token_usage.total_tokens,
    ) == (6, 2, None)


@pytest.mark.parametrize(
    ("factory", "post_target", "success_body", "schema_path"),
    [
        (
            lambda: _mistral_client(
                "https://gateway.example.invalid/v1/chat/completions"
            ),
            "src.ai.http_llm_openai.requests.post",
            _openai_chat_body(),
            lambda payload: "response_format" in payload,
        ),
        (
            lambda: _google_client(
                "https://gateway.example.invalid/v1beta/models/"
                "{model}:generateContent"
            ),
            "src.ai.http_llm_custom_providers.requests.post",
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": RAW_LIFE_RECORD}]},
                        "finishReason": "STOP",
                    }
                ]
            },
            lambda payload: "responseFormat"
            in payload.get("generationConfig", {}),
        ),
        (
            lambda: _cohere_client("https://gateway.example.invalid/v1/chat"),
            "src.ai.http_llm_custom_providers.requests.post",
            {"text": RAW_LIFE_RECORD, "finish_reason": "COMPLETE"},
            lambda payload: "response_format" in payload,
        ),
    ],
    ids=("mistral", "google-cloud", "cohere"),
)
def test_unverified_remaining_provider_uses_one_strict_historyless_request(
    monkeypatch,
    factory,
    post_target,
    success_body,
    schema_path,
):
    _patch_system_instruction(monkeypatch)
    captured = _capture_single_post(monkeypatch, post_target, success_body)

    result = asyncio.run(factory().generate_life_record_once(PROMPT))

    assert len(captured) == 1
    assert schema_path(captured[0]["json"]) is False
    assert _payload_contains_value(captured[0]["json"], SYSTEM_INSTRUCTION)
    assert _payload_contains_value(captured[0]["json"], PROMPT)
    assert result.text == RAW_LIFE_RECORD


@pytest.mark.parametrize(
    (
        "factory",
        "post_target",
        "unsupported_body",
        "success_body",
        "native_present",
        "expected_usage",
    ),
    [
        (
            _mistral_client,
            "src.ai.http_llm_openai.requests.post",
            {
                "error": {"message": "Unknown parameter: response_format"},
                "usage": {
                    "prompt_tokens": 2,
                    "completion_tokens": 1,
                    "total_tokens": 3,
                },
            },
            {
                **_openai_chat_body(),
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 4,
                    "total_tokens": 9,
                },
            },
            lambda payload: "response_format" in payload,
            (7, 5, 12),
        ),
        (
            _google_client,
            "src.ai.http_llm_custom_providers.requests.post",
            {
                "error": {
                    "message": (
                        'Unknown name "responseFormat" at '
                        "'generationConfig': Cannot find field."
                    )
                },
                "usageMetadata": {
                    "promptTokenCount": 3,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 4,
                },
            },
            {
                "candidates": [
                    {
                        "content": {"parts": [{"text": RAW_LIFE_RECORD}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 6,
                    "candidatesTokenCount": 2,
                    "totalTokenCount": 8,
                },
            },
            lambda payload: "responseFormat"
            in payload.get("generationConfig", {}),
            (9, 3, 12),
        ),
        (
            _cohere_client,
            "src.ai.http_llm_custom_providers.requests.post",
            {
                "error": {"message": "Unknown parameter: response_format"},
                "meta": {
                    "billed_units": {
                        "input_tokens": 4,
                        "output_tokens": 1,
                    }
                },
            },
            {
                "text": RAW_LIFE_RECORD,
                "finish_reason": "COMPLETE",
                "meta": {
                    "billed_units": {
                        "input_tokens": 7,
                        "output_tokens": 3,
                    }
                },
            },
            lambda payload: "response_format" in payload,
            (11, 4, None),
        ),
    ],
    ids=("mistral", "google-cloud", "cohere"),
)
@pytest.mark.parametrize("unsupported_status", (400, 422))
def test_remaining_native_rejection_falls_back_once_with_same_private_context(
    monkeypatch,
    factory,
    post_target,
    unsupported_body,
    success_body,
    native_present,
    expected_usage,
    unsupported_status,
):
    _patch_system_instruction(monkeypatch)
    captured = []
    responses = [
        DummyHTTPResponse(unsupported_body, status_code=unsupported_status),
        DummyHTTPResponse(success_body),
    ]

    def fake_post(url, *, headers=None, json=None, timeout=None):
        captured.append(deepcopy(json))
        return responses.pop(0)

    monkeypatch.setattr(post_target, fake_post)

    result = asyncio.run(factory().generate_life_record_once(PROMPT))

    assert len(captured) == 2
    assert native_present(captured[0]) is True
    assert native_present(captured[1]) is False
    for payload in captured:
        assert _payload_contains_value(payload, SYSTEM_INSTRUCTION)
        assert _payload_contains_value(payload, PROMPT)
        serialized = json_module.dumps(payload, ensure_ascii=False)
        assert all(sentinel not in serialized for sentinel in EXCLUDED_SENTINELS)
    assert (
        result.token_usage.input_tokens,
        result.token_usage.output_tokens,
        result.token_usage.total_tokens,
    ) == expected_usage


def test_ollama_verified_life_record_uses_fresh_schema_and_preserves_response(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    captured = _install_sequence(
        monkeypatch,
        [
            DummyHTTPResponse(
                _ollama_body(
                    done=False,
                    done_reason="length",
                    prompt_eval_count=7,
                    eval_count=3,
                    total_tokens=10,
                )
            )
        ],
    )
    client = _client()
    original_history = deepcopy(client._history)

    result = asyncio.run(client.generate_life_record_once(PROMPT))

    assert len(captured) == 1
    request = captured[0]
    assert request["url"] == "http://127.0.0.1:11434/api/chat"
    assert request["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "Bearer synthetic-key",
    }
    assert request["json"] == {
        "model": "synthetic-model",
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": PROMPT},
        ],
        "stream": False,
        "options": {
            "temperature": 0.4,
            "top_p": 0.8,
            "num_predict": 321,
        },
        "format": get_life_record_output_schema(),
    }
    serialized = json_module.dumps(request["json"], ensure_ascii=False)
    assert all(sentinel not in serialized for sentinel in EXCLUDED_SENTINELS)
    assert client._history == original_history
    assert result.text == RAW_LIFE_RECORD
    assert result.status is ResponseStatus.INCOMPLETE
    assert result.finish_reason == "length"
    assert (
        result.token_usage.input_tokens,
        result.token_usage.output_tokens,
        result.token_usage.total_tokens,
    ) == (7, 3, 10)


def test_ollama_unknown_endpoint_starts_with_one_strict_text_request(monkeypatch):
    _patch_system_instruction(monkeypatch)
    captured = _install_sequence(
        monkeypatch,
        [DummyHTTPResponse(_ollama_body(prompt_eval_count=4, eval_count=2))],
    )
    client = _client(endpoint="https://ollama.example.invalid/api/chat")

    result = asyncio.run(client.generate_life_record_once(PROMPT))

    assert len(captured) == 1
    assert "format" not in captured[0]["json"]
    assert captured[0]["json"]["messages"] == [
        {"role": "system", "content": SYSTEM_INSTRUCTION},
        {"role": "user", "content": PROMPT},
    ]
    assert result.status is ResponseStatus.COMPLETE
    assert result.token_usage.input_tokens == 4
    assert result.token_usage.output_tokens == 2
    assert result.token_usage.total_tokens is None


def test_ollama_explicit_format_unsupported_falls_back_once_and_caches_life_only(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    unsupported = DummyHTTPResponse(
        {
            "error": "The model does not support format",
            "prompt_eval_count": 2,
            "eval_count": 1,
        },
        status_code=400,
    )
    captured = _install_sequence(
        monkeypatch,
        [
            unsupported,
            DummyHTTPResponse(
                _ollama_body(
                    prompt_eval_count=5,
                    eval_count=4,
                    total_tokens=9,
                )
            ),
            DummyHTTPResponse(_ollama_body()),
        ],
    )
    client = _client()

    result = asyncio.run(client.generate_life_record_once(PROMPT))
    asyncio.run(client.generate_life_record_once(PROMPT))

    assert len(captured) == 3
    assert "format" in captured[0]["json"]
    assert "format" not in captured[1]["json"]
    assert "format" not in captured[2]["json"]
    for request in captured:
        assert request["json"]["messages"] == [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": PROMPT},
        ]
    assert (
        result.token_usage.input_tokens,
        result.token_usage.output_tokens,
        result.token_usage.total_tokens,
    ) == (7, 5, None)

    final_key = http_llm_common.build_capability_key(
        client._build_life_record_request_descriptor(PROMPT).profile,
    )
    assert (
        http_llm_common._HTTP_RESPONSE_CAPABILITY_REGISTRY.resolve(
            client._build_life_record_request_descriptor(PROMPT).profile,
            capability_key=final_key,
        )
        is ResponseMode.JSON_SCHEMA
    )


@pytest.mark.parametrize(
    ("status_code", "detail"),
    [
        (429, "The model does not support format"),
        (500, "The model does not support format"),
        (400, "invalid schema: unsupported schema keyword format"),
        (400, "synthetic unrelated bad request"),
    ],
)
def test_ollama_non_capability_failures_never_retry_or_cache(
    monkeypatch,
    status_code,
    detail,
):
    _patch_system_instruction(monkeypatch)
    captured = _install_sequence(
        monkeypatch,
        [DummyHTTPResponse(status_code=status_code, text=detail)],
    )
    client = _client()

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(client.generate_life_record_once(PROMPT))

    assert len(captured) == 1
    assert str(exc_info.value) == "life_record_generation_failed"
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert client._build_life_record_request_descriptor(PROMPT).response_mode is (
        ResponseMode.JSON_SCHEMA
    )


def test_concurrent_first_life_calls_share_native_capability_probe(monkeypatch):
    _patch_system_instruction(monkeypatch)
    client = _client()
    native_started = threading.Event()
    native_release = threading.Event()
    captured = []
    state_lock = threading.Lock()
    native_calls = 0

    def fake_post(url, *, headers=None, json=None, timeout=None):
        nonlocal native_calls
        payload = deepcopy(json)
        with state_lock:
            captured.append(payload)
        if "format" in payload:
            with state_lock:
                native_calls += 1
                current_native_call = native_calls
            if current_native_call == 1:
                native_started.set()
                assert native_release.wait(2)
            return DummyHTTPResponse(
                status_code=400,
                text="The model does not support format",
            )
        prompt = payload["messages"][-1]["content"]
        return DummyHTTPResponse(
            _ollama_body(json_module.dumps({"prompt": prompt}))
        )

    monkeypatch.setattr("src.ai.http_llm_ollama.requests.post", fake_post)

    async def run_concurrently():
        first = asyncio.create_task(client.generate_life_record_once("SYNTHETIC-A"))
        assert await asyncio.to_thread(native_started.wait, 2)
        second = asyncio.create_task(client.generate_life_record_once("SYNTHETIC-B"))
        await asyncio.sleep(0.05)
        native_release.set()
        return await asyncio.gather(first, second)

    first_result, second_result = asyncio.run(run_concurrently())

    assert len(captured) == 3
    assert sum("format" in payload for payload in captured) == 1
    assert json_module.loads(first_result.text) == {"prompt": "SYNTHETIC-A"}
    assert json_module.loads(second_result.text) == {"prompt": "SYNTHETIC-B"}
    assert client._build_life_record_request_descriptor(PROMPT).response_mode is (
        ResponseMode.LEGACY_TAGS
    )


def test_cancelled_probe_owner_releases_waiter_without_cache_mutation(
    monkeypatch,
    capsys,
):
    _patch_system_instruction(monkeypatch)
    client = _client()
    native_started = threading.Event()
    native_release = threading.Event()
    captured = []

    def fake_post(url, *, headers=None, json=None, timeout=None):
        payload = deepcopy(json)
        captured.append(payload)
        native_index = sum("format" in item for item in captured)
        if native_index == 1:
            native_started.set()
            assert native_release.wait(2)
            return DummyHTTPResponse(
                status_code=400,
                text="SYNTHETIC-RAW-CANCEL-SENTINEL: format is not supported",
            )
        prompt = payload["messages"][-1]["content"]
        return DummyHTTPResponse(
            _ollama_body(json_module.dumps({"prompt": prompt}))
        )

    monkeypatch.setattr("src.ai.http_llm_ollama.requests.post", fake_post)

    async def cancel_owner_and_wait():
        owner = asyncio.create_task(client.generate_life_record_once("SYNTHETIC-OWNER"))
        assert await asyncio.to_thread(native_started.wait, 2)
        waiter = asyncio.create_task(client.generate_life_record_once("SYNTHETIC-WAITER"))
        await asyncio.sleep(0.05)
        assert len(captured) == 1
        owner.cancel("synthetic-owner-cancel")
        await asyncio.sleep(0)
        native_release.set()
        with pytest.raises(asyncio.CancelledError):
            await owner
        return await waiter

    waiter_result = asyncio.run(cancel_owner_and_wait())

    assert len(captured) == 2
    assert all("format" in payload for payload in captured)
    assert json_module.loads(waiter_result.text) == {"prompt": "SYNTHETIC-WAITER"}
    assert client._build_life_record_request_descriptor(PROMPT).response_mode is (
        ResponseMode.JSON_SCHEMA
    )
    output = capsys.readouterr()
    assert "SYNTHETIC-RAW-CANCEL-SENTINEL" not in output.out
    assert "SYNTHETIC-RAW-CANCEL-SENTINEL" not in output.err


def test_probe_owner_exception_releases_waiter_with_safe_error_and_native_cache(
    monkeypatch,
    capsys,
):
    _patch_system_instruction(monkeypatch)
    client = _client()
    native_started = threading.Event()
    native_release = threading.Event()
    captured = []

    class InvalidJSONResponse(DummyHTTPResponse):
        def json(self):
            raise ValueError("SYNTHETIC-RAW-JSON-SENTINEL")

    def fake_post(url, *, headers=None, json=None, timeout=None):
        payload = deepcopy(json)
        captured.append(payload)
        if len(captured) == 1:
            native_started.set()
            assert native_release.wait(2)
            return InvalidJSONResponse(text="SYNTHETIC-RAW-BODY-SENTINEL")
        prompt = payload["messages"][-1]["content"]
        return DummyHTTPResponse(
            _ollama_body(json_module.dumps({"prompt": prompt}))
        )

    monkeypatch.setattr("src.ai.http_llm_ollama.requests.post", fake_post)

    async def fail_owner_and_wait():
        owner = asyncio.create_task(client.generate_life_record_once("SYNTHETIC-OWNER"))
        assert await asyncio.to_thread(native_started.wait, 2)
        waiter = asyncio.create_task(client.generate_life_record_once("SYNTHETIC-WAITER"))
        await asyncio.sleep(0.05)
        assert len(captured) == 1
        native_release.set()
        owner_result, waiter_result = await asyncio.gather(
            owner,
            waiter,
            return_exceptions=True,
        )
        return owner_result, waiter_result

    owner_error, waiter_result = asyncio.run(fail_owner_and_wait())

    assert isinstance(owner_error, RuntimeError)
    assert str(owner_error) == "life_record_generation_failed"
    assert owner_error.__cause__ is None
    assert owner_error.__context__ is None
    assert len(captured) == 2
    assert all("format" in payload for payload in captured)
    assert json_module.loads(waiter_result.text) == {"prompt": "SYNTHETIC-WAITER"}
    assert client._build_life_record_request_descriptor(PROMPT).response_mode is (
        ResponseMode.JSON_SCHEMA
    )
    output = capsys.readouterr()
    assert "SYNTHETIC-RAW-JSON-SENTINEL" not in output.out + output.err
    assert "SYNTHETIC-RAW-BODY-SENTINEL" not in output.out + output.err


def test_life_record_cancellation_during_native_drain_does_not_fallback_or_cache(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    client = _client()
    started = threading.Event()
    release = threading.Event()
    calls = []

    def requester(_descriptor):
        calls.append(_descriptor.response_mode)
        started.set()
        assert release.wait(2)
        response = DummyHTTPResponse(
            status_code=400,
            text="The model does not support format",
        )
        raise requests.HTTPError("SYNTHETIC-RAW-SENTINEL", response=response)

    async def cancel_during_native():
        task = asyncio.create_task(
            client._generate_life_record_once(PROMPT, requester)
        )
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel("synthetic-cancel")
        await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(cancel_during_native())

    assert calls == [ResponseMode.JSON_SCHEMA]
    assert client._build_life_record_request_descriptor(PROMPT).response_mode is (
        ResponseMode.JSON_SCHEMA
    )


def test_life_record_cancellation_during_fallback_drains_second_worker(
    monkeypatch,
):
    _patch_system_instruction(monkeypatch)
    client = _client()
    fallback_started = threading.Event()
    fallback_release = threading.Event()
    calls = []
    active_workers = 0
    state_lock = threading.Lock()

    def requester(descriptor):
        nonlocal active_workers
        calls.append(descriptor.response_mode)
        if descriptor.response_mode is ResponseMode.JSON_SCHEMA:
            response = DummyHTTPResponse(
                status_code=400,
                text="The model does not support format",
            )
            raise requests.HTTPError("SYNTHETIC-RAW-SENTINEL", response=response)
        with state_lock:
            active_workers += 1
        fallback_started.set()
        try:
            assert fallback_release.wait(2)
            return http_llm_common.HTTPStructuredOneShotResponse(
                text=RAW_LIFE_RECORD,
                status=ResponseStatus.COMPLETE,
            )
        finally:
            with state_lock:
                active_workers -= 1

    async def cancel_during_fallback():
        task = asyncio.create_task(
            client._generate_life_record_once(PROMPT, requester)
        )
        assert await asyncio.to_thread(fallback_started.wait, 2)
        task.cancel("synthetic-fallback-cancel")
        await asyncio.sleep(0)
        assert active_workers == 1
        fallback_release.set()
        with pytest.raises(asyncio.CancelledError) as exc_info:
            await task
        assert exc_info.value.args == ("synthetic-fallback-cancel",)

    asyncio.run(cancel_during_fallback())

    assert calls == [ResponseMode.JSON_SCHEMA, ResponseMode.LEGACY_TAGS]
    assert active_workers == 0
