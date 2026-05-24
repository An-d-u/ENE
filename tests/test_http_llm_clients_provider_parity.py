import asyncio

import pytest

from src.ai.http_llm_clients import (
    AnthropicClient,
    CohereClient,
    GoogleCloudClient,
    MistralClient,
    OllamaClient,
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
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
[약속:2026-04-06T21:10:00+09:00|쉬는 시간|user|10분만 쉬고 다시 할게]
좋은 저녁이에요. [smile]
こんばんは。
""".strip()

ANALYSIS_APPENDIX_MARKERS = (
    "[Internal Analysis Output Rules]",
    "[내부 분석 출력 규칙]",
)

SUMMARY_OUTPUT = """
[SUMMARY]
요약 대상 대화만 정리했다.

[MASTER_INFO]
- none

[ENE_INFO]
- none

[MEMORY_META]
memory_type: general
importance_reason: test
confidence: 0.9
entity_names: none
""".strip()


def _build_openai_compatible_client():
    return OpenAICompatibleClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1/chat/completions",
        provider_name="compat",
    )


def _build_openai_response_client():
    return OpenAIResponseAPIClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1/responses",
    )


def _build_mistral_client():
    return MistralClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1/chat/completions",
        provider_name="mistral",
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

    text, emotion, japanese_text, events, analysis, promises, thought, _goal_update = client.send_message("테스트")
    history = client.get_conversation_history()

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert japanese_text == "こんばんは。"
    assert events == []
    assert analysis["user_intent"] == "greeting"
    assert promises == [
        {
            "trigger_at": "2026-04-06T21:10:00+09:00",
            "title": "쉬는 시간",
            "source": "user",
            "source_excerpt": "10분만 쉬고 다시 할게",
        }
    ]
    assert thought == ""
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == RAW_OUTPUT


@pytest.mark.parametrize(
    ("factory", "request_method"),
    [
        (_build_openai_compatible_client, "_request_openai"),
        (_build_openai_response_client, "_request_responses"),
        (_build_google_client, "_request_google"),
        (_build_cohere_client, "_request_cohere"),
        (_build_anthropic_client, "_request_anthropic"),
        (_build_ollama_client, "_request_ollama"),
    ],
    ids=["openai_compatible", "openai_responses", "google_cloud", "cohere", "anthropic", "ollama"],
)
def test_provider_send_message_returns_fallback_when_response_is_empty(monkeypatch, factory, request_method):
    client = factory()
    monkeypatch.setattr(client, request_method, lambda *args, **kwargs: "   ")

    text, emotion, japanese_text, events, analysis, promises, thought, _goal_update = client.send_message("테스트")
    history = client.get_conversation_history()

    assert text == "음... 무슨 일이 있었나봐요."
    assert emotion == "confused"
    assert japanese_text is None
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == "음... 무슨 일이 있었나봐요."


@pytest.mark.parametrize(
    ("factory", "history_request_name"),
    [
        (_build_openai_compatible_client, "_request_openai"),
        (_build_openai_response_client, "_request_responses"),
        (_build_mistral_client, "_request_openai"),
        (_build_google_client, "_request_google"),
        (_build_cohere_client, "_request_cohere"),
        (_build_anthropic_client, "_request_anthropic"),
        (_build_ollama_client, "_request_ollama"),
    ],
    ids=["openai_compatible", "openai_responses", "mistral", "google_cloud", "cohere", "anthropic", "ollama"],
)
def test_provider_summarize_conversation_uses_one_shot_request_without_chat_history(
    monkeypatch,
    factory,
    history_request_name,
):
    client = factory()
    original_history = [
        {"role": "user", "content": "오래된 히스토리"},
        {"role": "assistant", "content": "오래된 답변"},
    ]
    client._history = list(original_history)
    captured = {}

    def fake_one_shot(prompt, include_sub_prompt=True):
        captured["prompt"] = prompt
        captured["include_sub_prompt"] = include_sub_prompt
        return SUMMARY_OUTPUT

    def fail_history_request(*_args, **_kwargs):
        raise AssertionError("summarize_conversation must not use chat-history request methods")

    monkeypatch.setattr(client, "_request_one_shot_raw", fake_one_shot)
    monkeypatch.setattr(client, history_request_name, fail_history_request)

    summary, _user_facts, _ene_facts, memory_meta = asyncio.run(
        client.summarize_conversation([("user", "요약 대상 대화", "2026-05-25 10:00")])
    )

    assert summary == "요약 대상 대화만 정리했다."
    assert memory_meta["memory_type"] == "general"
    assert "요약 대상 대화" in captured["prompt"]
    assert "오래된 히스토리" not in captured["prompt"]
    assert captured["include_sub_prompt"] is True
    assert client.get_conversation_history() == original_history


def test_mistral_one_shot_request_excludes_chat_history(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse({"choices": [{"message": {"content": "응답"}}]})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = _build_mistral_client()
    client._history = [
        {"role": "user", "content": "오래된 히스토리"},
        {"role": "assistant", "content": "오래된 답변"},
    ]

    assert client._request_one_shot_raw("요약 프롬프트") == "응답"

    payload_text = str(captured["json"]["messages"])
    assert "요약 프롬프트" in payload_text
    assert "오래된 히스토리" not in payload_text


@pytest.mark.parametrize(
    "factory",
    [
        _build_openai_compatible_client,
        _build_google_client,
        _build_cohere_client,
        _build_anthropic_client,
        _build_ollama_client,
    ],
    ids=["openai_compatible", "google_cloud", "cohere", "anthropic", "ollama"],
)
def test_provider_parse_response_removes_thinking_tags_before_extracting_tts_text(factory):
    client = factory()
    response_text = """
<think>
내부 추론은 사용자에게 보이면 안 된다.
</think>
좋은 저녁이에요. [smile]
こんばんは。
""".strip()

    text, emotion, japanese_text, events, analysis, promises, thought, _goal_update = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert japanese_text == "こんばんは。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


@pytest.mark.parametrize(
    "factory",
    [
        _build_openai_compatible_client,
        _build_google_client,
        _build_cohere_client,
        _build_anthropic_client,
        _build_ollama_client,
    ],
    ids=["openai_compatible", "google_cloud", "cohere", "anthropic", "ollama"],
)
def test_provider_parse_response_removes_leading_orphan_thinking_close_tag(factory):
    client = factory()
    response_text = """
</think>
좋은 저녁이에요. [smile]
こんばんは。
""".strip()

    text, emotion, japanese_text, events, analysis, promises, thought, _goal_update = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert japanese_text == "こんばんは。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""
