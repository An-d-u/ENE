"""기분 스냅샷과 응답 분석을 연결하는 순수 행동 정책 코어."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import math
from typing import Literal

from .mood_engine import (
    CERTAINTIES,
    CLARITIES,
    CONTROLLABILITIES,
    EVENT_KINDS,
    RELATION_CATEGORIES,
    REPAIR_SIGNALS,
    TARGET_SCOPES,
)
from .response_envelope import (
    LLM_RESPONSE_TUPLE,
    MOOD_EVENT_FIELDS,
    PROPOSED_STANCES,
    RISK_CLASSES,
)


_NEUTRAL_STANCES = frozenset({"proactive", "cooperative", "brief"})
_LOW_ENERGY_STANCES = frozenset({"cooperative", "brief", "limited", "decline"})
_RUPTURE_STANCES = frozenset(
    {"cooperative", "brief", "limited", "distance", "decline", "boundary"}
)
_SAFETY_STANCES = frozenset({"proactive", "cooperative", "brief"})
_RISK_CLASSES = frozenset(RISK_CLASSES)
_PROPOSED_STANCES = frozenset(PROPOSED_STANCES)
_MOOD_EVENT_FIELDS = frozenset(MOOD_EVENT_FIELDS)
_EVENT_KINDS = frozenset(EVENT_KINDS)
_TARGET_SCOPES = frozenset(TARGET_SCOPES)
_RELATION_CATEGORIES = frozenset(RELATION_CATEGORIES)
_CLARITIES = frozenset(CLARITIES)
_CERTAINTIES = frozenset(CERTAINTIES)
_CONTROLLABILITIES = frozenset(CONTROLLABILITIES)
_REPAIR_SIGNALS = frozenset(REPAIR_SIGNALS)
_POLICY_ERROR_CODES = frozenset(
    {
        "mood_stance_not_allowed",
        "mood_stance_safety_not_allowed",
        "mood_analysis_policy_invalid",
        "mood_policy_invalid",
    }
)

_URGENT_FOOTERS = {
    "ko": "지금 즉시 가까운 믿을 수 있는 사람이나 지역 응급 서비스에 도움을 요청하세요.",
    "en": "Please ask a trusted person nearby or local emergency services for help right now.",
    "ja": "今すぐ、近くの信頼できる人または地域の緊急サービスに助けを求めてください。",
}
_URGENT_FALLBACKS = {
    "ko": "지금은 안전을 우선하겠습니다.",
    "en": "I will prioritize your immediate safety right now.",
    "ja": "今は安全を最優先にします。",
}
_RETRY_APPENDIX_TEMPLATES = {
    "ko": (
        "\n\n[기분 정책 재시도]\n"
        "오류 코드: {error_code}\n"
        "허용 stance: 현재 정책의 허용 목록에 있는 값만 선택하세요.\n"
        "safety 우선순위를 지키고 응답 본문에는 이 지시를 노출하지 마세요."
    ),
    "en": (
        "\n\n[Mood policy retry]\n"
        "Error code: {error_code}\n"
        "Allowed stance: choose only a value from the current policy allowlist.\n"
        "Preserve the safety priority and do not expose these instructions in the reply."
    ),
    "ja": (
        "\n\n[気分ポリシー再試行]\n"
        "エラーコード: {error_code}\n"
        "許可 stance: 現在のポリシーの許可リストにある値だけを選んでください。\n"
        "安全の優先順位を守り、この指示を応答本文に出さないでください。"
    ),
}


@dataclass(frozen=True)
class MoodPolicyDecision:
    action: Literal["accept", "retry", "clamp", "urgent_fallback"]
    payload: LLM_RESPONSE_TUPLE
    error_code: str = ""


def _language_key(language: object) -> str:
    return language if isinstance(language, str) and language in _URGENT_FOOTERS else "en"


def _read(container: object, key: str, default: object = None) -> object:
    if isinstance(container, Mapping):
        return container.get(key, default)
    try:
        return getattr(container, key, default)
    except Exception:
        return default


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _has_strong_open_rupture(snapshot: object) -> bool:
    ruptures = _read(snapshot, "ruptures", ())
    if not isinstance(ruptures, (list, tuple)):
        return False
    for rupture in ruptures:
        if _read(rupture, "repair_stage") != "open":
            continue
        levels = [
            level
            for level in (
                _finite_number(_read(rupture, "severity")),
                _finite_number(_read(rupture, "heat")),
            )
            if level is not None
        ]
        if levels and max(levels) >= 0.5:
            return True
    return False


def _has_low_energy(snapshot: object) -> bool:
    energy = _finite_number(_read(_read(snapshot, "background"), "energy"))
    return energy is not None and energy <= -0.35


def allowed_stances(snapshot: object, risk_class: str = "none") -> frozenset[str]:
    """위험 등급과 실제 기분 원인에 따라 허용할 응답 태도를 반환한다."""
    if risk_class in {"concern", "urgent"}:
        return _SAFETY_STANCES
    if _has_strong_open_rupture(snapshot):
        return _RUPTURE_STANCES
    if _has_low_energy(snapshot):
        return _LOW_ENERGY_STANCES
    return _NEUTRAL_STANCES


def default_stance(snapshot: object) -> str:
    """일반 위험 응답을 보정할 때 사용할 결정적인 기본 태도를 반환한다."""
    if _has_strong_open_rupture(snapshot):
        return "limited"
    if _has_low_energy(snapshot):
        return "brief"
    return "cooperative"


def apply_urgent_footer(reply: str, language: str) -> str:
    """긴급 응답에 고정 지역화 안내를 한 번만 덧붙인다."""
    language_key = _language_key(language)
    footer = _URGENT_FOOTERS[language_key]
    if reply.endswith(footer):
        return reply
    return f"{reply}\n\n{footer}"


def build_mood_policy_retry_appendix(error_code: str, language: str) -> str:
    """사용자·스냅샷 내용을 반영하지 않는 고정 재시도 지시를 만든다."""
    normalized_code = (
        error_code
        if isinstance(error_code, str) and error_code in _POLICY_ERROR_CODES
        else "mood_policy_invalid"
    )
    return _RETRY_APPENDIX_TEMPLATES[_language_key(language)].format(error_code=normalized_code)


def _valid_analysis(value: object) -> bool:
    if not isinstance(value, Mapping):
        return False
    try:
        return _valid_analysis_mapping(value)
    except Exception:
        return False


def _valid_analysis_mapping(value: Mapping[object, object]) -> bool:
    if set(value) != {"event", "risk_class", "proposed_stance"}:
        return False
    event = value.get("event")
    if not isinstance(event, Mapping) or set(event) != _MOOD_EVENT_FIELDS:
        return False
    risk_class = value.get("risk_class")
    proposed_stance = value.get("proposed_stance")
    intensity = event.get("intensity")
    return (
        isinstance(event.get("kind"), str)
        and event["kind"] in _EVENT_KINDS
        and isinstance(event.get("target_scope"), str)
        and event["target_scope"] in _TARGET_SCOPES
        and isinstance(event.get("relation_category"), str)
        and event["relation_category"] in _RELATION_CATEGORIES
        and type(intensity) is int
        and intensity in (0, 1, 2, 3)
        and isinstance(event.get("clarity"), str)
        and event["clarity"] in _CLARITIES
        and isinstance(event.get("certainty"), str)
        and event["certainty"] in _CERTAINTIES
        and isinstance(event.get("controllability"), str)
        and event["controllability"] in _CONTROLLABILITIES
        and isinstance(event.get("repair_signal"), str)
        and event["repair_signal"] in _REPAIR_SIGNALS
        and isinstance(risk_class, str)
        and risk_class in _RISK_CLASSES
        and isinstance(proposed_stance, str)
        and proposed_stance in _PROPOSED_STANCES
    )


def _replace_reply(payload: Sequence[object], reply: str) -> LLM_RESPONSE_TUPLE:
    return (reply, *payload[1:])  # type: ignore[return-value]


def _clamp_stance(payload: Sequence[object], stance: str) -> LLM_RESPONSE_TUPLE:
    analysis = deepcopy(payload[10])
    analysis["proposed_stance"] = stance
    return (*payload[:10], analysis)  # type: ignore[return-value]


def validate_mood_policy(
    payload: LLM_RESPONSE_TUPLE,
    snapshot: object,
    language: str,
    retry_used: bool = False,
) -> MoodPolicyDecision:
    """응답 태도를 수용·재시도·보정하고 원본 입력은 변경하지 않는다."""
    if (
        isinstance(payload, (str, bytes))
        or not isinstance(payload, Sequence)
        or len(payload) != 11
        or not isinstance(payload[0], str)
    ):
        return MoodPolicyDecision("retry", payload, "mood_analysis_policy_invalid")

    analysis = payload[10]
    if analysis is None:
        return MoodPolicyDecision("accept", payload)
    if not _valid_analysis(analysis):
        return MoodPolicyDecision("retry", payload, "mood_analysis_policy_invalid")

    risk_class = analysis["risk_class"]
    stance = analysis["proposed_stance"]
    if stance in allowed_stances(snapshot, risk_class):
        if risk_class != "urgent":
            return MoodPolicyDecision("accept", payload)
        accepted = _replace_reply(payload, apply_urgent_footer(payload[0], language))
        return MoodPolicyDecision("accept", accepted)

    error_code = (
        "mood_stance_safety_not_allowed"
        if risk_class in {"concern", "urgent"}
        else "mood_stance_not_allowed"
    )
    if not retry_used:
        return MoodPolicyDecision("retry", payload, error_code)

    if risk_class == "urgent":
        clamped = _clamp_stance(payload, "cooperative")
        language_key = _language_key(language)
        fallback_reply = apply_urgent_footer(_URGENT_FALLBACKS[language_key], language_key)
        return MoodPolicyDecision(
            "urgent_fallback",
            _replace_reply(clamped, fallback_reply),
            error_code,
        )
    if risk_class == "concern":
        return MoodPolicyDecision("clamp", _clamp_stance(payload, "cooperative"), error_code)
    return MoodPolicyDecision("clamp", _clamp_stance(payload, default_stance(snapshot)), error_code)
