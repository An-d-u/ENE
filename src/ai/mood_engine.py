from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import math
import uuid
from typing import Any


EVENT_KINDS = (
    "neutral",
    "connection",
    "success",
    "loss",
    "threat",
    "conflict",
    "novelty",
    "repair",
)
TARGET_SCOPES = ("user", "ene", "relationship", "external", "unknown")
RELATION_CATEGORIES = ("none", "broken_commitment", "disrespect", "boundary_violation")
CLARITIES = ("explicit", "inferred", "ambiguous")
CERTAINTIES = ("low", "medium", "high")
CONTROLLABILITIES = ("low", "medium", "high")
REPAIR_SIGNALS = (
    "none",
    "acknowledgment",
    "apology",
    "explanation",
    "correction",
    "follow_through",
)
AFFECTS = (
    "joy",
    "tenderness",
    "amusement",
    "interest",
    "sadness",
    "hurt",
    "anger",
    "anxiety",
)

PRESET_BASELINES = {
    "calm": {"valence": 0.0, "energy": 0.0, "tension": 0.0},
    "balanced": {"valence": 0.0, "energy": 0.0, "tension": 0.0},
    "expressive": {"valence": 0.0, "energy": 0.0, "tension": 0.0},
}

_PRESET_ALIASES = {
    "calm": "calm",
    "affectionate": "balanced",
    "balanced": "balanced",
    "playful": "expressive",
    "expressive": "expressive",
}
_STATE_FIELDS = {
    "version",
    "revision",
    "preset",
    "updated_at_utc",
    "background",
    "relationship",
    "active_affects",
    "ruptures",
    "recent_event_ids",
    "spontaneous",
}
_ACTIVE_AFFECT_FIELDS = {
    "affect",
    "intensity",
    "source_kind",
    "target_scope",
    "relation_category",
    "repeat_count",
    "last_event_at_utc",
    "updated_at_utc",
}
_RUPTURE_FIELDS = {
    "category",
    "severity",
    "heat",
    "repair_stage",
    "repeat_count",
    "repair_evidence_count",
    "last_negative_at_utc",
    "updated_at_utc",
}


@dataclass(frozen=True)
class MoodEvent:
    event_id: str
    occurred_at_utc: datetime
    kind: str
    target_scope: str
    relation_category: str
    intensity: int
    clarity: str
    certainty: str
    controllability: str
    repair_signal: str


def normalize_preset(preset: object) -> str:
    if not isinstance(preset, str):
        return "balanced"
    return _PRESET_ALIASES.get(preset.strip().lower(), "balanced")


def format_utc(value: datetime) -> str:
    _require_utc_datetime(value, "시각")
    return value.isoformat(timespec="seconds")


def new_mood_state(now_utc: datetime, preset: str) -> dict[str, Any]:
    normalized_preset = normalize_preset(preset)
    return {
        "version": 3,
        "revision": 0,
        "preset": normalized_preset,
        "updated_at_utc": format_utc(now_utc),
        "background": dict(PRESET_BASELINES[normalized_preset]),
        "relationship": {"affection": 0.0, "trust": 0.0},
        "active_affects": [],
        "ruptures": [],
        "recent_event_ids": [],
        "spontaneous": {"last_at_utc": None, "seed_revision": 0},
    }


def normalize_event(raw: object, now_utc: datetime) -> MoodEvent:
    _require_utc_datetime(now_utc, "사건 시각")
    data = raw if isinstance(raw, Mapping) else {}
    event_id = data.get("event_id")
    valid_id = _is_uuid_v4(event_id)
    if not valid_id:
        event_id = _fallback_event_id(event_id, now_utc)
    else:
        event_id = str(uuid.UUID(str(event_id)))

    repair_signal = data.get("repair_signal")
    repair_context_is_valid = repair_signal == "none" or (
        data.get("kind") == "repair"
        and data.get("target_scope") == "relationship"
        and data.get("relation_category") in RELATION_CATEGORIES[1:]
    )

    valid = (
        valid_id
        and data.get("kind") in EVENT_KINDS
        and data.get("target_scope") in TARGET_SCOPES
        and data.get("relation_category") in RELATION_CATEGORIES
        and _is_int(data.get("intensity"), minimum=0, maximum=3)
        and data.get("clarity") in CLARITIES
        and data.get("certainty") in CERTAINTIES
        and data.get("controllability") in CONTROLLABILITIES
        and repair_signal in REPAIR_SIGNALS
        and repair_context_is_valid
    )
    if not valid:
        return MoodEvent(
            event_id=str(event_id),
            occurred_at_utc=now_utc,
            kind="neutral",
            target_scope="unknown",
            relation_category="none",
            intensity=0,
            clarity="ambiguous",
            certainty="low",
            controllability="low",
            repair_signal="none",
        )

    return MoodEvent(
        event_id=str(event_id),
        occurred_at_utc=now_utc,
        kind=str(data["kind"]),
        target_scope=str(data["target_scope"]),
        relation_category=str(data["relation_category"]),
        intensity=int(data["intensity"]),
        clarity=str(data["clarity"]),
        certainty=str(data["certainty"]),
        controllability=str(data["controllability"]),
        repair_signal=str(data["repair_signal"]),
    )


def validate_state(state: object) -> dict[str, Any]:
    if not isinstance(state, Mapping) or set(state) != _STATE_FIELDS:
        raise ValueError("기분 상태 필드가 올바르지 않습니다.")

    validated = deepcopy(dict(state))
    if type(validated["version"]) is not int or validated["version"] != 3:
        raise ValueError("지원하지 않는 기분 상태 버전입니다.")
    _require_int(validated["revision"], "revision", minimum=0)
    if validated["preset"] not in PRESET_BASELINES:
        raise ValueError("기분 프리셋이 올바르지 않습니다.")
    _parse_utc_string(validated["updated_at_utc"], "updated_at_utc")

    _validate_number_mapping(validated["background"], ("valence", "energy", "tension"), -1.0, 1.0)
    _validate_number_mapping(validated["relationship"], ("affection", "trust"), -1.0, 1.0)
    _validate_active_affects(validated["active_affects"])
    _validate_ruptures(validated["ruptures"])
    _validate_recent_event_ids(validated["recent_event_ids"])
    _validate_spontaneous(validated["spontaneous"])
    return validated


def _validate_active_affects(value: object) -> None:
    items = _require_list(value, "active_affects", maximum=5)
    for item in items:
        if not isinstance(item, Mapping) or set(item) != _ACTIVE_AFFECT_FIELDS:
            raise ValueError("활성 정서 흔적 필드가 올바르지 않습니다.")
        if item["affect"] not in AFFECTS or item["source_kind"] not in EVENT_KINDS:
            raise ValueError("활성 정서 종류가 올바르지 않습니다.")
        if item["target_scope"] not in TARGET_SCOPES:
            raise ValueError("활성 정서 대상이 올바르지 않습니다.")
        if item["relation_category"] not in RELATION_CATEGORIES:
            raise ValueError("활성 정서 관계 분류가 올바르지 않습니다.")
        _require_number(item["intensity"], "활성 정서 강도", 0.0, 1.0)
        _require_int(item["repeat_count"], "반복 횟수", 0, 3)
        _parse_utc_string(item["last_event_at_utc"], "마지막 사건 시각")
        _parse_utc_string(item["updated_at_utc"], "정서 갱신 시각")


def _validate_ruptures(value: object) -> None:
    items = _require_list(value, "ruptures", maximum=3)
    categories: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping) or set(item) != _RUPTURE_FIELDS:
            raise ValueError("관계 균열 필드가 올바르지 않습니다.")
        category = item["category"]
        if category not in RELATION_CATEGORIES[1:] or category in categories:
            raise ValueError("관계 균열 분류가 올바르지 않습니다.")
        categories.add(str(category))
        _require_number(item["severity"], "균열 심각도", 0.0, 1.0)
        _require_number(item["heat"], "균열 열기", 0.0, 1.0)
        if item["repair_stage"] not in {"open", "acknowledged", "observing"}:
            raise ValueError("회복 단계가 올바르지 않습니다.")
        _require_int(item["repeat_count"], "균열 반복 횟수", 0, 3)
        _require_int(item["repair_evidence_count"], "회복 증거 횟수", 0, 2)
        _parse_utc_string(item["last_negative_at_utc"], "마지막 관계 손상 시각")
        _parse_utc_string(item["updated_at_utc"], "균열 갱신 시각")


def _validate_recent_event_ids(value: object) -> None:
    items = _require_list(value, "recent_event_ids", maximum=64)
    if any(not _is_uuid_v4(item) for item in items):
        raise ValueError("최근 사건 ID는 UUIDv4여야 합니다.")
    if len(items) != len(set(items)):
        raise ValueError("최근 사건 ID는 중복될 수 없습니다.")


def _validate_spontaneous(value: object) -> None:
    if not isinstance(value, Mapping) or set(value) != {"last_at_utc", "seed_revision"}:
        raise ValueError("자발 변화 상태가 올바르지 않습니다.")
    if value["last_at_utc"] is not None:
        _parse_utc_string(value["last_at_utc"], "마지막 자발 변화 시각")
    _require_int(value["seed_revision"], "자발 변화 revision", minimum=0)


def _validate_number_mapping(value: object, keys: tuple[str, ...], minimum: float, maximum: float) -> None:
    if not isinstance(value, Mapping) or set(value) != set(keys):
        raise ValueError("수치 상태 필드가 올바르지 않습니다.")
    for key in keys:
        _require_number(value[key], key, minimum, maximum)


def _require_list(value: object, name: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{name} 배열이 올바르지 않습니다.")
    return value


def _require_number(value: object, name: str, minimum: float, maximum: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 값은 숫자여야 합니다.")
    numeric = float(value)
    if not math.isfinite(numeric) or not minimum <= numeric <= maximum:
        raise ValueError(f"{name} 값이 허용 범위를 벗어났습니다.")


def _is_int(value: object, minimum: int, maximum: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and minimum <= value <= maximum


def _require_int(value: object, name: str, minimum: int, maximum: int | None = None) -> None:
    upper = value if maximum is None else maximum
    if not _is_int(value, minimum, upper):
        raise ValueError(f"{name} 값은 정수 범위여야 합니다.")


def _require_utc_datetime(value: object, name: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(None):
        raise ValueError(f"{name}은 UTC aware datetime이어야 합니다.")


def _parse_utc_string(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{name}은 UTC 문자열이어야 합니다.")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{name} 형식이 올바르지 않습니다.") from exc
    _require_utc_datetime(parsed, name)
    return parsed


def _is_uuid_v4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError):
        return False
    return parsed.version == 4 and str(parsed) == value.lower()


def _fallback_event_id(value: object, now_utc: datetime) -> str:
    material = f"ene-mood-invalid:{value!r}:{format_utc(now_utc)}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))
