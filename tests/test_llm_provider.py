import inspect
from typing import Dict, List, get_type_hints

import pytest

from src.ai.http_llm_common import resolve_response_mode
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
    LLMFormat,
    LLMClientProtocol,
    LLMProviderConfig,
    PROVIDER_BUILDERS,
    create_llm_client,
    get_llm_provider_catalog,
    get_llm_provider_meta,
    register_llm_provider,
)
from src.ai.response_protocol import (
    OneShotGenerationResult,
    ProviderProfile,
    ResponseMode,
)


def test_create_llm_client_raises_for_unknown_provider():
    config = LLMProviderConfig(provider="unknown", api_key="k")
    with pytest.raises(ValueError):
        create_llm_client(config)


def test_llm_client_protocol_parsed_response_methods_include_goal_update_and_proactive_list():
    method_names = [
        "send_message_with_memory",
        "send_message_with_images",
        "send_message",
        "generate_diary_completion_reply",
        "generate_note_execution_report",
    ]

    for method_name in method_names:
        return_type = get_type_hints(getattr(LLMClientProtocol, method_name))["return"]
        assert len(return_type.__args__) == 11
        assert return_type.__args__[-4] == Dict[str, str]
        assert return_type.__args__[-3] == List[Dict]
        assert return_type.__args__[-2] is str
        assert return_type.__args__[-1] == Dict[str, object] | None


def test_llm_client_protocol_exposes_async_life_record_one_shot():
    method = LLMClientProtocol.generate_life_record_once

    assert inspect.iscoroutinefunction(method)
    assert inspect.signature(method).return_annotation is OneShotGenerationResult


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


def test_registered_strict_builder_ignores_unknown_knowledge_map_kwarg():
    class DummyClient:
        pass

    captured = {}

    def strict_builder(*, api_key, model_name, generation_params):
        captured["api_key"] = api_key
        captured["model_name"] = model_name
        captured["generation_params"] = generation_params
        return DummyClient()

    provider_name = "dummy-strict-knowledge-map"
    register_llm_provider(provider_name, strict_builder)
    try:
        config = LLMProviderConfig(provider=provider_name, api_key="k", model_name="m")
        client = create_llm_client(config, knowledge_map_manager="knowledge")
        assert isinstance(client, DummyClient)
        assert captured == {
            "api_key": "k",
            "model_name": "m",
            "generation_params": {},
        }
        assert client.knowledge_map_manager == "knowledge"
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
    assert client.provider_name == "openai"


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
    if format_value == "openai_response_api":
        assert client.provider_name == "custom_api"


def test_custom_api_format_normalization_keeps_builder_and_identity_aligned():
    class SettingsDummy:
        def get(self, key, default=None):
            values = {
                "custom_api_format": " ANTHROPIC ",
                "custom_api_url": "",
                "custom_api_request_model": "synthetic-model",
            }
            return values.get(key, default)

    client = create_llm_client(
        LLMProviderConfig(
            provider="custom_api",
            api_key="synthetic-key",
            model_name="",
        ),
        settings=SettingsDummy(),
    )

    assert isinstance(client, AnthropicClient)
    assert client.provider_name == "custom_api"
    assert client.wire_format == "anthropic"


@pytest.mark.parametrize(
    ("format_value", "expected_type", "expected_wire_format"),
    [
        (LLMFormat.GEMINI, OpenAICompatibleClient, "openai_chat"),
        (
            LLMFormat.OPENAI_COMPATIBLE,
            OpenAICompatibleClient,
            "openai_chat",
        ),
        (
            LLMFormat.OPENAI_RESPONSE_API,
            OpenAIResponseAPIClient,
            "openai_responses",
        ),
        (LLMFormat.ANTHROPIC, AnthropicClient, "anthropic"),
        (LLMFormat.MISTRAL, MistralClient, "mistral"),
        (LLMFormat.GOOGLE_CLOUD, GoogleCloudClient, "google_cloud"),
        (LLMFormat.COHERE, CohereClient, "cohere"),
        (LLMFormat.OLLAMA, OllamaClient, "ollama"),
        (LLMFormat.CUSTOM, OpenAICompatibleClient, "openai_chat"),
    ],
)
def test_custom_api_format_enum_values_keep_builder_and_identity_aligned(
    format_value,
    expected_type,
    expected_wire_format,
):
    class SettingsDummy:
        def get(self, key, default=None):
            values = {
                "custom_api_format": format_value,
                "custom_api_url": "",
                "custom_api_request_model": "synthetic-model",
            }
            return values.get(key, default)

    client = create_llm_client(
        LLMProviderConfig(
            provider="custom_api",
            api_key="synthetic-key",
            model_name="",
        ),
        settings=SettingsDummy(),
    )

    assert isinstance(client, expected_type)
    assert client.provider_name == "custom_api"
    assert client.wire_format == expected_wire_format


def test_registered_named_replacement_is_not_forced_to_builtin_identity():
    class FrozenClient:
        __slots__ = ()

    def replacement_builder():
        return FrozenClient()

    original_builder = PROVIDER_BUILDERS["openai"]
    register_llm_provider("openai", replacement_builder)
    try:
        client = create_llm_client(
            LLMProviderConfig(
                provider="openai",
                api_key="synthetic-key",
                model_name="synthetic-model",
            )
        )
    finally:
        PROVIDER_BUILDERS["openai"] = original_builder

    assert isinstance(client, FrozenClient)
    assert not hasattr(client, "provider_name")
    assert not hasattr(client, "wire_format")


def test_named_anthropic_and_ollama_clients_expose_provider_identity():
    anthropic = create_llm_client(
        LLMProviderConfig(
            provider="anthropic",
            api_key="synthetic-key",
            model_name="synthetic-model",
        )
    )
    ollama = create_llm_client(
        LLMProviderConfig(
            provider="ollama",
            api_key="",
            model_name="synthetic-model",
        )
    )

    assert anthropic.provider_name == "anthropic"
    assert anthropic.wire_format == "anthropic"
    assert ollama.provider_name == "ollama"
    assert ollama.wire_format == "ollama"


@pytest.mark.parametrize(
    ("client_type", "provider_name", "wire_format"),
    [
        (AnthropicClient, "anthropic", "anthropic"),
        (OllamaClient, "ollama", "ollama"),
    ],
)
def test_named_http_identity_preserves_existing_constructor_signature(
    client_type,
    provider_name,
    wire_format,
):
    parameters = inspect.signature(client_type).parameters

    assert "provider_name" not in parameters
    assert "wire_format" not in parameters

    client = client_type(
        api_key="synthetic-key",
        model_name="synthetic-model",
        endpoint="https://synthetic.invalid/v1/generate",
    )
    assert client.provider_name == provider_name
    assert client.wire_format == wire_format


@pytest.mark.parametrize(
    ("provider", "expected_wire_format", "expected_mode"),
    [
        ("openai", "openai_responses", ResponseMode.JSON_SCHEMA),
        ("openrouter", "openai_chat", ResponseMode.JSON_SCHEMA),
        ("deepseek", "openai_chat", ResponseMode.JSON_OBJECT),
    ],
)
def test_named_factory_identity_builds_resolvable_provider_profile(
    provider,
    expected_wire_format,
    expected_mode,
):
    client = create_llm_client(
        LLMProviderConfig(
            provider=provider,
            api_key="synthetic-key",
            model_name="synthetic-model",
        )
    )
    current = ProviderProfile(
        provider=client.provider_name,
        wire_format=client.wire_format,
        endpoint=client.endpoint,
        model=client.model_name,
    )

    assert client.wire_format == expected_wire_format
    assert resolve_response_mode(current) is expected_mode


@pytest.mark.parametrize(
    ("format_value", "expected_wire_format"),
    [
        ("openai_compatible", "openai_chat"),
        ("openai_response_api", "openai_responses"),
        ("anthropic", "anthropic"),
        ("mistral", "mistral"),
        ("google_cloud", "google_cloud"),
        ("cohere", "cohere"),
        ("ollama", "ollama"),
    ],
)
def test_custom_api_clients_expose_custom_identity_for_every_wire_format(
    format_value,
    expected_wire_format,
):
    class SettingsDummy:
        def get(self, key, default=None):
            values = {
                "custom_api_format": format_value,
                "custom_api_url": "https://synthetic.invalid/v1/generate",
                "custom_api_request_model": "synthetic-model",
            }
            return values.get(key, default)

    client = create_llm_client(
        LLMProviderConfig(
            provider="custom_api",
            api_key="synthetic-key",
            model_name="",
        ),
        settings=SettingsDummy(),
    )

    assert client.provider_name == "custom_api"
    assert client.wire_format == expected_wire_format


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
