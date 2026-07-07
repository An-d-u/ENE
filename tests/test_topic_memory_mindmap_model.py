from src.ai.knowledge_map_types import TopicMemoryClue, TopicMemoryTopic
from src.ui.topic_memory_mindmap_model import build_topic_memory_graph


def _topic(topic_id, keyword, clues, aliases=None, retrieval_terms=None):
    return TopicMemoryTopic(
        id=topic_id,
        keyword=keyword,
        aliases=list(aliases or []),
        retrieval_terms=list(retrieval_terms or []),
        clues=clues,
    )


def _clue(clue_id, subject, type="note", state="active", text="Synthetic clue text."):
    return TopicMemoryClue(
        id=clue_id,
        subject=subject,
        type=type,
        state=state,
        text=text,
        confidence=0.75,
    )


def test_build_graph_creates_central_topic_clue_nodes_and_primary_edges():
    graph = build_topic_memory_graph(
        [
            _topic(
                "topic-1",
                "Project Atlas",
                [_clue("clue-1", "planning", type="status")],
                aliases=["Atlas"],
                retrieval_terms=["roadmap"],
            )
        ]
    )

    assert graph.total_topics == 1
    assert graph.total_clues == 1
    assert graph.nodes["root"].label == "주제 기억"
    assert graph.nodes["topic:topic-1"].label == "Project Atlas"
    assert graph.nodes["clue:topic-1:clue-1"].label == "planning"
    assert ("root", "topic:topic-1", "topic") in {
        (edge.source_id, edge.target_id, edge.kind) for edge in graph.edges
    }
    assert ("topic:topic-1", "clue:topic-1:clue-1", "clue") in {
        (edge.source_id, edge.target_id, edge.kind) for edge in graph.edges
    }


def test_build_graph_uses_korean_fallback_label_for_blank_clue_subject_and_type():
    graph = build_topic_memory_graph(
        [_topic("topic-1", "Project Atlas", [_clue("clue-1", "", type="")])]
    )

    assert graph.nodes["clue:topic-1:clue-1"].label == "단서"


def test_build_graph_uses_injected_display_labels():
    graph = build_topic_memory_graph(
        [_topic("topic-1", "Project Atlas", [_clue("clue-1", "", type="")])],
        root_label="Topic Memory",
        fallback_clue_label="Clue",
    )

    assert graph.nodes["root"].label == "Topic Memory"
    assert graph.nodes["clue:topic-1:clue-1"].label == "Clue"


def test_build_graph_filters_locally_by_keyword_and_alias():
    graph = build_topic_memory_graph(
        [
            _topic("topic-1", "Project Atlas", [_clue("clue-1", "planning")], aliases=["Atlas"]),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "archive", text="Reference note")]),
        ],
        query="atlas",
    )

    assert "topic:topic-1" in graph.nodes
    assert "topic:topic-2" not in graph.nodes


def test_build_graph_filters_locally_by_retrieval_term():
    graph = build_topic_memory_graph(
        [
            _topic(
                "topic-1",
                "Project Atlas",
                [_clue("clue-1", "planning")],
                retrieval_terms=["roadmap"],
            ),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "archive")]),
        ],
        query="roadmap",
    )

    assert "topic:topic-1" in graph.nodes
    assert "topic:topic-2" not in graph.nodes


def test_build_graph_filters_locally_by_clue_text():
    graph = build_topic_memory_graph(
        [
            _topic("topic-1", "Project Atlas", [_clue("clue-1", "planning")]),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "archive", text="Reference note")]),
        ],
        query="reference",
    )

    assert "topic:topic-1" not in graph.nodes
    assert "topic:topic-2" in graph.nodes
    assert "clue:topic-2:clue-2" in graph.nodes


def test_build_graph_applies_max_topics_after_query_filtering():
    non_matching_topics = [
        _topic(f"topic-{index}", f"Archive {index}", [_clue(f"clue-{index}", "archive")])
        for index in range(80)
    ]
    matching_topic = _topic("topic-target", "Project Atlas", [_clue("clue-target", "planning")])

    graph = build_topic_memory_graph(
        [*non_matching_topics, matching_topic],
        query="atlas",
        max_topics=1,
    )

    assert graph.total_topics == 1
    assert "topic:topic-target" in graph.nodes


def test_build_graph_shows_clueless_topic_with_all_state_and_no_query():
    graph = build_topic_memory_graph([_topic("topic-1", "Project Atlas", [])])

    assert graph.total_topics == 1
    assert graph.total_clues == 0
    assert "topic:topic-1" in graph.nodes


def test_build_graph_shows_clueless_topic_with_all_state_and_matching_query():
    graph = build_topic_memory_graph(
        [_topic("topic-1", "Project Atlas", [])],
        query="atlas",
    )

    assert graph.total_topics == 1
    assert "topic:topic-1" in graph.nodes


def test_build_graph_hides_clueless_topic_with_specific_state_filter():
    graph = build_topic_memory_graph(
        [_topic("topic-1", "Project Atlas", [])],
        state_filter="active",
    )

    assert graph.total_topics == 0
    assert "topic:topic-1" not in graph.nodes


def test_build_graph_filters_by_state_without_mutating_topics():
    clue = _clue("clue-1", "planning", state="closed")
    topics = [_topic("topic-1", "Project Atlas", [clue])]

    graph = build_topic_memory_graph(topics, state_filter="active")

    assert graph.total_topics == 0
    assert graph.total_clues == 0
    assert topics[0].clues[0].state == "closed"


def test_build_graph_does_not_connect_topics_by_clue_subject_or_type():
    graph = build_topic_memory_graph(
        [
            _topic("topic-1", "Project Atlas", [_clue("clue-1", "planning", type="status")]),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "planning", type="status")]),
        ]
    )

    visual_edges = [edge for edge in graph.edges if edge.kind == "shared"]
    assert visual_edges == []


def test_build_graph_adds_shared_edge_for_retrieval_term_overlap():
    graph = build_topic_memory_graph(
        [
            _topic(
                "topic-1",
                "Project Atlas",
                [_clue("clue-1", "launch", type="milestone")],
                retrieval_terms=["roadmap"],
            ),
            _topic(
                "topic-2",
                "Topic Beta",
                [_clue("clue-2", "archive", type="status")],
                retrieval_terms=["roadmap"],
            ),
        ]
    )

    visual_edges = [edge for edge in graph.edges if edge.kind == "shared"]
    assert len(visual_edges) == 1
    assert visual_edges[0].reason == "roadmap"


def test_build_graph_adds_shared_edge_for_alias_overlap():
    graph = build_topic_memory_graph(
        [
            _topic(
                "topic-1",
                "Project Atlas",
                [_clue("clue-1", "launch", type="milestone")],
                aliases=["notebook"],
            ),
            _topic(
                "topic-2",
                "Topic Beta",
                [_clue("clue-2", "archive", type="status")],
                retrieval_terms=["notebook"],
            ),
        ]
    )

    visual_edges = [edge for edge in graph.edges if edge.kind == "shared"]
    assert len(visual_edges) == 1
    assert visual_edges[0].reason == "notebook"


def test_build_graph_places_shared_topics_closer_than_unrelated_topics():
    graph = build_topic_memory_graph(
        [
            _topic(
                "topic-1",
                "Project Atlas",
                [_clue("clue-1", "launch")],
                retrieval_terms=["notebook"],
            ),
            _topic(
                "topic-2",
                "Topic Beta",
                [_clue("clue-2", "archive")],
                retrieval_terms=["notebook"],
            ),
            _topic(
                "topic-3",
                "Topic Gamma",
                [_clue("clue-3", "separate")],
                retrieval_terms=["garden"],
            ),
        ]
    )

    atlas = graph.nodes["topic:topic-1"]
    beta = graph.nodes["topic:topic-2"]
    gamma = graph.nodes["topic:topic-3"]

    shared_distance = ((atlas.x - beta.x) ** 2 + (atlas.y - beta.y) ** 2) ** 0.5
    unrelated_distance = ((atlas.x - gamma.x) ** 2 + (atlas.y - gamma.y) ** 2) ** 0.5
    assert shared_distance < unrelated_distance


def test_build_graph_does_not_share_between_retrieval_term_and_clue_value():
    graph = build_topic_memory_graph(
        [
            _topic(
                "topic-1",
                "Project Atlas",
                [_clue("clue-1", "launch", type="milestone")],
                retrieval_terms=["planning"],
            ),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "planning", type="status")]),
        ]
    )

    visual_edges = [edge for edge in graph.edges if edge.kind == "shared"]
    assert visual_edges == []
