import requests

import pytest

from src.ai.http_llm_clients import OpenAIResponseAPIClient


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
    assert "[Internal Analysis Output Rules]" in captured["json"]["instructions"]


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

    text, emotion, japanese_text, events, analysis = client._parse_response(response_text)

    assert text == "좋은 저녁이에요. 오늘도 고생 많으셨어요."
    assert emotion == "smile"
    assert japanese_text == "こんばんは。"
    assert events == []
    assert analysis["user_emotion"] == "calm, tired"
    assert analysis["flags"] == "greeting"


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

    text, emotion, japanese_text, events, analysis = client.send_message("테스트")
    history = client.get_conversation_history()

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert japanese_text == "こんばんは。"
    assert events == []
    assert analysis["user_intent"] == "greeting"
    assert history[-1]["role"] == "assistant"
    assert history[-1]["content"] == raw_output
