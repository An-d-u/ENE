"""
앱 시작 시 LLM 클라이언트 설정을 해석하고 생성하는 유틸리티.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..ai.llm_provider import LLMProviderConfig, create_llm_client
from ..ai.openai_model_policy import normalize_reasoning_effort, resolve_openai_model_policy


@dataclass
class LLMRuntimeDependencies:
    """LLM 클라이언트에 연결할 런타임 의존성 묶음."""

    memory_manager: Any = None
    knowledge_map_manager: Any = None
    user_profile: Any = None
    ene_profile: Any = None
    settings: Any = None
    calendar_manager: Any = None
    mood_manager: Any = None
    goal_manager: Any = None


def _resolve_generation_params(settings, provider: str, model_name: str) -> dict:
    defaults = {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048}
    resolved = dict(defaults)
    raw = settings.get("llm_model_params", {}) if settings else {}
    candidate = None
    if isinstance(raw, dict):
        provider_map = raw.get(provider, {})
        if isinstance(provider_map, dict):
            model_key = str(model_name or "").strip()
            candidate = provider_map.get(model_key) if model_key else None
            if not isinstance(candidate, dict):
                candidate = provider_map.get("__default__")

    if isinstance(candidate, dict):
        try:
            resolved["temperature"] = max(
                0.0,
                min(2.0, float(candidate.get("temperature", defaults["temperature"]))),
            )
        except (TypeError, ValueError):
            pass
        try:
            resolved["top_p"] = max(0.0, min(1.0, float(candidate.get("top_p", defaults["top_p"]))))
        except (TypeError, ValueError):
            pass
        try:
            resolved["max_tokens"] = max(0, int(candidate.get("max_tokens", defaults["max_tokens"])))
        except (TypeError, ValueError):
            pass

    policy = resolve_openai_model_policy(provider, model_name)
    if policy.supports_reasoning_effort:
        value = candidate.get("reasoning_effort") if isinstance(candidate, dict) else None
        resolved["reasoning_effort"] = normalize_reasoning_effort(
            value,
            default=policy.default_reasoning_effort,
        )

    return resolved


def resolve_llm_bootstrap_config(
    settings,
    *,
    api_key_file: str | Path = "api_key.txt",
) -> LLMProviderConfig:
    """설정 객체에서 LLMProviderConfig를 만든다."""
    llm_provider = str(settings.get("llm_provider", "gemini")).strip().lower()
    llm_models = settings.get("llm_models", {})
    if not isinstance(llm_models, dict):
        llm_models = {}
    llm_model = str(llm_models.get(llm_provider, "")).strip()
    if not llm_model:
        llm_model = str(settings.get("llm_model", "")).strip()
    if llm_provider == "custom_api":
        llm_model = str(settings.get("custom_api_request_model", "")).strip() or llm_model

    llm_api_keys = settings.get("llm_api_keys", {})
    if not isinstance(llm_api_keys, dict):
        llm_api_keys = {}

    if llm_provider == "custom_api":
        api_key = str(settings.get("custom_api_key_or_password", "")).strip()
        if not api_key:
            api_key = str(llm_api_keys.get(llm_provider, "")).strip()
    else:
        api_key = str(llm_api_keys.get(llm_provider, "")).strip()

    if not api_key and llm_provider == "gemini":
        legacy_key_file = Path(api_key_file)
        if legacy_key_file.exists():
            api_key = legacy_key_file.read_text(encoding="utf-8-sig").strip()

    return LLMProviderConfig(
        provider=llm_provider,
        api_key=api_key,
        model_name=llm_model,
        generation_params=_resolve_generation_params(settings, llm_provider, llm_model),
    )


def create_llm_runtime_client(
    config: LLMProviderConfig,
    dependencies: LLMRuntimeDependencies,
):
    """해석된 설정과 런타임 의존성으로 실제 LLM 클라이언트를 만든다."""
    return create_llm_client(
        config,
        memory_manager=dependencies.memory_manager,
        knowledge_map_manager=dependencies.knowledge_map_manager,
        user_profile=dependencies.user_profile,
        ene_profile=dependencies.ene_profile,
        settings=dependencies.settings,
        calendar_manager=dependencies.calendar_manager,
        mood_manager=dependencies.mood_manager,
        goal_manager=dependencies.goal_manager,
    )
