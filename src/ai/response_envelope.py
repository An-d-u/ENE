"""공급자 중립 구조화 응답 스키마와 요청 시점 요구사항."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Iterable

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
