"""비활성 생활 기록의 순수 타입, 파서, 검증 도우미."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Iterable, Mapping

from src.core.local_time import LocalTimeContext, resolve_local_time_context


_OUTPUT_FIELDS = frozenset({"entries", "ending_state"})
_ENTRY_FIELDS = frozenset({"started_at", "ended_at", "place", "activity"})
_ENDING_FIELDS = frozenset({"place", "summary"})
_STORE_FIELDS = frozenset({"version", "records"})
_RECORD_FIELDS = frozenset(
    {
        "id",
        "inactive_started_at",
        "returned_at",
        "created_at",
        "updated_at",
        "revision",
        "timezone",
        "inactive_start_source",
        "mood_snapshot",
        "entries",
        "ending_state",
    }
)
_MOOD_FIELDS = frozenset(
    {"label", "valence", "energy", "bond", "stress", "short_term_mood"}
)
_MOOD_AXES = ("valence", "energy", "bond", "stress")
_INACTIVE_SOURCES = frozenset({"graceful_exit", "heartbeat_recovery"})
_JSON_FENCE = re.compile(r"\A```(?:json)?\s*\n(?P<body>.*)\n```\s*\Z", re.DOTALL)


class LifeRecordValidationError(ValueError):
    """외부 입력의 안정적인 오류 코드만 노출한다."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LifeRecordEntry:
    started_at: datetime
    ended_at: datetime
    place: str
    activity: str


@dataclass(frozen=True)
class LifeRecordEndingState:
    place: str
    summary: str


@dataclass(frozen=True)
class LifeRecordOutput:
    entries: tuple[LifeRecordEntry, ...]
    ending_state: LifeRecordEndingState


@dataclass(frozen=True)
class LifeRecord:
    id: str
    inactive_started_at: datetime
    returned_at: datetime
    created_at: datetime
    updated_at: datetime
    revision: int
    timezone: str
    inactive_start_source: str
    mood_snapshot: Mapping[str, object]
    entries: tuple[LifeRecordEntry, ...]
    ending_state: Mapping[str, str]


def _fail(code: str) -> None:
    raise LifeRecordValidationError(code)


def _strict_fields(value: object, expected: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, dict):
        _fail("invalid_object")
    keys = set(value)
    if keys - expected:
        _fail("extra_field")
    if expected - keys:
        _fail("missing_field")
    return value


def _non_empty_text(value: object) -> str:
    if not isinstance(value, str):
        _fail("invalid_text")
    stripped = value.strip()
    if not stripped:
        _fail("invalid_text")
    return stripped


def _time_context(timezone_name: object) -> LocalTimeContext:
    if not isinstance(timezone_name, str):
        _fail("invalid_timezone")
    resolution = resolve_local_time_context(timezone_name)
    if resolution.context is None:
        _fail("invalid_timezone")
    return resolution.context


def _parse_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            _fail("invalid_datetime")
    else:
        _fail("invalid_datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        _fail("invalid_datetime")
    return parsed


def _validated_endpoint(
    value: object,
    context: LocalTimeContext,
    *,
    allow_fractional: bool,
) -> datetime:
    parsed = _parse_datetime(value)
    if not allow_fractional and parsed.microsecond:
        _fail("invalid_datetime")
    if not context.matches_zone_rules(parsed):
        _fail("invalid_timezone_offset")
    return context.canonicalize_endpoint(parsed)


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _canonical_utc_second(value: datetime) -> datetime:
    parsed = _parse_datetime(value)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _utc_second_z(value: datetime) -> str:
    return _canonical_utc_second(value).strftime("%Y-%m-%dT%H:%M:%SZ")


def stable_life_record_id(inactive_started_at: datetime, returned_at: datetime) -> str:
    """구간의 UTC 정수 초 표현으로 안정적인 식별자를 만든다."""

    canonical = f"{_utc_second_z(inactive_started_at)}|{_utc_second_z(returned_at)}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _ending_state(value: object) -> LifeRecordEndingState:
    data = _strict_fields(value, _ENDING_FIELDS)
    return LifeRecordEndingState(
        place=_non_empty_text(data["place"]),
        summary=_non_empty_text(data["summary"]),
    )


def _entries(
    value: object,
    context: LocalTimeContext,
    *,
    allow_fractional: bool,
) -> tuple[LifeRecordEntry, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= 24:
        _fail("invalid_entries")
    parsed: list[LifeRecordEntry] = []
    for raw_entry in value:
        data = _strict_fields(raw_entry, _ENTRY_FIELDS)
        start = _validated_endpoint(
            data["started_at"], context, allow_fractional=allow_fractional
        )
        end = _validated_endpoint(
            data["ended_at"], context, allow_fractional=allow_fractional
        )
        if _utc(start) >= _utc(end):
            _fail("invalid_range")
        parsed.append(
            LifeRecordEntry(
                started_at=start,
                ended_at=end,
                place=_non_empty_text(data["place"]),
                activity=_non_empty_text(data["activity"]),
            )
        )
    return tuple(parsed)


def _validate_output_interval(
    entries: tuple[LifeRecordEntry, ...],
    ending_state: LifeRecordEndingState,
    start: datetime,
    end: datetime,
) -> None:
    if _utc(start) >= _utc(end):
        _fail("invalid_range")
    if _utc(entries[0].started_at) != _utc(start):
        _fail("out_of_range")
    if _utc(entries[-1].ended_at) != _utc(end):
        _fail("out_of_range")
    for left, right in zip(entries, entries[1:]):
        left_end = _utc(left.ended_at)
        right_start = _utc(right.started_at)
        if left_end < right_start:
            _fail("gap")
        if left_end > right_start:
            _fail("overlap")
    if entries[-1].place != ending_state.place:
        _fail("invalid_ending_state")


def _decode_model_json(raw_json: object) -> dict[str, object]:
    if not isinstance(raw_json, str):
        _fail("invalid_json")
    candidate = raw_json.strip()
    match = _JSON_FENCE.fullmatch(candidate)
    if match:
        candidate = match.group("body")
    try:
        value = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        _fail("invalid_json")
    if not isinstance(value, dict):
        _fail("invalid_json")
    return value


def parse_and_validate_life_record_output(
    raw_json: str,
    *,
    inactive_started_at: datetime,
    returned_at: datetime,
    timezone_name: str,
) -> LifeRecordOutput:
    """모델 JSON 출력만 파싱하고 호스트 구간에 정확히 맞는지 검증한다."""

    context = _time_context(timezone_name)
    start = _validated_endpoint(inactive_started_at, context, allow_fractional=True)
    end = _validated_endpoint(returned_at, context, allow_fractional=True)
    data = _strict_fields(_decode_model_json(raw_json), _OUTPUT_FIELDS)
    entries = _entries(data["entries"], context, allow_fractional=True)
    ending_state = _ending_state(data["ending_state"])
    _validate_output_interval(entries, ending_state, start, end)
    return LifeRecordOutput(entries=entries, ending_state=ending_state)


def _mood_snapshot(value: object) -> Mapping[str, object]:
    data = _strict_fields(value, _MOOD_FIELDS)
    copied: dict[str, object] = {
        "label": _non_empty_text(data["label"]),
        "short_term_mood": _non_empty_text(data["short_term_mood"]),
    }
    for field in _MOOD_AXES:
        number = data[field]
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            _fail("invalid_mood")
        if not math.isfinite(number):
            _fail("invalid_mood")
        copied[field] = number
    return MappingProxyType(copied)


def create_life_record(
    *,
    id: object,
    inactive_started_at: object,
    returned_at: object,
    created_at: object,
    updated_at: object,
    revision: object,
    timezone: object,
    inactive_start_source: object,
    mood_snapshot: object,
    entries: object,
    ending_state: object,
) -> LifeRecord:
    """역직렬화된 호스트 필드로 완전히 검증된 불변 기록을 만든다."""

    context = _time_context(timezone)
    start = _validated_endpoint(inactive_started_at, context, allow_fractional=False)
    end = _validated_endpoint(returned_at, context, allow_fractional=False)
    created = _validated_endpoint(created_at, context, allow_fractional=False)
    updated = _validated_endpoint(updated_at, context, allow_fractional=False)
    parsed_entries = _entries(entries, context, allow_fractional=False)
    parsed_ending = _ending_state(ending_state)
    _validate_output_interval(parsed_entries, parsed_ending, start, end)
    if _utc(start) >= _utc(end) or _utc(created) > _utc(updated):
        _fail("invalid_range")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
        _fail("invalid_revision")
    if (
        not isinstance(inactive_start_source, str)
        or inactive_start_source not in _INACTIVE_SOURCES
    ):
        _fail("invalid_source")
    expected_id = stable_life_record_id(start, end)
    if not isinstance(id, str) or id != expected_id:
        _fail("invalid_id")
    frozen_ending = MappingProxyType(
        {"place": parsed_ending.place, "summary": parsed_ending.summary}
    )
    return LifeRecord(
        id=id,
        inactive_started_at=start,
        returned_at=end,
        created_at=created,
        updated_at=updated,
        revision=revision,
        timezone=context.timezone_name,
        inactive_start_source=inactive_start_source,
        mood_snapshot=_mood_snapshot(mood_snapshot),
        entries=parsed_entries,
        ending_state=frozen_ending,
    )


def parse_life_record_store(raw: str) -> tuple[LifeRecord, ...]:
    """저장소 envelope와 모든 호스트 레코드를 strict 역직렬화한다."""

    if not isinstance(raw, str):
        _fail("invalid_store")
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        _fail("invalid_store")
    if not isinstance(decoded, dict):
        _fail("invalid_store")
    data = _strict_fields(decoded, _STORE_FIELDS)
    if type(data["version"]) is not int or data["version"] != 1:
        _fail("invalid_store")
    raw_records = data["records"]
    if not isinstance(raw_records, list):
        _fail("invalid_store")
    records: list[LifeRecord] = []
    seen: set[str] = set()
    for raw_record in raw_records:
        fields = _strict_fields(raw_record, _RECORD_FIELDS)
        record = create_life_record(**fields)
        if record.id in seen:
            _fail("duplicate_id")
        seen.add(record.id)
        records.append(record)
    return tuple(records)


def _entry_to_dict(entry: LifeRecordEntry) -> dict[str, object]:
    return {
        "started_at": entry.started_at.isoformat(timespec="seconds"),
        "ended_at": entry.ended_at.isoformat(timespec="seconds"),
        "place": entry.place,
        "activity": entry.activity,
    }


def life_record_to_dict(record: LifeRecord) -> dict[str, object]:
    """불변 레코드를 JSON 직렬화 가능한 새 객체로 변환한다."""

    return {
        "id": record.id,
        "inactive_started_at": record.inactive_started_at.isoformat(timespec="seconds"),
        "returned_at": record.returned_at.isoformat(timespec="seconds"),
        "created_at": record.created_at.isoformat(timespec="seconds"),
        "updated_at": record.updated_at.isoformat(timespec="seconds"),
        "revision": record.revision,
        "timezone": record.timezone,
        "inactive_start_source": record.inactive_start_source,
        "mood_snapshot": dict(record.mood_snapshot),
        "entries": [_entry_to_dict(entry) for entry in record.entries],
        "ending_state": dict(record.ending_state),
    }


def life_record_store_to_dict(records: Iterable[LifeRecord]) -> dict[str, object]:
    """Task 4가 그대로 저장할 수 있는 버전 envelope를 만든다."""

    return {"version": 1, "records": [life_record_to_dict(record) for record in records]}
