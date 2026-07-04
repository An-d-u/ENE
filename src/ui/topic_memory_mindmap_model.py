from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Iterable

from src.ai.knowledge_map_types import TopicMemoryClue, TopicMemoryTopic


ROOT_LABEL = "주제 기억"
FALLBACK_CLUE_LABEL = "단서"


@dataclass(frozen=True)
class MindmapNode:
    id: str
    label: str
    kind: str
    topic_id: str | None = None
    clue_id: str | None = None
    subtitle: str = ""
    x: float = 0.0
    y: float = 0.0


@dataclass(frozen=True)
class MindmapEdge:
    source_id: str
    target_id: str
    kind: str
    reason: str = ""
    strength: float = 1.0
    is_visual_hint: bool = False


@dataclass(frozen=True)
class TopicMemoryGraph:
    nodes: dict[str, MindmapNode] = field(default_factory=dict)
    edges: list[MindmapEdge] = field(default_factory=list)
    topic_index: dict[str, TopicMemoryTopic] = field(default_factory=dict)
    clue_index: dict[str, TopicMemoryClue] = field(default_factory=dict)
    total_topics: int = 0
    total_clues: int = 0


def build_topic_memory_graph(
    topics: Iterable[TopicMemoryTopic],
    *,
    query: str = "",
    state_filter: str = "all",
    max_topics: int = 80,
) -> TopicMemoryGraph:
    # 순수 표시용 변환이다. manager.search_* 또는 save 계열은 호출하지 않는다.
    normalized_topics = [topic for topic in topics or [] if topic.keyword]
    return _build_graph_from_topics(
        normalized_topics,
        query=query,
        state_filter=state_filter,
        max_topics=max_topics,
    )


def _build_graph_from_topics(
    topics: list[TopicMemoryTopic],
    *,
    query: str,
    state_filter: str,
    max_topics: int,
) -> TopicMemoryGraph:
    query_text = query.casefold().strip()
    state_text = state_filter.casefold().strip()
    visible_topics: list[tuple[TopicMemoryTopic, list[TopicMemoryClue]]] = []

    for topic in topics:
        topic_matches = _matches_query(_topic_search_values(topic), query_text)

        if not topic.clues:
            if state_text and state_text != "all":
                continue
            if query_text and not topic_matches:
                continue
            visible_topics.append((topic, []))
            continue

        state_matched_clues = [
            clue for clue in topic.clues if _matches_state(clue, state_text)
        ]
        if not state_matched_clues:
            continue

        query_matched_clues = [
            clue
            for clue in state_matched_clues
            if _matches_query(_clue_search_values(clue), query_text)
        ]

        if query_text and not topic_matches and not query_matched_clues:
            continue

        visible_clues = state_matched_clues if topic_matches else query_matched_clues
        if visible_clues:
            visible_topics.append((topic, visible_clues))

    visible_topics = visible_topics[: max(0, max_topics)]

    nodes: dict[str, MindmapNode] = {
        "root": MindmapNode(id="root", label=ROOT_LABEL, kind="root")
    }
    edges: list[MindmapEdge] = []
    topic_index: dict[str, TopicMemoryTopic] = {}
    clue_index: dict[str, TopicMemoryClue] = {}

    topic_positions = _circular_positions(len(visible_topics), radius=240.0)
    for topic_number, ((topic, clues), (topic_x, topic_y)) in enumerate(
        zip(visible_topics, topic_positions)
    ):
        topic_node_id = f"topic:{topic.id}"
        topic_index[topic.id] = topic
        nodes[topic_node_id] = MindmapNode(
            id=topic_node_id,
            label=topic.keyword,
            kind="topic",
            topic_id=topic.id,
            subtitle=_topic_subtitle(topic),
            x=topic_x,
            y=topic_y,
        )
        edges.append(MindmapEdge("root", topic_node_id, "topic"))

        for clue, (clue_x, clue_y) in zip(
            clues,
            _clue_positions(topic_x, topic_y, topic_number, len(visible_topics), len(clues)),
        ):
            clue_node_id = f"clue:{topic.id}:{clue.id}"
            clue_index[clue_node_id] = clue
            nodes[clue_node_id] = MindmapNode(
                id=clue_node_id,
                label=_clue_label(clue),
                kind="clue",
                topic_id=topic.id,
                clue_id=clue.id,
                subtitle=clue.state,
                x=clue_x,
                y=clue_y,
            )
            edges.append(MindmapEdge(topic_node_id, clue_node_id, "clue"))

    edges.extend(_shared_edges(visible_topics))

    return TopicMemoryGraph(
        nodes=nodes,
        edges=edges,
        topic_index=topic_index,
        clue_index=clue_index,
        total_topics=len(visible_topics),
        total_clues=sum(len(clues) for _, clues in visible_topics),
    )


def _matches_state(clue: TopicMemoryClue, state_filter: str) -> bool:
    if not state_filter or state_filter == "all":
        return True
    return clue.state.casefold() == state_filter


def _matches_query(values: Iterable[str], query: str) -> bool:
    if not query:
        return True
    return any(query in value.casefold() for value in values if value)


def _topic_search_values(topic: TopicMemoryTopic) -> list[str]:
    return [topic.keyword, *topic.aliases, *topic.retrieval_terms]


def _clue_search_values(clue: TopicMemoryClue) -> list[str]:
    return [clue.subject, clue.type, clue.state, clue.text]


def _topic_subtitle(topic: TopicMemoryTopic) -> str:
    if topic.aliases:
        return ", ".join(topic.aliases[:3])
    if topic.retrieval_terms:
        return ", ".join(topic.retrieval_terms[:3])
    return ""


def _clue_label(clue: TopicMemoryClue) -> str:
    return clue.subject or clue.type or FALLBACK_CLUE_LABEL


def _circular_positions(count: int, *, radius: float) -> list[tuple[float, float]]:
    if count <= 0:
        return []
    return [
        (
            round(math.cos(_angle(index, count)) * radius, 4),
            round(math.sin(_angle(index, count)) * radius, 4),
        )
        for index in range(count)
    ]


def _clue_positions(
    topic_x: float,
    topic_y: float,
    topic_index: int,
    topic_count: int,
    clue_count: int,
) -> list[tuple[float, float]]:
    if clue_count <= 0:
        return []

    base_angle = _angle(topic_index, max(topic_count, 1))
    if clue_count == 1:
        angles = [base_angle]
    else:
        spread = math.pi / 2
        angles = [
            base_angle - (spread / 2) + (spread * clue_index / (clue_count - 1))
            for clue_index in range(clue_count)
        ]

    return [
        (
            round(topic_x + math.cos(angle) * 120.0, 4),
            round(topic_y + math.sin(angle) * 120.0, 4),
        )
        for angle in angles
    ]


def _angle(index: int, count: int) -> float:
    return (-math.pi / 2) + (2 * math.pi * index / count)


def _shared_edges(
    visible_topics: list[tuple[TopicMemoryTopic, list[TopicMemoryClue]]],
) -> list[MindmapEdge]:
    edges: list[MindmapEdge] = []
    signatures = [
        (topic, _shared_signature(topic, clues)) for topic, clues in visible_topics
    ]

    for left_index, (left_topic, left_signature) in enumerate(signatures):
        for right_topic, right_signature in signatures[left_index + 1 :]:
            left_clue_values, left_terms = left_signature
            right_clue_values, right_terms = right_signature
            shared_clue_values = set(left_clue_values) & set(right_clue_values)
            shared_terms = set(left_terms) & set(right_terms)
            if shared_clue_values:
                reason = left_clue_values[sorted(shared_clue_values)[0]]
            elif shared_terms:
                reason = left_terms[sorted(shared_terms)[0]]
            else:
                continue

            edges.append(
                MindmapEdge(
                    source_id=f"topic:{left_topic.id}",
                    target_id=f"topic:{right_topic.id}",
                    kind="shared",
                    reason=reason,
                    strength=0.35,
                    is_visual_hint=True,
                )
            )

    return edges


def _shared_signature(
    topic: TopicMemoryTopic,
    clues: list[TopicMemoryClue],
) -> tuple[dict[str, str], dict[str, str]]:
    clue_values: list[str] = []
    for clue in clues:
        if clue.subject:
            clue_values.append(clue.subject)
        if clue.type:
            clue_values.append(clue.type)
    return _normalized_lookup(clue_values), _normalized_lookup(topic.retrieval_terms)


def _normalized_lookup(values: Iterable[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for value in values:
        text = value.strip()
        if text:
            lookup.setdefault(text.casefold(), text)
    return lookup
