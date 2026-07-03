"""주제 기억 맵을 저장하고 병합하며 직접 검색하는 관리자."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
from typing import Any, Iterable

from src.ai.knowledge_map_types import (
    TopicMemoryClue,
    TopicMemoryHint,
    TopicMemoryHistoryItem,
    TopicMemorySearchResult,
    TopicMemoryTopic,
)
from src.core.app_paths import load_json_data, resolve_user_storage_path, save_json_data


SCHEMA_VERSION = 1
DEFAULT_KNOWLEDGE_FILE = "knowledge_map.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _visible_text(value: Any) -> str:
    return str(value or "").strip()


def _is_phrase_match(left: str, right: str) -> bool:
    left_norm = _norm(left)
    right_norm = _norm(right)
    if not left_norm or not right_norm:
        return False
    return (
        left_norm == right_norm
        or _contains_phrase(left_norm, right_norm)
        or _contains_phrase(right_norm, left_norm)
    )


def _contains_phrase(container: str, phrase: str) -> bool:
    if phrase not in container:
        return False
    if re.search(r"[a-z0-9]", phrase):
        return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", container) is not None
    return True


def _append_unique(items: list[str], candidates: Iterable[str]) -> None:
    seen = {_norm(item) for item in items}
    for candidate in candidates:
        text = _visible_text(candidate)
        key = _norm(text)
        if not key or key in seen:
            continue
        seen.add(key)
        items.append(text)


def _query_contains_term(query: str, term: str) -> bool:
    term_norm = _norm(term)
    return bool(term_norm) and _contains_phrase(_norm(query), term_norm)


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-z0-9가-힣]{2,}", value or "")}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _coerce_hint(raw_hint: TopicMemoryHint | dict[str, Any]) -> TopicMemoryHint | None:
    if isinstance(raw_hint, TopicMemoryHint):
        return raw_hint
    if not isinstance(raw_hint, dict):
        return None

    data = dict(raw_hint)
    if (
        not _visible_text(data.get("keyword"))
        or not _visible_text(data.get("subject"))
        or not _visible_text(data.get("text"))
    ):
        return None
    data.setdefault("type", "")
    data.setdefault("state", "")
    try:
        return TopicMemoryHint.from_dict(data)
    except TypeError:
        return None


def _coerce_history_item(raw_item: TopicMemoryHistoryItem | dict[str, Any]) -> TopicMemoryHistoryItem | None:
    if isinstance(raw_item, TopicMemoryHistoryItem):
        if not raw_item.state or not raw_item.text:
            return None
        return raw_item
    if not isinstance(raw_item, dict):
        return None

    data = dict(raw_item)
    if not _visible_text(data.get("state")) or not _visible_text(data.get("text")):
        return None
    try:
        return TopicMemoryHistoryItem.from_dict(data)
    except TypeError:
        return None


def _coerce_clue(raw_clue: TopicMemoryClue | dict[str, Any]) -> TopicMemoryClue | None:
    if isinstance(raw_clue, TopicMemoryClue):
        if not raw_clue.id or not raw_clue.subject or not raw_clue.text:
            return None
        return raw_clue
    if not isinstance(raw_clue, dict):
        return None

    data = dict(raw_clue)
    if (
        not _visible_text(data.get("id"))
        or not _visible_text(data.get("subject"))
        or not _visible_text(data.get("text"))
    ):
        return None
    data.setdefault("type", "")
    data.setdefault("state", "")
    raw_history = data.get("history", [])
    if not isinstance(raw_history, list):
        raw_history = []
    data["history"] = [
        item
        for item in (_coerce_history_item(item) for item in raw_history)
        if item is not None
    ]
    try:
        return TopicMemoryClue.from_dict(data)
    except TypeError:
        return None


def _coerce_topic(raw_topic: TopicMemoryTopic | dict[str, Any]) -> TopicMemoryTopic | None:
    if isinstance(raw_topic, TopicMemoryTopic):
        if not raw_topic.id or not raw_topic.keyword:
            return None
        raw_topic.clues = [
            clue
            for clue in (_coerce_clue(clue) for clue in raw_topic.clues)
            if clue is not None
        ]
        return raw_topic
    if not isinstance(raw_topic, dict):
        return None

    data = dict(raw_topic)
    if not _visible_text(data.get("id")) or not _visible_text(data.get("keyword")):
        return None
    raw_clues = data.get("clues", [])
    if not isinstance(raw_clues, list):
        raw_clues = []
    data["clues"] = [
        clue
        for clue in (_coerce_clue(clue) for clue in raw_clues)
        if clue is not None
    ]
    try:
        return TopicMemoryTopic.from_dict(data)
    except TypeError:
        return None


def _next_numbered_id(prefix: str, ids: Iterable[str]) -> str:
    pattern = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    numbers = [
        int(match.group(1))
        for raw_id in ids
        if (match := pattern.fullmatch(str(raw_id or "").strip()))
    ]
    return f"{prefix}-{max(numbers, default=0) + 1}"


class KnowledgeMapManager:
    """`knowledge_map.json`의 로드, 저장, 병합, 검색을 담당한다."""

    def __init__(self, knowledge_file: str | Path | None = None, embedding_generator=None):
        self.knowledge_file = resolve_user_storage_path(knowledge_file or DEFAULT_KNOWLEDGE_FILE)
        self.embedding_generator = embedding_generator
        self.topics: list[TopicMemoryTopic] = []
        self.last_updated: str | None = None

    def load(self) -> "KnowledgeMapManager":
        if not self.knowledge_file.exists():
            self.topics = []
            self.last_updated = None
            return self

        data = load_json_data(self.knowledge_file)
        raw_topics = data.get("topics", []) if isinstance(data, dict) else []
        self.topics = []
        for raw_topic in raw_topics:
            topic = _coerce_topic(raw_topic)
            if topic is not None:
                self.topics.append(topic)
        self.last_updated = _visible_text(data.get("last_updated")) if isinstance(data, dict) else None
        return self

    def save(self) -> Path:
        self.last_updated = _now_iso()
        payload = {
            "schema_version": SCHEMA_VERSION,
            "topics": [topic.to_dict() for topic in self.topics],
            "last_updated": self.last_updated,
        }
        return save_json_data(self.knowledge_file, payload, encoding="utf-8", indent=2)

    def merge_hints_direct(
        self,
        hints: Iterable[TopicMemoryHint | dict[str, Any]],
        source_memory_id: str = "",
    ) -> list[TopicMemoryTopic]:
        for raw_hint in hints or []:
            hint = _coerce_hint(raw_hint)
            if hint is None:
                continue
            if not hint.keyword or not hint.subject or not hint.text:
                continue

            topic = self._find_single_topic_candidate(hint)
            if topic is None:
                topic = TopicMemoryTopic(
                    id=self._next_topic_id(),
                    keyword=hint.keyword,
                    aliases=list(hint.aliases),
                    retrieval_terms=list(hint.retrieval_terms),
                    clues=[],
                )
                self.topics.append(topic)
            else:
                _append_unique(topic.aliases, hint.aliases)
                _append_unique(topic.retrieval_terms, hint.retrieval_terms)

            self._merge_hint_into_topic(topic, hint, source_memory_id=source_memory_id)

        self.last_updated = _now_iso()
        return self.topics

    async def async_merge_hints(
        self,
        hints: Iterable[TopicMemoryHint | dict[str, Any]],
        source_memory_id: str = "",
    ) -> list[TopicMemoryTopic]:
        return self.merge_hints_direct(hints, source_memory_id=source_memory_id)

    def search_direct(self, query: str, top_k: int = 2) -> list[TopicMemorySearchResult]:
        query_text = _visible_text(query)
        if not query_text or top_k <= 0:
            return []

        results: list[tuple[int, TopicMemorySearchResult]] = []
        for index, topic in enumerate(self.topics):
            keyword_score, keyword_matches = self._keyword_score(topic, query_text)
            retrieval_score, retrieval_matches = self._retrieval_score(topic, query_text)

            if keyword_score <= 0 and retrieval_score <= 0:
                continue

            clue = topic.clues[0] if topic.clues else None
            clue_score = self._clue_keyword_score(clue, query_text)
            metadata_score = self._metadata_score(clue)
            score = min(1.0, keyword_score + retrieval_score + clue_score + metadata_score)
            matched_terms = keyword_matches + retrieval_matches
            results.append(
                (
                    index,
                    TopicMemorySearchResult(
                        topic=topic,
                        clue=clue,
                        score=score,
                        matched_terms=matched_terms,
                    ),
                )
            )

        results.sort(key=lambda item: (-item[1].score, item[0]))
        return [result for _, result in results[:top_k]]

    async def async_search(self, query: str, top_k: int = 2) -> list[TopicMemorySearchResult]:
        return self.search_direct(query, top_k=top_k)

    async def async_build_context_block(
        self,
        query: str,
        top_k: int = 2,
        language: str = "ko",
    ) -> str:
        results = self.search_direct(query, top_k=top_k)
        if not results:
            return ""

        lines = ["[주제 기억]"]
        for result in results:
            clue = result.clue
            if clue is None:
                lines.append(f"- {result.topic.keyword}")
                continue
            lines.append(f"- {result.topic.keyword} / {clue.subject}: {clue.text}")
        return "\n".join(lines)

    def _find_single_topic_candidate(self, hint: TopicMemoryHint) -> TopicMemoryTopic | None:
        candidate_terms = [hint.keyword, *hint.aliases]
        matches = [
            topic
            for topic in self.topics
            if self._topic_matches_any_term(topic, candidate_terms)
        ]
        if len(matches) != 1:
            return None
        return matches[0]

    def _topic_matches_any_term(self, topic: TopicMemoryTopic, terms: Iterable[str]) -> bool:
        topic_terms = [topic.keyword, *topic.aliases]
        return any(
            _is_phrase_match(candidate, topic_term)
            for candidate in terms
            for topic_term in topic_terms
        )

    def _merge_hint_into_topic(
        self,
        topic: TopicMemoryTopic,
        hint: TopicMemoryHint,
        *,
        source_memory_id: str,
    ) -> None:
        existing = next(
            (
                clue
                for clue in topic.clues
                if clue.subject == hint.subject and clue.type == hint.type
            ),
            None,
        )
        timestamp = _now_iso()
        if existing is None:
            topic.clues.append(
                TopicMemoryClue(
                    id=self._next_clue_id(topic),
                    subject=hint.subject,
                    type=hint.type,
                    state=hint.state,
                    text=hint.text,
                    confidence=hint.confidence,
                    source_memory_id=_visible_text(source_memory_id) or None,
                )
            )
            return

        existing.history.insert(
            0,
            TopicMemoryHistoryItem(
                state=existing.state,
                text=existing.text,
                timestamp=timestamp,
                confidence=existing.confidence,
                source_memory_id=existing.source_memory_id,
            ),
        )
        existing.state = hint.state
        existing.text = hint.text
        existing.confidence = hint.confidence
        existing.source_memory_id = _visible_text(source_memory_id) or None

    def _keyword_score(self, topic: TopicMemoryTopic, query: str) -> tuple[float, list[str]]:
        if _query_contains_term(query, topic.keyword):
            return 1.0, [topic.keyword]
        for alias in topic.aliases:
            if _query_contains_term(query, alias):
                return 0.9, [alias]
        return 0.0, []

    def _retrieval_score(self, topic: TopicMemoryTopic, query: str) -> tuple[float, list[str]]:
        matched = [term for term in topic.retrieval_terms if _query_contains_term(query, term)]
        if len(matched) < 2:
            return 0.0, []
        return min(0.7, 0.35 + 0.15 * len(matched)), matched

    def _clue_keyword_score(self, clue: TopicMemoryClue | None, query: str) -> float:
        if clue is None:
            return 0.0
        overlap = _tokens(clue.text) & _tokens(query)
        if not overlap:
            return 0.0
        return min(0.5, 0.1 * len(overlap))

    def _metadata_score(self, clue: TopicMemoryClue | None) -> float:
        if clue is None:
            return 0.0
        score = min(0.05, max(0.0, clue.confidence) * 0.05)
        latest_timestamp = clue.history[0].timestamp if clue.history else self.last_updated
        updated_at = _parse_datetime(latest_timestamp)
        if updated_at is not None:
            now = datetime.now(updated_at.tzinfo or timezone.utc)
            if now - updated_at <= timedelta(days=30):
                score += 0.05
        return score

    def _next_topic_id(self) -> str:
        return _next_numbered_id("topic", (topic.id for topic in self.topics))

    def _next_clue_id(self, topic: TopicMemoryTopic) -> str:
        return _next_numbered_id(f"{topic.id}-clue", (clue.id for clue in topic.clues))
