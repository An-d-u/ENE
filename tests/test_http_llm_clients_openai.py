import asyncio

import requests

import pytest

from src.ai.http_llm_clients import OpenAICompatibleClient, OpenAIResponseAPIClient
from src.ai.response_protocol import LLMRequestKind, ResponseMode
from src.ai.search_tool import SearchResponse, SearchResult
from src.ai.tool_calling import clear_web_search_cache

ANALYSIS_APPENDIX_MARKERS = (
    "[Internal Analysis Output Rules]",
    "[내부 분석 출력 규칙]",
)


class _DummyResponse:
    def __init__(self, *, status_code=200, json_data=None, text=""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error", response=self)

    def json(self):
        return self._json_data


class _SearchSettings:
    def __init__(self, *, auto_enabled=False):
        self.auto_enabled = auto_enabled

    def get(self, key, default=None):
        values = {
            "web_search_enabled": True,
            "web_search_auto_enabled": self.auto_enabled,
            "web_search_provider": "tavily",
            "web_search_max_results": 2,
            "web_search_timeout_sec": 5,
            "web_search_api_keys": {"tavily": "synthetic-key"},
        }
        return values.get(key, default)


class _RecordingTavilyProvider:
    provider_name = "tavily"
    queries = []

    def __init__(self, api_key, timeout_sec=12):
        self.api_key = api_key
        self.timeout_sec = timeout_sec

    def search(self, query):
        self.__class__.queries.append(query)
        return SearchResponse(
            query=query.query,
            provider=self.provider_name,
            results=[
                SearchResult(
                    title="Neutral Topic Result",
                    url="https://example.com/neutral-topic",
                    snippet="Synthetic neutral search result.",
                )
            ],
        )


def _install_fake_search(monkeypatch):
    clear_web_search_cache()
    _RecordingTavilyProvider.queries = []
    monkeypatch.setattr("src.ai.tool_calling.TavilySearchProvider", _RecordingTavilyProvider)
    return _RecordingTavilyProvider


def test_openai_client_preserves_normalized_reasoning_effort():
    client = OpenAIResponseAPIClient(
        api_key="test-key",
        model_name="gpt-5.6-sol",
        endpoint="https://api.openai.com/v1/responses",
        generation_params={"reasoning_effort": " HIGH "},
    )

    assert client.generation_params["reasoning_effort"] == "high"


def test_openai_responses_client_uses_official_endpoint_by_default():
    client = OpenAIResponseAPIClient(
        api_key="test-key",
        model_name="gpt-5.6-sol",
    )

    assert client.endpoint == "https://api.openai.com/v1/responses"


def test_openai_responses_request_applies_gpt_5_6_policy(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="test-key",
        model_name="gpt-5.6-sol",
        endpoint="https://api.openai.com/v1/responses",
        generation_params={
            "temperature": 0.4,
            "top_p": 0.7,
            "max_tokens": 1234,
            "reasoning_effort": "high",
        },
    )

    assert client._request_responses("Neutral request input.") == "Synthetic response."
    assert "temperature" not in captured["json"]
    assert "top_p" not in captured["json"]
    assert captured["json"]["reasoning"] == {"effort": "high"}
    assert captured["json"]["max_output_tokens"] == 1234


def test_openai_responses_one_shot_applies_gpt_5_6_policy(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="test-key",
        model_name="gpt-5.6",
        endpoint="https://api.openai.com/v1/responses",
        generation_params={
            "temperature": 0.3,
            "top_p": 0.6,
            "max_tokens": 1536,
            "reasoning_effort": "max",
        },
    )

    assert client._request_one_shot_raw(
        "Neutral one-shot input.",
        request_kind=LLMRequestKind.SUMMARY,
    ) == "Synthetic response."
    assert "temperature" not in captured["json"]
    assert "top_p" not in captured["json"]
    assert captured["json"]["reasoning"] == {"effort": "max"}
    assert captured["json"]["max_output_tokens"] == 1536


def test_official_openai_response_request_remains_legacy_during_classification(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)
    client = OpenAIResponseAPIClient(
        api_key="synthetic-key",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
    )

    assert client._request_responses("Synthetic final request.") == "Synthetic response."

    fingerprint = client.get_last_request_context_fingerprint()
    assert fingerprint["request_kind"] == LLMRequestKind.FINAL_REPLY.value
    assert fingerprint["response_mode"] == ResponseMode.LEGACY_TAGS.value
    assert fingerprint["schema_version"] == "1"
    assert "text" not in captured["json"]
    assert "response_format" not in captured["json"]


def test_openai_responses_gpt_5_6_defaults_reasoning_effort_to_low(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="test-key",
        model_name="gpt-5.6",
        endpoint="https://api.openai.com/v1/responses",
    )

    assert client._request_responses("Neutral default-effort input.") == "Synthetic response."
    assert captured["json"]["reasoning"] == {"effort": "low"}


def test_custom_responses_gpt_5_6_keeps_sampling_without_reasoning(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="test-key",
        model_name="gpt-5.6-sol",
        endpoint="https://example.com/v1/responses",
        provider_name="custom_api",
        generation_params={"temperature": 0.2, "top_p": 0.8},
    )

    assert client._request_responses("Neutral custom request input.") == "Synthetic response."
    assert captured["json"]["temperature"] == 0.2
    assert captured["json"]["top_p"] == 0.8
    assert "reasoning" not in captured["json"]


def test_openai_responses_request_includes_instructions(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _DummyResponse(json_data={"output_text": "응답"})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
    )

    assert client._request_responses("테스트") == "응답"
    assert captured["url"] == "https://api.openai.com/v1/responses"
    assert captured["json"]["model"] == "gpt-5.4-mini"
    assert captured["json"]["instructions"]
    assert any(marker in captured["json"]["instructions"] for marker in ANALYSIS_APPENDIX_MARKERS)
    assert captured["json"]["temperature"] == 0.9
    assert captured["json"]["top_p"] == 1.0
    assert "reasoning" not in captured["json"]


def test_openai_responses_send_message_with_memory_injects_manual_search_context(monkeypatch):
    provider = _install_fake_search(monkeypatch)
    stages = []
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
        settings=_SearchSettings(),
    )

    asyncio.run(
        client.send_message_with_memory(
            "Original final prompt.",
            latest_user_message="/search neutral topic",
            progress_callback=stages.append,
        )
    )

    text = captured["json"]["input"][-1]["content"][0]["text"]
    assert provider.queries[0].query == "neutral topic"
    assert provider.queries[0].max_results == 2
    assert "[WEB_SEARCH_RESULTS]" in text
    assert "[WEB_SEARCH_STATUS]" in text
    assert "Performed: yes" in text
    assert "Synthetic neutral search result." in text
    assert text.endswith("Original final prompt.")
    assert stages == ["searching", "thinking"]


def test_openai_web_search_cache_is_scoped_per_client(monkeypatch):
    provider = _install_fake_search(monkeypatch)
    captured_payloads = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_payloads.append(json)
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    first_client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
        settings=_SearchSettings(),
    )
    second_client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
        settings=_SearchSettings(),
    )

    asyncio.run(
        first_client.send_message_with_memory(
            "First final prompt.",
            latest_user_message="/search neutral topic",
        )
    )
    asyncio.run(
        second_client.send_message_with_memory(
            "Second final prompt.",
            latest_user_message="/search neutral topic",
        )
    )

    assert len(provider.queries) == 2
    assert "Reason: search_performed" in captured_payloads[0]["input"][-1]["content"][0]["text"]
    assert "Reason: search_performed" in captured_payloads[1]["input"][-1]["content"][0]["text"]


def test_openai_web_search_cache_reuses_results_within_same_client(monkeypatch):
    provider = _install_fake_search(monkeypatch)
    captured_payloads = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_payloads.append(json)
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
        settings=_SearchSettings(),
    )

    asyncio.run(
        client.send_message_with_memory(
            "First final prompt.",
            latest_user_message="/search neutral topic",
        )
    )
    asyncio.run(
        client.send_message_with_memory(
            "Second final prompt.",
            latest_user_message="/search neutral topic",
        )
    )

    first_text = captured_payloads[0]["input"][-1]["content"][0]["text"]
    second_text = captured_payloads[1]["input"][-1]["content"][0]["text"]
    assert len(provider.queries) == 1
    assert "Reason: search_performed" in first_text
    assert "Reason: cache_hit" in second_text
    assert "SearchContextSource: cache" in second_text


def test_openai_responses_auto_search_decision_injects_results(monkeypatch):
    provider = _install_fake_search(monkeypatch)
    captured_payloads = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_payloads.append(json)
        if len(captured_payloads) == 1:
            return _DummyResponse(
                json_data={
                    "output_text": (
                        '{"should_search": true, "query": "neutral release schedule", '
                        '"reason": "current info"}'
                    )
                }
            )
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
        settings=_SearchSettings(auto_enabled=True),
    )

    asyncio.run(
        client.send_message_with_memory(
            "Original final prompt.",
            latest_user_message="What is the latest neutral release schedule?",
        )
    )

    assert len(captured_payloads) == 2
    assert provider.queries[0].query == "neutral release schedule"
    final_text = captured_payloads[1]["input"][-1]["content"][0]["text"]
    assert "[WEB_SEARCH_RESULTS]" in final_text
    assert "[WEB_SEARCH_STATUS]" in final_text
    assert "Performed: yes" in final_text
    assert "Synthetic neutral search result." in final_text
    assert final_text.endswith("Original final prompt.")


def test_openai_responses_auto_no_search_skips_tavily_and_search_progress(monkeypatch):
    provider = _install_fake_search(monkeypatch)
    captured_payloads = []
    stages = []

    def fake_post(url, headers=None, json=None, timeout=None):
        captured_payloads.append(json)
        if len(captured_payloads) == 1:
            return _DummyResponse(
                json_data={
                    "output_text": (
                        '{"should_search": false, "query": "", '
                        '"reason": "conversation context is enough"}'
                    )
                }
            )
        return _DummyResponse(json_data={"output_text": "Synthetic response."})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
        settings=_SearchSettings(auto_enabled=True),
    )

    asyncio.run(
        client.send_message_with_memory(
            "Original final prompt.",
            latest_user_message="Help me outline a neutral short story.",
            progress_callback=stages.append,
        )
    )

    assert len(captured_payloads) == 2
    assert provider.queries == []
    final_text = captured_payloads[1]["input"][-1]["content"][0]["text"]
    assert "[WEB_SEARCH_RESULTS]" not in final_text
    assert "[WEB_SEARCH_STATUS]" in final_text
    assert "Performed: no" in final_text
    assert "Reason: auto_decision_no_search" in final_text
    assert "Decision: conversation context is enough" in final_text
    assert "Original final prompt." in final_text
    assert "searching" not in stages


def test_openai_compatible_send_message_with_memory_uses_latest_user_message_for_manual_detection(monkeypatch):
    provider = _install_fake_search(monkeypatch)
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(json_data={"choices": [{"message": {"content": "Synthetic response."}}]})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAICompatibleClient(
        api_key="k",
        model_name="compatible-model",
        endpoint="https://example.com/v1/chat/completions",
        provider_name="compatible",
        settings=_SearchSettings(),
    )

    asyncio.run(
        client.send_message_with_memory(
            "Header context\n/search should not run\nOriginal final prompt.",
            latest_user_message="Plain current message.",
        )
    )

    text = captured["json"]["messages"][-1]["content"]
    assert provider.queries == []
    assert "[WEB_SEARCH_RESULTS]" not in text
    assert "[WEB_SEARCH_STATUS]" in text
    assert "Performed: no" in text
    assert "/search should not run" in text


def test_openai_compatible_image_request_puts_search_context_in_text_part(monkeypatch):
    _install_fake_search(monkeypatch)
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse(json_data={"choices": [{"message": {"content": "Synthetic response."}}]})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAICompatibleClient(
        api_key="k",
        model_name="compatible-model",
        endpoint="https://example.com/v1/chat/completions",
        provider_name="compatible",
        settings=_SearchSettings(),
    )

    asyncio.run(
        client.send_message_with_images(
            "Describe this synthetic image.",
            [{"dataUrl": "data:image/png;base64,QUJD"}],
            latest_user_message="/search neutral topic",
        )
    )

    content = captured["json"]["messages"][-1]["content"]
    assert content[0]["type"] == "text"
    assert "[WEB_SEARCH_RESULTS]" in content[0]["text"]
    assert "[WEB_SEARCH_STATUS]" in content[0]["text"]
    assert "Performed: yes" in content[0]["text"]
    assert content[0]["text"].endswith("Describe this synthetic image.")


def test_openai_responses_error_includes_response_body(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        return _DummyResponse(
            status_code=400,
            json_data={"error": {"message": "Unsupported parameter: max_tokens"}},
            text='{"error":{"message":"Unsupported parameter: max_tokens"}}',
        )

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
    )

    with pytest.raises(requests.HTTPError, match="Unsupported parameter: max_tokens"):
        client._request_responses("테스트")


def test_openai_client_parse_response_hides_analysis_metadata_and_japanese():
    client = OpenAIResponseAPIClient.__new__(OpenAIResponseAPIClient)
    response_text = """
user_emotion=calm, tired
user_intent=greeting, check-in
interaction_effect=positive
bond_delta_hint=low_positive
stress_delta_hint=none
energy_delta_hint=none
valence_delta_hint=low_positive
confidence=0.9
flags=greeting

좋은 저녁이에요. 오늘도 고생 많으셨어요. [smile]
こんばんは。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

    assert text == "좋은 저녁이에요. 오늘도 고생 많으셨어요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert events == []
    assert analysis["user_emotion"] == "calm, tired"
    assert analysis["flags"] == "greeting"
    assert promises == []
    assert thought == ""


def test_openai_send_message_keeps_raw_assistant_output_in_history(monkeypatch):
    raw_output = """
[analysis]
user_emotion=calm
user_intent=greeting
confidence=0.8
[/analysis]
좋은 저녁이에요. [smile]
こんばんは。
""".strip()

    def fake_post(url, headers=None, json=None, timeout=None):
        return _DummyResponse(json_data={"output_text": raw_output})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = OpenAIResponseAPIClient(
        api_key="k",
        model_name="gpt-5.4-mini",
        endpoint="https://api.openai.com/v1/responses",
    )

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client.send_message("테스트")
    history = client.get_conversation_history()

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert events == []
    assert analysis["user_intent"] == "greeting"
    assert promises == []
    assert thought == ""
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == raw_output
