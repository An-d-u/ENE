from typing import Dict, get_type_hints

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
from src.ai.llm_provider import (
    LLMCapability,
    LLMClientProtocol,
    LLMProviderConfig,
    PROVIDER_BUILDERS,
    create_llm_client,
    get_llm_provider_catalog,
    get_llm_provider_meta,
    register_llm_provider,
)


def test_create_llm_client_raises_for_unknown_provider():
    config = LLMProviderConfig(provider="unknown", api_key="k")
    with pytest.raises(ValueError):
        create_llm_client(config)


def test_llm_client_protocol_parsed_response_methods_include_goal_update_dict():
    method_names = [
        "send_message_with_memory",
        "send_message_with_images",
        "send_message",
        "generate_diary_completion_reply",
        "generate_note_execution_report",
    ]

    for method_name in method_names:
        return_type = get_type_hints(getattr(LLMClientProtocol, method_name))["return"]
        assert len(return_type.__args__) == 8
        assert return_type.__args__[-1] == Dict[str, str]


def test_register_provider_and_create_client():
    class DummyClient:
        pass

    captured = {}

    def dummy_builder(**kwargs):
        captured.update(kwargs)
        return DummyClient()

    provider_name = "dummy-test"
    register_llm_provider(provider_name, dummy_builder)
    try:
        config = LLMProviderConfig(provider=provider_name, api_key="k", model_name="m")
        client = create_llm_client(config)
        assert isinstance(client, DummyClient)
        assert captured.get("generation_params") == {}
    finally:
        PROVIDER_BUILDERS.pop(provider_name, None)


def test_generation_params_are_forwarded_to_builder():
    class DummyClient:
        pass

    captured = {}

    def dummy_builder(**kwargs):
        captured.update(kwargs)
        return DummyClient()

    provider_name = "dummy-params"
    register_llm_provider(provider_name, dummy_builder)
    try:
        config = LLMProviderConfig(
            provider=provider_name,
            api_key="k",
            model_name="m",
            generation_params={"temperature": 0.2, "top_p": 0.5, "max_tokens": 1000},
        )
        client = create_llm_client(config)
        assert isinstance(client, DummyClient)
        assert captured.get("generation_params") == {"temperature": 0.2, "top_p": 0.5, "max_tokens": 1000}
    finally:
        PROVIDER_BUILDERS.pop(provider_name, None)


def test_goal_manager_is_forwarded_to_builder():
    class DummyClient:
        pass

    captured = {}

    def dummy_builder(**kwargs):
        captured.update(kwargs)
        return DummyClient()

    provider_name = "dummy-goal-manager"
    goal_manager = object()
    register_llm_provider(provider_name, dummy_builder)
    try:
        config = LLMProviderConfig(provider=provider_name, api_key="k", model_name="m")
        client = create_llm_client(config, goal_manager=goal_manager)
        assert isinstance(client, DummyClient)
        assert captured.get("goal_manager") is goal_manager
    finally:
        PROVIDER_BUILDERS.pop(provider_name, None)


def test_provider_catalog_contains_major_providers():
    catalog = get_llm_provider_catalog()
    for provider in ["gemini", "openai", "anthropic", "openrouter", "deepseek", "ollama"]:
        assert provider in catalog


def test_provider_meta_returns_none_for_unknown():
    assert get_llm_provider_meta("not-exists") is None


def test_create_openai_client_uses_responses_api():
    config = LLMProviderConfig(provider="openai", api_key="k", model_name="gpt-5.4-mini")
    client = create_llm_client(config)
    assert isinstance(client, OpenAIResponseAPIClient)
    assert client.endpoint == "https://api.openai.com/v1/responses"


@pytest.mark.parametrize(
    ("format_value", "expected_type"),
    [
        ("openai_compatible", OpenAICompatibleClient),
        ("openai_response_api", OpenAIResponseAPIClient),
        ("anthropic", AnthropicClient),
        ("mistral", MistralClient),
        ("google_cloud", GoogleCloudClient),
        ("cohere", CohereClient),
        ("ollama", OllamaClient),
    ],
)
def test_custom_api_format_clients_forward_goal_manager(format_value, expected_type):
    class SettingsDummy:
        def get(self, key, default=None):
            values = {
                "custom_api_format": format_value,
                "custom_api_url": "",
                "custom_api_request_model": "custom-model",
            }
            return values.get(key, default)

    goal_manager = object()
    config = LLMProviderConfig(provider="custom_api", api_key="k", model_name="")

    client = create_llm_client(config, settings=SettingsDummy(), goal_manager=goal_manager)

    assert isinstance(client, expected_type)
    assert client.goal_manager is goal_manager
    if isinstance(client, OpenAICompatibleClient):
        assert client.provider_name == "custom_api"


def test_create_llm_client_for_supported_providers():
    for provider in ["openai", "openrouter", "deepseek", "anthropic", "ollama", "custom_api"]:
        config = LLMProviderConfig(provider=provider, api_key="k", model_name="m")
        client = create_llm_client(config)
        assert client is not None


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        ("gemini", True),
        ("openai", True),
        ("openrouter", True),
        ("anthropic", True),
        ("deepseek", False),
        ("ollama", False),
        ("custom_api", False),
    ],
)
def test_create_llm_client_sets_image_input_capability(monkeypatch, provider, expected):
    if provider == "gemini":
        class DummyGeminiClient:
            pass

        monkeypatch.setitem(PROVIDER_BUILDERS, "gemini", lambda **_kwargs: DummyGeminiClient())

    config = LLMProviderConfig(provider=provider, api_key="k", model_name="m")
    client = create_llm_client(config)

    assert client.supports_image_input is expected
    assert client.llm_capabilities[LLMCapability.IMAGE_INPUT.value] is expected
