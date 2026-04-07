import asyncio
import json

from src.ai.embedding import EmbeddingGenerator
from src.ai.memory import MemoryManager
from src.ai.memory_types import MemoryEntry, create_memory_entry


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


def test_save_and_reload_roundtrip_preserves_extended_memory_fields(tmp_path):
    memory_file = tmp_path / "memory.json"
    manager = MemoryManager(str(memory_file))
    manager.memories.append(
        MemoryEntry(
            id="mem-extended",
            summary="확장 메모리",
            original_messages=["안녕"],
            timestamp="2026-04-08T00:00:00",
            is_important=True,
            embedding=[0.1, 0.2],
            tags=["test"],
            source="note",
            memory_type="task",
            importance_reason="user_marked",
            retrieval_count=3,
            last_used_at="2026-04-08T01:00:00",
            confidence=0.8,
            user_confirmed=True,
            entity_names=["ENE"],
            conversation_id="conv-1",
            expires_at="2026-04-09T00:00:00",
            schema_version=2,
            migration_meta={},
        )
    )
    manager.save()

    reloaded = MemoryManager(str(memory_file))
    restored = reloaded.memories[0]
    assert restored.source == "note"
    assert restored.memory_type == "task"
    assert restored.importance_reason == "user_marked"
    assert restored.retrieval_count == 3
    assert restored.last_used_at == "2026-04-08T01:00:00"
    assert restored.confidence == 0.8
    assert restored.user_confirmed is True
    assert restored.entity_names == ["ENE"]
    assert restored.conversation_id == "conv-1"
    assert restored.expires_at == "2026-04-09T00:00:00"
    assert restored.schema_version == 2


def test_load_legacy_memory_file_backfills_extended_fields(tmp_path):
    memory_file = tmp_path / "memory.json"
    memory_file.write_text(
        json.dumps(
            {
                "memories": [
                    {
                        "id": "mem-legacy",
                        "summary": "사용자는 내일 저녁에 병원 예약이 있다고 말함",
                        "original_messages": [
                            "내일 저녁에 병원 예약 있어.",
                            "까먹지 않게 나중에 한 번 말해줘.",
                        ],
                        "timestamp": "2026-04-02T22:10:00",
                        "is_important": True,
                        "embedding": [0.9, 0.1],
                        "tags": ["hospital", "tomorrow"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    manager = MemoryManager(str(memory_file))

    restored = manager.memories[0]
    assert restored.source == "legacy"
    assert restored.memory_type == "promise"
    assert restored.importance_reason == "promise"
    assert restored.retrieval_count == 0
    assert restored.user_confirmed is None
    assert restored.schema_version == 2


def test_load_legacy_memory_file_persists_migrated_schema(tmp_path):
    memory_file = tmp_path / "memory.json"
    memory_file.write_text(
        json.dumps(
            {
                "memories": [
                    {
                        "id": "mem-legacy",
                        "summary": "사용자는 Obsidian으로 일기를 정리하는 걸 좋아함",
                        "original_messages": ["옵시디언이 제일 편해."],
                        "timestamp": "2026-04-02T22:10:00",
                        "is_important": True,
                        "tags": ["obsidian"],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    MemoryManager(str(memory_file))

    migrated_payload = json.loads(memory_file.read_text(encoding="utf-8"))
    restored = migrated_payload["memories"][0]
    assert restored["schema_version"] == 2
    assert restored["source"] == "legacy"
    assert restored["memory_type"] == "preference"


def test_add_summary_persists_memory_metadata_fields(tmp_path):
    manager = MemoryManager(str(tmp_path / "memory.json"))

    created = asyncio.run(
        manager.add_summary(
            summary="메모리 메타 테스트",
            original_messages=["사용자가 ENE 구조를 정리하고 싶다고 말했다."],
            source="chat",
            memory_type="task",
            importance_reason="repeated_topic",
            confidence=0.85,
            entity_names=["ENE"],
        )
    )

    assert created.source == "chat"
    assert created.memory_type == "task"
    assert created.importance_reason == "repeated_topic"
    assert created.confidence == 0.85
    assert created.entity_names == ["ENE"]
