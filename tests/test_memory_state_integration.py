import asyncio
from types import SimpleNamespace

from src.ai.memory import MemoryManager
from src.ai.knowledge_map import KnowledgeMapManager
from src.ai.user_profile import UserProfile
from src.core.bridge import WebBridge


def test_auto_summary_waits_for_review_and_keeps_new_messages(tmp_path):
    messages = [("user", "모형 전시 계획은 취소했어.", "2026-02-01 10:00"), ("assistant", "취소를 확인했어.", "2026-02-01 10:01")]
    newer = ("user", "다음에는 색을 골라 보자.", "2026-02-01 10:02")
    rebuilt = []
    bridge = SimpleNamespace(
        conversation_buffer=list(messages),
        memory_manager=MemoryManager(tmp_path / "memories.json"),
        user_profile=UserProfile(tmp_path / "profile.json"), ene_profile=None,
        knowledge_map_manager=KnowledgeMapManager(tmp_path / "topics.json"),
        summary_notice=SimpleNamespace(emit=lambda *_args: None),
        summary_review_ready=SimpleNamespace(emit=lambda *_args: None),
    )
    bridge._create_memory_conversation_id = lambda _messages: "conv-auto-review"
    bridge._normalize_summary_result = lambda result: WebBridge._normalize_summary_result(bridge, result)
    bridge._build_summary_storage_payload = lambda batch: WebBridge._build_summary_storage_payload(bridge, batch)
    bridge._emit_summary_review = lambda: WebBridge._emit_summary_review(bridge)

    async def summarize(batch):
        bridge.conversation_buffer.append(newer)
        return ("모형 전시 취소", ["[goal] 모형 전시 계획을 취소했다."], [], {
            "profile_updates": [{"content": "모형 전시 계획을 취소했다.", "category": "goal", "subject": "모형 전시", "state": "cancelled", "assertion": "current", "evidence": messages[0][1]}],
        }, [{"keyword": "모형 전시", "subject": "전시 계획", "type": "status_flow", "state": "cancelled", "text": "모형 전시 계획 취소", "confidence": 0.9, "assertion": "current", "evidence": messages[0][1]}])

    bridge.llm_client = SimpleNamespace(summarize_conversation=summarize, clear_context=lambda: None, rebuild_context_from_conversation=lambda values: rebuilt.append(list(values)) or True)
    asyncio.run(WebBridge._auto_summarize(bridge))
    assert bridge.user_profile.facts == []
    assert bridge.knowledge_map_manager.topics == []
    assert bridge.conversation_buffer == messages + [newer]
    assert bridge._pending_summary_review["messages"] == messages
    assert bridge._pending_summary_review["origin"] == "auto"
    assert rebuilt == []


def test_auto_summary_does_not_race_manual_worker(tmp_path):
    calls = []
    async def summarize(messages):
        calls.append(messages)
        return ("가상 요약", [], [], {})
    bridge = SimpleNamespace(
        conversation_buffer=[("user", "가상 질문")],
        memory_manager=MemoryManager(tmp_path / "memories.json"),
        llm_client=SimpleNamespace(summarize_conversation=summarize),
        _summary_review_worker=SimpleNamespace(isRunning=lambda: True),
    )
    asyncio.run(WebBridge._auto_summarize(bridge))
    assert bridge.memory_manager.memories == []
    assert bridge.conversation_buffer
    assert calls == []


def test_auto_summary_cancel_rearms_after_one_full_threshold():
    started = []
    notices = []
    bridge = SimpleNamespace(
        conversation_buffer=[("user", "합성 1"), ("assistant", "합성 2")],
        memory_manager=object(),
        summarize_threshold=2,
        next_auto_summary_count=2,
        _summary_review_worker=None,
        _summary_in_progress=False,
        _pending_summary_review=None,
        summary_notice=SimpleNamespace(emit=lambda *args: notices.append(args)),
        summary_review_finished=SimpleNamespace(emit=lambda *_args: None),
    )
    bridge._start_summary_review_worker = lambda messages, **kwargs: started.append(
        (list(messages), kwargs)
    )

    WebBridge._check_auto_summarize(bridge)
    bridge._pending_summary_review = {
        "messages": list(bridge.conversation_buffer),
        "origin": "auto",
        "completion_action": "continue",
    }
    WebBridge.cancel_summary_review(bridge)
    bridge.conversation_buffer.append(("user", "합성 3"))
    WebBridge._check_auto_summarize(bridge)
    bridge.conversation_buffer.append(("assistant", "합성 4"))
    WebBridge._check_auto_summarize(bridge)

    assert len(started) == 2
    assert started[0][1]["origin"] == "auto"
    assert len(started[0][0]) == 2
    assert len(started[1][0]) == 4
    assert bridge.next_auto_summary_count == 4
    assert notices == [("요약 저장을 취소했어요.", "info")]


def test_clear_summary_cancel_completes_without_storage(tmp_path):
    messages = [("user", "가상 선택을 정했어."), ("assistant", "선택을 확인했어.")]
    bridge = SimpleNamespace(
        conversation_buffer=list(messages),
        memory_manager=MemoryManager(tmp_path / "memories.json"),
        llm_client=SimpleNamespace(),
        summary_notice=SimpleNamespace(emit=lambda *_args: None),
        summary_review_finished=SimpleNamespace(emit=lambda *_args: None),
    )
    started = []
    completed = []
    bridge._start_summary_review_worker = lambda batch, **kwargs: started.append(
        (list(batch), kwargs)
    )
    bridge._complete_conversation_clear = lambda: completed.append(True)

    WebBridge.clear_conversation(bridge)
    bridge._pending_summary_review = {
        "messages": list(messages),
        "origin": "clear",
        "completion_action": "clear",
    }
    WebBridge.cancel_summary_review(bridge)

    assert started[0][1]["origin"] == "clear"
    assert completed == [True]
    assert bridge.memory_manager.memories == []


def test_raw_recall_can_find_detail_outside_initial_summary_candidates(tmp_path):
    manager = MemoryManager(tmp_path / "memories.json")
    asyncio.run(manager.add_summary("부품 정리", [{"role": "user", "text": "가상 부품 VX900의 보관함은 파란 상자야."}]))
    chunks = asyncio.run(manager.find_relevant_raw_chunks("VX900 보관함", []))
    assert chunks and "파란 상자" in chunks[0][0].text
    assert asyncio.run(manager.find_relevant_raw_chunks("오로라 사진", [])) == []


def test_topic_state_does_not_reverse_on_historical_or_duplicate_update(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "topics.json")
    current = {"keyword": "모형 전시", "subject": "계획", "type": "status_flow", "state": "cancelled", "text": "모형 전시 취소", "effective_at": "2026-02-01"}
    manager.merge_hints_direct([current], source_memory_id="new")
    manager.merge_hints_direct([current], source_memory_id="new")
    manager.merge_hints_direct([{**current, "state": "active", "text": "모형 전시 준비", "effective_at": "2026-01-01"}], source_memory_id="old")
    clue = manager.topics[0].clues[0]
    assert clue.state == "cancelled"
    assert clue.history == []


def test_raw_recall_rejects_unrelated_chunks_even_with_summary_candidate(tmp_path):
    manager = MemoryManager(tmp_path / "memories.json")
    memory = asyncio.run(manager.add_summary("가상 요약", ["검은 연필과 하얀 공책"]))
    assert asyncio.run(manager.find_relevant_raw_chunks("오로라 사진", [(memory, 0.9)])) == []


def test_raw_fallback_limits_embedding_candidates(tmp_path):
    manager = MemoryManager(tmp_path / "memories.json")
    for index in range(12):
        asyncio.run(manager.add_summary("가상 부품", [f"부품 VX900의 가상 슬롯 {index}"]))
    embedded = []
    async def embed_chunks(chunks):
        embedded.extend(chunks)
    manager._ensure_chunk_embeddings = embed_chunks
    asyncio.run(manager.find_relevant_raw_chunks("VX900", [], top_k=2))
    assert len(embedded) == 6


def test_retry_rebuild_includes_recent_summarized_context():
    recent = [("user", "가상 선택 A와 B"), ("assistant", "두 선택 확인")]
    rebuilt = []
    bridge = SimpleNamespace(
        _summarized_recent_context=recent,
        conversation_buffer=[("user", "두 번째를 골라 줘"), ("assistant", "B")],
        llm_client=SimpleNamespace(rollback_last_assistant_turn=lambda: False, rebuild_context_from_conversation=lambda messages: rebuilt.append(messages) or True),
    )
    assert WebBridge._rollback_last_turn_pair_for_retry(bridge)
    assert rebuilt == [recent]


def test_topic_confirmation_advances_current_evidence_time(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "topics.json")
    hint = {"keyword": "가상 장치", "subject": "조립", "type": "status_flow", "state": "active", "text": "가상 장치 조립 중", "effective_at": "2026-01-01"}
    manager.merge_hints_direct([hint], source_memory_id="first")
    manager.merge_hints_direct([{**hint, "effective_at": "2026-03-01"}], source_memory_id="confirmation")
    manager.merge_hints_direct([{**hint, "state": "cancelled", "text": "조립 취소", "effective_at": "2026-02-01"}], source_memory_id="delayed")
    assert manager.topics[0].clues[0].state == "active"
    assert manager.topics[0].clues[0].history == []


def test_raw_recall_handles_particles_in_question(tmp_path):
    manager = MemoryManager(tmp_path / "memories.json")
    asyncio.run(manager.add_summary("부품 정리", ["VX900의 보관함은 파란 상자야."]))
    chunks = asyncio.run(manager.find_relevant_raw_chunks("VX900은 어디에 보관했지?", []))
    assert chunks and "파란 상자" in chunks[0][0].text


def test_context_includes_each_memory_summary_only_once():
    from src.ai.memory_context_builder import build_memory_context
    memory = SimpleNamespace(id="memory-example", summary="가상 부품 보관 기록", timestamp="2026-01-01")
    async def find_similar(*args, **kwargs):
        return [(memory, 0.8)]
    manager = SimpleNamespace(get_important=lambda: [memory], get_recent=lambda **kwargs: [memory], find_similar=find_similar)
    context = asyncio.run(build_memory_context(SimpleNamespace(memory_manager=manager), "가상 부품"))
    assert context.count(memory.summary) == 1
