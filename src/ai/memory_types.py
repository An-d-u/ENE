"""
장기기억 데이터 구조
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any
import re


CURRENT_MEMORY_SCHEMA_VERSION = 3
LEGACY_MIGRATION_VERSION = 1

_PREFERENCE_PATTERNS = ("좋아", "선호", "편해", "익숙", "싫어", "자주")
_PROMISE_PATTERNS = ("말해줘", "기억해줘", "리마인드", "까먹지", "알려줘")
_EVENT_PATTERNS = ("일정", "예약", "회의", "약속", "날짜", "시간", "내일", "오늘", "주말")
_TASK_PATTERNS = ("해야", "할 일", "정리해야", "비교해", "작업", "TODO", "todo", "하고 싶")
_RELATIONSHIP_PATTERNS = ("호칭", "친밀", "관계", "성격", "애칭")


def _now_iso() -> str:
    """현재 시각을 로컬 타임존 ISO 문자열로 반환한다."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_str_list(value: Any) -> list[str]:
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


def _normalize_role(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text or "unknown"


_ASSISTANT_STRONG_CUES = (
    "마스터",
    "괜찮으신",
    "부탁드려요",
    "도와드릴게요",
    "알려드릴게요",
    "죄송해요",
)
_ASSISTANT_POLITE_ENDINGS = (
    "요",
    "니다",
    "이에요",
    "예요",
    "세요",
    "군요",
    "네요",
    "까요",
)
_USER_STRONG_CUES = (
    "에네",
    "안녕",
    "응",
    "그래",
    "고마워",
    "미안",
    "해줘",
    "말이야",
    "거든",
)
_USER_CASUAL_ENDINGS = (
    "어",
    "아",
    "야",
    "지",
    "네",
    "냐",
    "래",
    "까",
    "거야",
    "같아",
    "없어",
    "있어",
)


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"[\n\r]+|(?<=[.!?])\s+", str(text or "").strip())
    return [part.strip(" \"'“”‘’") for part in parts if part.strip(" \"'“”‘’")]


def _score_legacy_message_role(text: str) -> tuple[float, float]:
    """레거시 문자열 메시지의 화자를 존댓말/반말 경향으로 점수화한다."""
    normalized = str(text or "").strip()
    if not normalized:
        return 0.0, 0.0

    assistant_score = 0.0
    user_score = 0.0
    lowered = normalized.lower()

    for cue in _ASSISTANT_STRONG_CUES:
        if cue in normalized:
            assistant_score += 3.0

    for cue in _USER_STRONG_CUES:
        if cue in normalized:
            user_score += 2.0

    for sentence in _split_sentences(normalized):
        trimmed = sentence.rstrip("...~!?,. ")
        for ending in _ASSISTANT_POLITE_ENDINGS:
            if trimmed.endswith(ending):
                assistant_score += 1.5
                break
        for ending in _USER_CASUAL_ENDINGS:
            if trimmed.endswith(ending):
                user_score += 1.2
                break

        if re.search(r"(할게|줄게|볼게|갈게|할까|줄래|싶어|됐어|맞아|좋아|싫어|없어|있어)$", trimmed):
            user_score += 1.5
        if re.search(r"(할게요|드릴게요|볼까요|주세요|있어요|없어요|맞아요|좋아요|같아요)$", trimmed):
            assistant_score += 1.5

    if "마스터" in normalized and "에네" not in normalized:
        assistant_score += 1.0
    if "에네" in normalized and "마스터" not in normalized:
        user_score += 0.8
    if "?" in normalized or "?" in lowered:
        user_score += 0.2

    return assistant_score, user_score


def _infer_legacy_message_roles(raw_items: list[Any]) -> list[str]:
    """레거시 문자열 메시지 리스트의 화자를 순서와 말투를 기준으로 추정한다."""
    texts = [str(item or "").strip() for item in raw_items]
    roles: list[str | None] = []

    for text in texts:
        assistant_score, user_score = _score_legacy_message_role(text)
        if assistant_score > user_score:
            roles.append("assistant")
        elif user_score > assistant_score:
            roles.append("user")
        else:
            roles.append(None)

    resolved: list[str | None] = []
    previous_role: str | None = None

    for index, role in enumerate(roles):
        next_explicit_role = next(
            (candidate for candidate in roles[index + 1 :] if candidate is not None),
            None,
        )
        if role == "user" and previous_role == "user":
            role = "assistant"
        elif role is None:
            if previous_role == "user":
                role = "assistant"
            elif previous_role == "assistant":
                role = "user" if next_explicit_role == "assistant" else "assistant"
            elif index == 0:
                role = "user"
            elif next_explicit_role == "assistant":
                role = "user"
        resolved.append(role)
        if role is not None:
            previous_role = role

    if any(role is None for role in resolved):
        for index, role in enumerate(resolved):
            if role is not None:
                continue
            if index == 0:
                resolved[index] = "user"
            else:
                prev = resolved[index - 1]
                resolved[index] = "assistant" if prev in {"user", "assistant"} else "user"

    return [str(role) for role in resolved]


def _needs_legacy_role_reinference(raw_items: list[Any], fallback_conversation_id: str) -> bool:
    """이미 객체로 저장된 레거시 unknown 메시지들인지 판별한다."""
    if not raw_items:
        return False
    if not str(fallback_conversation_id or "").startswith("legacy-"):
        return False

    saw_message_like = False
    for item in raw_items:
        if isinstance(item, MemoryMessage):
            saw_message_like = True
            if _normalize_role(item.role) != "unknown":
                return False
        elif isinstance(item, dict):
            saw_message_like = True
            if _normalize_role(item.get("role")) != "unknown":
                return False
        else:
            return False
    return saw_message_like


@dataclass(eq=False)
class MemoryMessage:
    """원문 메시지 1건."""

    role: str
    text: str
    timestamp: str
    conversation_id: str
    turn_index: int

    @classmethod
    def from_value(
        cls,
        value: Any,
        *,
        fallback_timestamp: str,
        fallback_conversation_id: str,
        fallback_turn_index: int,
    ) -> tuple["MemoryMessage", bool]:
        """다양한 입력을 표준 메시지 구조로 정규화한다."""
        if isinstance(value, cls):
            return (
                cls(
                    role=_normalize_role(value.role),
                    text=str(value.text or "").strip(),
                    timestamp=str(value.timestamp or fallback_timestamp).strip() or fallback_timestamp,
                    conversation_id=str(value.conversation_id or fallback_conversation_id).strip() or fallback_conversation_id,
                    turn_index=int(value.turn_index),
                ),
                False,
            )

        if isinstance(value, dict):
            turn_index_value = value.get("turn_index", fallback_turn_index)
            try:
                turn_index = int(turn_index_value)
            except (TypeError, ValueError):
                turn_index = fallback_turn_index
            return (
                cls(
                    role=_normalize_role(value.get("role")),
                    text=str(value.get("text", "")).strip(),
                    timestamp=str(value.get("timestamp") or fallback_timestamp).strip() or fallback_timestamp,
                    conversation_id=str(value.get("conversation_id") or fallback_conversation_id).strip() or fallback_conversation_id,
                    turn_index=turn_index,
                ),
                False,
            )

        return (
            cls(
                role="unknown",
                text=str(value or "").strip(),
                timestamp=fallback_timestamp,
                conversation_id=fallback_conversation_id,
                turn_index=fallback_turn_index,
            ),
            True,
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MemoryMessage):
            return (
                self.role == other.role
                and self.text == other.text
                and self.timestamp == other.timestamp
                and self.conversation_id == other.conversation_id
                and self.turn_index == other.turn_index
            )
        if isinstance(other, str):
            return self.text == other
        if isinstance(other, dict):
            return self.to_dict() == other
        return NotImplemented

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(eq=False)
class MemoryChunk:
    """원문 회상에 사용하는 chunk 1건."""

    memory_id: str
    conversation_id: str
    start_turn_index: int
    end_turn_index: int
    text: str
    messages: list[MemoryMessage] = field(default_factory=list)
    embedding: list[float] | None = None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, MemoryChunk):
            return (
                self.memory_id == other.memory_id
                and self.conversation_id == other.conversation_id
                and self.start_turn_index == other.start_turn_index
                and self.end_turn_index == other.end_turn_index
                and self.text == other.text
                and self.messages == other.messages
                and self.embedding == other.embedding
            )
        return NotImplemented


def _normalize_original_messages(
    value: Any,
    *,
    fallback_timestamp: str,
    fallback_conversation_id: str,
) -> tuple[list[MemoryMessage], bool]:
    raw_items = value if isinstance(value, list) else ([] if value is None else [value])
    normalized: list[MemoryMessage] = []
    used_legacy_strings = False

    if raw_items and all(not isinstance(item, (dict, MemoryMessage)) for item in raw_items):
        inferred_roles = _infer_legacy_message_roles(raw_items)
        for index, item in enumerate(raw_items):
            text = str(item or "").strip()
            if not text:
                continue
            normalized.append(
                MemoryMessage(
                    role=inferred_roles[index],
                    text=text,
                    timestamp=fallback_timestamp,
                    conversation_id=fallback_conversation_id,
                    turn_index=index,
                )
            )
        return normalized, True

    if _needs_legacy_role_reinference(raw_items, fallback_conversation_id):
        inferred_roles = _infer_legacy_message_roles(
            [
                item.text if isinstance(item, MemoryMessage) else item.get("text", "")
                for item in raw_items
            ]
        )
        for index, item in enumerate(raw_items):
            if isinstance(item, MemoryMessage):
                text = str(item.text or "").strip()
                timestamp = str(item.timestamp or fallback_timestamp).strip() or fallback_timestamp
                conversation_id = str(item.conversation_id or fallback_conversation_id).strip() or fallback_conversation_id
                turn_index = int(item.turn_index)
            else:
                text = str(item.get("text", "")).strip()
                timestamp = str(item.get("timestamp") or fallback_timestamp).strip() or fallback_timestamp
                conversation_id = str(item.get("conversation_id") or fallback_conversation_id).strip() or fallback_conversation_id
                try:
                    turn_index = int(item.get("turn_index", index))
                except (TypeError, ValueError):
                    turn_index = index
            if not text:
                continue
            normalized.append(
                MemoryMessage(
                    role=inferred_roles[index],
                    text=text,
                    timestamp=timestamp,
                    conversation_id=conversation_id,
                    turn_index=turn_index,
                )
            )
        return normalized, True

    for index, item in enumerate(raw_items):
        message, is_legacy_string = MemoryMessage.from_value(
            item,
            fallback_timestamp=fallback_timestamp,
            fallback_conversation_id=fallback_conversation_id,
            fallback_turn_index=index,
        )
        if message.text:
            normalized.append(message)
        used_legacy_strings = used_legacy_strings or is_legacy_string

    return normalized, used_legacy_strings


def _message_texts(messages: list[MemoryMessage]) -> list[str]:
    return [message.text for message in messages if str(message.text or "").strip()]


def _extract_entity_names(summary: str, original_messages: list[MemoryMessage], tags: list[str]) -> list[str]:
    """요약/원문/태그에서 보수적으로 엔티티 이름을 추출한다."""
    candidates: list[str] = []
    seen: set[str] = set()
    combined = "\n".join([summary, *_message_texts(original_messages), " ".join(tags)])

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


def _infer_memory_type(summary: str, original_messages: list[MemoryMessage], tags: list[str]) -> str:
    combined = "\n".join([summary, *_message_texts(original_messages), " ".join(tags)]).lower()

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
    """단일 기억 항목."""

    id: str
    summary: str
    original_messages: list[MemoryMessage]
    timestamp: str
    is_important: bool = False
    embedding: list[float] | None = None
    tags: list[str] = field(default_factory=list)
    source: str = "legacy"
    memory_type: str = "general"
    importance_reason: str = "none"
    retrieval_count: int = 0
    last_used_at: str | None = None
    confidence: float = 0.5
    user_confirmed: bool | None = None
    entity_names: list[str] = field(default_factory=list)
    conversation_id: str | None = None
    expires_at: str | None = None
    schema_version: int = CURRENT_MEMORY_SCHEMA_VERSION
    migration_meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        fallback_timestamp = str(self.timestamp or "").strip() or _now_iso()
        fallback_conversation_id = str(
            self.conversation_id or f"legacy-{self.id or 'memory'}"
        ).strip() or f"legacy-{self.id or 'memory'}"
        self.timestamp = fallback_timestamp
        self.original_messages, _ = _normalize_original_messages(
            self.original_messages,
            fallback_timestamp=fallback_timestamp,
            fallback_conversation_id=fallback_conversation_id,
        )
        self.tags = _normalize_str_list(self.tags)
        self.entity_names = _normalize_str_list(self.entity_names)
        self.confidence = _clamp_confidence(self.confidence)
        self.schema_version = max(int(self.schema_version or 0), CURRENT_MEMORY_SCHEMA_VERSION)
        self.conversation_id = (
            str(self.conversation_id).strip()
            if self.conversation_id is not None and str(self.conversation_id).strip()
            else (self.original_messages[0].conversation_id if self.original_messages else None)
        )

    def to_dict(self) -> dict[str, Any]:
        """딕셔너리로 변환한다."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEntry":
        """딕셔너리에서 복원한다."""
        normalized = dict(data or {})
        inferred_fields: list[str] = []
        field_names = {field_def.name for field_def in fields(cls)}

        summary = str(normalized.get("summary", "")).strip()
        timestamp = str(normalized.get("timestamp", "")).strip() or _now_iso()
        memory_id = str(normalized.get("id", "")).strip() or "legacy-memory"
        fallback_conversation_id = str(
            normalized.get("conversation_id") or f"legacy-{memory_id}"
        ).strip() or f"legacy-{memory_id}"

        original_messages, used_legacy_strings = _normalize_original_messages(
            normalized.get("original_messages"),
            fallback_timestamp=timestamp,
            fallback_conversation_id=fallback_conversation_id,
        )
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

        normalized_conversation_id = str(normalized.get("conversation_id") or "").strip()
        if not normalized_conversation_id:
            normalized["conversation_id"] = original_messages[0].conversation_id if original_messages else None
            if normalized["conversation_id"]:
                inferred_fields.append("conversation_id")
        else:
            normalized["conversation_id"] = normalized_conversation_id

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
        if used_legacy_strings:
            migration_meta = {
                **migration_meta,
                "legacy_original_messages": True,
                "inferred_message_fields": [
                    "role",
                    "timestamp",
                    "conversation_id",
                    "turn_index",
                ],
            }
        if schema_version < CURRENT_MEMORY_SCHEMA_VERSION or inferred_fields or used_legacy_strings:
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

        normalized["id"] = memory_id
        normalized["summary"] = summary
        normalized["original_messages"] = original_messages
        normalized["tags"] = tags
        normalized["embedding"] = normalized.get("embedding")
        normalized["timestamp"] = timestamp

        filtered = {name: normalized.get(name) for name in field_names}
        return cls(**filtered)

    def __repr__(self) -> str:
        important = "*" if self.is_important else ""
        return f"{important}[{self.timestamp}] {self.summary[:50]}..."


def create_memory_entry(
    summary: str,
    original_messages: list[Any],
    is_important: bool = False,
    embedding: list[float] | None = None,
    tags: list[str] | None = None,
    source: str = "chat",
    memory_type: str = "general",
    importance_reason: str | None = None,
    confidence: float | None = None,
    entity_names: list[str] | None = None,
) -> MemoryEntry:
    """새 기억 항목을 생성한다."""
    import uuid

    normalized_tags = tags or []
    normalized_memory_type = str(memory_type or "general").strip() or "general"
    resolved_importance_reason = importance_reason or (
        "user_marked"
        if is_important
        else _default_importance_reason(is_important=False, memory_type=normalized_memory_type)
    )
    resolved_confidence = _clamp_confidence(
        confidence if confidence is not None else _default_confidence(is_important, normalized_memory_type)
    )
    memory_id = str(uuid.uuid4())
    timestamp = datetime.now().astimezone().isoformat(timespec="seconds")
    fallback_conversation_id = f"legacy-{memory_id}"
    normalized_original_messages, used_legacy_strings = _normalize_original_messages(
        original_messages,
        fallback_timestamp=timestamp,
        fallback_conversation_id=fallback_conversation_id,
    )
    resolved_entity_names = _normalize_str_list(entity_names)
    if not resolved_entity_names:
        resolved_entity_names = _extract_entity_names(summary, normalized_original_messages, normalized_tags)
    conversation_id = normalized_original_messages[0].conversation_id if normalized_original_messages else None
    migration_meta: dict[str, Any] = {}
    if used_legacy_strings:
        migration_meta = {
            "legacy_original_messages": True,
            "inferred_message_fields": [
                "role",
                "timestamp",
                "conversation_id",
                "turn_index",
            ],
        }

    return MemoryEntry(
        id=memory_id,
        summary=summary,
        original_messages=normalized_original_messages,
        timestamp=timestamp,
        is_important=is_important,
        embedding=embedding,
        tags=normalized_tags,
        source=str(source or "chat").strip() or "chat",
        memory_type=normalized_memory_type,
        importance_reason=resolved_importance_reason,
        confidence=resolved_confidence,
        entity_names=resolved_entity_names,
        conversation_id=conversation_id,
        schema_version=CURRENT_MEMORY_SCHEMA_VERSION,
        migration_meta=migration_meta,
    )
