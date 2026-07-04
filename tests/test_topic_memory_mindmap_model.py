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


def test_build_graph_filters_locally_by_keyword_alias_term_and_clue_text():
    graph = build_topic_memory_graph(
        [
            _topic("topic-1", "Project Atlas", [_clue("clue-1", "planning")], aliases=["Atlas"]),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "archive", text="Reference note")]),
        ],
        query="atlas",
    )

    assert "topic:topic-1" in graph.nodes
    assert "topic:topic-2" not in graph.nodes


def test_build_graph_filters_by_state_without_mutating_topics():
    clue = _clue("clue-1", "planning", state="closed")
    topics = [_topic("topic-1", "Project Atlas", [clue])]

    graph = build_topic_memory_graph(topics, state_filter="active")

    assert graph.total_topics == 0
    assert graph.total_clues == 0
    assert topics[0].clues[0].state == "closed"


def test_build_graph_adds_visual_shared_edges_only():
    graph = build_topic_memory_graph(
        [
            _topic("topic-1", "Project Atlas", [_clue("clue-1", "planning", type="status")]),
            _topic("topic-2", "Topic Beta", [_clue("clue-2", "planning", type="status")]),
        ]
    )

    visual_edges = [edge for edge in graph.edges if edge.kind == "shared"]
    assert visual_edges
    assert visual_edges[0].is_visual_hint is True
    assert "planning" in visual_edges[0].reason or "status" in visual_edges[0].reason
