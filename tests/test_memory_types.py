from src.ai.memory_types import MemoryEntry, MemoryMessage, create_memory_entry


def test_create_memory_entry_sets_defaults():
    entry = create_memory_entry("요약", ["원문1", "원문2"])
    assert entry.summary == "요약"
    assert entry.original_messages == ["원문1", "원문2"]
    assert entry.is_important is False
    assert entry.embedding is None
    assert entry.tags == []
    assert isinstance(entry.id, str)
    assert isinstance(entry.timestamp, str)



def test_create_memory_entry_accepts_activation_metadata():
    entry = create_memory_entry(
        "릴리스 회의 요약",
        ["릴리스 회의는 금요일 오후로 정리했다."],
        aliases=[" 릴리즈 회의 ", "release meeting"],
        trigger_terms=[" 배포 ", "릴리스", "배포"],
    )

    assert entry.aliases == ["릴리즈 회의", "release meeting"]
    assert entry.trigger_terms == ["배포", "릴리스"]

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
    assert restored.conversation_id == "legacy-mem-legacy"
    assert restored.expires_at is None
    assert restored.schema_version == 4
    assert restored.migration_meta["migration_version"] == 1
    assert "memory_type" in restored.migration_meta["inferred_fields"]


def test_memory_entry_from_legacy_dict_backfills_activation_fields():
    restored = MemoryEntry.from_dict(
        {
            "id": "mem-activation-legacy",
            "summary": "프로젝트 릴리스 회의는 금요일 오후로 정리함",
            "original_messages": ["릴리스 회의는 금요일 오후로 잡자."],
            "timestamp": "2026-05-01T10:00:00",
            "schema_version": 3,
            "aliases": [" 릴리즈 회의 ", "", "release meeting"],
            "trigger_terms": [" 배포 ", "릴리스", ""],
            "linked_memory_ids": [" mem-detail ", "", "mem-detail"],
            "activation_weight": "1.4",
            "last_activated_at": "2026-05-02T10:00:00",
        }
    )

    assert restored.aliases == ["릴리즈 회의", "release meeting"]
    assert restored.trigger_terms == ["배포", "릴리스"]
    assert restored.linked_memory_ids == ["mem-detail"]
    assert restored.activation_weight == 1.4
    assert restored.last_activated_at == "2026-05-02T10:00:00"
    assert restored.schema_version == 4


def test_create_memory_entry_normalizes_structured_original_messages():
    entry = create_memory_entry(
        "summary",
        [
            {
                "role": "user",
                "text": "hello",
                "timestamp": "2026-04-14T20:00:00+09:00",
                "conversation_id": "conv-1",
                "turn_index": 0,
            },
            MemoryMessage(
                role="assistant",
                text="hi",
                timestamp="2026-04-14T20:00:05+09:00",
                conversation_id="conv-1",
                turn_index=1,
            ),
        ],
    )

    assert entry.original_messages == [
        MemoryMessage(
            role="user",
            text="hello",
            timestamp="2026-04-14T20:00:00+09:00",
            conversation_id="conv-1",
            turn_index=0,
        ),
        MemoryMessage(
            role="assistant",
            text="hi",
            timestamp="2026-04-14T20:00:05+09:00",
            conversation_id="conv-1",
            turn_index=1,
        ),
    ]


def test_memory_entry_from_legacy_message_strings_backfills_message_metadata():
    restored = MemoryEntry.from_dict(
        {
            "id": "mem-legacy-msgs",
            "summary": "legacy summary",
            "original_messages": ["안녕 에네.", "안녕하세요, 마스터."],
            "timestamp": "2026-04-14T20:00:00+09:00",
            "schema_version": 2,
        }
    )

    assert restored.original_messages == [
        MemoryMessage(
            role="user",
            text="안녕 에네.",
            timestamp="2026-04-14T20:00:00+09:00",
            conversation_id="legacy-mem-legacy-msgs",
            turn_index=0,
        ),
        MemoryMessage(
            role="assistant",
            text="안녕하세요, 마스터.",
            timestamp="2026-04-14T20:00:00+09:00",
            conversation_id="legacy-mem-legacy-msgs",
            turn_index=1,
        ),
    ]
    assert restored.schema_version == 4
    assert restored.migration_meta["legacy_original_messages"] is True


def test_memory_entry_from_legacy_message_strings_falls_back_to_alternating_roles():
    restored = MemoryEntry.from_dict(
        {
            "id": "mem-legacy-alt",
            "summary": "legacy alt summary",
            "original_messages": ["메모 하나", "메모 둘", "메모 셋"],
            "timestamp": "2026-04-14T20:00:00+09:00",
            "schema_version": 2,
        }
    )

    assert [message.role for message in restored.original_messages] == [
        "user",
        "assistant",
        "assistant",
    ]


def test_memory_entry_reinfers_roles_for_legacy_unknown_message_objects():
    restored = MemoryEntry.from_dict(
        {
            "id": "mem-legacy-reinfer",
            "summary": "legacy reinfer summary",
            "original_messages": [
                {
                    "role": "unknown",
                    "text": "안녕 에네.",
                    "timestamp": "2026-04-14T20:00:00+09:00",
                    "conversation_id": "legacy-mem-legacy-reinfer",
                    "turn_index": 0,
                },
                {
                    "role": "unknown",
                    "text": "안녕하세요, 마스터.",
                    "timestamp": "2026-04-14T20:00:00+09:00",
                    "conversation_id": "legacy-mem-legacy-reinfer",
                    "turn_index": 1,
                },
            ],
            "timestamp": "2026-04-14T20:00:00+09:00",
            "schema_version": 3,
        }
    )

    assert [message.role for message in restored.original_messages] == [
        "user",
        "assistant",
    ]


def test_memory_entry_allows_consecutive_assistant_roles_for_ambiguous_legacy_messages():
    restored = MemoryEntry.from_dict(
        {
            "id": "mem-legacy-assistant-run",
            "summary": "legacy assistant run summary",
            "original_messages": [
                "안녕 에네.",
                "메모 정리 중입니다.",
                "곧 말씀드릴게요.",
            ],
            "timestamp": "2026-04-14T20:00:00+09:00",
            "schema_version": 2,
        }
    )

    assert [message.role for message in restored.original_messages] == [
        "user",
        "assistant",
        "assistant",
    ]


def test_memory_entry_uses_assistant_lookahead_to_keep_bridge_user_turn():
    restored = MemoryEntry.from_dict(
        {
            "id": "mem-legacy-lookahead",
            "summary": "legacy lookahead summary",
            "original_messages": [
                "오늘 일정 정리가 잘 안 되네",
                "그럼 우선 가장 작은 할 일 하나부터 정리해볼까요?",
                "좋아, 먼저 책상 정리부터 할게.",
                "좋아요. 끝나면 다음 할 일을 하나만 더 정해봐요.",
            ],
            "timestamp": "2026-04-14T20:00:00+09:00",
            "schema_version": 2,
        }
    )

    assert [message.role for message in restored.original_messages] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
