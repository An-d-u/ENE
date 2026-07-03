from src.ai.knowledge_map_types import (
    TopicMemoryClue,
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
