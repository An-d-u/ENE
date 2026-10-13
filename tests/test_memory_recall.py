"""명시적 사용자 근거가 하나일 때만 생략된 대상을 연결한다."""

import pytest


def message(text, role="user", turn_id="turn-1"):
    return dict(text=text, role=role, turn_id=turn_id, timestamp="2025-01-01")


@pytest.mark.parametrize("query,text,name", [
    ("그건 어떤 모양이었지?", "등대 모형 이야기를 이어가자.", "등대 모형"),
    ("What color was it?", "I am assembling Lantern Kit.", "Lantern Kit"),
    ("それは何色だった？", "紙の塔について話そう。", "紙の塔"),
    ("그건 무슨 색이었더라?", "등대 모형을 보고 있어.", "등대 모형"),
])
def test_unambiguous_user_entity_can_expand_narrow_recall(query, text, name):
    from src.ai.memory_recall import KnownEntity, resolve_followup_recall
    plan = resolve_followup_recall(query, [message(text)], [KnownEntity("target", name)])
    assert plan.entity_id == "target"
    assert plan.evidence_turn_id == "turn-1"
    assert plan.query == query
    assert name in plan.expanded_query


@pytest.mark.parametrize("query,messages", [
    ("그건 어떤 모양이었지?", [message("등대 모형과 바람 모형을 비교한다.")]),
    ("그건 어떤 모양이었지?", [message("등대 모형을 살펴볼까요?", "assistant")]),
    ("그건 어떤 모양이었지?", [message("설명서에 '등대 모형을 조립했다'라는 말이 있다.")]),
    ("그건 어떤 모양이었지?", [message("등대 모형을 조립한 건 아니야.")]),
    ("다른 이야기인데 그건 어떤 모양이야?", [message("등대 모형을 조립한다.")]),
    ("바람 모형은 어떤 모양이야?", [message("등대 모형을 조립한다.")]),
    ("그건 종이 비행기와 어떻게 달라?", [message("등대 모형을 조립한다.")]),
    ("그건 어떤 모양이었지?", []),
    ("그건 어떤 모양이었지?", [message("등대 모형을 조립한다."), message("바람 모형은 어때요?", "assistant")]),
])
def test_unclear_or_switched_context_does_not_expand(query, messages):
    from src.ai.memory_recall import KnownEntity, resolve_followup_recall
    entities = [KnownEntity("tower", "등대 모형"), KnownEntity("wind", "바람 모형")]
    assert resolve_followup_recall(query, messages, entities) is None


def test_alias_collision_is_not_resolved_by_recency():
    from src.ai.memory_recall import KnownEntity, resolve_followup_recall
    entities = [KnownEntity("a", "첫 모형", ("작은 탑",)), KnownEntity("b", "둘째 모형", ("작은 탑",))]
    assert resolve_followup_recall("그건 어떤 모양이었지?", [message("작은 탑을 꺼냈다.")], entities) is None


@pytest.mark.parametrize("raw_limit", [0, 3])
@pytest.mark.parametrize("recent", [
    [message("유리 풍차를 살펴볼까요?", "assistant")],
    [message("유리 풍차를 보자."), message("다른 이야기로 넘어가자. 종이 터널을 보자.")],
])
def test_unresolved_reference_reaches_response_even_with_existing_memory(tmp_path, raw_limit, recent):
    import asyncio
    from types import SimpleNamespace
    from src.ai.memory import MemoryManager
    from src.ai.memory_types import MemoryEntry
    from src.ai.memory_context_builder import build_memory_context

    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [MemoryEntry("glass", "유리 풍차는 상자에 있다.", [], "2025-01-01", entity_names=["유리 풍차"])]
    client = SimpleNamespace(memory_manager=manager, settings=SimpleNamespace(config={"max_raw_chunks_in_context": raw_limit}))
    result = asyncio.run(build_memory_context(client, "그건 어디에 있었지?", recent_memory_messages=recent))
    assert "MEMORY_REFERENCE_UNRESOLVED" in result
    resolved = asyncio.run(build_memory_context(client, "그건 어디에 있었지?", recent_memory_messages=[message("유리 풍차를 보자.")]))
    assert "MEMORY_REFERENCE_UNRESOLVED" not in resolved


@pytest.mark.parametrize("next_text", ["Switch topics. I am holding a blue umbrella.", "이제 다른 얘기를 하자.", "파란 우산을 펼쳤어."])
def test_later_user_subject_cannot_inherit_an_older_known_entity(next_text):
    from src.ai.memory_recall import KnownEntity, resolve_followup_recall
    messages = [message("Lantern Kit is complete."), message(next_text)]
    assert resolve_followup_recall("What color was it?", messages, [KnownEntity("kit", "Lantern Kit")]) is None


@pytest.mark.parametrize("primary_candidate", [False, True])
def test_followup_recovers_missing_summary_and_low_similarity_raw(tmp_path, primary_candidate):
    import asyncio
    from types import SimpleNamespace
    from src.ai.memory import MemoryManager
    from src.ai.memory_types import MemoryEntry, MemoryContextTrace
    from src.ai.memory_context_builder import build_memory_context
    manager = MemoryManager(tmp_path / "memory.json")
    memory = MemoryEntry("tower", "등대 모형을 만들었다.", [
        {"role": "user", "text": "등대 모형 받침은 육각형이다.", "timestamp": "2025-01-01"}
    ], "2025-01-01", entity_names=["등대 모형"])
    manager.memories = [memory]
    if primary_candidate:
        memory.trigger_terms = ["모양이었지"]
    base = asyncio.run(manager.find_activated("그건 어떤 모양이었지?", mark_retrieved=False))
    assert bool(base) is primary_candidate
    assert asyncio.run(manager.find_relevant_raw_chunks("그건 어떤 모양이었지?", [(item.memory, item.activation_score) for item in base])) == []
    client = SimpleNamespace(memory_manager=manager, _prompt_language=lambda: "ko",
                             settings=SimpleNamespace(config={"max_recent_memories": 0, "max_important_memories": 0}))
    trace = MemoryContextTrace()
    context = asyncio.run(build_memory_context(client, "그건 어떤 모양이었지?",
        recent_memory_messages=[message("등대 모형을 보고 있어.")], trace=trace, memory_request_id="followup"))
    assert "육각형" in context
    assert "tower" in trace.summary_ids
    assert trace.raw_chunks
    assert memory.retrieval_count == 1


def test_supplement_and_lexical_fallback_share_bound_before_embedding(tmp_path):
    import asyncio
    from src.ai.memory import MemoryManager
    from src.ai.memory_types import MemoryEntry
    from src.ai.memory_recall import KnownEntity, resolve_followup_recall
    from scripts.memory_quality_eval import SyntheticEmbedding
    class Embedding(SyntheticEmbedding):
        def __init__(self):
            self.batches = []
        async def embed_batch(self, texts):
            self.batches.append(list(texts))
            return await super().embed_batch(texts)
    embedding = Embedding()
    manager = MemoryManager(tmp_path / "memory.json", embedding)
    memory = MemoryEntry("tower", "등대 모형", [
        dict(role="user", text=f"등대 모형의 부품 {index}는 육각형이다.", timestamp="2025-01-01")
        for index in range(80)
    ], "2025-01-01", entity_names=["등대 모형"])
    manager.memories = [memory]
    plan = resolve_followup_recall("그건 어떤 모양이었지?", [message("등대 모형을 본다.")], [KnownEntity("tower", "등대 모형")])
    selected = asyncio.run(manager.find_relevant_raw_chunks(
        plan.query, [], supplemental_memories=[(memory, 1.0)], recall_plan=plan, top_k=2))
    assert selected
    assert sum(len(batch) for batch in embedding.batches) <= 6


def test_japanese_entity_and_raw_tokens_survive_normalization(tmp_path):
    import asyncio
    from src.ai.memory import MemoryManager
    from src.ai.memory_types import MemoryEntry
    manager = MemoryManager(tmp_path / "memory.json")
    memory = MemoryEntry("paper", "紙の門は白い。", [{"role": "user", "text": "紙の門は白い。"}],
                         "2025-01-01", entity_names=["紙の門"])
    manager.memories = [memory]
    results = asyncio.run(manager.find_activated("紙の門 それは何色だった？", mark_retrieved=False))
    assert results and results[0].memory is memory
    raw = asyncio.run(manager.find_relevant_raw_chunks("紙の門", [(memory, 1.0)]))
    assert raw
    assert asyncio.run(manager.find_activated("紙の門番", mark_retrieved=False)) == []


@pytest.mark.parametrize("raw_limit", [0, 2])
def test_supplement_disabled_or_failed_keeps_original_context(tmp_path, raw_limit):
    import asyncio
    from types import SimpleNamespace
    from src.ai.memory import MemoryManager
    from src.ai.memory_types import MemoryEntry
    from src.ai.memory_context_builder import build_memory_context
    manager = MemoryManager(tmp_path / "memory.json")
    manager.memories = [MemoryEntry("tower", "등대 모형을 만들었다.", [], "2025-01-01",
                                   entity_names=["등대 모형"], trigger_terms=["모양이었지"])]
    client = SimpleNamespace(memory_manager=manager, _prompt_language=lambda: "ko",
                             settings=SimpleNamespace(config={"max_raw_chunks_in_context": raw_limit}))
    query = "그건 어떤 모양이었지?"
    original = asyncio.run(build_memory_context(client, query))
    calls = []
    search = manager.find_activated
    async def failing_supplement(text, **kwargs):
        calls.append(text)
        if text != query:
            raise RuntimeError("합성 보완 검색 실패")
        return await search(text, **kwargs)
    manager.find_activated = failing_supplement
    result = asyncio.run(build_memory_context(client, query, recent_memory_messages=[message("등대 모형을 본다.")]))
    assert result == original
    assert len(calls) == (1 if raw_limit == 0 else 2)
