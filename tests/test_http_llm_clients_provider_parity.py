import asyncio
import inspect
from typing import get_type_hints

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
from src.ai.response_protocol import (
    LLMRequestKind,
    OneShotGenerationResult,
    ResponseMode,
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

[TOPIC_MEMORY]
- keyword: Project Lambda
  subject: summary handoff
  text: Project Lambda summary handoff is ready.
  retrieval_terms: summary, handoff
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
    "factory",
    [
        _build_openai_compatible_client,
        _build_openai_response_client,
        _build_anthropic_client,
    ],
    ids=("openai-chat", "openai-responses", "anthropic"),
)
def test_native_http_clients_expose_async_life_record_generation(factory):
    client = factory()

    assert inspect.iscoroutinefunction(client.generate_life_record_once)
    assert (
        get_type_hints(client.generate_life_record_once).get("return")
        is OneShotGenerationResult
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
    ("factory", "request_name", "request_args", "response_body", "expected_provider_format"),
    [
        (
            _build_openai_compatible_client,
            "_request_openai",
            ("비공개 사용자 메시지",),
            {"choices": [{"message": {"content": "응답"}}]},
            "openai_chat",
        ),
        (
            _build_openai_response_client,
            "_request_responses",
            ("비공개 사용자 메시지",),
            {"output_text": "응답"},
            "openai_responses",
        ),
        (
            _build_mistral_client,
            "_request_openai",
            ("비공개 사용자 메시지",),
            {"choices": [{"message": {"content": "응답"}}]},
            "mistral",
        ),
        (
            _build_google_client,
            "_request_google",
            ("비공개 사용자 메시지",),
            {"candidates": [{"content": {"parts": [{"text": "응답"}]}}]},
            "google_cloud",
        ),
        (
            _build_cohere_client,
            "_request_cohere",
            ("비공개 사용자 메시지",),
            {"text": "응답"},
            "cohere",
        ),
        (
            _build_anthropic_client,
            "_request_anthropic",
            ([{"type": "text", "text": "비공개 사용자 메시지"}],),
            {"content": [{"type": "text", "text": "응답"}]},
            "anthropic",
        ),
        (
            _build_ollama_client,
            "_request_ollama",
            ("비공개 사용자 메시지",),
            {"message": {"content": "응답"}},
            "ollama",
        ),
    ],
    ids=["openai_compatible", "openai_responses", "mistral", "google_cloud", "cohere", "anthropic", "ollama"],
)
def test_provider_requests_record_privacy_safe_context_fingerprint(
    monkeypatch,
    factory,
    request_name,
    request_args,
    response_body,
    expected_provider_format,
):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(response_body)

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = factory()
    client._history = [
        {"role": "user", "content": "비공개 이전 질문"},
        {"role": "assistant", "content": "비공개 이전 답변"},
    ]

    getattr(client, request_name)(*request_args)

    fingerprint = client.get_last_request_context_fingerprint()
    serialized = str(fingerprint)

    assert fingerprint["system_prompt_sha256"]
    assert fingerprint["provider_format"] == expected_provider_format
    assert fingerprint["user_content_sha256"]
    assert fingerprint["history_sha256"]
    assert fingerprint["history_turns"] == 2
    assert fingerprint["request_kind"] == LLMRequestKind.FINAL_REPLY.value
    assert fingerprint["response_mode"] == ResponseMode.LEGACY_TAGS.value
    assert fingerprint["schema_version"] == "1"
    assert client.get_conversation_history() == [
        {"role": "user", "content": "비공개 이전 질문"},
        {"role": "assistant", "content": "비공개 이전 답변"},
    ]
    assert "비공개" not in serialized
    assert "사용자 메시지" not in serialized
    assert "이전 질문" not in serialized
    assert "비공개 이전 질문" in str(captured["json"])
    assert "비공개 사용자 메시지" in str(captured["json"])


@pytest.mark.parametrize(
    ("factory", "response_body", "expected_provider_format", "payload_to_text"),
    [
        (
            _build_openai_compatible_client,
            {"choices": [{"message": {"content": "응답"}}]},
            "openai_chat_one_shot",
            lambda payload: str(payload["messages"]),
        ),
        (
            _build_openai_response_client,
            {"output_text": "응답"},
            "openai_responses_one_shot",
            lambda payload: str(payload["input"]),
        ),
        (
            _build_mistral_client,
            {"choices": [{"message": {"content": "응답"}}]},
            "mistral_one_shot",
            lambda payload: str(payload["messages"]),
        ),
        (
            _build_google_client,
            {"candidates": [{"content": {"parts": [{"text": "응답"}]}}]},
            "google_cloud_one_shot",
            lambda payload: str(payload["contents"]),
        ),
        (
            _build_cohere_client,
            {"text": "응답"},
            "cohere_one_shot",
            lambda payload: str(payload),
        ),
        (
            _build_anthropic_client,
            {"content": [{"type": "text", "text": "응답"}]},
            "anthropic_one_shot",
            lambda payload: str(payload["messages"]),
        ),
        (
            _build_ollama_client,
            {"message": {"content": "응답"}},
            "ollama_one_shot",
            lambda payload: str(payload["messages"]),
        ),
    ],
    ids=["openai_compatible", "openai_responses", "mistral", "google_cloud", "cohere", "anthropic", "ollama"],
)
def test_provider_one_shot_requests_exclude_history_and_record_one_shot_fingerprint(
    monkeypatch,
    factory,
    response_body,
    expected_provider_format,
    payload_to_text,
):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(response_body)

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = factory()
    client._history = [
        {"role": "user", "content": "오래된 히스토리"},
        {"role": "assistant", "content": "오래된 답변"},
    ]

    assert client._request_one_shot_raw(
        "요약 프롬프트",
        request_kind=LLMRequestKind.SUMMARY,
    ) == "응답"

    fingerprint = client.get_last_request_context_fingerprint()
    payload_text = payload_to_text(captured["json"])

    assert fingerprint["provider_format"] == expected_provider_format
    assert fingerprint["history_turns"] == 0
    assert fingerprint["request_kind"] == LLMRequestKind.SUMMARY.value
    assert fingerprint["response_mode"] == ResponseMode.LEGACY_TAGS.value
    assert fingerprint["schema_version"] == "1"
    assert client.get_conversation_history() == [
        {"role": "user", "content": "오래된 히스토리"},
        {"role": "assistant", "content": "오래된 답변"},
    ]
    assert "요약 프롬프트" in payload_text
    assert "오래된 히스토리" not in payload_text
    assert "오래된 답변" not in payload_text


def test_request_context_deep_copies_nested_history_before_fingerprinting():
    client = _build_openai_compatible_client()
    image_turn = {
        "role": "user",
        "content": [
            {"type": "text", "text": "이전 이미지"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
        ],
    }
    client._history = [image_turn]

    context = client._build_request_context(
        "다음 질문",
        provider_format="test",
        request_kind=LLMRequestKind.FINAL_REPLY,
    )
    before = context.fingerprint()

    image_turn["content"][0]["text"] = "변경된 히스토리"
    image_turn["content"][1]["image_url"]["url"] = "data:image/png;base64,REVG"

    after = context.fingerprint()
    assert context.history[0]["content"][0]["text"] == "이전 이미지"
    assert context.history[0]["content"][1]["image_url"]["url"] == "data:image/png;base64,QUJD"
    assert after == before


def test_request_context_fingerprint_records_kind_mode_and_schema_version():
    client = _build_openai_compatible_client()

    context = client._build_request_context(
        "합성 요청",
        provider_format="openai_responses",
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
    )

    fingerprint = context.fingerprint()
    assert fingerprint["request_kind"] == "final_reply"
    assert fingerprint["response_mode"] == "json_schema"
    assert fingerprint["schema_version"] == "1"


def test_summary_retry_remains_a_summary_request(monkeypatch):
    client = _build_openai_compatible_client()
    calls = []
    responses = iter(["[SUMMARY]\n부분 합성 요약", SUMMARY_OUTPUT])

    def fake_one_shot(_prompt, *, request_kind, include_sub_prompt=True):
        calls.append((request_kind, include_sub_prompt))
        return next(responses)

    monkeypatch.setattr(client, "_request_one_shot_raw", fake_one_shot)

    assert client._request_summary_text("합성 요약 입력") == SUMMARY_OUTPUT
    assert calls == [
        (LLMRequestKind.SUMMARY, False),
        (LLMRequestKind.SUMMARY, False),
    ]


def test_http_web_search_decision_uses_decision_request_kind(monkeypatch):
    client = _build_openai_compatible_client()
    calls = []

    def fake_one_shot(_prompt, *, request_kind, include_sub_prompt=True):
        calls.append((request_kind, include_sub_prompt))
        return '{"should_search": false, "query": "", "reason": "synthetic context"}'

    monkeypatch.setattr(client, "_request_one_shot_raw", fake_one_shot)

    decision = client._create_web_search_decision_provider()("합성 최신 정보 질문")

    assert decision.should_search is False
    assert calls == [(LLMRequestKind.DECISION, False)]


def test_http_markdown_diary_and_note_requests_use_explicit_kinds(monkeypatch):
    client = _build_openai_compatible_client()
    calls = []

    async def fake_memory_context(_message):
        return "합성 메모리 컨텍스트"

    def fake_one_shot(_prompt, *, request_kind, include_sub_prompt=True):
        calls.append((request_kind, include_sub_prompt))
        return "합성 일회성 응답"

    monkeypatch.setattr(client, "_build_memory_context", fake_memory_context)
    monkeypatch.setattr(client, "_request_one_shot_raw", fake_one_shot)

    asyncio.run(client.generate_markdown_document("합성 문서 요청"))
    asyncio.run(client.generate_diary_completion_reply("합성 일기 완료 컨텍스트"))
    asyncio.run(client.generate_note_command_plan("합성 노트 계획 컨텍스트"))
    asyncio.run(client.generate_note_execution_report("합성 노트 완료 컨텍스트"))

    assert calls == [
        (LLMRequestKind.MARKDOWN, False),
        (LLMRequestKind.PLAIN_TEXT, True),
        (LLMRequestKind.DECISION, False),
        (LLMRequestKind.PLAIN_TEXT, True),
    ]


def test_include_sub_prompt_true_does_not_make_one_shot_a_final_reply(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse({"choices": [{"message": {"content": "합성 완료 안내"}}]})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)
    client = _build_openai_compatible_client()

    assert client._request_one_shot_raw(
        "합성 완료 컨텍스트",
        request_kind=LLMRequestKind.PLAIN_TEXT,
        include_sub_prompt=True,
    ) == "합성 완료 안내"

    system_prompt = captured["json"]["messages"][0]["content"]
    assert client.get_last_request_context_fingerprint()["request_kind"] == "plain_text"
    assert all(marker not in system_prompt for marker in ANALYSIS_APPENDIX_MARKERS)
    assert "[최종 응답 형식]" not in system_prompt
    assert "[Final Response Format]" not in system_prompt


def test_debug_context_parity_logs_only_salted_fingerprints_and_metadata(monkeypatch, capsys):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse({"candidates": [{"content": {"parts": [{"text": "응답"}]}}]})

    class _Settings:
        def get(self, key, default=None):
            if key == "debug_llm_context_parity":
                return True
            return default

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = GoogleCloudClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1beta/models/{model}:generateContent",
        settings=_Settings(),
    )
    client._history = [
        {"role": "user", "content": "비공개 이전 질문"},
        {"role": "assistant", "content": "비공개 이전 답변"},
    ]
    image_data = "data:image/png;base64,aW1hZ2UtYnl0ZXM="

    client._request_google("비공개 사용자 메시지", images_data=[{"dataUrl": image_data}])

    out = capsys.readouterr().out
    fingerprint = client.get_last_request_context_fingerprint()

    assert "request context fingerprint" in out
    assert fingerprint["attachment_count"] == 1
    assert fingerprint["attachments_sha256"] in out
    assert "비공개" not in out
    assert "사용자 메시지" not in out
    assert "이전 질문" not in out
    assert "aW1hZ2UtYnl0ZXM" not in out
    assert "image-bytes" not in out
    assert captured["json"]["contents"][-1]["parts"][-1]["inlineData"]["data"] == "aW1hZ2UtYnl0ZXM="


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
def test_provider_send_message_keeps_visible_assistant_output_in_history(monkeypatch, factory, request_method):
    client = factory()
    monkeypatch.setattr(client, request_method, lambda *args, **kwargs: RAW_OUTPUT)

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client.send_message("테스트")
    history = client.get_conversation_history()

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
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
    assert history[-1]["content"] == text


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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client.send_message("테스트")
    history = client.get_conversation_history()

    assert text == "음... 무슨 일이 있었나봐요."
    assert emotion == "confused"
    assert tts_text is None
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

    def fake_one_shot(prompt, *, request_kind, include_sub_prompt=True):
        captured["prompt"] = prompt
        captured["request_kind"] = request_kind
        captured["include_sub_prompt"] = include_sub_prompt
        return SUMMARY_OUTPUT

    def fail_history_request(*_args, **_kwargs):
        raise AssertionError("summarize_conversation must not use chat-history request methods")

    monkeypatch.setattr(client, "_request_one_shot_raw", fake_one_shot)
    monkeypatch.setattr(client, history_request_name, fail_history_request)

    summary, _user_facts, _ene_facts, memory_meta, topic_hints = asyncio.run(
        client.summarize_conversation([("user", "요약 대상 대화", "2026-05-25 10:00")])
    )

    assert summary == "요약 대상 대화만 정리했다."
    assert memory_meta["memory_type"] == "general"
    assert [hint.keyword for hint in topic_hints] == ["Project Lambda"]
    assert "요약 대상 대화" in captured["prompt"]
    assert "오래된 히스토리" not in captured["prompt"]
    assert captured["include_sub_prompt"] is False
    assert captured["request_kind"] is LLMRequestKind.SUMMARY
    assert client.get_conversation_history() == original_history


def test_provider_summarize_conversation_accepts_loaded_topic_memory_context(monkeypatch):
    client = _build_openai_compatible_client()
    captured = {}

    def fake_one_shot(prompt, *, request_kind, include_sub_prompt=True):
        captured["prompt"] = prompt
        captured["request_kind"] = request_kind
        captured["include_sub_prompt"] = include_sub_prompt
        return SUMMARY_OUTPUT

    monkeypatch.setattr(client, "_request_one_shot_raw", fake_one_shot)

    asyncio.run(
        client.summarize_conversation(
            [("user", "Project Lambda finished rollout.", "2026-05-25 10:00")],
            loaded_topic_memory_context=(
                "- keyword: Project Lambda\n"
                "  subject: rollout status\n"
                "  type: status_flow\n"
                "  state: active\n"
                "  text: Rollout is in progress."
            ),
        )
    )

    assert "[LOADED_TOPIC_MEMORY]" in captured["prompt"]
    assert "Project Lambda" in captured["prompt"]
    assert "비교용 기존 주제 기억" in captured["prompt"]
    assert captured["include_sub_prompt"] is False
    assert captured["request_kind"] is LLMRequestKind.SUMMARY


def test_provider_summarize_conversation_empty_response_returns_topic_hints_fallback(monkeypatch):
    client = _build_openai_compatible_client()

    monkeypatch.setattr(client, "_request_one_shot_raw", lambda *_args, **_kwargs: "   ")

    summary, user_facts, ene_facts, memory_meta, topic_hints = asyncio.run(
        client.summarize_conversation([("user", "Neutral summary target", "2026-05-25 10:00")])
    )

    assert summary
    assert user_facts == []
    assert ene_facts == []
    assert memory_meta["importance_reason"] == "empty_llm_response"
    assert topic_hints == []


def test_provider_summarize_conversation_retries_incomplete_response_with_larger_budget(monkeypatch):
    client = _build_openai_compatible_client()
    client.generation_params["max_tokens"] = 2048
    captured_max_tokens = []
    captured_request_kinds = []
    responses = [
        "[SUMMARY]\n- 첫 응답은 중간에 끊겼다.",
        SUMMARY_OUTPUT,
    ]

    def fake_one_shot(prompt, *, request_kind, include_sub_prompt=True):
        captured_max_tokens.append(client.generation_params["max_tokens"])
        captured_request_kinds.append(request_kind)
        return responses.pop(0)

    monkeypatch.setattr(client, "_request_one_shot_raw", fake_one_shot)

    summary, _user_facts, _ene_facts, _memory_meta, topic_hints = asyncio.run(
        client.summarize_conversation([("user", "요약 대상 대화", "2026-05-25 10:00")])
    )

    assert summary == "요약 대상 대화만 정리했다."
    assert [hint.keyword for hint in topic_hints] == ["Project Lambda"]
    assert captured_max_tokens == [4096, 4096]
    assert captured_request_kinds == [LLMRequestKind.SUMMARY, LLMRequestKind.SUMMARY]
    assert client.generation_params["max_tokens"] == 2048


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

    assert client._request_one_shot_raw(
        "요약 프롬프트",
        request_kind=LLMRequestKind.SUMMARY,
    ) == "응답"

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert analysis == {}
    assert promises == []
    assert thought == ""
    assert events == []


def _build_task10_openai_chat_client():
    from tests.http_structured_fixtures import structured_settings

    return OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.openai.com/v1/chat/completions",
        provider_name="openai",
        settings=structured_settings(),
    )


def _build_task10_openai_responses_client():
    from tests.http_structured_fixtures import structured_settings

    return OpenAIResponseAPIClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.openai.com/v1/responses",
        settings=structured_settings(),
    )


def _build_task10_mistral_client():
    from tests.http_structured_fixtures import structured_settings

    return MistralClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://example.com/v1/chat/completions",
        provider_name="mistral",
        settings=structured_settings(),
    )


def _build_task10_google_client():
    from tests.http_structured_fixtures import structured_settings

    return GoogleCloudClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://example.com/v1beta/models/{model}:generateContent",
        settings=structured_settings(),
    )


def _build_task10_cohere_client():
    from tests.http_structured_fixtures import structured_settings

    return CohereClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://example.com/v1/chat",
        settings=structured_settings(),
    )


def _build_task10_anthropic_client():
    from tests.http_structured_fixtures import structured_settings

    return AnthropicClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.anthropic.com/v1/messages",
        settings=structured_settings(),
    )


def _build_task10_ollama_client():
    from tests.http_structured_fixtures import structured_settings

    return OllamaClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="http://localhost:11434/api/chat",
        settings=structured_settings(),
    )


@pytest.mark.parametrize(
    ("factory", "request_method", "native"),
    [
        (_build_task10_openai_chat_client, "_request_openai", True),
        (_build_task10_openai_responses_client, "_request_responses", True),
        (_build_task10_mistral_client, "_request_openai", False),
        (_build_task10_google_client, "_request_google", False),
        (_build_task10_cohere_client, "_request_cohere", False),
        (_build_task10_anthropic_client, "_request_anthropic", True),
        (_build_task10_ollama_client, "_request_ollama", True),
    ],
    ids=(
        "openai-chat",
        "openai-responses",
        "mistral",
        "google",
        "cohere",
        "anthropic",
        "ollama",
    ),
)
def test_provider_send_message_stores_visible_reply_only_in_history(
    monkeypatch,
    factory,
    request_method,
    native,
):
    from tests.http_structured_fixtures import (
        install_client_request_sequence,
        legacy_final_reply,
        native_final_reply,
    )

    visible_reply = "검증된 합성 표시 답변"
    carrier = (
        native_final_reply(visible_reply)
        if native
        else legacy_final_reply(visible_reply)
    )
    client = factory()
    records = install_client_request_sequence(
        monkeypatch,
        client,
        request_method,
        [carrier],
    )

    payload = client.send_message("중립 합성 입력")
    history = client.get_conversation_history()

    assert payload[0] == visible_reply
    assert history == [
        {"role": "user", "content": "중립 합성 입력"},
        {"role": "assistant", "content": visible_reply},
    ]
    assert records[0].context.response_mode is (
        ResponseMode.JSON_SCHEMA if native else ResponseMode.LEGACY_TAGS
    )
    metadata = client.get_last_response_delivery_metadata()
    assert metadata.response_mode == records[0].context.response_mode.value
    assert metadata.schema_version == "1"
    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_http_final_response_regenerates_from_same_history_snapshot(monkeypatch):
    from tests.http_structured_fixtures import (
        install_client_request_sequence,
        native_final_reply,
    )

    client = _build_task10_openai_chat_client()
    client._history = [
        {"role": "user", "content": "Earlier synthetic question."},
        {"role": "assistant", "content": "Earlier synthetic answer."},
    ]
    records = install_client_request_sequence(
        monkeypatch,
        client,
        "_request_openai",
        ["not-json", native_final_reply("Regenerated visible reply.")],
    )

    payload = client.send_message("Current synthetic question.")

    assert payload[0] == "Regenerated visible reply."
    assert [record.attempt.phase for record in records] == ["primary", "regenerate"]
    assert records[0].context.history == records[1].context.history == [
        {"role": "user", "content": "Earlier synthetic question."},
        {"role": "assistant", "content": "Earlier synthetic answer."},
    ]
    assert client.get_conversation_history()[-2:] == [
        {"role": "user", "content": "Current synthetic question."},
        {"role": "assistant", "content": "Regenerated visible reply."},
    ]


def test_explicit_unsupported_downgrades_and_caches_only_same_profile(monkeypatch):
    from tests.http_structured_fixtures import (
        explicit_unsupported_error,
        install_client_request_sequence,
        legacy_final_reply,
        native_final_reply,
    )

    client = _build_task10_openai_chat_client()
    records = install_client_request_sequence(
        monkeypatch,
        client,
        "_request_openai",
        [
            explicit_unsupported_error(),
            legacy_final_reply("Legacy fallback reply."),
            legacy_final_reply("Cached legacy reply."),
            native_final_reply("Different model native reply."),
        ],
    )

    assert client.send_message("First request.")[0] == "Legacy fallback reply."
    assert client.send_message("Second request.")[0] == "Cached legacy reply."
    client.model_name = "different-synthetic-model"
    assert client.send_message("Third request.")[0] == "Different model native reply."

    assert [record.context.response_mode for record in records] == [
        ResponseMode.JSON_SCHEMA,
        ResponseMode.LEGACY_TAGS,
        ResponseMode.LEGACY_TAGS,
        ResponseMode.JSON_SCHEMA,
    ]


def test_http_failure_keeps_history_and_clears_delivery_metadata(monkeypatch):
    from tests.http_structured_fixtures import (
        install_client_request_sequence,
        native_final_reply,
    )

    client = _build_task10_openai_chat_client()
    install_client_request_sequence(
        monkeypatch,
        client,
        "_request_openai",
        [native_final_reply("Committed reply."), requests.Timeout("synthetic timeout")],
    )

    client.send_message("Committed request.")
    committed_history = client.get_conversation_history()
    assert client.get_last_response_delivery_metadata().response_mode == "json_schema"

    with pytest.raises(requests.Timeout, match="synthetic timeout"):
        client.send_message("Failed request.")

    assert client.get_conversation_history() == committed_history
    assert client.get_last_response_delivery_metadata().response_mode == ""


def test_repair_is_historyless_and_uses_frozen_turn_context(monkeypatch):
    from tests.http_structured_fixtures import native_final_reply, structured_settings

    client = OpenAICompatibleClient(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://api.openai.com/v1/chat/completions",
        provider_name="openai",
        generation_params={"max_tokens": 321},
        settings=structured_settings(enable_ene_thoughts=True),
    )
    original_history = [
        {"role": "user", "content": "Earlier private-free fixture."},
        {"role": "assistant", "content": "Earlier visible fixture."},
    ]
    client._history = list(original_history)
    records = []

    def fake_request(*_args, request_descriptor=None, **_kwargs):
        records.append(request_descriptor)
        if len(records) == 1:
            client.settings["prompt_language"] = "en"
            client.generation_params["max_tokens"] = 999
            client._history.append(
                {"role": "assistant", "content": "Transient mutation."}
            )
            return native_final_reply("Validated visible reply.")
        return '{"thought":"Synthetic short inner note."}'

    monkeypatch.setattr(client, "_request_openai", fake_request)

    payload = client.send_message("Current repair request.")

    assert payload[0] == "Validated visible reply."
    assert payload[6] == "Synthetic short inner note."
    assert [record.attempt.phase for record in records] == ["primary", "repair"]
    primary, repair = records
    assert primary.context.history == original_history
    assert repair.context.history == []
    assert repair.context.attachments_metadata == []
    assert repair.context.system_prompt == ""
    assert repair.context.include_sub_prompt is False
    assert repair.context.generation_params == primary.context.generation_params
    assert repair.context.generation_params["max_tokens"] == 321
    assert repair.schema_name == "ene_response_repair_v1"
    assert tuple(repair.schema["properties"]) == ("thought",)
    assert "Response language: ko" in repair.context.user_content
    assert "Current repair request." not in repair.context.user_content
    assert "Earlier private-free fixture." not in repair.context.user_content
    assert client.get_conversation_history() == original_history + [
        {"role": "user", "content": "Current repair request."},
        {"role": "assistant", "content": "Validated visible reply."},
    ]
    assert client.get_last_response_delivery_metadata().repair_performed is True


def test_memory_path_commits_original_user_message_only(monkeypatch):
    from tests.http_structured_fixtures import (
        install_client_request_sequence,
        legacy_final_reply,
    )

    client = _build_task10_mistral_client()

    async def fake_memory_context(
        _message,
        recent_context="",
        head_pat_count_before_message=None,
    ):
        return "Synthetic memory context."

    monkeypatch.setattr(client, "_build_memory_context", fake_memory_context)
    records = install_client_request_sequence(
        monkeypatch,
        client,
        "_request_openai",
        [legacy_final_reply("Visible memory reply.")],
    )

    payload = asyncio.run(
        client.send_message_with_memory(
            "Original synthetic user message.",
            latest_user_message="Original synthetic user message.",
        )
    )

    assert payload[0] == "Visible memory reply."
    assert records[0].context.user_content != "Original synthetic user message."
    assert client.get_conversation_history() == [
        {"role": "user", "content": "Original synthetic user message."},
        {"role": "assistant", "content": "Visible memory reply."},
    ]
