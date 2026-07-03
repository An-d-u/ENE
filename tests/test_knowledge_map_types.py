from src.ai.knowledge_map_types import (
    TopicMemoryClue,
    TopicMemoryHistoryItem,
    TopicMemoryHint,
    TopicMemorySearchResult,
    TopicMemoryTopic,
)


def test_topic_memory_hint가_문자열_목록_confidence를_정규화한다():
    hint = TopicMemoryHint(
        keyword="  합성 주제  ",
        aliases=[" 짧은 별칭 ", "", "짧은 별칭"],
        retrieval_terms=[" 진행 ", "결정"],
        subject="  합성 항목  ",
        type="status_flow",
        state="active",
        text="합성 항목이 진행 중으로 정리됨.",
        confidence=2,
    )

    assert hint.keyword == "합성 주제"
    assert hint.aliases == ["짧은 별칭"]
    assert hint.retrieval_terms == ["진행", "결정"]
    assert hint.subject == "합성 항목"
    assert hint.confidence == 1.0


def test_topic_memory_topic이_dict_roundtrip에서_history와_embedding_metadata를_보존한다():
    topic = TopicMemoryTopic(
        id="topic-1",
        keyword="합성 주제",
        clues=[
            TopicMemoryClue(
                id="clue-1",
                subject="합성 항목",
                type="purchase_flow",
                state="purchased",
                text="합성 항목을 구매한 상태로 정리됨.",
                confidence=0.8,
                embedding=[0.1, 0.2],
                embedding_provider="FAKE",
                embedding_model="fake-topic-model",
                history=[{"state": "wanted", "text": "합성 항목을 사고 싶어 함."}],
            )
        ],
    )

    restored = TopicMemoryTopic.from_dict(topic.to_dict())

    assert restored.keyword == "합성 주제"
    assert restored.clues[0].history[0]["state"] == "wanted"
    assert restored.clues[0].embedding == [0.1, 0.2]
    assert restored.clues[0].embedding_provider == "fake"


def test_topic_memory_search_result가_dict_roundtrip에서_중첩_타입을_복원한다():
    result = TopicMemorySearchResult(
        topic=TopicMemoryTopic(
            id="topic-2",
            keyword="합성 주제",
            clues=[
                TopicMemoryClue(
                    id="clue-2",
                    subject="합성 항목",
                    type="status_flow",
                    state="active",
                    text="합성 항목이 진행 중으로 정리됨.",
                )
            ],
        ),
        clue=TopicMemoryClue(
            id="clue-2",
            subject="합성 항목",
            type="status_flow",
            state="active",
            text="합성 항목이 진행 중으로 정리됨.",
        ),
        score=1.2,
        matched_terms=[" 합성 ", "", "합성", "진행"],
    )

    restored = TopicMemorySearchResult.from_dict(result.to_dict())

    assert restored.topic.id == "topic-2"
    assert restored.clue is not None
    assert restored.clue.id == "clue-2"
    assert restored.score == 1.0
    assert restored.matched_terms == ["합성", "진행"]


def test_topic_memory_history_item이_dict_roundtrip에서_정규화와_confidence_clamp를_보존한다():
    item = TopicMemoryHistoryItem(
        state="  wanted  ",
        text="  합성 항목을 검토 중으로 정리함.  ",
        timestamp="  2026-01-01T00:00:00+09:00  ",
        confidence=2,
    )

    restored = TopicMemoryHistoryItem.from_dict(item.to_dict())

    assert restored.state == "wanted"
    assert restored.text == "합성 항목을 검토 중으로 정리함."
    assert restored.timestamp == "2026-01-01T00:00:00+09:00"
    assert restored.confidence == 1.0


def test_topic_memory_hint가_dict_roundtrip에서_정규화된_값을_보존한다():
    hint = TopicMemoryHint(
        keyword="  합성 주제  ",
        aliases=[" 대표 별칭 ", "", "대표 별칭"],
        retrieval_terms=[" 검색어 ", "검색어", "단서"],
        subject="  합성 항목  ",
        type="status_flow",
        state="active",
        text="  합성 항목이 활성 상태로 정리됨.  ",
        confidence=0.7,
    )

    restored = TopicMemoryHint.from_dict(hint.to_dict())

    assert restored.keyword == "합성 주제"
    assert restored.aliases == ["대표 별칭"]
    assert restored.retrieval_terms == ["검색어", "단서"]
    assert restored.text == "합성 항목이 활성 상태로 정리됨."
    assert restored.confidence == 0.7


def test_topic_memory_topic_roundtrip이_aliases와_retrieval_terms를_정규화한다():
    topic = TopicMemoryTopic(
        id=" topic-3 ",
        keyword="  합성 주제  ",
        aliases=[" 대표 별칭 ", "", "대표 별칭", "다른 별칭"],
        retrieval_terms=[" 검색어 ", "검색어", "", "단서"],
        clues=[],
    )

    restored = TopicMemoryTopic.from_dict(topic.to_dict())

    assert restored.id == "topic-3"
    assert restored.keyword == "합성 주제"
    assert restored.aliases == ["대표 별칭", "다른 별칭"]
    assert restored.retrieval_terms == ["검색어", "단서"]


def test_topic_memory_clue는_빈_embedding_metadata를_none으로_정규화한다():
    clue = TopicMemoryClue(
        id="clue-3",
        subject="합성 항목",
        type="status_flow",
        state="active",
        text="합성 항목이 활성 상태로 정리됨.",
        embedding_provider="   ",
        embedding_model="",
    )

    restored = TopicMemoryClue.from_dict(clue.to_dict())

    assert restored.embedding_provider is None
    assert restored.embedding_model is None


def test_confidence는_하한_0으로_clamp된다():
    hint = TopicMemoryHint(
        keyword="합성 주제",
        subject="합성 항목",
        type="status_flow",
        state="active",
        text="합성 항목이 활성 상태로 정리됨.",
        confidence=-1,
    )
    clue = TopicMemoryClue(
        id="clue-4",
        subject="합성 항목",
        type="status_flow",
        state="active",
        text="합성 항목이 활성 상태로 정리됨.",
        confidence=-0.2,
    )
    result = TopicMemorySearchResult(
        topic=TopicMemoryTopic(id="topic-4", keyword="합성 주제"),
        score=-0.5,
    )

    assert hint.confidence == 0.0
    assert clue.confidence == 0.0
    assert result.score == 0.0
