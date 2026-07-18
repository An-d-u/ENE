import traceback

import pytest
import requests

from src.ai.http_llm_clients import (
    AnthropicClient,
    CohereClient,
    GoogleCloudClient,
    MistralClient,
    OllamaClient,
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
)
from src.ai.http_llm_common import (
    _raise_for_status_with_detail,
    is_explicit_structured_output_unsupported,
)
from src.ai.response_protocol import LLMRequestKind


RAW_BODY_SENTINEL = "unknown parameter: response_format SYNTHETIC-RAW-BODY-SENTINEL"
ENDPOINT_SENTINEL = "synthetic-endpoint-secret"
API_KEY_SENTINEL = "synthetic-api-key-secret"
PROMPT_SENTINEL = "SYNTHETIC-ORIGINAL-PROMPT-SENTINEL"
ORIGINAL_ERROR_SENTINEL = "SYNTHETIC-ORIGINAL-HTTP-ERROR-SENTINEL"
NESTED_CAUSE_SENTINEL = "SYNTHETIC-NESTED-CAUSE-SENTINEL"


class _LeakyResponse:
    status_code = 422
    text = RAW_BODY_SENTINEL

    def raise_for_status(self):
        try:
            raise ValueError(NESTED_CAUSE_SENTINEL)
        except ValueError as cause:
            raise requests.HTTPError(
                " ".join(
                    (
                        ORIGINAL_ERROR_SENTINEL,
                        RAW_BODY_SENTINEL,
                        ENDPOINT_SENTINEL,
                        API_KEY_SENTINEL,
                        PROMPT_SENTINEL,
                    )
                ),
                response=self,
            ) from cause


class _ExplodingProvider:
    def __str__(self):
        raise RuntimeError(API_KEY_SENTINEL)


class _ExplodingStatus:
    def __int__(self):
        raise RuntimeError(RAW_BODY_SENTINEL)


def _openai_compatible():
    return OpenAICompatibleClient(
        api_key=API_KEY_SENTINEL,
        model_name="synthetic-model",
        endpoint=f"https://example.invalid/{ENDPOINT_SENTINEL}?key={API_KEY_SENTINEL}",
        provider_name="custom_api",
    )


def _openai_responses():
    return OpenAIResponseAPIClient(
        api_key=API_KEY_SENTINEL,
        model_name="synthetic-model",
        endpoint=f"https://example.invalid/{ENDPOINT_SENTINEL}?key={API_KEY_SENTINEL}",
        provider_name="custom_api",
    )


def _mistral():
    return MistralClient(
        api_key=API_KEY_SENTINEL,
        model_name="synthetic-model",
        endpoint=f"https://example.invalid/{ENDPOINT_SENTINEL}?key={API_KEY_SENTINEL}",
        provider_name="custom_api",
    )


def _anthropic():
    return AnthropicClient(
        api_key=API_KEY_SENTINEL,
        model_name="synthetic-model",
        endpoint=f"https://example.invalid/{ENDPOINT_SENTINEL}?key={API_KEY_SENTINEL}",
    )


def _ollama():
    return OllamaClient(
        api_key=API_KEY_SENTINEL,
        model_name="synthetic-model",
        endpoint=f"http://127.0.0.1:11434/{ENDPOINT_SENTINEL}?key={API_KEY_SENTINEL}",
    )


def _google_cloud():
    return GoogleCloudClient(
        api_key=API_KEY_SENTINEL,
        model_name="synthetic-model",
        endpoint=f"https://example.invalid/{ENDPOINT_SENTINEL}",
    )


def _cohere():
    return CohereClient(
        api_key=API_KEY_SENTINEL,
        model_name="synthetic-model",
        endpoint=f"https://example.invalid/{ENDPOINT_SENTINEL}?key={API_KEY_SENTINEL}",
    )


def _final_openai_compatible(client):
    client._request_openai(PROMPT_SENTINEL)


def _final_openai_responses(client):
    client._request_responses(PROMPT_SENTINEL)


def _final_mistral(client):
    client._request_openai(PROMPT_SENTINEL)


def _final_anthropic(client):
    client._request_anthropic([{"type": "text", "text": PROMPT_SENTINEL}])


def _final_ollama(client):
    client._request_ollama(PROMPT_SENTINEL)


def _final_google_cloud(client):
    client._request_google(PROMPT_SENTINEL)


def _final_cohere(client):
    client._request_cohere(PROMPT_SENTINEL)


def _one_shot(client):
    client._request_one_shot_raw(
        PROMPT_SENTINEL,
        request_kind=LLMRequestKind.SUMMARY,
    )


@pytest.mark.parametrize(
    ("client_factory", "invoke", "provider"),
    [
        (_openai_compatible, _final_openai_compatible, "custom_api"),
        (_openai_compatible, _one_shot, "custom_api"),
        (_openai_responses, _final_openai_responses, "custom_api"),
        (_openai_responses, _one_shot, "custom_api"),
        (_mistral, _final_mistral, "custom_api"),
        (_mistral, _one_shot, "custom_api"),
        (_anthropic, _final_anthropic, "anthropic"),
        (_anthropic, _one_shot, "anthropic"),
        (_ollama, _final_ollama, "ollama"),
        (_ollama, _one_shot, "ollama"),
        (_google_cloud, _final_google_cloud, "custom_api"),
        (_google_cloud, _one_shot, "custom_api"),
        (_cohere, _final_cohere, "custom_api"),
        (_cohere, _one_shot, "custom_api"),
    ],
)
def test_http_provider_errors_hide_sensitive_content_and_keep_classifier_body(
    monkeypatch,
    capsys,
    client_factory,
    invoke,
    provider,
):
    response = _LeakyResponse()
    monkeypatch.setattr(requests, "post", lambda *args, **kwargs: response)

    with pytest.raises(requests.HTTPError) as exc_info:
        invoke(client_factory())

    failure = exc_info.value
    rendered_traceback = "".join(
        traceback.format_exception(type(failure), failure, failure.__traceback__)
    )
    captured = capsys.readouterr()
    visible = "\n".join(
        (str(failure), repr(failure), rendered_traceback, captured.out, captured.err)
    )

    for sentinel in (
        RAW_BODY_SENTINEL,
        ENDPOINT_SENTINEL,
        API_KEY_SENTINEL,
        PROMPT_SENTINEL,
        ORIGINAL_ERROR_SENTINEL,
        NESTED_CAUSE_SENTINEL,
    ):
        assert sentinel not in visible
    assert provider in str(failure)
    assert "status=422" in str(failure)

    assert "category=http_error" in str(failure)
    assert failure.response is response
    assert failure.response.text == RAW_BODY_SENTINEL
    assert is_explicit_structured_output_unsupported(failure) is True


@pytest.mark.parametrize(
    ("client_factory", "invoke", "provider"),
    [
        (_openai_compatible, _final_openai_compatible, "custom_api"),
        (_openai_compatible, _one_shot, "custom_api"),
        (_openai_responses, _final_openai_responses, "custom_api"),
        (_openai_responses, _one_shot, "custom_api"),
        (_mistral, _final_mistral, "custom_api"),
        (_mistral, _one_shot, "custom_api"),
        (_anthropic, _final_anthropic, "anthropic"),
        (_anthropic, _one_shot, "anthropic"),
        (_ollama, _final_ollama, "ollama"),
        (_ollama, _one_shot, "ollama"),
        (_google_cloud, _final_google_cloud, "custom_api"),
        (_google_cloud, _one_shot, "custom_api"),
        (_cohere, _final_cohere, "custom_api"),
        (_cohere, _one_shot, "custom_api"),
    ],
)
@pytest.mark.parametrize(
    "error_type",
    [requests.ConnectionError, requests.Timeout, requests.RequestException],
)
def test_http_provider_network_errors_hide_request_and_cause(
    monkeypatch,
    capsys,
    client_factory,
    invoke,
    provider,
    error_type,
):
    attempted_urls = []

    def raise_network_error(*args, **kwargs):
        attempted_urls.append(str(args[0]))
        try:
            raise ValueError(NESTED_CAUSE_SENTINEL)
        except ValueError as cause:
            raise error_type(
                " ".join(
                    (
                        ORIGINAL_ERROR_SENTINEL,
                        RAW_BODY_SENTINEL,
                        attempted_urls[-1],
                        PROMPT_SENTINEL,
                    )
                )
            ) from cause

    monkeypatch.setattr(requests, "post", raise_network_error)

    with pytest.raises(error_type) as exc_info:
        invoke(client_factory())

    failure = exc_info.value
    rendered_traceback = "".join(
        traceback.format_exception(type(failure), failure, failure.__traceback__)
    )
    captured = capsys.readouterr()
    visible = "\n".join(
        (str(failure), repr(failure), rendered_traceback, captured.out, captured.err)
    )

    for sentinel in (
        RAW_BODY_SENTINEL,
        ENDPOINT_SENTINEL,
        API_KEY_SENTINEL,
        PROMPT_SENTINEL,
        ORIGINAL_ERROR_SENTINEL,
        NESTED_CAUSE_SENTINEL,
    ):
        assert sentinel not in visible
    if client_factory is _google_cloud:
        assert f"?key={API_KEY_SENTINEL}" in attempted_urls[0]
    assert str(failure) == (
        f"provider={provider} status=unknown category=network_error"
    )


@pytest.mark.parametrize(
    ("provider_name", "status_code", "expected_provider", "expected_status"),
    [
        (_ExplodingProvider(), 422, "unknown", "422"),
        ("custom_api", _ExplodingStatus(), "custom_api", "unknown"),
        ("custom_api", float("inf"), "custom_api", "unknown"),
    ],
)
def test_http_status_error_uses_safe_fallback_for_malformed_metadata(
    provider_name,
    status_code,
    expected_provider,
    expected_status,
):
    response = _LeakyResponse()
    response.status_code = status_code

    with pytest.raises(requests.HTTPError) as exc_info:
        _raise_for_status_with_detail(response, provider_name)

    failure = exc_info.value
    rendered_traceback = "".join(
        traceback.format_exception(type(failure), failure, failure.__traceback__)
    )
    visible = "\n".join((str(failure), repr(failure), rendered_traceback))

    for sentinel in (
        RAW_BODY_SENTINEL,
        ENDPOINT_SENTINEL,
        API_KEY_SENTINEL,
        PROMPT_SENTINEL,
        ORIGINAL_ERROR_SENTINEL,
        NESTED_CAUSE_SENTINEL,
    ):
        assert sentinel not in visible
    assert str(failure) == (
        f"provider={expected_provider} status={expected_status} category=http_error"
    )
    assert failure.response is response
