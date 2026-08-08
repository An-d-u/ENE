"""개인정보 경계를 고정한 생활 기록 생성 프롬프트를 만든다."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
from typing import Literal, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_MOOD_SOURCE_FIELDS = frozenset(
    {"current_mood", "temporary_state", "valence", "energy", "bond", "stress"}
)
_MOOD_LABELS = frozenset(
    {"calm", "tense", "sensitive", "tired", "affectionate", "cheerful"}
)
_SHORT_TERM_MOODS = frozenset(
    {"steady", "guarded", "pout", "drained", "playful", "focused"}
)
_LANGUAGES = frozenset({"ko", "en", "ja"})
_PROFILE_FACT_CATEGORIES = frozenset(
    {"basic", "preference", "goal", "habit", "relationship_tone"}
)


class LifeWorldEmptyError(ValueError):
    """생활 환경이 비어 LLM 호출을 시작할 수 없음을 나타낸다."""


@dataclass(frozen=True, repr=False)
class LifeMoodSnapshot:
    label: str
    valence: float
    energy: float
    bond: float
    stress: float
    short_term_mood: str


@dataclass(frozen=True, repr=False)
class LifeRecordGenerationContext:
    inactive_started_at: datetime
    returned_at: datetime
    timezone: str
    inactive_start_source: str
    world_markdown: str
    ene_identity: dict[str, object]
    relationship_tone: object
    profile_facts: tuple[dict[str, object], ...]
    display_names: dict[str, str]
    previous_record: dict[str, object] | None
    mood_snapshot: LifeMoodSnapshot
    language: Literal["ko", "en", "ja"]


def _mood_code(value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str):
        raise ValueError("invalid_mood_code")
    code = value.strip().lower()
    if code not in allowed:
        raise ValueError("invalid_mood_code")
    return code


def _mood_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_mood_number")
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ValueError("invalid_mood_number") from None
    if not math.isfinite(number):
        raise ValueError("invalid_mood_number")
    return number


def snapshot_life_mood(raw_snapshot: Mapping[str, object]) -> LifeMoodSnapshot:
    """전용 여섯 필드만 검증해 불변 생활 기록 기분으로 복사한다."""

    if not isinstance(raw_snapshot, Mapping) or set(raw_snapshot) != _MOOD_SOURCE_FIELDS:
        raise ValueError("invalid_mood_fields")
    return LifeMoodSnapshot(
        label=_mood_code(raw_snapshot["current_mood"], _MOOD_LABELS),
        valence=_mood_number(raw_snapshot["valence"]),
        energy=_mood_number(raw_snapshot["energy"]),
        bond=_mood_number(raw_snapshot["bond"]),
        stress=_mood_number(raw_snapshot["stress"]),
        short_term_mood=_mood_code(
            raw_snapshot["temporary_state"], _SHORT_TERM_MOODS
        ),
    )


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"unsupported prompt value: {type(value).__name__}")


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=_json_default,
    )


def _validated_interval(context: LifeRecordGenerationContext) -> tuple[datetime, datetime]:
    if context.language not in _LANGUAGES:
        raise ValueError("invalid_language")
    try:
        zone = ZoneInfo(context.timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValueError("invalid_timezone") from None
    start = context.inactive_started_at
    end = context.returned_at
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or end.tzinfo is None
        or start.utcoffset() is None
        or end.utcoffset() is None
        or start.astimezone(timezone.utc) >= end.astimezone(timezone.utc)
    ):
        raise ValueError("invalid_interval")
    return start.astimezone(zone), end.astimezone(zone)


def _granularity(start: datetime, end: datetime) -> str:
    elapsed = end.astimezone(timezone.utc) - start.astimezone(timezone.utc)
    if elapsed.total_seconds() <= 24 * 60 * 60:
        return "1일 이하는 활동을 30분에서 수시간 단위로 나눈다."
    if elapsed.total_seconds() <= 7 * 24 * 60 * 60:
        return "1일 초과 7일 이하는 활동을 수시간에서 하루 단위로 묶는다."
    return "7일 초과는 반복 생활을 여러 날 단위로 요약한다."


def _text_items(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        return ()
    return tuple(str(item).strip() for item in values if str(item).strip())


def _profile_facts(value: object) -> tuple[dict[str, str], ...]:
    if not isinstance(value, tuple):
        return ()
    exported: list[dict[str, str]] = []
    for fact in value:
        if not isinstance(fact, Mapping):
            continue
        category = str(fact.get("category", "")).strip()
        content = str(fact.get("content", "")).strip()
        if category in _PROFILE_FACT_CATEGORIES and content:
            exported.append({"category": category, "content": content})
    return tuple(exported)


def build_life_record_prompt(context: LifeRecordGenerationContext) -> str:
    """화이트리스트 DTO만 사용해 생활 기록 전용 user prompt를 만든다."""

    world = str(context.world_markdown or "")
    if not world.strip():
        raise LifeWorldEmptyError("life_world_empty")
    local_start, local_end = _validated_interval(context)
    language_rule = {
        "ko": "activity와 ending_state의 자연어 값은 한국어로 작성한다.",
        "en": "Write natural-language values in activity and ending_state in English.",
        "ja": "activityとending_stateの自然言語値は日本語で書く。",
    }[context.language]
    previous_record = (
        context.previous_record if context.previous_record is not None else None
    )
    identity = context.ene_identity.get("identity", ())
    prompt_context = {
        "display_names": {
            key: str(context.display_names.get(key, "")).strip()
            for key in ("assistant", "user")
        },
        "ene_identity": {"identity": _text_items(identity)},
        "inactive_interval": {
            "inactive_started_at": context.inactive_started_at.isoformat(),
            "returned_at": context.returned_at.isoformat(),
            "timezone": context.timezone,
            "inactive_start_source": context.inactive_start_source,
            "local_start": f"{local_start.isoformat()} ({local_start.strftime('%A')})",
            "local_end": f"{local_end.isoformat()} ({local_end.strftime('%A')})",
            "local_start_date": f"{local_start.date().isoformat()} ({local_start.strftime('%A')})",
            "local_end_date": f"{local_end.date().isoformat()} ({local_end.strftime('%A')})",
        },
        "relationship_tone": _text_items(context.relationship_tone),
        "profile_facts": _profile_facts(context.profile_facts),
        "previous_record": previous_record,
        "mood_snapshot": asdict(context.mood_snapshot),
        "language": context.language,
    }
    return f"""[생활 기록 생성 작업]
아래 생활 환경 안에서 에네의 비활성 구간 생활 기록을 생성한다.
현재 생활 환경이 직전 기록과 충돌하면 현재 생활 환경을 우선한다.
직전 기록을 그대로 복사하지 말고 같은 행동의 불필요한 반복을 피한다.

[허용된 생성 컨텍스트]
{_json(prompt_context)}

[현재 생활 환경 전체]
{world}

[시간과 복귀 사실]
- 사용자는 inactive_started_at부터 returned_at 직전까지 돌아오지 않았다.
- 사용자의 복귀를 확인하는 행동은 returned_at 전에 배치하지 않는다.
- 첫 entry의 started_at부터 마지막 entry의 ended_at까지 전체 비활성 구간을 빠짐없이 덮는다.
- entry 사이에는 공백이나 겹침이 없어야 하며, 시간은 ISO 8601 오프셋 포함 형식으로 쓴다.
- {_granularity(local_start, local_end)}
- entries는 최대 24개다. 제한을 넘길 것 같으면 구간을 버리지 말고 시간 단위를 넓힌다.

[출력 계약]
- {language_rule}
- Markdown이나 설명 없이 JSON 객체 하나만 출력한다.
- 최상위 키는 entries와 ending_state만 허용한다.
- entries의 각 항목은 started_at, ended_at, place, activity만 가진다.
- ending_state는 place와 summary만 가지며 마지막 entry의 place와 같아야 한다.
"""
