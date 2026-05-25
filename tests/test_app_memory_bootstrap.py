from src.core.app_memory_bootstrap import (
    MemoryProfileRuntime,
    build_memory_manager,
    build_profile_runtime,
)


class _Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


def test_build_memory_manager_uses_voyage_embedding_when_key_exists():
    calls = {}

    def embedding_factory(*, api_key, model):
        calls["embedding"] = {"api_key": api_key, "model": model}
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
    assert calls["embedding"] == {"api_key": "voyage-key", "model": "voyage-large-2"}
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
