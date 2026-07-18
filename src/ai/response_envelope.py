"""공급자 중립 구조화 응답 스키마와 요청 시점 요구사항."""

from __future__ import annotations

from copy import deepcopy
import json
from dataclasses import dataclass
from typing import Iterable, Sequence

from .analysis_prompt import (
    is_conversation_promise_enabled,
    is_response_analysis_enabled,
    is_schedule_recognition_enabled,
)
from .goal_prompt import is_goal_prompt_enabled
from .prompt_language import resolve_prompt_language, resolve_tts_language
from .response_contract import (
    get_available_proactive_cooldown_keys,
    is_proactive_conversation_enabled,
    is_synthetic_gesture_enabled,
)
from .thought_prompt import is_thought_prompt_enabled


RESPONSE_ENVELOPE_SCHEMA_NAME = "ene_response_envelope_v1"
TOP_LEVEL_FIELDS = (
    "reply",
    "emotion",
    "tts_text",
    "events",
    "analysis",
    "promises",
    "thought",
    "goal_update",
    "proactive_conversations",
    "gesture",
)
ANALYSIS_FIELDS = (
    "user_emotion",
    "user_intent",
    "interaction_effect",
    "bond_delta_hint",
    "stress_delta_hint",
    "energy_delta_hint",
    "valence_delta_hint",
    "confidence",
    "flags",
)


def _string_fields(field_names: Iterable[str]) -> dict[str, dict[str, str]]:
    return {field_name: {"type": "string"} for field_name in field_names}


def _strict_object(properties: dict[str, dict]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_RESPONSE_ENVELOPE_V1_SCHEMA_TEMPLATE = _strict_object(
    {
        "reply": {"type": "string"},
        "emotion": {"type": "string"},
        "tts_text": {"type": "string"},
        "events": {
            "type": "array",
            "items": _strict_object(_string_fields(("date", "title", "description"))),
        },
        "analysis": _strict_object(_string_fields(ANALYSIS_FIELDS)),
        "promises": {
            "type": "array",
            "items": _strict_object(
                _string_fields(("trigger_at", "title", "source", "source_excerpt"))
            ),
        },
        "thought": {"type": "string"},
        "goal_update": _strict_object(
            _string_fields(
                ("action", "type", "id", "title", "reason", "completion_reason")
            )
        ),
        "proactive_conversations": {
            "type": "array",
            "items": _strict_object(
                _string_fields(
                    (
                        "trigger_at",
                        "title",
                        "generation_prompt",
                        "source_excerpt",
                        "reason",
                        "cooldown_key",
                    )
                )
            ),
        },
        "gesture": {"type": "string"},
    }
)

RESPONSE_ENVELOPE_V1_SCHEMA = deepcopy(_RESPONSE_ENVELOPE_V1_SCHEMA_TEMPLATE)


def get_response_envelope_v1_schema() -> dict:
    """런타임 어댑터가 공유 상태를 오염시키지 않도록 새 스키마 복사본을 반환한다."""
    return deepcopy(_RESPONSE_ENVELOPE_V1_SCHEMA_TEMPLATE)


@dataclass(frozen=True)
class ResponseRequirements:
    response_language: str
    tts_language: str
    require_thought: bool
    require_tts_text: bool
    enable_analysis: bool
    enable_events: bool
    enable_promises: bool
    enable_goal_update: bool
    enable_proactive_conversations: bool
    enable_gesture: bool
    allowed_emotions: tuple[str, ...]
    allowed_proactive_cooldown_keys: tuple[str, ...]


def _normalize_emotions(available_emotions: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for emotion in available_emotions:
        value = str(emotion or "").strip().lower()
        if value and value not in seen:
            normalized.append(value)
            seen.add(value)
    return tuple(normalized or ("normal",))


def build_response_requirements(
    settings_source: object | None,
    available_emotions: Iterable[str] = ("normal",),
) -> ResponseRequirements:
    """현재 요청에 사용할 응답 요구사항을 불변 값으로 고정한다."""
    response_language = resolve_prompt_language(settings_source=settings_source)
    tts_language = resolve_tts_language(
        settings_source=settings_source,
        response_language=response_language,
    )
    cooldown_keys = tuple(get_available_proactive_cooldown_keys(settings_source))

    return ResponseRequirements(
        response_language=response_language,
        tts_language=tts_language,
        require_thought=is_thought_prompt_enabled(settings_source),
        require_tts_text=tts_language != response_language,
        enable_analysis=is_response_analysis_enabled(settings_source),
        enable_events=is_schedule_recognition_enabled(settings_source),
        enable_promises=is_conversation_promise_enabled(settings_source),
        enable_goal_update=is_goal_prompt_enabled(settings_source),
        enable_proactive_conversations=(
            is_proactive_conversation_enabled(settings_source) and bool(cooldown_keys)
        ),
        enable_gesture=is_synthetic_gesture_enabled(settings_source),
        allowed_emotions=_normalize_emotions(available_emotions),
        allowed_proactive_cooldown_keys=cooldown_keys,
    )

EVENT_FIELDS = ("date", "title", "description")
PROMISE_FIELDS = ("trigger_at", "title", "source", "source_excerpt")
GOAL_UPDATE_FIELDS = (
    "action",
    "type",
    "id",
    "title",
    "reason",
    "completion_reason",
)
PROACTIVE_CONVERSATION_FIELDS = (
    "trigger_at",
    "title",
    "generation_prompt",
    "source_excerpt",
    "reason",
    "cooldown_key",
)
ALLOWED_GESTURES = ("nod", "bow", "shake", "surprise", "tilt", "sway")

LLM_RESPONSE_TUPLE = tuple[
    str,
    str,
    str | None,
    list[dict],
    dict[str, str],
    list[dict],
    str,
    dict[str, str],
    list[dict],
    str,
]


@dataclass(frozen=True)
class ResponseEnvelopeDecodeResult:
    payload: LLM_RESPONSE_TUPLE | None
    present_fields: frozenset[str]
    missing_required_fields: tuple[str, ...]
    invalid_paths: tuple[str, ...]
    root_error: str = ""

    @property
    def has_valid_reply(self) -> bool:
        return self.payload is not None and bool(self.payload[0].strip())


def _add_invalid(invalid_paths: list[str], path: str) -> None:
    invalid_paths.append(path)


def _normalize_string(value: object, path: str, invalid_paths: list[str]) -> str:
    if not isinstance(value, str):
        _add_invalid(invalid_paths, path)
        return ""
    return value.strip()


def _normalize_object_item(
    value: object,
    *,
    path: str,
    field_names: tuple[str, ...],
    invalid_paths: list[str],
    exact: bool,
) -> tuple[dict[str, str], bool] | None:
    if not isinstance(value, dict):
        _add_invalid(invalid_paths, path)
        return None

    structural_error = False
    allowed = set(field_names)
    if exact:
        for field_name in field_names:
            if field_name not in value:
                _add_invalid(invalid_paths, f"{path}.{field_name}")
                structural_error = True
        if set(value) - allowed:
            _add_invalid(invalid_paths, f"{path}.<extra>")
            structural_error = True

    cleaned: dict[str, str] = {}
    for field_name in field_names:
        if field_name not in value:
            cleaned[field_name] = ""
            continue
        field_value = value[field_name]
        if not isinstance(field_value, str):
            _add_invalid(invalid_paths, f"{path}.{field_name}")
            cleaned[field_name] = ""
            structural_error = True
            continue
        cleaned[field_name] = field_value.strip()
    return cleaned, structural_error


def _normalize_side_effect_items(
    value: object,
    *,
    path: str,
    field_names: tuple[str, ...],
    required_nonempty: tuple[str, ...],
    invalid_paths: list[str],
    exact: bool,
) -> list[tuple[int, dict[str, str]]]:
    if not isinstance(value, list):
        _add_invalid(invalid_paths, path)
        return []

    normalized: list[tuple[int, dict[str, str]]] = []
    for index, item in enumerate(value):
        item_path = f"{path}[{index}]"
        result = _normalize_object_item(
            item,
            path=item_path,
            field_names=field_names,
            invalid_paths=invalid_paths,
            exact=exact,
        )
        if result is None:
            continue
        cleaned, structural_error = result
        missing = [field_name for field_name in required_nonempty if not cleaned[field_name]]
        for field_name in missing:
            _add_invalid(invalid_paths, f"{item_path}.{field_name}")
        if not structural_error and not missing:
            normalized.append((index, cleaned))
    return normalized


def _normalize_analysis(
    value: object,
    invalid_paths: list[str],
    *,
    exact: bool,
) -> dict[str, str]:
    if not isinstance(value, dict):
        _add_invalid(invalid_paths, "analysis")
        return {}

    normalized: dict[str, str] = {}
    allowed = set(ANALYSIS_FIELDS)
    if exact:
        for field_name in ANALYSIS_FIELDS:
            if field_name not in value:
                _add_invalid(invalid_paths, f"analysis.{field_name}")
        if set(value) - allowed:
            _add_invalid(invalid_paths, "analysis.<extra>")

    for field_name in ANALYSIS_FIELDS:
        if field_name not in value:
            continue
        field_value = value[field_name]
        if not isinstance(field_value, str):
            _add_invalid(invalid_paths, f"analysis.{field_name}")
            continue
        cleaned = field_value.strip()
        if cleaned:
            normalized[field_name] = cleaned
    return normalized


def _normalize_goal_update(
    value: object,
    invalid_paths: list[str],
    *,
    preserve_none: bool,
    exact: bool,
) -> dict[str, str]:
    if value in ({}, None) and not exact:
        return {}
    result = _normalize_object_item(
        value,
        path="goal_update",
        field_names=GOAL_UPDATE_FIELDS,
        invalid_paths=invalid_paths,
        exact=exact,
    )
    if result is None:
        return {}
    cleaned, structural_error = result
    if structural_error:
        return {}

    action = cleaned["action"].lower()
    cleaned["action"] = action
    if action not in {"none", "create", "update", "complete", "cancel"}:
        _add_invalid(invalid_paths, "goal_update.action")
        return {}

    goal_type = cleaned["type"].lower()
    cleaned["type"] = goal_type
    if goal_type not in {"", "short_term", "long_term"}:
        _add_invalid(invalid_paths, "goal_update.type")
        return {}

    if action == "none":
        return {"action": "none"} if preserve_none else {}
    if action == "create":
        missing = [name for name in ("type", "title", "reason") if not cleaned[name]]
    elif action == "update":
        missing = [] if cleaned["id"] else ["id"]
        if not cleaned["title"] and not cleaned["reason"]:
            missing.extend(("title", "reason"))
    else:
        missing = [] if cleaned["id"] else ["id"]

    for field_name in missing:
        _add_invalid(invalid_paths, f"goal_update.{field_name}")
    if missing:
        return {}
    if action == "update":
        normalized_update = {"action": action, "id": cleaned["id"]}
        normalized_update.update(
            {
                field_name: cleaned[field_name]
                for field_name in ("title", "reason")
                if cleaned[field_name]
            }
        )
        return normalized_update
    return cleaned


def _normalize_proactive_items(
    value: object,
    invalid_paths: list[str],
    allowed_cooldown_keys: tuple[str, ...],
    *,
    exact: bool,
) -> list[dict[str, str]]:
    candidates = _normalize_side_effect_items(
        value,
        path="proactive_conversations",
        field_names=PROACTIVE_CONVERSATION_FIELDS,
        required_nonempty=("trigger_at", "title", "generation_prompt", "cooldown_key"),
        invalid_paths=invalid_paths,
        exact=exact,
    )
    normalized: list[dict[str, str]] = []
    allowed = set(allowed_cooldown_keys)
    for index, item in candidates:
        item_path = f"proactive_conversations[{index}]"
        if item["cooldown_key"] not in allowed:
            _add_invalid(invalid_paths, f"{item_path}.cooldown_key")
            continue
        if normalized:
            _add_invalid(invalid_paths, item_path)
            continue
        normalized.append(item)
    return normalized


def _normalize_response_tuple(
    payload: Sequence[object],
    requirements: ResponseRequirements,
    invalid_paths: list[str],
    *,
    preserve_none_goal: bool,
    exact_objects: bool,
) -> LLM_RESPONSE_TUPLE:
    if len(payload) != 10:
        raise ValueError("invalid_response_tuple")

    reply = _normalize_string(payload[0], "reply", invalid_paths)
    emotion = _normalize_string(payload[1], "emotion", invalid_paths).lower()
    allowed_emotions = {item.lower() for item in requirements.allowed_emotions}
    if not emotion or emotion not in allowed_emotions:
        _add_invalid(invalid_paths, "emotion")
        emotion = "normal"

    raw_tts_text = payload[2]
    normalized_tts = (
        _normalize_string(raw_tts_text, "tts_text", invalid_paths)
        if exact_objects or requirements.tts_language != requirements.response_language
        else ""
    )
    tts_text: str | None = (
        reply
        if requirements.tts_language == requirements.response_language
        else normalized_tts or None
    )

    event_candidates = (
        _normalize_side_effect_items(
            payload[3],
            path="events",
            field_names=EVENT_FIELDS,
            required_nonempty=("date", "title"),
            invalid_paths=invalid_paths,
            exact=exact_objects,
        )
        if exact_objects or requirements.enable_events
        else []
    )
    events = [item for _index, item in event_candidates] if requirements.enable_events else []

    normalized_analysis = (
        _normalize_analysis(payload[4], invalid_paths, exact=exact_objects)
        if exact_objects or requirements.enable_analysis
        else {}
    )
    analysis = normalized_analysis if requirements.enable_analysis else {}

    promise_candidates = (
        _normalize_side_effect_items(
            payload[5],
            path="promises",
            field_names=PROMISE_FIELDS,
            required_nonempty=("trigger_at", "title"),
            invalid_paths=invalid_paths,
            exact=exact_objects,
        )
        if exact_objects or requirements.enable_promises
        else []
    )
    promises = (
        [item for _index, item in promise_candidates]
        if requirements.enable_promises
        else []
    )

    normalized_thought = (
        _normalize_string(payload[6], "thought", invalid_paths)
        if exact_objects or requirements.require_thought
        else ""
    )
    thought = normalized_thought if requirements.require_thought else ""

    normalized_goal_update = (
        _normalize_goal_update(
            payload[7],
            invalid_paths,
            preserve_none=preserve_none_goal,
            exact=exact_objects,
        )
        if exact_objects or requirements.enable_goal_update
        else {}
    )
    goal_update = normalized_goal_update if requirements.enable_goal_update else {}

    normalized_proactive = (
        _normalize_proactive_items(
            payload[8],
            invalid_paths,
            requirements.allowed_proactive_cooldown_keys,
            exact=exact_objects,
        )
        if exact_objects or requirements.enable_proactive_conversations
        else []
    )
    proactive_conversations = (
        normalized_proactive if requirements.enable_proactive_conversations else []
    )

    gesture_candidate = (
        _normalize_string(payload[9], "gesture", invalid_paths).lower()
        if exact_objects or requirements.enable_gesture
        else ""
    )
    if gesture_candidate and gesture_candidate not in ALLOWED_GESTURES:
        _add_invalid(invalid_paths, "gesture")
    gesture = (
        gesture_candidate
        if requirements.enable_gesture and gesture_candidate in ALLOWED_GESTURES
        else ""
    )
    return (
        reply,
        emotion,
        tts_text,
        events,
        analysis,
        promises,
        thought,
        goal_update,
        proactive_conversations,
        gesture,
    )


def normalize_response_tuple(
    payload: Sequence[object],
    *,
    requirements: ResponseRequirements,
    preserve_none_goal: bool = False,
) -> LLM_RESPONSE_TUPLE:
    """구조화·레거시 응답에 동일한 도메인 정규화 규칙을 적용한다."""
    return _normalize_response_tuple(
        payload,
        requirements,
        [],
        preserve_none_goal=preserve_none_goal,
        exact_objects=False,
    )


def _reject_nonstandard_json_constant(_value: str) -> None:
    raise ValueError("invalid_json_constant")


def decode_response_envelope(
    carrier: str,
    *,
    requirements: ResponseRequirements,
) -> ResponseEnvelopeDecodeResult:
    """JSON envelope에서 유효한 필드만 회수해 기존 응답 튜플로 변환한다."""
    try:
        root = json.loads(carrier, parse_constant=_reject_nonstandard_json_constant)
    except (RecursionError, TypeError, ValueError):
        return ResponseEnvelopeDecodeResult(
            payload=None,
            present_fields=frozenset(),
            missing_required_fields=(),
            invalid_paths=(),
            root_error="invalid_json",
        )

    if not isinstance(root, dict):
        return ResponseEnvelopeDecodeResult(
            payload=None,
            present_fields=frozenset(),
            missing_required_fields=(),
            invalid_paths=(),
            root_error="root_not_object",
        )

    present_fields = frozenset(set(root) & set(TOP_LEVEL_FIELDS))
    invalid_paths: list[str] = []
    for field_name in TOP_LEVEL_FIELDS:
        if field_name not in root:
            _add_invalid(invalid_paths, field_name)
    if set(root) - set(TOP_LEVEL_FIELDS):
        _add_invalid(invalid_paths, "root.<extra>")

    reply_value = root.get("reply")
    if not isinstance(reply_value, str) or not reply_value.strip():
        _add_invalid(invalid_paths, "reply")
        return ResponseEnvelopeDecodeResult(
            payload=None,
            present_fields=present_fields,
            missing_required_fields=(),
            invalid_paths=tuple(sorted(set(invalid_paths))),
            root_error="reply_missing_or_invalid",
        )

    payload = _normalize_response_tuple(
        tuple(root.get(field_name) for field_name in TOP_LEVEL_FIELDS),
        requirements,
        invalid_paths,
        preserve_none_goal=False,
        exact_objects=True,
    )
    missing_required_fields: list[str] = []
    if requirements.require_thought and not payload[6]:
        missing_required_fields.append("thought")
    translation_tts_required = (
        requirements.require_tts_text
        and requirements.tts_language != requirements.response_language
    )
    if translation_tts_required and not payload[2]:
        missing_required_fields.append("tts_text")

    return ResponseEnvelopeDecodeResult(
        payload=payload,
        present_fields=present_fields,
        missing_required_fields=tuple(missing_required_fields),
        invalid_paths=tuple(sorted(set(invalid_paths))),
    )
