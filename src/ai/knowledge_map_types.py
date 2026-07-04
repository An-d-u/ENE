"""주제 기억 지식 지도에서 공유하는 데이터 구조."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
import math
from typing import Any


def _normalize_str(value: Any) -> str:
    return str(value or "").strip()


def _normalize_optional_str(value: Any, *, lower: bool = False) -> str | None:
    text = _normalize_str(value)
    if not text:
        return None
    return text.lower() if lower else text


def _normalize_unique_str_list(value: Any) -> list[str]:
    if value is None:
        raw_items: list[Any] = []
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        text = _normalize_str(item)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(text)
    return normalized


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(confidence):
        return 0.5
    return max(0.0, min(1.0, confidence))


def _filter_dataclass_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    field_names = {field_def.name for field_def in fields(cls)}
    return {name: data.get(name) for name in field_names if name in data}


def _normalize_history_items(value: Any) -> list["TopicMemoryHistoryItem"]:
    if not isinstance(value, list):
        return []

    normalized: list[TopicMemoryHistoryItem] = []
    for item in value:
        if isinstance(item, TopicMemoryHistoryItem):
            normalized.append(item)
        elif isinstance(item, dict):
            normalized.append(TopicMemoryHistoryItem.from_dict(item))
    return normalized


@dataclass
class TopicMemoryHint:
    """LLM 응답에서 추출한 주제 기억 후보."""

    keyword: str
    subject: str
    type: str
    state: str
    text: str
    aliases: list[str] = field(default_factory=list)
    retrieval_terms: list[str] = field(default_factory=list)
    confidence: float = 0.5

    def __post_init__(self) -> None:
        self.keyword = _normalize_str(self.keyword)
        self.subject = _normalize_str(self.subject)
        self.type = _normalize_str(self.type)
        self.state = _normalize_str(self.state)
        self.text = _normalize_str(self.text)
        self.aliases = _normalize_unique_str_list(self.aliases)
        self.retrieval_terms = _normalize_unique_str_list(self.retrieval_terms)
        self.confidence = _clamp_confidence(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "keyword": self.keyword,
            "subject": self.subject,
            "type": self.type,
            "state": self.state,
            "text": self.text,
            "aliases": list(self.aliases),
            "retrieval_terms": list(self.retrieval_terms),
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicMemoryHint":
        return cls(**_filter_dataclass_fields(cls, dict(data or {})))


@dataclass
class TopicMemoryHistoryItem:
    """단서 상태가 바뀐 이력을 표현하는 항목."""

    state: str
    text: str
    timestamp: str | None = None
    confidence: float | None = None
    source_memory_id: str | None = None

    def __post_init__(self) -> None:
        self.state = _normalize_str(self.state)
        self.text = _normalize_str(self.text)
        self.timestamp = _normalize_optional_str(self.timestamp)
        self.source_memory_id = _normalize_optional_str(self.source_memory_id)
        if self.confidence is not None:
            self.confidence = _clamp_confidence(self.confidence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "text": self.text,
            "timestamp": self.timestamp,
            "confidence": self.confidence,
            "source_memory_id": self.source_memory_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicMemoryHistoryItem":
        return cls(**_filter_dataclass_fields(cls, dict(data or {})))


@dataclass
class TopicMemoryClue:
    """특정 주제 안에서 검색과 병합에 쓰는 기억 단서."""

    id: str
    subject: str
    type: str
    state: str
    text: str
    confidence: float = 0.5
    source_memory_id: str | None = None
    embedding: list[float] | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    history: list[TopicMemoryHistoryItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.id = _normalize_str(self.id)
        self.subject = _normalize_str(self.subject)
        self.type = _normalize_str(self.type)
        self.state = _normalize_str(self.state)
        self.text = _normalize_str(self.text)
        self.confidence = _clamp_confidence(self.confidence)
        self.source_memory_id = _normalize_optional_str(self.source_memory_id)
        self.embedding_provider = _normalize_optional_str(self.embedding_provider, lower=True)
        self.embedding_model = _normalize_optional_str(self.embedding_model)
        self.history = _normalize_history_items(self.history)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "subject": self.subject,
            "type": self.type,
            "state": self.state,
            "text": self.text,
            "confidence": self.confidence,
            "source_memory_id": self.source_memory_id,
            "embedding": list(self.embedding) if self.embedding is not None else None,
            "embedding_provider": self.embedding_provider,
            "embedding_model": self.embedding_model,
            "history": [item.to_dict() for item in self.history],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicMemoryClue":
        return cls(**_filter_dataclass_fields(cls, dict(data or {})))


@dataclass
class TopicMemoryTopic:
    """하나의 주제와 그 아래에 묶인 기억 단서 목록."""

    id: str
    keyword: str
    clues: list[TopicMemoryClue] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    retrieval_terms: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.id = _normalize_str(self.id)
        self.keyword = _normalize_str(self.keyword)
        self.aliases = _normalize_unique_str_list(self.aliases)
        self.retrieval_terms = _normalize_unique_str_list(self.retrieval_terms)
        self.clues = [
            clue if isinstance(clue, TopicMemoryClue) else TopicMemoryClue.from_dict(clue)
            for clue in self.clues
            if isinstance(clue, (TopicMemoryClue, dict))
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "keyword": self.keyword,
            "clues": [clue.to_dict() for clue in self.clues],
            "aliases": list(self.aliases),
            "retrieval_terms": list(self.retrieval_terms),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicMemoryTopic":
        return cls(**_filter_dataclass_fields(cls, dict(data or {})))


@dataclass
class TopicMemorySearchResult:
    """주제 기억 검색 결과."""

    topic: TopicMemoryTopic
    clue: TopicMemoryClue | None = None
    score: float = 0.0
    matched_terms: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.topic, dict):
            self.topic = TopicMemoryTopic.from_dict(self.topic)
        if isinstance(self.clue, dict):
            self.clue = TopicMemoryClue.from_dict(self.clue)
        self.score = _clamp_confidence(self.score)
        self.matched_terms = _normalize_unique_str_list(self.matched_terms)

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic.to_dict(),
            "clue": self.clue.to_dict() if self.clue is not None else None,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TopicMemorySearchResult":
        return cls(**_filter_dataclass_fields(cls, dict(data or {})))
