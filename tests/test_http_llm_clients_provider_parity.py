import pytest

from src.ai.http_llm_clients import (
    AnthropicClient,
    CohereClient,
    GoogleCloudClient,
    OllamaClient,
    OpenAICompatibleClient,
)


class _DummyResponse:
    def __init__(self, json_data):
        self._json_data = json_data
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data


RAW_OUTPUT = """
[analysis]
user_emotion=calm
user_intent=greeting
confidence=0.8
[/analysis]
좋은 저녁이에요. [smile]
こんばんは。
""".strip()

ANALYSIS_APPENDIX_MARKERS = (
    "[Internal Analysis Output Rules]",
    "[내부 분석 출력 규칙]",
)


def _build_openai_compatible_client():
    return OpenAICompatibleClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1/chat/completions",
        provider_name="compat",
    )


def _build_google_client():
    return GoogleCloudClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1beta/models/{model}:generateContent",
    )


def _build_cohere_client():
    return CohereClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1/chat",
    )


def _build_anthropic_client():
    return AnthropicClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1/messages",
    )


def _build_ollama_client():
    return OllamaClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/api/chat",
    )


@pytest.mark.parametrize(
    ("factory", "request_name", "request_args", "extract_prompt", "response_body"),
    [
        (
            _build_openai_compatible_client,
            "_request_openai",
            ("테스트",),
            lambda payload: payload["messages"][0]["content"],
            {"choices": [{"message": {"content": "응답"}}]},
        ),
        (
            _build_google_client,
            "_request_google",
            ("테스트",),
            lambda payload: payload["systemInstruction"]["parts"][0]["text"],
            {"candidates": [{"content": {"parts": [{"text": "응답"}]}}]},
        ),
        (
            _build_cohere_client,
            "_request_cohere",
            ("테스트",),
            lambda payload: payload["preamble"],
            {"text": "응답"},
        ),
        (
            _build_anthropic_client,
            "_request_anthropic",
            ([{"type": "text", "text": "테스트"}],),
            lambda payload: payload["system"],
            {"content": [{"type": "text", "text": "응답"}]},
        ),
        (
            _build_ollama_client,
            "_request_ollama",
            ("테스트",),
            lambda payload: payload["messages"][0]["content"],
            {"message": {"content": "응답"}},
        ),
    ],
    ids=["openai_compatible", "google_cloud", "cohere", "anthropic", "ollama"],
)
def test_provider_requests_include_analysis_appendix(
    monkeypatch,
    factory,
    request_name,
    request_args,
    extract_prompt,
    response_body,
):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(response_body)

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = factory()
    getattr(client, request_name)(*request_args)

    assert any(marker in extract_prompt(captured["json"]) for marker in ANALYSIS_APPENDIX_MARKERS)


@pytest.mark.parametrize(
    ("factory", "request_method"),
    [
        (_build_openai_compatible_client, "_request_openai"),
        (_build_google_client, "_request_google"),
        (_build_cohere_client, "_request_cohere"),
        (_build_anthropic_client, "_request_anthropic"),
        (_build_ollama_client, "_request_ollama"),
    ],
    ids=["openai_compatible", "google_cloud", "cohere", "anthropic", "ollama"],
)
def test_provider_send_message_keeps_raw_assistant_output_in_history(monkeypatch, factory, request_method):
    client = factory()
    monkeypatch.setattr(client, request_method, lambda *args, **kwargs: RAW_OUTPUT)

    text, emotion, japanese_text, events, analysis = client.send_message("테스트")
    history = client.get_conversation_history()

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert japanese_text == "こんばんは。"
    assert events == []
    assert analysis["user_intent"] == "greeting"
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == RAW_OUTPUT
