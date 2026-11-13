"""공급자 설정과 요청 경계는 합성 데이터만으로 검증한다."""

import asyncio
from types import SimpleNamespace

import pytest

from src.ai.http_llm_clients import AnthropicClient, OllamaClient
from src.ai.http_llm_common import clear_http_response_capability_cache
from src.ai.llm_provider import LLMProviderConfig, create_llm_client, get_llm_provider_meta
from src.ai.response_protocol import LLMRequestKind, ResponseMode
from src.core.app import ENEApplication
from src.core.app_llm_bootstrap import resolve_llm_bootstrap_config
from src.core.settings import Settings


@pytest.fixture(autouse=True)
def isolate_prompts(monkeypatch):
    monkeypatch.setattr("src.ai.prompt_config._should_sync_store_python_prompt_dirs", lambda: False)
    monkeypatch.setattr("src.ai.http_llm_common.build_runtime_system_prompt", lambda **kwargs: "합성 지침")
    monkeypatch.setattr("src.ai.llm_client.build_runtime_system_prompt", lambda **kwargs: "합성 지침")
    clear_http_response_capability_cache()
    yield
    clear_http_response_capability_cache()


@pytest.mark.parametrize("provider,wire_format,expected", [
    ("ollama", "openai_compatible", True),
    ("custom_api", "ollama", True),
    ("gemini", "ollama", False),
    ("anthropic", "ollama", False),
    ("custom_api", "anthropic", False),
])
def test_bootstrap_allows_missing_key_only_for_ollama(monkeypatch, provider, wire_format, expected):
    monkeypatch.setattr("src.core.app.resolve_llm_bootstrap_config", lambda _: LLMProviderConfig(provider=provider))
    created = SimpleNamespace()
    monkeypatch.setattr("src.core.app.create_llm_runtime_client", lambda *args: created)
    app = SimpleNamespace(
        settings={"custom_api_format": wire_format}, memory_manager=None,
        user_profile=None, life_record_manager=None, _init_tts=lambda: None,
    )
    ENEApplication._init_llm_client(app)
    assert (app.llm_client is created) is expected


@pytest.mark.parametrize("key", ["", "synthetic-token"])
def test_local_ollama_ignores_stale_custom_url_and_model(key):
    settings = {
        "llm_provider": "ollama", "llm_api_keys": {"ollama": key},
        "llm_model": "synthetic-external-model",
        "custom_api_url": "https://example.invalid/previous-service",
    }
    config = resolve_llm_bootstrap_config(settings)
    client = create_llm_client(config, settings=settings)
    assert client.endpoint == "http://127.0.0.1:11434/api/chat"
    assert client.model_name == "llama3.1"


@pytest.mark.parametrize("provider", ["ollama", "custom_api"])
@pytest.mark.parametrize("enabled", [False, True])
def test_ollama_vision_is_explicit_and_streaming_is_not_advertised(provider, enabled):
    client = create_llm_client(LLMProviderConfig(provider=provider), settings={
        "custom_api_format": "ollama", "ollama_image_input_enabled": enabled,
    })
    assert client.supports_image_input is enabled
    assert client.llm_capabilities["image_input"] is enabled
    assert client.llm_capabilities["streaming"] is False
    assert client.endpoint == "http://127.0.0.1:11434/api/chat"


@pytest.mark.parametrize("request_kind", ["chat", "image", "summary", "life_record"])
@pytest.mark.parametrize("key", ["", "synthetic-token"])
def test_ollama_authentication_is_consistent(monkeypatch, request_kind, key):
    calls = []
    def post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
            "message": {"content": "합성 응답"}, "done": True, "done_reason": "stop",
        })
    monkeypatch.setattr("src.ai.http_llm_ollama.requests.post", post)
    client = OllamaClient(api_key=key, model_name="synthetic-model", endpoint="https://example.invalid/api/chat")
    if request_kind == "life_record":
        asyncio.run(asyncio.wait_for(client.generate_life_record_once("합성 기록을 생성하세요."), timeout=5))
    elif request_kind == "summary":
        client._request_one_shot_raw("합성 요약", request_kind=LLMRequestKind.SUMMARY)
    else:
        client._request_ollama("합성 요청", images_data=[{"dataUrl": "data:image/png;base64,c3ludGhldGlj"}] if request_kind == "image" else None)
    assert calls
    for url, kwargs in calls:
        assert url == "https://example.invalid/api/chat"
        headers = kwargs.get("headers", {})
        assert headers.get("Authorization") == (f"Bearer {key}" if key else None)
        assert headers.get("Content-Type") == "application/json"
        assert kwargs["json"]["stream"] is False
    if request_kind == "image":
        assert calls[0][1]["json"]["messages"][-1]["images"] == ["c3ludGhldGlj"]


@pytest.mark.parametrize("model", ["claude-sonnet-4-6", "claude-opus-4-7", "claude-sonnet-5-5"])
@pytest.mark.parametrize("one_shot", [False, True])
def test_claude_requests_omit_sampling_parameters(monkeypatch, model, one_shot):
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"content": [{"type": "text", "text": "합성 응답"}]})
    monkeypatch.setattr("src.ai.http_llm_anthropic.requests.post", post)
    client = AnthropicClient(api_key="synthetic-token", model_name=model, endpoint="https://example.invalid/messages", generation_params={"temperature": 0.4, "top_p": 0.8, "max_tokens": 1024})
    if one_shot:
        client._request_one_shot_raw("합성 요약", request_kind=LLMRequestKind.SUMMARY)
    else:
        client._request_anthropic([{"type": "text", "text": "합성 요청"}])
    assert calls[0]["max_tokens"] == 1024
    assert "temperature" not in calls[0]
    assert "top_p" not in calls[0]


def test_claude_default_and_retired_default_resolution():
    expected = "claude-sonnet-4-6"
    assert get_llm_provider_meta("anthropic").default_model == expected
    assert Settings.DEFAULT_CONFIG["llm_models"]["anthropic"] == expected
    for model in ("", "claude-3-5-sonnet-latest"):
        client = create_llm_client(LLMProviderConfig(provider="anthropic", model_name=model))
        assert client.model_name == expected
    config = resolve_llm_bootstrap_config({"llm_provider": "anthropic", "llm_models": {"anthropic": "claude-3-5-sonnet-latest"}})
    assert config.model_name == expected
    assert create_llm_client(LLMProviderConfig(provider="anthropic", model_name="claude-opus-4-7")).model_name == "claude-opus-4-7"


@pytest.mark.parametrize("model,sampling", [
    ("gemini-2.5-flash", True), ("gemini-3-flash-preview", True),
    ("gemini-3.5-flash", True), ("gemini-3.5-flash-lite", False),
    ("models/gemini-3.6-flash", False), ("gemini-3.8-flash", False),
    ("gemini-4-argon", False), ("gemini-flash-latest", False),
])
def test_gemini_all_config_paths_obey_model_sampling_policy(gemini_harness, model, sampling):
    client = gemini_harness.client([])
    client.model_name = model
    params = {"temperature": 0.4, "top_p": 0.8, "max_tokens": 1024}
    client.generation_params = params
    configs = [
        client._build_chat_config(request_kind=LLMRequestKind.FINAL_REPLY),
        client._build_life_record_config(system_instruction="합성 지침", use_native_schema=True, generation_params=params),
        client._build_summary_config(request_kind=LLMRequestKind.SUMMARY),
        client._build_repair_config(response_mode=ResponseMode.JSON_SCHEMA, schema={"type": "object"}, generation_params=params),
    ]
    for config in configs:
        assert ("temperature" in config) is sampling
        assert ("top_p" in config) is sampling
        assert config["max_output_tokens"] >= 1024
