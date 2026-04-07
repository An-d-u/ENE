"""
장기기억 데이터 구조
"""
from dataclasses import dataclass, field, asdict, fields
from datetime import datetime
from typing import List, Optional, Dict, Any
import re


CURRENT_MEMORY_SCHEMA_VERSION = 2
LEGACY_MIGRATION_VERSION = 1

_PREFERENCE_PATTERNS = ("좋아", "선호", "편해", "익숙", "싫어", "자주")
_PROMISE_PATTERNS = ("말해줘", "기억해줘", "리마인드", "까먹지", "알려줘")
_EVENT_PATTERNS = ("일정", "예약", "회의", "약속", "날짜", "시간", "내일", "오늘", "주말")
_TASK_PATTERNS = ("해야", "할 일", "정리해야", "비교해", "작업", "TODO", "todo", "하고 싶")
_RELATIONSHIP_PATTERNS = ("호칭", "친밀", "관계", "성격", "애칭")


def _now_iso() -> str:
    """현재 시각을 로컬 타임존 ISO 문자열로 반환한다."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_str_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def _clamp_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _extract_entity_names(summary: str, original_messages: List[str], tags: List[str]) -> List[str]:
    """요약/원문/태그에서 보수적으로 엔티티 이름을 추출한다."""
    candidates: List[str] = []
    seen: set[str] = set()
    combined = "\n".join([summary, *original_messages, " ".join(tags)])

    for match in re.findall(r"[A-Z][A-Za-z0-9_.-]{1,}", combined):
        normalized = match.strip()
        key = normalized.casefold()
        if key not in seen:
            seen.add(key)
            candidates.append(normalized)

    for tag in tags:
        normalized = str(tag).strip()
        if not normalized:
            continue
        if re.search(r"[A-Z]", normalized):
            key = normalized.casefold()
            if key not in seen:
                seen.add(key)
                candidates.append(normalized)

    return candidates


def _infer_memory_type(summary: str, original_messages: List[str], tags: List[str]) -> str:
    combined = "\n".join([summary, *original_messages, " ".join(tags)]).lower()

    if any(pattern in combined for pattern in _PROMISE_PATTERNS):
        return "promise"
    if any(pattern in combined for pattern in _PREFERENCE_PATTERNS):
        return "preference"
    if any(pattern in combined for pattern in _EVENT_PATTERNS):
        return "event"
    if any(pattern in combined for pattern in _TASK_PATTERNS):
        return "task"
    if any(pattern in combined for pattern in _RELATIONSHIP_PATTERNS):
        return "relationship"
    if summary.strip():
        return "fact"
    return "general"


def _default_importance_reason(is_important: bool, memory_type: str) -> str:
    if memory_type == "promise":
        return "promise"
    if is_important:
        return "legacy_important"
    return "none"


def _default_confidence(is_important: bool, memory_type: str) -> float:
    if memory_type == "promise":
        return 0.7
    if is_important:
        return 0.6
    return 0.5


@dataclass
class MemoryEntry:
    """단일 기억 항목"""
    id: str
    summary: str
    original_messages: List[str]
    timestamp: str  # ISO format
    is_important: bool = False
    embedding: Optional[List[float]] = None
    tags: List[str] = field(default_factory=list)
    source: str = "legacy"
    memory_type: str = "general"
    importance_reason: str = "none"
    retrieval_count: int = 0
    last_used_at: Optional[str] = None
    confidence: float = 0.5
    user_confirmed: Optional[bool] = None
    entity_names: List[str] = field(default_factory=list)
    conversation_id: Optional[str] = None
    expires_at: Optional[str] = None
    schema_version: int = CURRENT_MEMORY_SCHEMA_VERSION
    migration_meta: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환 (JSON 저장용)"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MemoryEntry':
        """딕셔너리에서 복원"""
        normalized = dict(data or {})
        inferred_fields: List[str] = []
        field_names = {field_def.name for field_def in fields(cls)}

        summary = str(normalized.get("summary", "")).strip()
        original_messages = _normalize_str_list(normalized.get("original_messages"))
        tags = _normalize_str_list(normalized.get("tags"))
        is_important = bool(normalized.get("is_important", False))

        if "source" not in normalized or not str(normalized.get("source", "")).strip():
            normalized["source"] = "legacy"

        if "memory_type" not in normalized or not str(normalized.get("memory_type", "")).strip():
            normalized["memory_type"] = _infer_memory_type(summary, original_messages, tags)
            inferred_fields.append("memory_type")

        if "importance_reason" not in normalized or not str(normalized.get("importance_reason", "")).strip():
            normalized["importance_reason"] = _default_importance_reason(
                is_important=is_important,
                memory_type=str(normalized["memory_type"]),
            )
            inferred_fields.append("importance_reason")

        if "retrieval_count" not in normalized:
            normalized["retrieval_count"] = 0

        if "last_used_at" not in normalized:
            normalized["last_used_at"] = None

        if "confidence" not in normalized:
            normalized["confidence"] = _default_confidence(
                is_important=is_important,
                memory_type=str(normalized["memory_type"]),
            )
            inferred_fields.append("confidence")
        normalized["confidence"] = _clamp_confidence(normalized.get("confidence"))

        if "user_confirmed" not in normalized:
            normalized["user_confirmed"] = None

        if "entity_names" not in normalized:
            normalized["entity_names"] = _extract_entity_names(summary, original_messages, tags)
            if normalized["entity_names"]:
                inferred_fields.append("entity_names")
        else:
            normalized["entity_names"] = _normalize_str_list(normalized.get("entity_names"))

        if "conversation_id" not in normalized:
            normalized["conversation_id"] = None

        if "expires_at" not in normalized:
            normalized["expires_at"] = None

        raw_schema_version = normalized.get("schema_version", 0)
        try:
            schema_version = int(raw_schema_version)
        except (TypeError, ValueError):
            schema_version = 0
        normalized["schema_version"] = max(schema_version, CURRENT_MEMORY_SCHEMA_VERSION)

        migration_meta = normalized.get("migration_meta")
        if not isinstance(migration_meta, dict):
            migration_meta = {}
        if schema_version < CURRENT_MEMORY_SCHEMA_VERSION or inferred_fields:
            existing_inferred = migration_meta.get("inferred_fields")
            combined_inferred = _normalize_str_list(existing_inferred)
            for field_name in inferred_fields:
                if field_name not in combined_inferred:
                    combined_inferred.append(field_name)
            migration_meta = {
                **migration_meta,
                "migrated_at": migration_meta.get("migrated_at") or _now_iso(),
                "migration_version": migration_meta.get("migration_version", LEGACY_MIGRATION_VERSION),
                "inferred_fields": combined_inferred,
            }
        normalized["migration_meta"] = migration_meta

        normalized["summary"] = summary
        normalized["original_messages"] = original_messages
        normalized["tags"] = tags
        normalized["embedding"] = normalized.get("embedding")
        normalized["timestamp"] = str(normalized.get("timestamp", "")).strip() or _now_iso()

        filtered = {name: normalized.get(name) for name in field_names}
        return cls(**filtered)
    
    def __repr__(self) -> str:
        important = "⭐" if self.is_important else ""
        return f"{important}[{self.timestamp}] {self.summary[:50]}..."


def create_memory_entry(
    summary: str,
    original_messages: List[str],
    is_important: bool = False,
    embedding: Optional[List[float]] = None,
    tags: Optional[List[str]] = None,
    source: str = "chat",
    memory_type: str = "general",
    importance_reason: Optional[str] = None,
    confidence: Optional[float] = None,
    entity_names: Optional[List[str]] = None,
) -> MemoryEntry:
    """새 기억 항목 생성"""
    import uuid

    normalized_tags = tags or []
    normalized_memory_type = str(memory_type or "general").strip() or "general"
    resolved_importance_reason = importance_reason or (
        "user_marked" if is_important else _default_importance_reason(is_important=False, memory_type=normalized_memory_type)
    )
    resolved_confidence = _clamp_confidence(
        confidence if confidence is not None else _default_confidence(is_important, normalized_memory_type)
    )
    resolved_entity_names = _normalize_str_list(entity_names)
    if not resolved_entity_names:
        resolved_entity_names = _extract_entity_names(summary, original_messages, normalized_tags)

    return MemoryEntry(
        id=str(uuid.uuid4()),
        summary=summary,
        original_messages=original_messages,
        timestamp=datetime.now().isoformat(),
        is_important=is_important,
        embedding=embedding,
        tags=normalized_tags,
        source=str(source or "chat").strip() or "chat",
        memory_type=normalized_memory_type,
        importance_reason=resolved_importance_reason,
        confidence=resolved_confidence,
        entity_names=resolved_entity_names,
        schema_version=CURRENT_MEMORY_SCHEMA_VERSION,
    )
