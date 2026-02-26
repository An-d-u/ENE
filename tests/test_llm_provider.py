import pytest

from src.ai.llm_provider import (
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


def test_provider_catalog_contains_major_providers():
    catalog = get_llm_provider_catalog()
    for provider in ["gemini", "openai", "anthropic", "openrouter", "deepseek", "ollama"]:
        assert provider in catalog


def test_provider_meta_returns_none_for_unknown():
    assert get_llm_provider_meta("not-exists") is None


def test_create_llm_client_for_supported_providers():
    for provider in ["openai", "openrouter", "deepseek", "anthropic", "ollama", "custom_api"]:
        config = LLMProviderConfig(provider=provider, api_key="k", model_name="m")
        client = create_llm_client(config)
        assert client is not None
