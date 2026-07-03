import asyncio
import json

from src.ai.knowledge_map import KnowledgeMapManager
from src.ai.knowledge_map_types import TopicMemoryHint, TopicMemoryTopic


def _hint(
    keyword="Project Alpha",
    subject="planning",
    type="status",
    state="active",
    text="Project Alpha planning is active.",
    aliases=None,
    retrieval_terms=None,
    confidence=0.8,
):
    return TopicMemoryHint(
        keyword=keyword,
        subject=subject,
        type=type,
        state=state,
        text=text,
        aliases=list(aliases or []),
        retrieval_terms=list(retrieval_terms or []),
        confidence=confidence,
    )


def test_file_missing_loads_empty_topics(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")

    manager.load()

    assert manager.topics == []


def test_save_reload_roundtrip_preserves_schema_and_source(tmp_path):
    path = tmp_path / "knowledge_map.json"
    manager = KnowledgeMapManager(path)
    manager.merge_hints_direct(
        [
            _hint(
                keyword="Project Alpha",
                subject="planning",
                type="status",
                text="Project Alpha planning is ready for review.",
                aliases=["Alpha Plan"],
                retrieval_terms=["review", "planning"],
            )
        ],
        source_memory_id="memory-001",
    )

    manager.save()
    restored = KnowledgeMapManager(path)
    restored.load()

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1
    assert raw["last_updated"]
    assert len(restored.topics) == 1
    assert restored.topics[0].keyword == "Project Alpha"
    assert restored.topics[0].aliases == ["Alpha Plan"]
    assert restored.topics[0].retrieval_terms == ["review", "planning"]
    assert restored.topics[0].clues[0].source_memory_id == "memory-001"


def test_same_keyword_or_alias_merges_into_one_topic(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")

    manager.merge_hints_direct(
        [
            _hint(
                keyword="Project Alpha",
                subject="planning",
                text="Project Alpha planning is active.",
                aliases=["Alpha Plan"],
                retrieval_terms=["planning"],
            ),
            _hint(
                keyword="alpha plan",
                subject="budget",
                type="note",
                text="Alpha Plan budget notes are collected.",
                aliases=["Project Alpha Roadmap"],
                retrieval_terms=["budget"],
            ),
        ]
    )

    assert len(manager.topics) == 1
    assert manager.topics[0].keyword == "Project Alpha"
    assert manager.topics[0].aliases == ["Alpha Plan", "Project Alpha Roadmap"]
    assert manager.topics[0].retrieval_terms == ["planning", "budget"]
    assert {clue.subject for clue in manager.topics[0].clues} == {"planning", "budget"}


def test_dict_hint_requires_only_keyword_subject_and_text(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")

    manager.merge_hints_direct(
        [
            {
                "keyword": "Project Alpha",
                "subject": "planning",
                "text": "Project Alpha planning has a neutral update.",
            },
            {
                "keyword": "   ",
                "subject": "ignored",
                "text": "This neutral example should not be stored.",
            },
        ]
    )

    assert len(manager.topics) == 1
    assert manager.topics[0].clues[0].type == ""


def test_missing_required_dict_hint_keys_are_discarded_without_stopping(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")

    manager.merge_hints_direct(
        [
            {"subject": "ignored", "text": "A neutral malformed hint is ignored."},
            {"keyword": "Ignored Topic", "text": "A neutral malformed hint is ignored."},
            {"keyword": "Ignored Topic", "subject": "ignored"},
            {
                "keyword": "Project Alpha",
                "subject": "planning",
                "text": "Project Alpha planning remains usable.",
            },
        ]
    )

    assert len(manager.topics) == 1
    assert manager.topics[0].keyword == "Project Alpha"


def test_load_skips_topics_and_clues_missing_required_fields(tmp_path):
    path = tmp_path / "knowledge_map.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_updated": "2026-01-01T00:00:00+00:00",
                "topics": [
                    {"id": "topic-broken", "clues": []},
                    {
                        "id": "topic-7",
                        "keyword": "Project Alpha",
                        "clues": [
                            {
                                "id": "clue-broken",
                                "subject": "planning",
                                "type": "status",
                            },
                            {
                                "id": "clue-7",
                                "subject": "planning",
                                "type": "status",
                                "state": "active",
                                "text": "Project Alpha planning is active.",
                            },
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    manager = KnowledgeMapManager(path)

    manager.load()

    assert len(manager.topics) == 1
    assert manager.topics[0].id == "topic-7"
    assert len(manager.topics[0].clues) == 1
    assert manager.topics[0].clues[0].id == "clue-7"


def test_load_keeps_clue_when_history_contains_malformed_item(tmp_path):
    path = tmp_path / "knowledge_map.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_updated": "2026-01-01T00:00:00+00:00",
                "topics": [
                    {
                        "id": "topic-1",
                        "keyword": "Project Alpha",
                        "clues": [
                            {
                                "id": "clue-1",
                                "subject": "planning",
                                "type": "status",
                                "state": "active",
                                "text": "Project Alpha planning is active.",
                                "history": [
                                    {"state": "draft"},
                                    {
                                        "state": "review",
                                        "text": "Project Alpha planning was reviewed.",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manager = KnowledgeMapManager(path)

    manager.load()

    assert len(manager.topics) == 1
    assert len(manager.topics[0].clues) == 1
    assert manager.topics[0].clues[0].id == "clue-1"
    assert len(manager.topics[0].clues[0].history) == 1
    assert manager.topics[0].clues[0].history[0].state == "review"


def test_short_inner_english_fragment_does_not_merge_unrelated_topics(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    manager.merge_hints_direct(
        [
            _hint(
                keyword="paid",
                subject="billing",
                text="Paid status is recorded for a neutral sample.",
            )
        ]
    )

    manager.merge_hints_direct(
        [
            _hint(
                keyword="AI",
                subject="tooling",
                text="AI tooling is recorded for a neutral sample.",
            )
        ]
    )

    assert [topic.keyword for topic in manager.topics] == ["paid", "AI"]


def test_english_word_inner_substring_does_not_merge_unrelated_topics(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    manager.merge_hints_direct(
        [
            _hint(
                keyword="concatenate",
                subject="text",
                text="Concatenate operation is recorded for a neutral sample.",
            )
        ]
    )

    manager.merge_hints_direct(
        [
            _hint(
                keyword="cat",
                subject="label",
                text="Cat label is recorded for a neutral sample.",
            )
        ]
    )

    assert [topic.keyword for topic in manager.topics] == ["concatenate", "cat"]


def test_alias_phrase_still_merges_on_token_boundary(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    manager.merge_hints_direct(
        [
            _hint(
                keyword="Project Alpha",
                subject="planning",
                text="Project Alpha planning is active.",
                aliases=["Alpha Plan"],
            )
        ]
    )

    manager.merge_hints_direct(
        [
            _hint(
                keyword="Alpha Plan Review",
                subject="review",
                type="note",
                text="Alpha Plan Review notes are recorded.",
            )
        ]
    )

    assert len(manager.topics) == 1
    assert {clue.subject for clue in manager.topics[0].clues} == {"planning", "review"}


def test_alias_matching_multiple_topics_creates_new_topic(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    manager.topics = [
        TopicMemoryTopic(id="topic-1", keyword="Project Alpha", aliases=["Shared Tag"]),
        TopicMemoryTopic(id="topic-2", keyword="Project Beta", aliases=["Shared Tag"]),
    ]

    manager.merge_hints_direct(
        [
            _hint(
                keyword="Shared Tag",
                subject="decision",
                type="note",
                text="Shared Tag decision is recorded as a separate topic.",
            )
        ]
    )

    assert len(manager.topics) == 3
    assert manager.topics[-1].keyword == "Shared Tag"


def test_same_subject_and_type_replaces_active_clue_and_moves_previous_to_history(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    manager.merge_hints_direct(
        [
            _hint(
                keyword="Project Alpha",
                subject="planning",
                type="status",
                state="draft",
                text="Project Alpha planning is in draft.",
                confidence=0.4,
            )
        ],
        source_memory_id="memory-old",
    )

    manager.merge_hints_direct(
        [
            _hint(
                keyword="project alpha",
                subject="planning",
                type="status",
                state="review",
                text="Project Alpha planning is ready for review.",
                confidence=0.9,
            )
        ],
        source_memory_id="memory-new",
    )

    clue = manager.topics[0].clues[0]
    assert clue.state == "review"
    assert clue.text == "Project Alpha planning is ready for review."
    assert clue.confidence == 0.9
    assert clue.source_memory_id == "memory-new"
    assert len(clue.history) == 1
    assert clue.history[0].state == "draft"
    assert clue.history[0].text == "Project Alpha planning is in draft."
    assert clue.history[0].source_memory_id == "memory-old"


def test_search_direct_matches_keyword_alias_and_retrieval_terms(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    manager.merge_hints_direct(
        [
            _hint(
                keyword="Project Alpha",
                subject="planning",
                text="Project Alpha planning is ready for review.",
                aliases=["Alpha Plan"],
                retrieval_terms=["review", "planning", "draft"],
            ),
            _hint(
                keyword="Project Beta",
                subject="launch",
                text="Project Beta launch checklist is active.",
                aliases=["Beta Launch"],
                retrieval_terms=["launch", "checklist"],
            ),
        ]
    )

    keyword_result = manager.search_direct("What changed in Project Alpha?", top_k=1)
    alias_result = manager.search_direct("Show Alpha Plan notes", top_k=1)
    retrieval_result = manager.search_direct("review planning details", top_k=1)

    assert keyword_result[0].topic.keyword == "Project Alpha"
    assert keyword_result[0].score >= 1.0
    assert alias_result[0].topic.keyword == "Project Alpha"
    assert alias_result[0].score >= 0.9
    assert retrieval_result[0].topic.keyword == "Project Alpha"
    assert retrieval_result[0].score >= 0.65


def test_search_direct_does_not_return_candidate_for_clue_text_only(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    manager.merge_hints_direct(
        [
            _hint(
                keyword="Project Alpha",
                subject="planning",
                text="Project Alpha planning mentions a neutral marker phrase.",
                retrieval_terms=["planning"],
            )
        ]
    )

    results = manager.search_direct("neutral marker phrase", top_k=2)

    assert results == []


def test_search_handles_naive_timestamps_without_type_error(tmp_path):
    path = tmp_path / "knowledge_map.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "last_updated": "2026-01-01T00:00:00",
                "topics": [
                    {
                        "id": "topic-1",
                        "keyword": "Project Alpha",
                        "clues": [
                            {
                                "id": "clue-1",
                                "subject": "planning",
                                "type": "status",
                                "state": "active",
                                "text": "Project Alpha planning is active.",
                                "history": [
                                    {
                                        "state": "draft",
                                        "text": "Project Alpha planning was drafted.",
                                        "timestamp": "2026-01-01T00:00:00",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    manager = KnowledgeMapManager(path)
    manager.load()

    results = manager.search_direct("Project Alpha", top_k=1)

    assert results[0].topic.keyword == "Project Alpha"


def test_next_topic_id_uses_existing_numeric_max_after_gap(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    manager.topics = [
        TopicMemoryTopic(id="topic-1", keyword="Project Alpha"),
        TopicMemoryTopic(id="topic-3", keyword="Project Beta"),
    ]

    manager.merge_hints_direct(
        [
            _hint(
                keyword="Project Gamma",
                subject="planning",
                text="Project Gamma planning is active.",
            )
        ]
    )

    assert [topic.id for topic in manager.topics] == ["topic-1", "topic-3", "topic-4"]


def test_save_creates_utf8_without_bom(tmp_path):
    path = tmp_path / "knowledge_map.json"
    manager = KnowledgeMapManager(path)

    manager.save()

    assert path.read_bytes()[:3] != b"\xef\xbb\xbf"


def test_async_wrappers_use_direct_logic(tmp_path):
    manager = KnowledgeMapManager(tmp_path / "knowledge_map.json")
    asyncio.run(
        manager.async_merge_hints(
            [
                _hint(
                    keyword="Project Alpha",
                    subject="planning",
                    text="Project Alpha planning is ready for review.",
                    aliases=["Alpha Plan"],
                )
            ]
        )
    )

    results = asyncio.run(manager.async_search("Alpha Plan", top_k=1))
    context = asyncio.run(manager.async_build_context_block("Alpha Plan", top_k=1))

    assert results[0].topic.keyword == "Project Alpha"
    assert "[주제 기억]" in context
    assert "Project Alpha" in context
