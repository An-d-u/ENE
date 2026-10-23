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


def test_query_uses_only_recent_user_evidence_and_bounds_search_text():
    from src.ai.experience_memory import build_experience_query
    frame = build_experience_query("균형을 다시 잡으려 해", [
        {"role": "user", "text": "나무 모빌을 만들고 있어", "turn_id": "u"},
        {"role": "assistant", "text": "금속 돛 얘기도 해보자", "turn_id": "a"},
    ])
    assert "나무 모빌" in frame.expanded_query and "금속 돛" not in frame.expanded_query
    assert frame.evidence_turn_ids == ("u",)
    bounded = build_experience_query("가" * 2000, [{"role": "user", "text": "나" * 2000, "turn_id": "u"}])
    assert len(bounded.expanded_query) <= 1840


def test_explicit_topic_switch_clears_earlier_search_context():
    from src.ai.experience_memory import build_experience_query
    frame = build_experience_query("다른 이야기로 넘어가자. 구름은 왜 생겨?", [
        {"role": "user", "text": "나무 모빌 균형", "turn_id": "u"}])
    assert "모빌" not in frame.expanded_query
    assert not frame.evidence_turn_ids


def test_request_cache_is_request_scoped_and_separates_provider_and_model():
    from src.ai.memory import RequestEmbeddingCache
    class Generator:
        provider = "synthetic"
        model = "one"
        calls = 0
        async def embed(self, text):
            self.calls += 1
            return [float(self.calls)]
    async def run():
        generator = Generator()
        cache = RequestEmbeddingCache()
        assert await cache.embed(generator, "입력") == await cache.embed(generator, "입력")
        assert generator.calls == 1
        generator.model = "two"
        assert await cache.embed(generator, "입력") == [2.0]
        assert await RequestEmbeddingCache().embed(generator, "입력") == [3.0]
    asyncio.run(run())


def test_retrieval_preserves_user_advice_and_reaction_without_recall_cue(tmp_path):
    from src.ai.experience_memory import retrieve_experiences
    from src.ai.memory import MemoryManager
    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [memory()]
    result = asyncio.run(retrieve_experiences(manager, "나무 모빌의 균형을 맞추고 싶어", [], [], [(manager.memories[0], .8)]))
    assert len(result) == 1
    assert [m.role for m in result[0].messages] == ["user", "assistant", "user"]
    assert result[0].refs[0].turn_indexes == (0, 1, 2)


def test_assistant_only_match_does_not_become_user_experience(tmp_path):
    from src.ai.experience_memory import retrieve_experiences
    from src.ai.memory import MemoryManager
    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [memory(messages=[{"role": "user", "text": "안녕"},
                                       {"role": "assistant", "text": "나무 모빌의 균형을 맞췄었지"}])]
    assert not asyncio.run(retrieve_experiences(manager, "나무 모빌 균형", [], [], [(manager.memories[0], 1.0)]))


def test_cancellation_does_not_publish_late_embeddings(tmp_path):
    from src.ai.experience_memory import retrieve_experiences
    from src.ai.memory import MemoryManager
    class Generator:
        provider = "synthetic"
        model = "slow"
        async def embed(self, text):
            await asyncio.sleep(30)
            return [1.0, 0.0]
    async def run():
        manager = MemoryManager(tmp_path / "memory.json", Generator())
        manager.memories = [memory()]
        task = asyncio.create_task(retrieve_experiences(manager, "나무 모빌 균형", [], [], [(manager.memories[0], .8)]))
        await asyncio.sleep(0)
        task.cancel()
        import pytest
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not manager._raw_chunk_embedding_cache
    asyncio.run(run())


def test_unrelated_short_question_does_not_inherit_previous_subject(tmp_path):
    from src.ai.experience_memory import retrieve_experiences
    from src.ai.memory import MemoryManager
    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [memory()]
    recent = [{"role": "user", "text": "나무 모빌 균형을 맞추고 있었어", "turn_id": "u"}]
    assert not asyncio.run(retrieve_experiences(manager, "구름은 왜 하얘?", recent, [], [(manager.memories[0], .8)]))


def test_experience_trace_has_source_ids_and_bounded_inputs(tmp_path):
    from src.ai.experience_memory import retrieve_experiences
    from src.ai.memory import MemoryManager
    from src.ai.memory_types import MemoryContextTrace
    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [memory()]
    trace = MemoryContextTrace()
    asyncio.run(retrieve_experiences(manager, "나무 모빌 균형", [], [], [(manager.memories[0], .8)], trace=trace))
    assert trace.candidates["experience_memories"] == ["past"]
    assert trace.calls["experience_chunk_inputs"] <= 6
    assert trace.timings["experience_ms"] >= 0


def test_extra_embedding_cap_counts_cache_misses_and_rejects_partial_batch(tmp_path):
    from src.ai.experience_memory import retrieve_experiences
    from src.ai.memory import MemoryManager, RequestEmbeddingCache
    from src.ai.memory_types import MemoryContextTrace
    from scripts.memory_quality_eval import SyntheticEmbedding
    class Generator(SyntheticEmbedding):
        batch_sizes = []
        partial = False
        async def embed_batch(self, texts):
            self.batch_sizes.append(len(texts))
            values = await super().embed_batch(texts)
            return values[:-1] if self.partial else values
    async def run():
        generator = Generator()
        manager = MemoryManager(tmp_path / "memory.json", generator)
        manager.memories = [memory(str(index)) for index in range(30)]
        cache = RequestEmbeddingCache()
        for round_index in range(2):
            trace = MemoryContextTrace()
            await retrieve_experiences(manager, "나무 모빌 균형", [], [], [], query_cache=cache, trace=trace)
            assert len(trace.candidates["experience_memories"]) == 24
            assert trace.calls["experience_chunk_inputs"] == (6 if round_index == 0 else 0)
        assert generator.batch_sizes == [6]
        manager._raw_chunk_embedding_cache.clear()
        generator.partial = True
        chunks = [manager.build_raw_chunks(item)[0] for item in manager.memories[:2]]
        await manager._ensure_chunk_embeddings(chunks)
        assert not manager._raw_chunk_embedding_cache
        assert all(not chunk.embedding for chunk in chunks)
    asyncio.run(run())


def test_topic_switch_keeps_later_relevant_exchange(tmp_path):
    from src.ai.experience_memory import retrieve_experiences
    from src.ai.memory import MemoryManager
    manager = MemoryManager(tmp_path / "memory.json")
    item = memory(messages=[
        {"role": "user", "text": "구름을 그렸어.", "turn_index": 0},
        {"role": "assistant", "text": "둥글게 그렸구나.", "turn_index": 1},
        {"role": "user", "text": "다른 이야기로 넘어가자. 나무 모빌이 기울어.", "turn_index": 2},
        {"role": "assistant", "text": "양쪽 무게를 맞춰보자.", "turn_index": 3},
        {"role": "user", "text": "맞추니 수평이 됐어.", "turn_index": 4},
    ])
    manager.memories = [item]
    evidence = asyncio.run(retrieve_experiences(manager, "나무 모빌 균형", [], [], [(item, .8)]))
    assert evidence[0].refs[0].turn_indexes == (2, 3, 4)


def test_experience_never_evicts_existing_multi_source_answer_evidence(tmp_path):
    from src.ai.experience_memory import retrieve_experiences, allocate_raw_budget
    from src.ai.memory import MemoryManager
    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [memory(identity) for identity in ("a", "b", "c")]
    raw = [(manager.build_raw_chunks(item)[0], .99, {}) for item in manager.memories[:2]]
    manager.memories = manager.memories[2:]
    evidence = asyncio.run(retrieve_experiences(manager, "나무 모빌 균형", [], [], [(manager.memories[0], .8)]))
    assert evidence
    selected_raw, selected_experiences = allocate_raw_budget(raw, evidence, 2)
    assert [row[0].memory_id for row in selected_raw] == ["a", "b"]
    assert not selected_experiences


def test_embedding_wait_cannot_sign_old_messages_with_new_revision(tmp_path):
    from src.ai.experience_memory import retrieve_experiences, render_experiences
    from src.ai.memory import MemoryManager
    from scripts.memory_quality_eval import SyntheticEmbedding
    class Generator(SyntheticEmbedding):
        async def embed_batch(self, texts):
            manager.memories[0].original_messages = []
            return await super().embed_batch(texts)
    manager = MemoryManager(tmp_path / "memory.json", Generator())
    manager.memories = [memory()]
    evidence = asyncio.run(retrieve_experiences(manager, "나무 모빌 균형", [], [], []))
    block, selected = render_experiences(evidence, manager.memories, [])
    assert not block and not selected
