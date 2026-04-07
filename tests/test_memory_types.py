from src.ai.memory_types import MemoryEntry, create_memory_entry


def test_create_memory_entry_sets_defaults():
    entry = create_memory_entry("요약", ["원문1", "원문2"])
    assert entry.summary == "요약"
    assert entry.original_messages == ["원문1", "원문2"]
    assert entry.is_important is False
    assert entry.embedding is None
    assert entry.tags == []
    assert isinstance(entry.id, str)
    assert isinstance(entry.timestamp, str)


def test_memory_entry_roundtrip_dict():
    original = MemoryEntry(
        id="mem-1",
        summary="테스트",
        original_messages=["a", "b"],
        timestamp="2026-02-26T00:00:00",
        is_important=True,
        embedding=[0.1, 0.2],
        tags=["x"],
    )
    restored = MemoryEntry.from_dict(original.to_dict())
    assert restored == original


def test_memory_entry_from_legacy_dict_backfills_new_fields():
    legacy = {
        "id": "mem-legacy",
        "summary": "사용자는 Obsidian으로 일기를 정리하는 걸 좋아함",
        "original_messages": [
            "나는 일기 같은 건 옵시디언에 정리하는 게 제일 편해.",
            "그쪽이 더 익숙하고 나중에 찾기도 쉬워.",
        ],
        "timestamp": "2026-03-10T20:30:00",
        "is_important": True,
        "embedding": [0.1, 0.2],
        "tags": ["obsidian", "diary"],
    }

    restored = MemoryEntry.from_dict(legacy)

    assert restored.source == "legacy"
    assert restored.memory_type == "preference"
    assert restored.importance_reason == "legacy_important"
    assert restored.retrieval_count == 0
    assert restored.last_used_at is None
    assert restored.confidence == 0.6
    assert restored.user_confirmed is None
    assert restored.entity_names == ["Obsidian"]
    assert restored.conversation_id is None
    assert restored.expires_at is None
    assert restored.schema_version == 2
    assert restored.migration_meta["migration_version"] == 1
    assert "memory_type" in restored.migration_meta["inferred_fields"]
