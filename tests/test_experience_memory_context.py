"""기존 원문 예산과 현재 상태를 지키는 경험 전달."""
import asyncio
from types import SimpleNamespace

from src.ai.memory import MemoryManager
from src.ai.memory_context_builder import build_memory_context
from src.ai.memory_types import MemoryContextTrace
from tests.test_experience_memory import memory


def client_for(tmp_path, enabled=True, raw_limit=2):
    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [memory()]
    return SimpleNamespace(memory_manager=manager, _prompt_language=lambda: "ko", settings=SimpleNamespace(config={
        "experience_memory_enabled": enabled, "max_raw_chunks_in_context": raw_limit,
        "max_important_memories": 0, "max_recent_memories": 0,
    }))


def test_enabled_context_preserves_advice_reaction_once_with_sources(tmp_path):
    client = client_for(tmp_path)
    trace = MemoryContextTrace()
    context = asyncio.run(build_memory_context(client, "나무 모빌 균형을 맞추고 싶어", trace=trace, memory_request_id="req"))
    assert "[과거 대화 경험]" in context
    assert context.count("양쪽 무게를 맞춰보자.") == 1
    assert context.count("맞추니 수평이 됐어.") == 1
    assert trace.experience_refs[0]["memory_id"] == "past"
    assert trace.experience_chars <= 2800
    assert client.memory_manager.memories[0].retrieval_count == 1


def test_feature_disabled_has_no_experience_search_or_block(tmp_path):
    client = client_for(tmp_path, enabled=False)
    trace = MemoryContextTrace()
    context = asyncio.run(build_memory_context(client, "나무 모빌 균형", trace=trace))
    assert "[과거 대화 경험]" not in context
    assert "experience_memories" not in trace.candidates


def test_zero_raw_budget_does_not_inject_raw_experiences(tmp_path):
    client = client_for(tmp_path, raw_limit=0)
    context = asyncio.run(build_memory_context(client, "나무 모빌 균형"))
    assert "양쪽 무게를 맞춰보자." not in context
    assert "맞추니 수평이 됐어." not in context


def test_unresolved_recall_cannot_be_answered_by_experience_bypass(tmp_path):
    client = client_for(tmp_path)
    context = asyncio.run(build_memory_context(client, "그건 무슨 색이었지?", recent_memory_messages=[
        {"role": "assistant", "text": "나무 모빌 이야기였어", "turn_id": "a"}]))
    assert "MEMORY_REFERENCE_UNRESOLVED" in context
    assert "[과거 대화 경험]" not in context


def test_render_drops_changed_sources_and_rejects_overlong_claims(tmp_path):
    from src.ai.experience_memory import retrieve_experiences, render_experiences
    client = client_for(tmp_path)
    manager = client.memory_manager
    items = asyncio.run(retrieve_experiences(manager, "나무 모빌 균형", [], [], [(manager.memories[0], .8)]))
    manager.memories[0].original_messages[0].text = "전혀 다른 작업"
    block, selected = render_experiences(items, manager.memories, [])
    assert not block and not selected


def test_rendered_raw_blocks_share_one_budget(tmp_path):
    client = client_for(tmp_path, raw_limit=1)
    trace = MemoryContextTrace()
    asyncio.run(build_memory_context(client, "나무 모빌 균형", trace=trace))
    assert len(trace.raw_chunks) == 1
    assert len(trace.experience_refs) == 1
