import asyncio

from src.ai.embedding import EmbeddingGenerator
from src.ai.memory import MemoryManager
from src.ai.memory_types import create_memory_entry


class FakeEmbeddingGenerator:
    async def embed(self, text: str):
        if "python" in text.lower():
            return [1.0, 0.0]
        return [0.0, 1.0]

    @staticmethod
    def cosine_similarity(vec1, vec2):
        return EmbeddingGenerator.cosine_similarity(vec1, vec2)


def test_load_missing_file_starts_empty(tmp_path):
    memory_file = tmp_path / "memory.json"
    manager = MemoryManager(str(memory_file))
    assert manager.memories == []


def test_save_and_reload_roundtrip(tmp_path):
    memory_file = tmp_path / "memory.json"
    manager = MemoryManager(str(memory_file))
    manager.memories.append(
        create_memory_entry(
            summary="테스트 요약",
            original_messages=["안녕", "반가워"],
            is_important=True,
            embedding=[0.1, 0.2, 0.3],
            tags=["test"],
        )
    )
    manager.save()

    reloaded = MemoryManager(str(memory_file))
    assert len(reloaded.memories) == 1
    assert reloaded.memories[0].summary == "테스트 요약"
    assert reloaded.memories[0].is_important is True


def test_get_recent_returns_descending_by_timestamp(tmp_path):
    manager = MemoryManager(str(tmp_path / "memory.json"))
    old_entry = create_memory_entry("오래된 기억", ["a"])
    new_entry = create_memory_entry("최신 기억", ["b"])
    old_entry.timestamp = "2026-01-01T10:00:00"
    new_entry.timestamp = "2026-01-02T10:00:00"
    manager.memories = [old_entry, new_entry]

    recent = manager.get_recent(count=2)
    assert [m.summary for m in recent] == ["최신 기억", "오래된 기억"]


def test_get_important_filters_only_important(tmp_path):
    manager = MemoryManager(str(tmp_path / "memory.json"))
    manager.memories = [
        create_memory_entry("중요", ["a"], is_important=True),
        create_memory_entry("일반", ["b"], is_important=False),
    ]
    important = manager.get_important()
    assert len(important) == 1
    assert important[0].summary == "중요"


def test_find_similar_returns_ranked_results(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=FakeEmbeddingGenerator(),
    )

    memory_python = create_memory_entry("파이썬 얘기", ["python"], embedding=[1.0, 0.0])
    memory_food = create_memory_entry("음식 얘기", ["food"], embedding=[0.0, 1.0])
    manager.memories = [memory_food, memory_python]

    results = asyncio.run(
        manager.find_similar("python 질문", top_k=2, min_similarity=0.1)
    )

    assert len(results) == 1
    assert results[0][0].summary == "파이썬 얘기"
    assert results[0][1] == 1.0
