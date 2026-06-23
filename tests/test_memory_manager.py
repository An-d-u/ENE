import asyncio
import json

from src.ai.embedding import EmbeddingGenerator
from src.ai.memory import MemoryManager
from src.ai.memory_types import MemoryChunk, MemoryEntry, MemoryMessage, create_memory_entry


class FakeEmbeddingGenerator:
    async def embed(self, text: str):
        if "python" in text.lower():
            return [1.0, 0.0]
        return [0.0, 1.0]

    @staticmethod
    def cosine_similarity(vec1, vec2):
        return EmbeddingGenerator.cosine_similarity(vec1, vec2)


class ScoreEmbeddingGenerator:
    async def embed(self, text: str):
        return [1.0]

    @staticmethod
    def cosine_similarity(vec1, vec2):
        if not vec2:
            return 0.0
        return float(vec2[0])


class ChunkBiasEmbeddingGenerator:
    async def embed(self, text: str):
        normalized = str(text or "")
        if "병원" in normalized or "3시" in normalized:
            return [1.0, 0.0]
        if "영화" in normalized or "10시" in normalized:
            return [0.0, 1.0]
        return [0.5, 0.5]

    async def embed_batch(self, texts):
        return [await self.embed(text) for text in texts]

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


def test_find_activated_boosts_alias_terms_and_recent_context(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    plain_match = MemoryEntry(
        id="mem-plain",
        summary="일반 배포 메모",
        original_messages=["배포 일정은 아직 정하지 않았다."],
        timestamp="2026-05-01T09:00:00",
        embedding=[0.82],
    )
    activated_match = MemoryEntry(
        id="mem-activation",
        summary="릴리스 회의는 금요일 오후로 정리함",
        original_messages=["릴리스 회의는 금요일 오후로 잡자."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.75],
        aliases=["릴리즈 회의"],
        trigger_terms=["배포"],
        activation_weight=1.3,
    )
    manager.memories = [plain_match, activated_match]

    results = asyncio.run(
        manager.find_activated(
            "배포 일정 알려줘",
            recent_context="방금 릴리즈 회의 이야기를 했다.",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )

    assert len(results) == 1
    assert results[0].memory.id == "mem-activation"
    assert results[0].keyword_score > 0
    assert results[0].recent_context_score > 0
    assert activated_match.retrieval_count == 1
    assert activated_match.last_activated_at is not None
    assert plain_match.retrieval_count == 0


def test_find_activated_reports_raw_similarity_without_metadata_bonus(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    metadata_rich = MemoryEntry(
        id="mem-metadata-rich",
        summary="배포 체크리스트를 정리함",
        original_messages=["배포 전에 체크리스트를 확인하기로 했다."],
        timestamp="2026-05-01T10:00:00",
        is_important=True,
        embedding=[0.6],
        memory_type="task",
        importance_reason="user_marked",
        confidence=1.0,
        trigger_terms=["배포"],
    )
    manager.memories = [metadata_rich]

    results = asyncio.run(
        manager.find_activated("배포 체크리스트", top_k=1, min_similarity=0.5)
    )

    assert len(results) == 1
    assert results[0].similarity_score == 0.6


def test_find_activated_includes_direct_alias_candidate_below_similarity_threshold(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    alias_match = MemoryEntry(
        id="mem-soundboard",
        summary="오디오 도구 설정을 정리함",
        original_messages=["도구 설정값을 따로 적어 두기로 했다."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.1],
        aliases=["사운드보드 설정"],
    )
    manager.memories = [alias_match]

    results = asyncio.run(
        manager.find_activated(
            "사운드보드 설정 다시 알려줘",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )

    assert len(results) == 1
    assert results[0].memory.id == "mem-soundboard"
    assert results[0].similarity_score == 0.0
    assert results[0].direct_match_score > 0
    assert alias_match.retrieval_count == 1


def test_find_activated_prioritizes_exact_alias_over_weak_semantic_candidate(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    weak_semantic = MemoryEntry(
        id="mem-weak-semantic",
        summary="다른 작업의 점검 내용을 정리함",
        original_messages=["작업 점검표를 확인했다."],
        timestamp="2026-05-01T09:00:00",
        embedding=[0.55],
    )
    alias_match = MemoryEntry(
        id="mem-soundboard",
        summary="오디오 도구 설정을 정리함",
        original_messages=["도구 설정값을 따로 적어 두기로 했다."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.1],
        aliases=["사운드보드 설정"],
    )
    manager.memories = [weak_semantic, alias_match]

    results = asyncio.run(
        manager.find_activated(
            "사운드보드 설정",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )

    assert len(results) == 1
    assert results[0].memory.id == "mem-soundboard"
    assert weak_semantic.retrieval_count == 0


def test_find_activated_uses_conservative_trigger_direct_candidates(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    single_short_trigger = MemoryEntry(
        id="mem-single-trigger",
        summary="짧은 단일 트리거만 있는 기억",
        original_messages=["짧은 검색 단서 하나만 남겼다."],
        timestamp="2026-05-01T09:00:00",
        embedding=[0.1],
        trigger_terms=["배포"],
    )
    paired_trigger = MemoryEntry(
        id="mem-paired-trigger",
        summary="배포 체크 절차를 정리함",
        original_messages=["배포 전에 체크 절차를 보기로 했다."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.1],
        trigger_terms=["배포", "체크"],
    )
    manager.memories = [single_short_trigger, paired_trigger]

    single_results = asyncio.run(
        manager.find_activated(
            "배포",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )
    paired_results = asyncio.run(
        manager.find_activated(
            "배포 체크",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )

    assert single_results == []
    assert len(paired_results) == 1
    assert paired_results[0].memory.id == "mem-paired-trigger"


def test_find_activated_does_not_match_ascii_entity_inside_other_words(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    entity_match = MemoryEntry(
        id="mem-entity",
        summary="프로젝트 이름을 정리함",
        original_messages=["프로젝트 이름을 따로 남겼다."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.1],
        entity_names=["ENE"],
    )
    manager.memories = [entity_match]

    results = asyncio.run(
        manager.find_activated(
            "scene 설정 알려줘",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )

    assert results == []
    assert entity_match.retrieval_count == 0


def test_find_activated_prefers_alias_over_newer_entity_match(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    alias_match = MemoryEntry(
        id="mem-alias",
        summary="도구 설정을 정리함",
        original_messages=["도구 설정값을 남겼다."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.1],
        aliases=["사운드보드 설정"],
    )
    entity_match = MemoryEntry(
        id="mem-entity",
        summary="사운드보드라는 대상 이름만 있는 기억",
        original_messages=["대상 이름을 기록했다."],
        timestamp="2026-05-02T10:00:00",
        embedding=[0.1],
        entity_names=["사운드보드"],
    )
    manager.memories = [entity_match, alias_match]

    results = asyncio.run(
        manager.find_activated(
            "사운드보드 설정",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )

    assert len(results) == 1
    assert results[0].memory.id == "mem-alias"


def test_find_activated_uses_direct_match_without_embedding_generator(tmp_path):
    manager = MemoryManager(str(tmp_path / "memory.json"))
    alias_match = MemoryEntry(
        id="mem-direct-only",
        summary="오디오 도구 설정을 정리함",
        original_messages=["도구 설정값을 따로 적어 두기로 했다."],
        timestamp="2026-05-01T10:00:00",
        aliases=["사운드보드 설정"],
    )
    manager.memories = [alias_match]

    results = asyncio.run(
        manager.find_activated(
            "사운드보드 설정 다시 알려줘",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )

    assert len(results) == 1
    assert results[0].memory.id == "mem-direct-only"
    assert results[0].similarity_score == 0.0
    assert results[0].direct_match_score > 0


def test_find_activated_matches_korean_three_syllable_and_ascii_acronym_triggers(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    korean_trigger = MemoryEntry(
        id="mem-korean-trigger",
        summary="검색어 설정을 정리함",
        original_messages=["검색어 설정을 남겼다."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.1],
        trigger_terms=["검색어"],
    )
    api_trigger = MemoryEntry(
        id="mem-api-trigger",
        summary="API 설정을 정리함",
        original_messages=["API 설정을 남겼다."],
        timestamp="2026-05-01T10:01:00",
        embedding=[0.1],
        trigger_terms=["API"],
    )
    data_trigger = MemoryEntry(
        id="mem-data-trigger",
        summary="데이터 설정을 정리함",
        original_messages=["데이터 설정을 남겼다."],
        timestamp="2026-05-01T10:02:00",
        embedding=[0.1],
        trigger_terms=["data"],
    )
    manager.memories = [korean_trigger, api_trigger, data_trigger]

    korean_results = asyncio.run(
        manager.find_activated(
            "검색어 다시 알려줘",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )
    api_results = asyncio.run(
        manager.find_activated(
            "API 설정 다시 알려줘",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )
    metadata_results = asyncio.run(
        manager.find_activated(
            "metadata 설정 다시 알려줘",
            top_k=1,
            min_similarity=0.5,
            expand_hops=0,
        )
    )

    assert len(korean_results) == 1
    assert korean_results[0].memory.id == "mem-korean-trigger"
    assert len(api_results) == 1
    assert api_results[0].memory.id == "mem-api-trigger"
    assert metadata_results == []


def test_find_activated_expands_linked_memories(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    primary = MemoryEntry(
        id="mem-release",
        summary="릴리스 회의가 금요일에 있음",
        original_messages=["릴리스 회의를 금요일에 하기로 했다."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.82],
        linked_memory_ids=["mem-time"],
    )
    linked_detail = MemoryEntry(
        id="mem-time",
        summary="회의 시간은 오후 4시로 정리함",
        original_messages=["회의 시간은 오후 4시가 좋겠다."],
        timestamp="2026-05-01T10:05:00",
        embedding=[0.1],
    )
    unrelated = MemoryEntry(
        id="mem-unrelated",
        summary="다른 작업 메모",
        original_messages=["다른 작업을 정리했다."],
        timestamp="2026-05-01T11:00:00",
        embedding=[0.81],
    )
    manager.memories = [primary, linked_detail, unrelated]

    results = asyncio.run(
        manager.find_activated(
            "릴리스 회의 시간",
            top_k=3,
            min_similarity=0.5,
            expand_hops=1,
        )
    )

    result_ids = [result.memory.id for result in results]
    assert result_ids[0] == "mem-release"
    assert "mem-time" in result_ids
    assert next(result for result in results if result.memory.id == "mem-time").link_score > 0
    assert linked_detail.retrieval_count == 1


def test_find_activated_does_not_let_unrelated_link_displace_better_candidate(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    primary = MemoryEntry(
        id="mem-release",
        summary="릴리스 회의가 금요일에 있음",
        original_messages=["릴리스 회의를 금요일에 하기로 했다."],
        timestamp="2026-05-01T10:00:00",
        embedding=[0.82],
        activation_weight=1.2,
        linked_memory_ids=["mem-unrelated-link"],
    )
    unrelated_link = MemoryEntry(
        id="mem-unrelated-link",
        summary="책상 정리 메모",
        original_messages=["책상 위 물건을 정리하기로 했다."],
        timestamp="2026-05-01T10:05:00",
        embedding=[0.1],
    )
    better_candidate = MemoryEntry(
        id="mem-time",
        summary="릴리스 회의 시간은 오후 4시로 정리함",
        original_messages=["릴리스 회의 시간은 오후 4시가 좋겠다."],
        timestamp="2026-05-01T11:00:00",
        embedding=[0.74],
    )
    manager.memories = [primary, unrelated_link, better_candidate]

    results = asyncio.run(
        manager.find_activated(
            "릴리스 회의 시간",
            top_k=2,
            min_similarity=0.5,
            expand_hops=1,
        )
    )

    assert [result.memory.id for result in results] == ["mem-release", "mem-time"]
    assert unrelated_link.retrieval_count == 0


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
            aliases=["에네 구조"],
            trigger_terms=["ENE", "구조"],
            conversation_id="conv-1",
            expires_at="2026-04-09T00:00:00",
            schema_version=3,
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
    assert restored.schema_version == 4
    assert restored.aliases == ["에네 구조"]
    assert restored.trigger_terms == ["ENE", "구조"]
    assert restored.linked_memory_ids == []
    assert restored.activation_weight == 1.0
    assert restored.last_activated_at is None


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
    assert restored.schema_version == 4
    assert restored.aliases == []
    assert restored.trigger_terms == []
    assert restored.linked_memory_ids == []
    assert restored.activation_weight == 1.0
    assert restored.last_activated_at is None


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
    assert restored["schema_version"] == 4
    assert restored["source"] == "legacy"
    assert restored["memory_type"] == "preference"
    assert restored["aliases"] == []
    assert restored["trigger_terms"] == []
    assert restored["linked_memory_ids"] == []
    assert restored["activation_weight"] == 1.0
    assert restored["last_activated_at"] is None


def test_load_v4_memory_file_persists_canonical_activation_fields(tmp_path):
    memory_file = tmp_path / "memory.json"
    memory_file.write_text(
        json.dumps(
            {
                "memories": [
                    {
                        "id": "mem-v4-noncanonical",
                        "summary": "릴리스 회의는 금요일 오후로 정리함",
                        "original_messages": ["릴리스 회의는 금요일 오후로 잡자."],
                        "timestamp": "2026-05-01T10:00:00",
                        "schema_version": 4,
                        "source": "chat",
                        "memory_type": "event",
                        "importance_reason": "none",
                        "retrieval_count": 0,
                        "last_used_at": None,
                        "confidence": 0.5,
                        "user_confirmed": None,
                        "entity_names": [],
                        "conversation_id": "conv-1",
                        "expires_at": None,
                        "migration_meta": {},
                        "aliases": " 릴리즈 회의 ",
                        "trigger_terms": [" 배포 ", "배포"],
                        "linked_memory_ids": [" mem-detail ", "mem-detail"],
                        "activation_weight": 99,
                        "last_activated_at": "",
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
    assert restored["aliases"] == ["릴리즈 회의"]
    assert restored["trigger_terms"] == ["배포"]
    assert restored["linked_memory_ids"] == ["mem-detail"]
    assert restored["activation_weight"] == 3.0
    assert restored["last_activated_at"] is None


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
            aliases=["에네 구조"],
            trigger_terms=["ENE", "구조"],
        )
    )

    assert created.source == "chat"
    assert created.memory_type == "task"
    assert created.importance_reason == "repeated_topic"
    assert created.confidence == 0.85
    assert created.entity_names == ["ENE"]
    assert created.aliases == ["에네 구조"]
    assert created.trigger_terms == ["ENE", "구조"]


def test_save_and_reload_roundtrip_preserves_structured_original_messages(tmp_path):
    memory_file = tmp_path / "memory.json"
    manager = MemoryManager(str(memory_file))
    manager.memories.append(
        create_memory_entry(
            summary="structured summary",
            original_messages=[
                {
                    "role": "user",
                    "text": "hello",
                    "timestamp": "2026-04-14T20:00:00+09:00",
                    "conversation_id": "conv-structured",
                    "turn_index": 0,
                },
                {
                    "role": "assistant",
                    "text": "hi there",
                    "timestamp": "2026-04-14T20:00:05+09:00",
                    "conversation_id": "conv-structured",
                    "turn_index": 1,
                },
            ],
        )
    )
    manager.save()

    reloaded = MemoryManager(str(memory_file))

    assert reloaded.memories[0].original_messages == [
        MemoryMessage(
            role="user",
            text="hello",
            timestamp="2026-04-14T20:00:00+09:00",
            conversation_id="conv-structured",
            turn_index=0,
        ),
        MemoryMessage(
            role="assistant",
            text="hi there",
            timestamp="2026-04-14T20:00:05+09:00",
            conversation_id="conv-structured",
            turn_index=1,
        ),
    ]


def test_find_similar_reranks_by_metadata_bonus(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    base_winner = create_memory_entry(
        "일반적인 일정 메모",
        ["내일 일정이 있다."],
        embedding=[0.78],
        memory_type="general",
        confidence=0.5,
    )
    metadata_winner = create_memory_entry(
        "병원 예약 일정 메모",
        ["내일 병원 예약이 있다."],
        is_important=True,
        embedding=[0.74],
        memory_type="event",
        importance_reason="promise",
        confidence=0.95,
    )
    manager.memories = [base_winner, metadata_winner]

    results = asyncio.run(
        manager.find_similar("내일 일정 알려줘", top_k=2, min_similarity=0.5)
    )

    assert [memory.summary for memory, _ in results] == [
        "병원 예약 일정 메모",
        "일반적인 일정 메모",
    ]
    assert results[0][1] > results[1][1]


def test_find_similar_metadata_bonus_does_not_bypass_min_similarity(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    manager.memories = [
        create_memory_entry(
            "중요한 약속 메모",
            ["내일 꼭 알려줘."],
            is_important=True,
            embedding=[0.34],
            memory_type="promise",
            importance_reason="promise",
            confidence=0.99,
        )
    ]

    results = asyncio.run(
        manager.find_similar("내일 약속 기억해줘", top_k=3, min_similarity=0.35)
    )

    assert results == []


def test_find_similar_updates_retrieval_metadata_for_returned_results(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ScoreEmbeddingGenerator(),
    )
    returned = create_memory_entry(
        "반환되는 메모",
        ["python"],
        embedding=[0.9],
    )
    returned.retrieval_count = 2
    untouched = create_memory_entry(
        "반환되지 않는 메모",
        ["food"],
        embedding=[0.1],
    )
    untouched.retrieval_count = 5
    manager.memories = [returned, untouched]

    results = asyncio.run(
        manager.find_similar("python 질문", top_k=1, min_similarity=0.5)
    )

    assert len(results) == 1
    assert results[0][0].summary == "반환되는 메모"
    assert returned.retrieval_count == 3
    assert isinstance(returned.last_used_at, str)
    assert untouched.retrieval_count == 5
    assert untouched.last_used_at is None


def test_build_raw_chunks_creates_six_turn_windows_with_role_text(tmp_path):
    manager = MemoryManager(str(tmp_path / "memory.json"))
    memory = create_memory_entry(
        "chunk test",
        original_messages=[
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "text": f"message-{index}",
                "timestamp": f"2026-04-14T20:0{index}:00+09:00",
                "conversation_id": "conv-chunk",
                "turn_index": index,
            }
            for index in range(8)
        ],
    )

    chunks = manager.build_raw_chunks(memory, chunk_turns=6)

    assert chunks == [
        MemoryChunk(
            memory_id=memory.id,
            conversation_id="conv-chunk",
            start_turn_index=0,
            end_turn_index=5,
            text="\n".join(
                [
                    "[user] message-0",
                    "[assistant] message-1",
                    "[user] message-2",
                    "[assistant] message-3",
                    "[user] message-4",
                    "[assistant] message-5",
                ]
            ),
            messages=memory.original_messages[:6],
        ),
        MemoryChunk(
            memory_id=memory.id,
            conversation_id="conv-chunk",
            start_turn_index=2,
            end_turn_index=7,
            text="\n".join(
                [
                    "[user] message-2",
                    "[assistant] message-3",
                    "[user] message-4",
                    "[assistant] message-5",
                    "[user] message-6",
                    "[assistant] message-7",
                ]
            ),
            messages=memory.original_messages[2:8],
        ),
    ]


def test_build_raw_chunks_returns_single_chunk_when_conversation_is_short(tmp_path):
    manager = MemoryManager(str(tmp_path / "memory.json"))
    memory = create_memory_entry(
        "short chunk test",
        original_messages=[
            {
                "role": "user",
                "text": "짧은 대화",
                "timestamp": "2026-04-14T20:00:00+09:00",
                "conversation_id": "conv-short",
                "turn_index": 0,
            },
            {
                "role": "assistant",
                "text": "응답",
                "timestamp": "2026-04-14T20:01:00+09:00",
                "conversation_id": "conv-short",
                "turn_index": 1,
            },
        ],
    )

    chunks = manager.build_raw_chunks(memory, chunk_turns=6)

    assert len(chunks) == 1
    assert chunks[0].start_turn_index == 0
    assert chunks[0].end_turn_index == 1
    assert chunks[0].text == "[user] 짧은 대화\n[assistant] 응답"


def test_find_relevant_raw_chunks_prefers_latest_user_query_over_older_support_context(tmp_path):
    manager = MemoryManager(
        str(tmp_path / "memory.json"),
        embedding_generator=ChunkBiasEmbeddingGenerator(),
    )
    hospital_memory = create_memory_entry(
        "병원 예약 기억",
        original_messages=[
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "text": text,
                "timestamp": f"2026-04-14T20:0{index}:00+09:00",
                "conversation_id": "conv-hospital",
                "turn_index": index,
            }
            for index, text in enumerate(
                [
                    "내일 병원 예약 있어",
                    "응, 오후 3시였지",
                    "맞아 3시야",
                    "까먹지 않게 다시 말해줄게",
                    "병원 위치도 다시 볼까",
                    "응 필요하면 말해줘",
                ]
            )
        ],
    )
    movie_memory = create_memory_entry(
        "영화 약속 기억",
        original_messages=[
            {
                "role": "user" if index % 2 == 0 else "assistant",
                "text": text,
                "timestamp": f"2026-04-14T21:0{index}:00+09:00",
                "conversation_id": "conv-movie",
                "turn_index": index,
            }
            for index, text in enumerate(
                [
                    "오늘 영화 보자",
                    "응 10시 영화로 하자",
                    "좋아 10시 맞지",
                    "표도 예매해둘게",
                    "좌석은 가운데가 좋아",
                    "응 기억해둘게",
                ]
            )
        ],
    )

    results = asyncio.run(
        manager.find_relevant_raw_chunks(
            "병원 예약 시간이 몇 시였지?",
            [(hospital_memory, 0.75), (movie_memory, 0.9)],
            recent_context="아까 영화 10시 얘기를 했었어",
            top_k=1,
            chunk_turns=6,
        )
    )

    assert len(results) == 1
    best_chunk, _, meta = results[0]
    assert best_chunk.conversation_id == "conv-hospital"
    assert "병원 예약" in best_chunk.text
    assert meta["primary_similarity"] > meta["support_similarity"]
