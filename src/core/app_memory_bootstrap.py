"""
앱 시작 시 메모리와 프로필 런타임을 생성하는 유틸리티.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable
import traceback


@dataclass
class MemoryProfileRuntime:
    """메모리/프로필 계열 런타임 객체 묶음."""

    memory_manager: Any = None
    user_profile: Any = None
    ene_profile: Any = None


def build_memory_manager(
    settings,
    *,
    embedding_factory: Callable[..., Any] | None = None,
    memory_manager_factory: Callable[..., Any] | None = None,
):
    """설정에서 메모리 매니저와 선택적 임베딩 생성기를 만든다."""
    if memory_manager_factory is None:
        from src.ai.memory import MemoryManager

        memory_manager_factory = MemoryManager

    embedding_provider = str(settings.get("embedding_provider", "voyage")).strip().lower()
    default_models = {
        "voyage": "voyage-3",
        "openai": "text-embedding-3-small",
        "openai_compatible": "text-embedding-3-small",
        "gemini": "gemini-embedding-2",
    }
    default_api_urls = {
        "openai": "https://api.openai.com/v1",
        "openai_compatible": "http://127.0.0.1:8000/v1",
    }
    embedding_model = (
        str(settings.get("embedding_model", default_models.get(embedding_provider, "voyage-3"))).strip()
        or default_models.get(embedding_provider, "voyage-3")
    )
    embedding_api_keys = settings.get("embedding_api_keys", {})
    if not isinstance(embedding_api_keys, dict):
        embedding_api_keys = {}
    embedding_api_key = str(embedding_api_keys.get(embedding_provider, "")).strip()
    embedding_provider_configs = settings.get("embedding_provider_configs", {})
    if not isinstance(embedding_provider_configs, dict):
        embedding_provider_configs = {}
    provider_config = embedding_provider_configs.get(embedding_provider, {})
    if not isinstance(provider_config, dict):
        provider_config = {}
    embedding_api_url = str(provider_config.get("api_url", default_api_urls.get(embedding_provider, ""))).strip()
    supported_providers = {"voyage", "openai", "openai_compatible", "gemini"}

    embedding_gen = None
    if embedding_provider not in supported_providers:
        print(f"WARNING: 지원하지 않는 임베딩 공급자입니다: {embedding_provider}")
    elif not embedding_api_key and embedding_provider != "openai_compatible":
        print("WARNING: 임베딩 API 키가 없습니다.")
        print("장기기억 기능이 제한적으로 작동합니다 (임베딩 없음).")
    elif embedding_api_key == "your-voyage-api-key-here":
        print("WARNING: Voyage AI API 키를 설정해주세요.")
    else:
        if embedding_factory is None:
            from src.ai.embedding import create_embedding_generator

            embedding_factory = create_embedding_generator
        embedding_gen = embedding_factory(
            provider=embedding_provider,
            api_key=embedding_api_key,
            model=embedding_model,
            api_url=embedding_api_url,
        )
        print(f"OK: 임베딩 생성기 초기화 성공 ({embedding_provider}/{embedding_model})")

    memory_manager = memory_manager_factory(
        memory_file="memory.json",
        embedding_generator=embedding_gen,
    )
    print("OK: 메모리 매니저 초기화 성공")
    return memory_manager


def build_profile_runtime(
    *,
    user_profile_factory: Callable[..., Any] | None = None,
    ene_profile_factory: Callable[..., Any] | None = None,
) -> MemoryProfileRuntime:
    """사용자 프로필을 먼저 만들고, 그 다음 에네 프로필을 연결해 만든다."""
    try:
        if user_profile_factory is None:
            user_profile_factory = import_module("src.ai.user_profile").UserProfile
        user_profile = user_profile_factory(profile_file="user_profile.json")
        print("OK: 사용자 프로필 초기화 성공")
    except Exception as e:
        print(f"ERROR: 사용자 프로필 초기화 실패: {e}")
        traceback.print_exc()
        user_profile = None

    try:
        if ene_profile_factory is None:
            ene_profile_factory = import_module("src.ai.ene_profile").EneProfile
        ene_profile = ene_profile_factory(profile_file="ene_profile.json", user_profile=user_profile)
        print("OK: 에네 프로필 초기화 성공")
    except Exception as e:
        print(f"ERROR: 에네 프로필 초기화 실패: {e}")
        traceback.print_exc()
        ene_profile = None

    return MemoryProfileRuntime(
        memory_manager=None,
        user_profile=user_profile,
        ene_profile=ene_profile,
    )
