"""실제로 입력에 포함된 요약·원문의 기억 ID 합집합만 기록한다."""

import asyncio
from types import SimpleNamespace

from src.ai.memory import MemoryManager
from src.ai.memory_types import MemoryEntry, MemoryContextTrace
from src.ai.memory_context_builder import build_memory_context


def client_for(tmp_path):
    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [MemoryEntry("paper", "종이 돛 제작", [
        {"role": "user", "text": "종이 돛 길이는 34센티미터다.", "timestamp": "2025-01-01"}
    ], "2025-01-01", entity_names=["종이 돛"])]
    return SimpleNamespace(memory_manager=manager, _prompt_language=lambda: "ko",
                           settings=SimpleNamespace(config={"max_recent_memories": 0, "max_important_memories": 0}))


def test_summary_and_raw_are_counted_once_across_automatic_retry(tmp_path):
    client = client_for(tmp_path)
    trace = MemoryContextTrace()
    for _ in range(2):
        asyncio.run(build_memory_context(client, "종이 돛 길이", trace=trace, memory_request_id="same-request"))
    memory = client.memory_manager.memories[0]
    assert memory.retrieval_count == 1
    assert trace.raw_chunks
    assert memory.last_activated_at
    asyncio.run(build_memory_context(client, "종이 돛 길이", memory_request_id="reroll"))
    assert memory.retrieval_count == 2


def test_raw_only_recall_counts_usage_without_activation(tmp_path):
    client = client_for(tmp_path)
    client.memory_manager.memories[0].entity_names = []
    asyncio.run(build_memory_context(client, "34센티미터 종이 돛", memory_request_id="raw-request"))
    memory = client.memory_manager.memories[0]
    assert memory.retrieval_count == 1
    assert memory.last_activated_at is None


def test_important_only_context_does_not_count_retrieval(tmp_path):
    client = client_for(tmp_path)
    client.settings.config.update(max_important_memories=1, max_raw_chunks_in_context=0)
    memory = client.memory_manager.memories[0]
    memory.is_important = True
    asyncio.run(build_memory_context(client, "금속 구름 색깔", memory_request_id="unrelated"))
    assert memory.retrieval_count == 0


def test_usage_save_failure_is_visible_without_failing_answer_context(tmp_path, monkeypatch):
    client = client_for(tmp_path)
    monkeypatch.setattr(client.memory_manager, "save", lambda: False)
    trace = MemoryContextTrace()
    context = asyncio.run(build_memory_context(client, "종이 돛 길이", trace=trace))
    assert "34센티미터" in context
    assert trace.usage_recorded is False
    assert client.memory_manager.memories[0].retrieval_count == 0
