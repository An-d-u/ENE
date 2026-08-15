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

HALF_LIFE_SECONDS = {
    "very_short": 600,
    "short": 3600,
    "medium": 21600,
    "long": 86400,
}
AFFECT_HALF_LIFE_CLASS = {
    "joy": "short",
    "tenderness": "medium",
    "amusement": "very_short",
    "interest": "short",
    "sadness": "long",
    "hurt": "long",
    "anger": "medium",
    "anxiety": "medium",
}

PRESET_BASELINES = {
    "calm": {"valence": 0.0, "energy": 0.0, "tension": 0.0},
    "balanced": {"valence": 0.0, "energy": 0.0, "tension": 0.0},
    "expressive": {"valence": 0.0, "energy": 0.0, "tension": 0.0},
}

INTENSITY_WEIGHT = {0: 0.0, 1: 0.45, 2: 0.75, 3: 1.0}
CLARITY_WEIGHT = {"explicit": 1.0, "inferred": 0.75, "ambiguous": 0.35}
CERTAINTY_WEIGHT = {"low": 0.5, "medium": 0.75, "high": 1.0}
PRESET_WEIGHT = {"calm": 0.75, "balanced": 1.0, "expressive": 1.25}
RELATION_REPEAT_WEIGHT = {0: 1.00, 1: 0.85, 2: 0.70, 3: 0.55}

BACKGROUND_HALF_LIFE_SECONDS = {
    "valence": 12 * 3600,
    "energy": 4 * 3600,
    "tension": 6 * 3600,
}
SPONTANEOUS_COOLDOWN_SECONDS = 6 * 3600
SPONTANEOUS_THRESHOLD = 0.92

RELATION_CONNECTION_BASE = {
    "connection": {"affection": 0.018, "trust": 0.010},
    "success": {"affection": 0.006, "trust": 0.012},
}
RELATION_CONFLICT_BASE = {
    "broken_commitment": {"affection": -0.008, "trust": -0.040},
    "disrespect": {"affection": -0.025, "trust": -0.015},
    "boundary_violation": {"affection": -0.020, "trust": -0.030},
}
RELATION_REPAIR_BASE = {
    "acknowledgment": {"affection": 0.000, "trust": 0.004},
    "apology": {"affection": 0.006, "trust": 0.008},
    "explanation": {"affection": 0.000, "trust": 0.004},
    "correction": {"affection": 0.004, "trust": 0.012},
    "follow_through": {"affection": 0.006, "trust": 0.016},
}

RUPTURE_CATEGORY_BASE = {
    "broken_commitment": 0.18,
    "disrespect": 0.16,
    "boundary_violation": 0.20,
}
RUPTURE_REPAIR_DECREASE = {
    "acknowledgment": {"heat": 0.04, "severity": 0.01},
    "apology": {"heat": 0.08, "severity": 0.06},
    "explanation": {"heat": 0.03, "severity": 0.02},
    "correction": {"heat": 0.03, "severity": 0.04},
    "follow_through": {"heat": 0.04, "severity": 0.06},
}

BACKGROUND_BASE = {
    "neutral": (0.00, 0.00, 0.00),
    "connection": (0.03, 0.01, -0.02),
    "success": (0.04, 0.03, -0.01),
    "loss": (-0.05, -0.03, 0.02),
    "threat": (-0.03, 0.01, 0.06),
    "conflict": (-0.04, 0.02, 0.07),
    "novelty": (0.01, 0.04, 0.01),
    "repair": (0.02, 0.00, -0.03),
}

AFFECT_BASE = {
    "connection": {"tenderness": 0.18, "joy": 0.06},
    "success": {"joy": 0.22},
    "loss": {"sadness": 0.24},
    "threat": {"anxiety": 0.25},
    "conflict": {"anger": 0.22, "hurt": 0.16},
    "novelty": {"interest": 0.22, "amusement": 0.06},
    "repair": {"tenderness": 0.12},
}

_AFFECT_ORDER = {affect: index for index, affect in enumerate(AFFECTS)}

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


@dataclass(frozen=True)
class MoodTransition:
    state: dict[str, Any]
    applied: bool
    rule_ids: tuple[str, ...]


def affect_half_life_seconds(affect: str) -> int:
    return HALF_LIFE_SECONDS[AFFECT_HALF_LIFE_CLASS[affect]]


def normalize_preset(preset: object) -> str:
    if not isinstance(preset, str):
        return "balanced"
    return _PRESET_ALIASES.get(preset.strip().lower(), "balanced")


def format_utc(value: datetime) -> str:
    _require_utc_datetime(value, "시각")
    timespec = "microseconds" if value.microsecond else "seconds"
    return value.isoformat(timespec=timespec)


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
    preset = validated["preset"]
    if not isinstance(preset, str) or preset not in PRESET_BASELINES:
        raise ValueError("기분 프리셋이 올바르지 않습니다.")
    _parse_utc_string(validated["updated_at_utc"], "updated_at_utc")

    _validate_number_mapping(validated["background"], ("valence", "energy", "tension"), -1.0, 1.0)
    _validate_number_mapping(validated["relationship"], ("affection", "trust"), -1.0, 1.0)
    _validate_active_affects(validated["active_affects"])
    _validate_ruptures(validated["ruptures"])
    _validate_recent_event_ids(validated["recent_event_ids"])
    _validate_spontaneous(validated["spontaneous"])
    return validated


def advance_time(state: object, now_utc: datetime, preset: str) -> MoodTransition:
    """실제 UTC 경과시간만큼 상태를 결정론적으로 전진시킵니다."""
    validated = validate_state(state)
    _require_utc_datetime(now_utc, "시간 전진 시각")
    previous_at = _parse_utc_string(validated["updated_at_utc"], "updated_at_utc")
    if now_utc <= previous_at:
        return MoodTransition(state=validated, applied=False, rule_ids=())

    rule_ids = _advance_time_in_place(validated, now_utc, preset)
    validated["revision"] += 1
    return MoodTransition(
        state=validate_state(validated),
        applied=True,
        rule_ids=tuple(rule_ids),
    )


def derive_snapshot(state: object, previous_primary: object = None) -> dict[str, object]:
    """저장 상태를 바꾸지 않고 현재 감정과 행동 지침을 파생합니다."""
    validated = validate_state(state)
    strengths = {affect: 0.0 for affect in AFFECTS}
    for trace in validated["active_affects"]:
        affect = trace["affect"]
        strengths[affect] = max(strengths[affect], float(trace["intensity"]))

    ranked = sorted(AFFECTS, key=lambda affect: (-strengths[affect], _AFFECT_ORDER[affect]))
    candidate = ranked[0] if strengths[ranked[0]] >= 0.16 else None
    primary = candidate
    if (
        candidate is not None
        and isinstance(previous_primary, str)
        and previous_primary in strengths
        and strengths[previous_primary] >= 0.16
        and _at_or_below(strengths[candidate] - strengths[previous_primary], 0.04)
    ):
        primary = previous_primary

    secondary = None
    if primary is not None:
        for affect in ranked:
            if affect == primary:
                continue
            intensity = strengths[affect]
            if intensity >= 0.14 and intensity >= strengths[primary] * 0.75:
                secondary = affect
            break

    return {
        "state": deepcopy(validated),
        "primary_emotion": primary,
        "secondary_emotion": secondary,
        "behavior_guidance": derive_behavior_guidance(validated, "ko"),
    }


def derive_behavior_guidance(state: object, language: str) -> tuple[str, ...]:
    """수치나 사건 원문을 노출하지 않는 최소 행동 지침을 파생합니다."""
    validated = validate_state(state)
    selected_language = (
        language if isinstance(language, str) and language in {"ko", "en", "ja"} else "ko"
    )
    messages = {
        "ko": {
            "rupture": "열린 관계 균열이 강하므로 단정하지 말고 차분하게 확인합니다.",
            "energy": "에너지가 낮으므로 짧고 부담이 적은 표현을 사용합니다.",
            "relationship": "관계 온도가 낮으므로 친밀함을 전제하지 않고 존중하는 거리를 둡니다.",
            "safety": "안전 안내, 중지나 취소, 권한 철회, 위험 작업 확인은 mood보다 항상 우선합니다.",
        },
        "en": {
            "rupture": "A strong open rupture calls for calm clarification without assumptions.",
            "energy": "Low energy calls for brief, low-pressure phrasing.",
            "relationship": "Low relational warmth calls for respectful distance without assumed intimacy.",
            "safety": "Safety guidance, stopping or cancellation, permission withdrawal, and hazardous-action confirmation always override mood.",
        },
        "ja": {
            "rupture": "強い未解決の関係亀裂があるため、決めつけず落ち着いて確認します。",
            "energy": "エネルギーが低いため、短く負担の少ない表現を使います。",
            "relationship": "関係の温度が低いため、親密さを前提にせず敬意ある距離を保ちます。",
            "safety": "安全案内、停止や取消、権限の撤回、危険作業の確認は常にmoodより優先します。",
        },
    }
    text = messages[selected_language]
    guidance: list[str] = []
    strong_open_rupture = any(
        rupture["repair_stage"] == "open"
        and max(float(rupture["severity"]), float(rupture["heat"])) >= 0.5
        for rupture in validated["ruptures"]
    )
    if strong_open_rupture:
        guidance.append(text["rupture"])
    if float(validated["background"]["energy"]) <= -0.35:
        guidance.append(text["energy"])
    warmth = (
        float(validated["relationship"]["affection"])
        + float(validated["relationship"]["trust"])
    ) / 2.0
    if warmth <= -0.35:
        guidance.append(text["relationship"])
    guidance.append(text["safety"])
    return tuple(guidance)


def reduce_mood(
    previous_state: object,
    event: object,
    now_utc: datetime,
    preset: str,
) -> MoodTransition:
    state = validate_state(previous_state)
    duplicate_event_id = _extract_canonical_event_id(event)
    if duplicate_event_id is not None and duplicate_event_id in state["recent_event_ids"]:
        return MoodTransition(state=state, applied=False, rule_ids=("event.duplicate",))

    normalized_event = _coerce_event(event, now_utc)
    if normalized_event.event_id in state["recent_event_ids"]:
        return MoodTransition(state=state, applied=False, rule_ids=("event.duplicate",))

    _require_utc_datetime(now_utc, "사건 적용 시각")
    if now_utc < _parse_utc_string(state["updated_at_utc"], "updated_at_utc"):
        raise ValueError("사건 적용 시각은 상태 갱신 시각보다 빠를 수 없습니다.")

    normalized_preset = normalize_preset(preset)
    rule_ids: list[str] = []
    if now_utc > _parse_utc_string(state["updated_at_utc"], "updated_at_utc"):
        rule_ids.extend(_advance_time_in_place(state, now_utc, normalized_preset))
    impact = (
        INTENSITY_WEIGHT[normalized_event.intensity]
        * CLARITY_WEIGHT[normalized_event.clarity]
        * CERTAINTY_WEIGHT[normalized_event.certainty]
        * PRESET_WEIGHT[normalized_preset]
    )
    repeat_count = _next_repeat_count(state, normalized_event, now_utc)
    relationship_impact = impact * RELATION_REPEAT_WEIGHT[repeat_count]
    if impact != 0.0 and any(BACKGROUND_BASE[normalized_event.kind]):
        _apply_background(state, normalized_event.kind, impact)
        rule_ids.append("event.background")

    if impact != 0.0 and AFFECT_BASE.get(normalized_event.kind):
        _apply_affects(state, normalized_event, now_utc, impact)
        rule_ids.append("event.affect")

    relation_base = _relationship_base(normalized_event)
    if relationship_impact != 0.0 and relation_base is not None:
        _apply_relationship(state, relation_base, relationship_impact)
        rule_ids.append("event.relationship")

    if _apply_rupture(
        state,
        normalized_event,
        now_utc,
        relationship_impact,
    ):
        rule_ids.append("event.rupture")

    if len(state["active_affects"]) > 5:
        _trim_active_affects(state["active_affects"])
        rule_ids.append("state.active_affects.limit")

    state["preset"] = normalized_preset
    state["updated_at_utc"] = format_utc(now_utc)
    state["revision"] += 1
    state["recent_event_ids"] = [*state["recent_event_ids"], normalized_event.event_id][-64:]
    rule_ids.append("event.recorded")
    return MoodTransition(state=validate_state(state), applied=True, rule_ids=tuple(rule_ids))


def _advance_time_in_place(state: dict[str, Any], now_utc: datetime, preset: str) -> list[str]:
    previous_at = _parse_utc_string(state["updated_at_utc"], "updated_at_utc")
    elapsed_seconds = (now_utc - previous_at).total_seconds()
    normalized_preset = normalize_preset(preset)
    rule_ids: list[str] = []

    background_changed = False
    for field, half_life in BACKGROUND_HALF_LIFE_SECONDS.items():
        current = float(state["background"][field])
        target = float(PRESET_BASELINES[normalized_preset][field])
        decayed = target + (current - target) * 2 ** (-elapsed_seconds / half_life)
        state["background"][field] = decayed
        background_changed = background_changed or decayed != current
    if background_changed:
        rule_ids.append("time.background")

    if state["active_affects"]:
        surviving = []
        for trace in state["active_affects"]:
            decayed = float(trace["intensity"]) * 2 ** (
                -elapsed_seconds / affect_half_life_seconds(trace["affect"])
            )
            if decayed < 0.01:
                continue
            trace["intensity"] = decayed
            trace["updated_at_utc"] = format_utc(now_utc)
            surviving.append(trace)
        state["active_affects"] = surviving
        rule_ids.append("time.affect")

    rupture_changed = False
    for rupture in state["ruptures"]:
        current_heat = float(rupture["heat"])
        if current_heat == 0.0:
            continue
        rupture["heat"] = current_heat * 2 ** (-elapsed_seconds / (6 * 3600))
        rupture["updated_at_utc"] = format_utc(now_utc)
        rupture_changed = True
    if rupture_changed:
        rule_ids.append("time.rupture")

    spontaneous = state["spontaneous"]
    anchor = previous_at
    if spontaneous["last_at_utc"] is not None:
        anchor = _parse_utc_string(spontaneous["last_at_utc"], "마지막 자발 변화 시각")
    if (now_utc - anchor).total_seconds() >= SPONTANEOUS_COOLDOWN_SECONDS:
        bucket = int(now_utc.timestamp()) // SPONTANEOUS_COOLDOWN_SECONDS
        seed_revision = spontaneous["seed_revision"]
        material = f"mood-v3|{normalized_preset}|{seed_revision}|{bucket}".encode("utf-8")
        digest = hashlib.sha256(material).digest()
        sample = int.from_bytes(digest[:8], "big") / 2**64
        if sample > SPONTANEOUS_THRESHOLD:
            for field, chunk in (("valence", digest[8:16]), ("energy", digest[16:24])):
                unit = int.from_bytes(chunk, "big") / 2**64
                impulse = unit * 0.03 - 0.015
                state["background"][field] = _clamp(
                    float(state["background"][field]) + impulse,
                    -1.0,
                    1.0,
                )
            spontaneous["seed_revision"] += 1
            spontaneous["last_at_utc"] = format_utc(now_utc)
            rule_ids.append("time.spontaneous")

    for field in state["background"]:
        state["background"][field] = _clamp(float(state["background"][field]), -1.0, 1.0)
    state["preset"] = normalized_preset
    state["updated_at_utc"] = format_utc(now_utc)
    return rule_ids


def _extract_canonical_event_id(event: object) -> str | None:
    if isinstance(event, MoodEvent):
        event_id = event.event_id
    elif isinstance(event, Mapping):
        event_id = event.get("event_id")
    else:
        return None
    if not _is_uuid_v4(event_id):
        return None
    return str(uuid.UUID(event_id))


def _coerce_event(event: object, now_utc: datetime) -> MoodEvent:
    if not isinstance(event, MoodEvent):
        return normalize_event(event, now_utc)
    return normalize_event(
        {
            "event_id": event.event_id,
            "kind": event.kind,
            "target_scope": event.target_scope,
            "relation_category": event.relation_category,
            "intensity": event.intensity,
            "clarity": event.clarity,
            "certainty": event.certainty,
            "controllability": event.controllability,
            "repair_signal": event.repair_signal,
        },
        now_utc,
    )


def _apply_background(state: dict[str, Any], kind: str, impact: float) -> None:
    for axis, delta in zip(("valence", "energy", "tension"), BACKGROUND_BASE[kind], strict=True):
        state["background"][axis] = _clamp(state["background"][axis] + delta * impact, -1.0, 1.0)


def _next_repeat_count(
    state: dict[str, Any],
    event: MoodEvent,
    now_utc: datetime,
) -> int:
    event_group = [
        item
        for item in state["active_affects"]
        if (item["source_kind"], item["target_scope"], item["relation_category"])
        == (event.kind, event.target_scope, event.relation_category)
    ]
    if not event_group:
        return 0
    prior_trace = max(
        event_group,
        key=lambda item: (
            _parse_utc_string(item["last_event_at_utc"], "last_event_at_utc"),
            item["repeat_count"],
        ),
    )
    elapsed = now_utc - _parse_utc_string(prior_trace["last_event_at_utc"], "last_event_at_utc")
    if elapsed.total_seconds() > 30 * 60:
        return 0
    return min(prior_trace["repeat_count"] + 1, 3)


def _relationship_base(event: MoodEvent) -> dict[str, float] | None:
    if not _can_change_relationship(event):
        return None
    if event.kind in RELATION_CONNECTION_BASE:
        return RELATION_CONNECTION_BASE[event.kind]
    if event.kind == "conflict" and event.relation_category in RELATION_CONFLICT_BASE:
        return RELATION_CONFLICT_BASE[event.relation_category]
    if event.kind == "repair" and event.repair_signal in RELATION_REPAIR_BASE:
        return RELATION_REPAIR_BASE[event.repair_signal]
    return None


def _is_clear_relationship_event(event: MoodEvent) -> bool:
    return (
        event.target_scope in {"ene", "relationship"}
        and event.clarity != "ambiguous"
        and event.certainty != "low"
    )


def _can_change_relationship(event: MoodEvent) -> bool:
    if not _is_clear_relationship_event(event):
        return False
    return event.repair_signal != "explanation" or (
        event.clarity == "explicit" and event.certainty == "high"
    )


def _apply_relationship(
    state: dict[str, Any],
    base: dict[str, float],
    impact: float,
) -> None:
    caps = {"affection": 0.025, "trust": 0.040}
    for axis in ("affection", "trust"):
        current = state["relationship"][axis]
        delta = base[axis] * impact * (1.0 - abs(current))
        delta = _clamp(delta, -caps[axis], caps[axis])
        state["relationship"][axis] = _clamp(current + delta, -1.0, 1.0)


def _apply_rupture(
    state: dict[str, Any],
    event: MoodEvent,
    now_utc: datetime,
    impact: float,
) -> bool:
    if not _can_change_relationship(event):
        return False
    rupture = next(
        (item for item in state["ruptures"] if item["category"] == event.relation_category),
        None,
    )
    timestamp = format_utc(now_utc)
    if (
        impact != 0.0
        and event.kind == "conflict"
        and event.relation_category in RUPTURE_CATEGORY_BASE
    ):
        base = RUPTURE_CATEGORY_BASE[event.relation_category]
        if rupture is None:
            initial = _clamp(base * impact, 0.0, 1.0)
            state["ruptures"].append(
                {
                    "category": event.relation_category,
                    "severity": initial,
                    "heat": initial,
                    "repair_stage": "open",
                    "repeat_count": 0,
                    "repair_evidence_count": 0,
                    "last_negative_at_utc": timestamp,
                    "updated_at_utc": timestamp,
                }
            )
            return True
        rupture["severity"] = _clamp(
            rupture["severity"] + base * impact * (1.0 - rupture["severity"]),
            0.0,
            1.0,
        )
        rupture["heat"] = _clamp(
            rupture["heat"] + base * impact * (1.0 - rupture["heat"]),
            0.0,
            1.0,
        )
        rupture["repair_stage"] = "open"
        rupture["repeat_count"] = min(rupture["repeat_count"] + 1, 3)
        rupture["repair_evidence_count"] = 0
        rupture["last_negative_at_utc"] = timestamp
        rupture["updated_at_utc"] = timestamp
        return True

    if event.kind != "repair" or rupture is None or event.repair_signal not in RUPTURE_REPAIR_DECREASE:
        return False
    decrease = RUPTURE_REPAIR_DECREASE[event.repair_signal]
    rupture["severity"] = _clamp(rupture["severity"] - decrease["severity"] * impact, 0.0, 1.0)
    rupture["heat"] = _clamp(rupture["heat"] - decrease["heat"] * impact, 0.0, 1.0)
    if event.repair_signal in {"correction", "follow_through"}:
        rupture["repair_stage"] = "observing"
        rupture["repair_evidence_count"] = min(rupture["repair_evidence_count"] + 1, 2)
    else:
        rupture["repair_stage"] = "acknowledged"
    rupture["updated_at_utc"] = timestamp

    resolved_by_evidence = rupture["repair_evidence_count"] == 2 and _at_or_below(
        rupture["severity"], 0.12
    )
    resolved_by_apology = event.repair_signal == "apology" and _at_or_below(
        rupture["severity"], 0.08
    )
    if resolved_by_evidence or resolved_by_apology:
        state["ruptures"].remove(rupture)
    return True


def _apply_affects(
    state: dict[str, Any],
    event: MoodEvent,
    now_utc: datetime,
    impact: float,
) -> None:
    timestamp = format_utc(now_utc)
    event_group = [
        item
        for item in state["active_affects"]
        if (item["source_kind"], item["target_scope"], item["relation_category"])
        == (event.kind, event.target_scope, event.relation_category)
    ]
    if event_group:
        prior_trace = max(
            event_group,
            key=lambda item: (
                _parse_utc_string(item["last_event_at_utc"], "마지막 사건 시각"),
                item["repeat_count"],
            ),
        )
        elapsed = now_utc - _parse_utc_string(prior_trace["last_event_at_utc"], "마지막 사건 시각")
        if elapsed.total_seconds() <= 30 * 60:
            next_repeat_count = min(prior_trace["repeat_count"] + 1, 3)
        else:
            next_repeat_count = 0
    else:
        next_repeat_count = 0

    for affect, base in AFFECT_BASE[event.kind].items():
        if (
            affect == "anger"
            and event.kind == "conflict"
            and event.target_scope in {"ene", "relationship"}
            and event.relation_category != "none"
            and event.clarity == "ambiguous"
            and event.certainty == "low"
        ):
            continue
        trace = next(
            (
                item
                for item in state["active_affects"]
                if (
                    item["source_kind"],
                    item["target_scope"],
                    item["relation_category"],
                    item["affect"],
                )
                == (event.kind, event.target_scope, event.relation_category, affect)
            ),
            None,
        )
        if trace is None:
            state["active_affects"].append(
                {
                    "affect": affect,
                    "intensity": _clamp(base * impact, 0.0, 1.0),
                    "source_kind": event.kind,
                    "target_scope": event.target_scope,
                    "relation_category": event.relation_category,
                    "repeat_count": next_repeat_count,
                    "last_event_at_utc": timestamp,
                    "updated_at_utc": timestamp,
                }
            )
            continue

        trace["repeat_count"] = next_repeat_count
        current = trace["intensity"]
        trace["intensity"] = _clamp(current + base * impact * (1.0 - current), 0.0, 1.0)
        trace["last_event_at_utc"] = timestamp
        trace["updated_at_utc"] = timestamp


def _trim_active_affects(active_affects: list[dict[str, Any]]) -> None:
    while len(active_affects) > 5:
        evicted = min(
            active_affects,
            key=lambda item: (
                item["intensity"] * affect_half_life_seconds(item["affect"]),
                _parse_utc_string(item["updated_at_utc"], "정서 갱신 시각"),
                _AFFECT_ORDER[item["affect"]],
                item["source_kind"],
                item["target_scope"],
                item["relation_category"],
                item["last_event_at_utc"],
                item["updated_at_utc"],
            ),
        )
        active_affects.remove(evicted)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _at_or_below(value: float, threshold: float) -> bool:
    return value <= threshold or math.isclose(value, threshold, rel_tol=0.0, abs_tol=1e-12)


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
        repair_stage = item["repair_stage"]
        if not isinstance(repair_stage, str) or repair_stage not in {"open", "acknowledged", "observing"}:
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
