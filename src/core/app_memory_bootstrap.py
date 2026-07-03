"""
앱 시작 시 메모리, 지식 맵, 프로필 계열 런타임을 생성하는 유틸리티.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable
import traceback


@dataclass
class MemoryProfileRuntime:
    """메모리와 프로필 계열 런타임 객체 묶음."""

    memory_manager: Any = None
    user_profile: Any = None
    ene_profile: Any = None


@dataclass
class MemoryKnowledgeRuntime:
    """메모리와 주제 지식 맵 런타임 객체 묶음."""

    memory_manager: Any = None
    knowledge_map_manager: Any = None
    embedding_generator: Any = None


def _build_embedding_generator(
    settings,
    *,
    embedding_factory: Callable[..., Any] | None = None,
):
    """설정에서 embedding 생성기를 만든다. API 키가 없으면 None을 반환한다."""
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

    if embedding_provider not in supported_providers:
        print(f"WARNING: 지원하지 않는 임베딩 공급자입니다: {embedding_provider}")
        return None
    if not embedding_api_key and embedding_provider != "openai_compatible":
        print("WARNING: 임베딩 API 키가 없습니다.")
        print("기억 검색 기능은 제한적으로 동작합니다. (임베딩 없음).")
        return None
    if embedding_api_key == "your-voyage-api-key-here":
        print("WARNING: Voyage AI API 키를 설정해주세요.")
        return None

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
    return embedding_gen


def _build_memory_manager_with_embedding(
    *,
    embedding_generator,
    memory_manager_factory: Callable[..., Any] | None = None,
):
    if memory_manager_factory is None:
        from src.ai.memory import MemoryManager

        memory_manager_factory = MemoryManager

    memory_manager = memory_manager_factory(
        memory_file="memory.json",
        embedding_generator=embedding_generator,
    )
    print("OK: 메모리 매니저 초기화 성공")
    return memory_manager


def build_memory_manager(
    settings,
    *,
    embedding_factory: Callable[..., Any] | None = None,
    memory_manager_factory: Callable[..., Any] | None = None,
):
    """설정에서 기존 호환 API인 메모리 매니저 하나만 생성한다."""
    embedding_gen = _build_embedding_generator(
        settings,
        embedding_factory=embedding_factory,
    )
    return _build_memory_manager_with_embedding(
        embedding_generator=embedding_gen,
        memory_manager_factory=memory_manager_factory,
    )


def build_memory_knowledge_runtime(
    settings,
    *,
    embedding_factory: Callable[..., Any] | None = None,
    memory_manager_factory: Callable[..., Any] | None = None,
    knowledge_map_manager_factory: Callable[..., Any] | None = None,
) -> MemoryKnowledgeRuntime:
    """메모리 매니저와 지식 맵 매니저를 같은 embedding 생성기로 초기화한다."""
    embedding_gen = _build_embedding_generator(
        settings,
        embedding_factory=embedding_factory,
    )
    memory_manager = _build_memory_manager_with_embedding(
        embedding_generator=embedding_gen,
        memory_manager_factory=memory_manager_factory,
    )

    knowledge_map_manager = None
    try:
        if knowledge_map_manager_factory is None:
            from src.ai.knowledge_map import KnowledgeMapManager

            knowledge_map_manager_factory = KnowledgeMapManager
        knowledge_map_manager = knowledge_map_manager_factory(
            knowledge_file="knowledge_map.json",
            embedding_generator=embedding_gen,
        )
        loader = getattr(knowledge_map_manager, "load", None)
        if callable(loader):
            loaded_manager = loader()
            if loaded_manager is not None:
                knowledge_map_manager = loaded_manager
        print("OK: 주제 지식 맵 매니저 초기화 성공")
    except Exception as e:
        print(f"ERROR: 주제 지식 맵 매니저 초기화 실패: {e}")
        traceback.print_exc()
        knowledge_map_manager = None

    return MemoryKnowledgeRuntime(
        memory_manager=memory_manager,
        knowledge_map_manager=knowledge_map_manager,
        embedding_generator=embedding_gen,
    )


def build_profile_runtime(
    *,
    user_profile_factory: Callable[..., Any] | None = None,
    ene_profile_factory: Callable[..., Any] | None = None,
) -> MemoryProfileRuntime:
    """사용자 프로필을 먼저 만들고 그 다음 에네 프로필을 연결해 만든다."""
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
