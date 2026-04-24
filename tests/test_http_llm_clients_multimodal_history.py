import asyncio

import pytest

from src.ai.http_llm_clients import (
    AnthropicClient,
    GoogleCloudClient,
    OllamaClient,
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
)


IMAGE_DATA_URL = "data:image/png;base64,QUJD"
RAW_OUTPUT = """
[analysis]
user_emotion=calm
user_intent=image_reference
confidence=0.8
[/analysis]
네, 그 이미지 기억하고 있어요. [smile]
その画像、覚えています。
""".strip()


class _DummyResponse:
    def __init__(self, json_data):
        self._json_data = json_data
        self.text = ""

    def raise_for_status(self):
        return None

    def json(self):
        return self._json_data


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


def _build_google_client():
    return GoogleCloudClient(
        api_key="k",
        model_name="m",
        endpoint="https://example.com/v1beta/models/{model}:generateContent",
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
    ("factory", "request_method", "assert_history"),
    [
        (
            _build_openai_compatible_client,
            "_request_openai",
            lambda history: (
                history[0]["content"][0]["type"] == "text"
                and history[0]["content"][0]["text"] == "설명"
                and history[0]["content"][1]["type"] == "image_url"
                and history[0]["content"][1]["image_url"]["url"] == IMAGE_DATA_URL
            ),
        ),
        (
            _build_openai_response_client,
            "_request_responses",
            lambda history: (
                history[0]["content"][0]["type"] == "text"
                and history[0]["content"][0]["text"] == "설명"
                and history[0]["content"][1]["type"] == "image_url"
                and history[0]["content"][1]["image_url"]["url"] == IMAGE_DATA_URL
            ),
        ),
        (
            _build_google_client,
            "_request_google",
            lambda history: (
                history[0]["content"][0]["text"] == "설명"
                and history[0]["content"][1]["inlineData"]["data"] == "QUJD"
            ),
        ),
        (
            _build_anthropic_client,
            "_request_anthropic",
            lambda history: (
                history[0]["content"][0]["type"] == "text"
                and history[0]["content"][0]["text"] == "설명"
                and history[0]["content"][1]["type"] == "image"
                and history[0]["content"][1]["source"]["data"] == "QUJD"
            ),
        ),
        (
            _build_ollama_client,
            "_request_ollama",
            lambda history: (
                history[0]["content"]["content"] == "설명"
                and history[0]["content"]["images"] == ["QUJD"]
            ),
        ),
    ],
    ids=["openai_compatible", "openai_response", "google_cloud", "anthropic", "ollama"],
)
def test_multimodal_turn_is_preserved_in_history(monkeypatch, factory, request_method, assert_history):
    client = factory()

    async def fake_memory_context(_message, recent_context: str = "", head_pat_count_before_message: int | None = None):
        return ""

    monkeypatch.setattr(client, "_build_memory_context", fake_memory_context)
    monkeypatch.setattr(client, request_method, lambda *args, **kwargs: RAW_OUTPUT)

    asyncio.run(client.send_message_with_images("설명", [{"dataUrl": IMAGE_DATA_URL}]))

    history = client.get_conversation_history()
    assert history[0]["role"] == "user"
    assert assert_history(history)


def test_openai_response_history_rehydrates_prior_image_turn():
    client = _build_openai_response_client()
    client._history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "이전 이미지"},
                {"type": "image_url", "image_url": {"url": IMAGE_DATA_URL}},
            ],
        }
    ]

    items = client._input_items("다음 질문")

    assert items[0]["role"] == "user"
    assert items[0]["content"][0] == {"type": "input_text", "text": "이전 이미지"}
    assert items[0]["content"][1] == {
        "type": "input_image",
        "detail": "auto",
        "image_url": IMAGE_DATA_URL,
    }


def test_google_history_rehydrates_prior_image_turn(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse({"candidates": [{"content": {"parts": [{"text": "응답"}]}}]})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = _build_google_client()
    client._history = [
        {
            "role": "user",
            "content": [
                {"text": "이전 이미지"},
                {"inlineData": {"mimeType": "image/png", "data": "QUJD"}},
            ],
        }
    ]

    client._request_google("다음 질문")

    assert captured["json"]["contents"][0]["parts"][0]["text"] == "이전 이미지"
    assert captured["json"]["contents"][0]["parts"][1]["inlineData"]["data"] == "QUJD"


def test_anthropic_history_rehydrates_prior_image_turn(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse({"content": [{"type": "text", "text": "응답"}]})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = _build_anthropic_client()
    client._history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "이전 이미지"},
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"},
                },
            ],
        }
    ]

    client._request_anthropic([{"type": "text", "text": "다음 질문"}])

    assert captured["json"]["messages"][0]["content"][0]["text"] == "이전 이미지"
    assert captured["json"]["messages"][0]["content"][1]["source"]["data"] == "QUJD"


def test_ollama_history_rehydrates_prior_image_turn(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _DummyResponse({"message": {"content": "응답"}})

    monkeypatch.setattr("src.ai.http_llm_clients.requests.post", fake_post)

    client = _build_ollama_client()
    client._history = [
        {
            "role": "user",
            "content": {"content": "이전 이미지", "images": ["QUJD"]},
        }
    ]

    client._request_ollama("다음 질문")

    assert captured["json"]["messages"][1]["content"] == "이전 이미지"
    assert captured["json"]["messages"][1]["images"] == ["QUJD"]


def test_http_rebuild_context_from_conversation_prefixes_message_time():
    client = _build_openai_compatible_client()

    ok = client.rebuild_context_from_conversation(
        [
            ("user", "안녕", "2026-03-24 10:00"),
            ("assistant", "반가워", "2026-03-24 10:01"),
        ]
    )

    assert ok is True
    assert client.get_conversation_history() == [
        {"role": "user", "content": "[Message Time: 2026-03-24 10:00]\n안녕"},
        {"role": "assistant", "content": "[Message Time: 2026-03-24 10:01]\n반가워"},
    ]
