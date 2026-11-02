"""합성 시간 근거의 전달 계약. 모델의 날짜 추론 정확도를 판정하지 않는다."""
import asyncio
import json

import pytest

from src.ai.experience_memory import retrieve_experiences, render_experiences
from src.ai.knowledge_map_types import TopicMemoryHistoryItem
from src.ai.memory_context_builder import build_memory_context
from tests.test_experience_memory import topic_result
from tests.test_experience_memory_context import client_for


def temporal_source(tmp_path, *, raw=True, event_at="2099-01-02"):
    client = client_for(tmp_path)
    source = client.memory_manager.memories[0]
    source.timestamp = "2099-01-10T10:00:00+09:00"
    source.original_messages = []
    if raw:
        from src.ai.memory_types import MemoryMessage
        source.original_messages = [MemoryMessage(
            conversation_id=source.conversation_id, role="user", text="나무 모빌 균형 작업은 당시 아직 미완료였어.",
            timestamp="2099-01-09T09:00:00+09:00", turn_index=0,
        )]
    result = topic_result()
    result.clue.text = "나무 모빌 균형 작업은 현재 완성됐어."
    result.clue.state = "completed"
    result.clue.effective_at = "2099-01-12"
    result.clue.history = [TopicMemoryHistoryItem(
        "active", "나무 모빌 균형 작업은 당시 아직 미완료였어.",
        timestamp="2099-01-11T11:00:00+09:00",
        source_memory_id=source.id, effective_at=event_at,
    )]
    return client, source, result


def payloads(block):
    return [json.loads(line) for line in block.splitlines() if line.startswith('{"source":')]


@pytest.mark.parametrize("raw", [True, False], ids=["raw", "history-only"])
@pytest.mark.parametrize("event_at", ["2099-01-02", ""], ids=["dated", "unknown-event"])
def test_retrieval_and_json_keep_distinct_temporal_provenance(tmp_path, raw, event_at):
    client, source, result = temporal_source(tmp_path, raw=raw, event_at=event_at)
    items = asyncio.run(retrieve_experiences(
        client.memory_manager, "나무 모빌 균형 작업", [], [result], [(source, .8)],
    ))
    assert len(items) == 1
    item = items[0]
    # 이력 갱신 시각이나 최신 상태의 effective_at으로 대체하면 안 된다.
    recorded_at = source.original_messages[0].timestamp if raw else source.timestamp
    assert (item.event_at, item.recorded_at) == (event_at or None, recorded_at)
    assert item.historical_state == result.clue.history[0].text
    block, selected = render_experiences(items, [source], [result])
    assert selected == items
    payload, = payloads(block)
    assert payload["event_at"] == (event_at or None)
    assert payload["recorded_at"] == recorded_at
    assert payload["historical_state"] == "나무 모빌 균형 작업은 당시 아직 미완료였어."
    assert payload["source_quality"] == ("raw" if raw else "history_only")
    assert payload["messages"] == ([{
        "role": "user", "text": source.original_messages[0].text,
        "recorded_at": source.original_messages[0].timestamp,
    }] if raw else [])
    assert result.clue.text not in block


def test_context_keeps_current_completion_separate_from_historical_incompletion(tmp_path):
    client, source, result = temporal_source(tmp_path)
    async def search(*args, **kwargs):
        return [result]
    from types import SimpleNamespace
    from src.ai.knowledge_map import KnowledgeMapManager
    client.knowledge_map_manager = SimpleNamespace(
        async_search=search, topics=[result.topic],
        format_context_block=KnowledgeMapManager.format_context_block,
    )
    context = asyncio.run(build_memory_context(client, "나무 모빌 균형 작업"))
    payload, = payloads(context)
    assert payload["event_at"] == "2099-01-02"
    assert payload["recorded_at"] == source.original_messages[0].timestamp
    assert payload["historical_state"] == result.clue.history[0].text
    topic_block = context.split("[주제 기억]", 1)[1].split("[과거 대화 경험]", 1)[0]
    assert "state: completed" in topic_block
    assert "effective_at: 2099-01-12" in topic_block
    assert result.clue.text in topic_block
    assert result.clue.history[0].text not in topic_block
    assert "사용자의 현재 명시적 정정과 검증된 최신 프로필·주제 상태를 우선한다." in context
    assert "현재 발화와 최신 정정을 우선한다." in context
