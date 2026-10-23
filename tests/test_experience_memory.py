"""경험 근거의 출처·이력·일반 문맥 계약."""
import asyncio
from types import SimpleNamespace

from src.ai.knowledge_map import KnowledgeMapManager
from src.ai.knowledge_map_types import TopicMemoryTopic, TopicMemoryClue, TopicMemoryHistoryItem, TopicMemorySearchResult
from src.ai.memory_types import MemoryEntry


def memory(identity="past", messages=None):
    return MemoryEntry(identity, "가상 조립 작업", messages if messages is not None else [
        {"role": "user", "text": "나무 모빌의 균형이 맞지 않아.", "turn_index": 0},
        {"role": "assistant", "text": "양쪽 무게를 맞춰보자.", "turn_index": 1},
        {"role": "user", "text": "맞추니 수평이 됐어.", "turn_index": 2},
    ], "2025-01-02", entity_names=["나무 모빌"], conversation_id="synthetic-session")


def topic_result():
    clue = TopicMemoryClue("clue", "나무 모빌", "status_flow", "active", "새 모빌 제작 중", source_memory_id="new",
        history=[TopicMemoryHistoryItem("completed", "예전 모빌의 균형을 맞췄다", timestamp="2025-03-01", source_memory_id="past", effective_at="2025-01-02")])
    return TopicMemorySearchResult(TopicMemoryTopic("topic", "나무 모빌", [clue]), clue, .8)


def test_topic_formatter_reuses_results_without_searching(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "topics.json")
    assert hasattr(manager, "format_context_block"), "구조화 검색 결과를 다시 사용해야 한다"
    block = manager.format_context_block([topic_result()])
    assert "새 모빌 제작 중" in block and "예전 모빌" not in block
    async def search(*args, **kwargs):
        return [topic_result()]
    manager.async_search = search
    assert asyncio.run(manager.async_build_context_block("모빌")) == block


def test_history_sources_are_grounded_and_keep_event_time():
    from src.ai.experience_memory import collect_history_evidence
    result = topic_result()
    result.clue.history.insert(0, TopicMemoryHistoryItem("active", "누락 원문", source_memory_id="missing"))
    # 최근 순서만 자르면 마지막의 관련 이력을 놓치게 된다.
    result.clue.history = [TopicMemoryHistoryItem("active", "다른 변경", source_memory_id="missing") for _ in range(30)] + result.clue.history
    evidence = collect_history_evidence([result], [memory()])
    assert len(evidence) == 1
    assert evidence[0].event_at == "2025-01-02"
    assert evidence[0].refs[0].memory_id == "past"
    assert evidence[0].historical_state == "예전 모빌의 균형을 맞췄다"


def test_history_does_not_invent_raw_messages_or_event_dates():
    from src.ai.experience_memory import collect_history_evidence
    result = topic_result()
    result.clue.history[0].effective_at = ""
    evidence = collect_history_evidence([result], [memory(messages=[])])[0]
    assert evidence.event_at is None
    assert evidence.messages == ()
    assert evidence.source_quality == "history_only"


def test_revision_detects_edits_and_deletions_but_not_usage():
    from src.ai.experience_memory import collect_history_evidence, evidence_is_current
    item = memory()
    result = topic_result()
    evidence = collect_history_evidence([result], [item])[0]
    item.retrieval_count += 1
    assert evidence_is_current(evidence, [item], [result])
    assert not evidence_is_current(evidence, [], [result])
    result.clue.history[0].text = "정정된 과거 기록"
    assert not evidence_is_current(evidence, [item], [result])
    evidence = collect_history_evidence([result], [item])[0]
    item.original_messages[0].text = "수정한 원문"
    assert not evidence_is_current(evidence, [item], [result])
