from src.core.app_memory_bootstrap import (
    MemoryKnowledgeRuntime,
    MemoryProfileRuntime,
    build_memory_knowledge_runtime,
    build_memory_manager,
    build_profile_runtime,
)

import builtins


class _Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_build_memory_manager_uses_voyage_embedding_when_key_exists():
    calls = {}

    def embedding_factory(*, provider, api_key, model, api_url):
        calls["embedding"] = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "api_url": api_url,
        }
        return "embedding"

    def memory_manager_factory(*, memory_file, embedding_generator):
        calls["memory"] = {
            "memory_file": memory_file,
            "embedding_generator": embedding_generator,
        }
        return "memory"

    settings = _Settings(
        {
            "embedding_provider": "voyage",
            "embedding_model": "voyage-large-2",
            "embedding_api_keys": {"voyage": "voyage-key"},
        }
    )

    manager = build_memory_manager(
        settings,
        embedding_factory=embedding_factory,
        memory_manager_factory=memory_manager_factory,
    )

    assert manager == "memory"
    assert calls["embedding"] == {
        "provider": "voyage",
        "api_key": "voyage-key",
        "model": "voyage-large-2",
        "api_url": "",
    }
    assert calls["memory"] == {
        "memory_file": "memory.json",
        "embedding_generator": "embedding",
    }


def test_build_memory_manager_keeps_memory_without_embedding_when_key_is_missing():
    calls = {}

    def embedding_factory(**_kwargs):
        raise AssertionError("API 키가 없으면 임베딩 생성기를 만들지 않아야 한다.")

    def memory_manager_factory(*, memory_file, embedding_generator):
        calls["memory"] = {
            "memory_file": memory_file,
            "embedding_generator": embedding_generator,
        }
        return "memory"

    settings = _Settings(
        {
            "embedding_provider": "voyage",
            "embedding_model": "voyage-3",
            "embedding_api_keys": {},
        }
    )

    manager = build_memory_manager(
        settings,
        embedding_factory=embedding_factory,
        memory_manager_factory=memory_manager_factory,
    )

    assert manager == "memory"
    assert calls["memory"]["embedding_generator"] is None


def test_build_memory_manager_uses_openai_embedding_when_key_exists():
    calls = {}

    def embedding_factory(*, provider, api_key, model, api_url):
        calls["embedding"] = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "api_url": api_url,
        }
        return "embedding"

    def memory_manager_factory(*, memory_file, embedding_generator):
        calls["memory"] = {
            "memory_file": memory_file,
            "embedding_generator": embedding_generator,
        }
        return "memory"

    manager = build_memory_manager(
        _Settings(
            {
                "embedding_provider": "openai",
                "embedding_model": "text-embedding-3-large",
                "embedding_api_keys": {"openai": "openai-key"},
            }
        ),
        embedding_factory=embedding_factory,
        memory_manager_factory=memory_manager_factory,
    )

    assert manager == "memory"
    assert calls["embedding"] == {
        "provider": "openai",
        "api_key": "openai-key",
        "model": "text-embedding-3-large",
        "api_url": "https://api.openai.com/v1",
    }


def test_build_memory_manager_uses_openai_compatible_embedding_url():
    calls = {}

    def embedding_factory(*, provider, api_key, model, api_url):
        calls["embedding"] = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "api_url": api_url,
        }
        return "embedding"

    manager = build_memory_manager(
        _Settings(
            {
                "embedding_provider": "openai_compatible",
                "embedding_model": "local-embedding",
                "embedding_api_keys": {"openai_compatible": "local-key"},
                "embedding_provider_configs": {
                    "openai_compatible": {"api_url": "http://127.0.0.1:8000/v1"}
                },
            }
        ),
        embedding_factory=embedding_factory,
        memory_manager_factory=lambda **kwargs: kwargs["embedding_generator"],
    )

    assert manager == "embedding"
    assert calls["embedding"] == {
        "provider": "openai_compatible",
        "api_key": "local-key",
        "model": "local-embedding",
        "api_url": "http://127.0.0.1:8000/v1",
    }


def test_build_memory_manager_allows_openai_compatible_without_key():
    calls = {}

    def embedding_factory(*, provider, api_key, model, api_url):
        calls["embedding"] = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "api_url": api_url,
        }
        return "embedding"

    manager = build_memory_manager(
        _Settings(
            {
                "embedding_provider": "openai_compatible",
                "embedding_model": "local-embedding",
                "embedding_api_keys": {},
                "embedding_provider_configs": {
                    "openai_compatible": {"api_url": "http://127.0.0.1:8000/v1"}
                },
            }
        ),
        embedding_factory=embedding_factory,
        memory_manager_factory=lambda **kwargs: kwargs["embedding_generator"],
    )

    assert manager == "embedding"
    assert calls["embedding"] == {
        "provider": "openai_compatible",
        "api_key": "",
        "model": "local-embedding",
        "api_url": "http://127.0.0.1:8000/v1",
    }


def test_build_memory_manager_uses_gemini_embedding_when_key_exists():
    calls = {}

    def embedding_factory(*, provider, api_key, model, api_url):
        calls["embedding"] = {
            "provider": provider,
            "api_key": api_key,
            "model": model,
            "api_url": api_url,
        }
        return "embedding"

    build_memory_manager(
        _Settings(
            {
                "embedding_provider": "gemini",
                "embedding_model": "gemini-embedding-2",
                "embedding_api_keys": {"gemini": "gemini-key"},
            }
        ),
        embedding_factory=embedding_factory,
        memory_manager_factory=lambda **kwargs: kwargs["embedding_generator"],
    )

    assert calls["embedding"] == {
        "provider": "gemini",
        "api_key": "gemini-key",
        "model": "gemini-embedding-2",
        "api_url": "",
    }


def test_build_memory_knowledge_runtime_shares_embedding_generator_and_loads_knowledge_map():
    calls = {}
    embedding = object()

    class FakeKnowledgeMap:
        def __init__(self, *, knowledge_file, embedding_generator):
            calls["knowledge"] = {
                "knowledge_file": knowledge_file,
                "embedding_generator": embedding_generator,
            }
            self.load_calls = 0

        def load(self):
            self.load_calls += 1
            return self

    def embedding_factory(**kwargs):
        calls["embedding"] = kwargs
        return embedding

    def memory_manager_factory(*, memory_file, embedding_generator):
        calls["memory"] = {
            "memory_file": memory_file,
            "embedding_generator": embedding_generator,
        }
        return "memory"

    settings = _Settings(
        {
            "embedding_provider": "voyage",
            "embedding_model": "voyage-3",
            "embedding_api_keys": {"voyage": "voyage-key"},
        }
    )

    runtime = build_memory_knowledge_runtime(
        settings,
        embedding_factory=embedding_factory,
        memory_manager_factory=memory_manager_factory,
        knowledge_map_manager_factory=FakeKnowledgeMap,
    )

    assert runtime == MemoryKnowledgeRuntime(
        memory_manager="memory",
        knowledge_map_manager=runtime.knowledge_map_manager,
        embedding_generator=embedding,
    )
    assert calls["memory"]["embedding_generator"] is embedding
    assert calls["knowledge"] == {
        "knowledge_file": "knowledge_map.json",
        "embedding_generator": embedding,
    }
    assert runtime.knowledge_map_manager.load_calls == 1


def test_build_memory_knowledge_runtime_keeps_knowledge_map_without_embedding_when_key_is_missing():
    calls = {}

    def embedding_factory(**_kwargs):
        raise AssertionError("API 키가 없으면 embedding 생성기를 만들면 안 된다.")

    def memory_manager_factory(*, memory_file, embedding_generator):
        calls["memory_embedding"] = embedding_generator
        return "memory"

    def knowledge_map_manager_factory(*, knowledge_file, embedding_generator):
        calls["knowledge_file"] = knowledge_file
        calls["knowledge_embedding"] = embedding_generator

        class FakeKnowledgeMap:
            def load(self):
                calls["loaded"] = True
                return self

        return FakeKnowledgeMap()

    runtime = build_memory_knowledge_runtime(
        _Settings({"embedding_provider": "voyage", "embedding_api_keys": {}}),
        embedding_factory=embedding_factory,
        memory_manager_factory=memory_manager_factory,
        knowledge_map_manager_factory=knowledge_map_manager_factory,
    )

    assert runtime.memory_manager == "memory"
    assert runtime.knowledge_map_manager is not None
    assert runtime.embedding_generator is None
    assert calls["memory_embedding"] is None
    assert calls["knowledge_embedding"] is None
    assert calls["loaded"] is True


def test_build_memory_knowledge_runtime_preserves_memory_when_knowledge_map_creation_fails():
    def knowledge_map_manager_factory(**_kwargs):
        raise RuntimeError("knowledge map failed")

    runtime = build_memory_knowledge_runtime(
        _Settings({"embedding_provider": "voyage", "embedding_api_keys": {}}),
        memory_manager_factory=lambda **_kwargs: "memory",
        knowledge_map_manager_factory=knowledge_map_manager_factory,
    )

    assert runtime.memory_manager == "memory"
    assert runtime.knowledge_map_manager is None


def test_build_memory_manager_does_not_import_embedding_when_key_is_missing(monkeypatch):
    real_import = builtins.__import__
    calls = {}

    def guarded_import(name, *args, **kwargs):
        if name == "src.ai.embedding":
            raise AssertionError("API 키가 없으면 임베딩 모듈도 import하지 않아야 한다.")
        return real_import(name, *args, **kwargs)

    def memory_manager_factory(*, memory_file, embedding_generator):
        calls["memory"] = {
            "memory_file": memory_file,
            "embedding_generator": embedding_generator,
        }
        return "memory"

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    manager = build_memory_manager(
        _Settings({"embedding_provider": "voyage", "embedding_api_keys": {}}),
        memory_manager_factory=memory_manager_factory,
    )

    assert manager == "memory"
    assert calls["memory"]["embedding_generator"] is None


def test_build_profile_runtime_creates_user_then_ene_profile():
    calls = []

    def user_profile_factory(*, profile_file):
        calls.append(("user", profile_file))
        return "user-profile"

    def ene_profile_factory(*, profile_file, user_profile):
        calls.append(("ene", profile_file, user_profile))
        return "ene-profile"

    runtime = build_profile_runtime(
        user_profile_factory=user_profile_factory,
        ene_profile_factory=ene_profile_factory,
    )

    assert runtime == MemoryProfileRuntime(
        memory_manager=None,
        user_profile="user-profile",
        ene_profile="ene-profile",
    )
    assert calls == [
        ("user", "user_profile.json"),
        ("ene", "ene_profile.json", "user-profile"),
    ]


def test_build_profile_runtime_preserves_user_profile_when_ene_profile_fails():
    def user_profile_factory(*, profile_file):
        return f"user:{profile_file}"

    def ene_profile_factory(**_kwargs):
        raise RuntimeError("ene profile failed")

    runtime = build_profile_runtime(
        user_profile_factory=user_profile_factory,
        ene_profile_factory=ene_profile_factory,
    )

    assert runtime == MemoryProfileRuntime(
        memory_manager=None,
        user_profile="user:user_profile.json",
        ene_profile=None,
    )


def test_build_profile_runtime_preserves_user_profile_when_ene_profile_import_fails(monkeypatch):
    from src.core import app_memory_bootstrap

    real_import_module = app_memory_bootstrap.import_module

    def guarded_import_module(name):
        if name == "src.ai.ene_profile":
            raise ImportError("ene profile import failed")
        return real_import_module(name)

    monkeypatch.setattr(app_memory_bootstrap, "import_module", guarded_import_module)

    runtime = build_profile_runtime(
        user_profile_factory=lambda *, profile_file: f"user:{profile_file}",
    )

    assert runtime == MemoryProfileRuntime(
        memory_manager=None,
        user_profile="user:user_profile.json",
        ene_profile=None,
    )
