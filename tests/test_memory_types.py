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
