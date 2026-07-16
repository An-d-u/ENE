from src.ai.llm_provider import LLMProviderConfig
from src.core.app_llm_bootstrap import (
    LLMRuntimeDependencies,
    create_llm_runtime_client,
    resolve_llm_bootstrap_config,
)


class _Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_resolve_llm_bootstrap_config_uses_provider_model_params_and_key(tmp_path):
    settings = _Settings(
        {
            "llm_provider": "openai",
            "llm_models": {"openai": "gpt-5-mini"},
            "llm_model_params": {
                "openai": {
                    "gpt-5-mini": {
                        "temperature": 3,
                        "top_p": -1,
                        "max_tokens": "4096",
                    }
                }
            },
            "llm_api_keys": {"openai": "sk-openai"},
        }
    )

    config = resolve_llm_bootstrap_config(settings, api_key_file=tmp_path / "api_key.txt")

    assert config == LLMProviderConfig(
        provider="openai",
        api_key="sk-openai",
        model_name="gpt-5-mini",
        generation_params={"temperature": 2.0, "top_p": 0.0, "max_tokens": 4096},
    )


def test_resolve_llm_bootstrap_config_defaults_openai_gpt_5_6_reasoning_to_low():
    settings = _Settings(
        {
            "llm_provider": "openai",
            "llm_model": "gpt-5.6-sol",
            "llm_model_params": {
                "openai": {
                    "gpt-5.6-sol": {
                        "temperature": 0.4,
                        "top_p": 0.8,
                        "max_tokens": 4096,
                        "reasoning_effort": "invalid",
                    }
                }
            },
        }
    )

    resolved = resolve_llm_bootstrap_config(settings)

    assert resolved.generation_params == {
        "temperature": 0.4,
        "top_p": 0.8,
        "max_tokens": 4096,
        "reasoning_effort": "low",
    }


def test_resolve_llm_bootstrap_config_defaults_openai_gpt_5_6_reasoning_without_model_params():
    settings = _Settings(
        {
            "llm_provider": "openai",
            "llm_model": "gpt-5.6-sol",
        }
    )

    resolved = resolve_llm_bootstrap_config(settings)

    assert resolved.generation_params == {
        "temperature": 0.9,
        "top_p": 1.0,
        "max_tokens": 2048,
        "reasoning_effort": "low",
    }


def test_resolve_llm_bootstrap_config_falls_back_to_legacy_gemini_key_file(tmp_path):
    api_key_file = tmp_path / "api_key.txt"
    api_key_file.write_text(" legacy-key \n", encoding="utf-8-sig")
    settings = _Settings(
        {
            "llm_provider": "gemini",
            "llm_models": {"gemini": "gemini-test"},
            "llm_api_keys": {},
            "llm_model_params": {},
        }
    )

    config = resolve_llm_bootstrap_config(settings, api_key_file=api_key_file)

    assert config.api_key == "legacy-key"
    assert config.provider == "gemini"
    assert config.model_name == "gemini-test"


def test_resolve_llm_bootstrap_config_uses_custom_api_password_fallback(tmp_path):
    settings = _Settings(
        {
            "llm_provider": "custom_api",
            "llm_models": {"custom_api": "custom-model"},
            "llm_api_keys": {},
            "custom_api_key_or_password": "custom-secret",
            "llm_model_params": {},
        }
    )

    config = resolve_llm_bootstrap_config(settings, api_key_file=tmp_path / "api_key.txt")

    assert config.api_key == "custom-secret"


def test_resolve_llm_bootstrap_config_prefers_custom_api_dedicated_credentials(tmp_path):
    settings = _Settings(
        {
            "llm_provider": "custom_api",
            "llm_models": {"custom_api": "hidden-model"},
            "llm_api_keys": {"custom_api": "hidden-key"},
            "custom_api_key_or_password": "custom-secret",
            "custom_api_request_model": "custom-model",
            "llm_model_params": {},
        }
    )

    config = resolve_llm_bootstrap_config(settings, api_key_file=tmp_path / "api_key.txt")

    assert config.api_key == "custom-secret"
    assert config.model_name == "custom-model"


def test_create_llm_runtime_client_forwards_runtime_dependencies(monkeypatch):
    captured = {}

    def fake_create_llm_client(config, **kwargs):
        captured["config"] = config
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("src.core.app_llm_bootstrap.create_llm_client", fake_create_llm_client)
    config = LLMProviderConfig(provider="openai", api_key="k", model_name="m")
    dependencies = LLMRuntimeDependencies(
        memory_manager="memory",
        knowledge_map_manager="knowledge",
        user_profile="user",
        ene_profile="ene",
        settings="settings",
        calendar_manager="calendar",
        mood_manager="mood",
        goal_manager="goal",
    )

    client = create_llm_runtime_client(config, dependencies)

    assert client is not None
    assert captured["config"] is config
    assert captured["kwargs"] == {
        "memory_manager": "memory",
        "knowledge_map_manager": "knowledge",
        "user_profile": "user",
        "ene_profile": "ene",
        "settings": "settings",
        "calendar_manager": "calendar",
        "mood_manager": "mood",
        "goal_manager": "goal",
    }
