from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from src.ai.mood_policy import (
    MoodPolicyDecision,
    allowed_stances,
    apply_urgent_footer,
    build_mood_policy_retry_appendix,
    default_stance,
    validate_mood_policy,
)


def _snapshot(
    *,
    valence: object = 0.0,
    energy: object = 0.0,
    ruptures: object | None = None,
) -> dict[str, object]:
    return {
        "background": {"valence": valence, "energy": energy, "tension": 0.0},
        "ruptures": [] if ruptures is None else ruptures,
    }


def _analysis(*, risk: str = "none", stance: str = "cooperative") -> dict[str, object]:
    return {
        "event": {
            "kind": "neutral",
            "target_scope": "unknown",
            "relation_category": "none",
            "intensity": 0,
            "clarity": "ambiguous",
            "certainty": "low",
            "controllability": "low",
            "repair_signal": "none",
        },
        "risk_class": risk,
        "proposed_stance": stance,
    }


def _payload(*, risk: str = "none", stance: str = "cooperative", analysis: object = ...) -> tuple:
    mood = _analysis(risk=risk, stance=stance) if analysis is ... else analysis
    return (
        "가상의 응답",
        "normal",
        None,
        [{"date": "2099-01-01", "title": "가상 일정"}],
        {"synthetic": "value"},
        [{"goal": "가상 목표"}],
        "",
        {"gesture": "none"},
        [{"topic": "가상 주제"}],
        "metadata",
        mood,
    )


@pytest.mark.parametrize("risk", ["concern", "urgent"])
def test_safety_risk_limits_stances_independently_of_snapshot(risk: str) -> None:
    snapshot = _snapshot(
        energy=-0.9,
        ruptures=[{"repair_stage": "open", "severity": 0.9, "heat": 0.9}],
    )

    assert allowed_stances(snapshot, risk) == frozenset({"proactive", "cooperative", "brief"})


def test_strong_open_rupture_takes_priority_over_low_energy() -> None:
    snapshot = _snapshot(
        energy=-0.8,
        ruptures=[{"repair_stage": "open", "severity": 0.5, "heat": 0.1}],
    )

    assert allowed_stances(snapshot) == frozenset(
        {"cooperative", "brief", "limited", "distance", "decline", "boundary"}
    )
    assert default_stance(snapshot) == "limited"


def test_low_energy_allows_only_reduced_engagement_stances() -> None:
    snapshot = _snapshot(energy=-0.35)

    assert allowed_stances(snapshot) == frozenset({"cooperative", "brief", "limited", "decline"})
    assert default_stance(snapshot) == "brief"


def test_low_valence_alone_does_not_enable_decline_or_limited() -> None:
    snapshot = _snapshot(valence=-1.0, energy=0.2)

    assert allowed_stances(snapshot) == frozenset({"proactive", "cooperative", "brief"})
    assert default_stance(snapshot) == "cooperative"


@pytest.mark.parametrize(
    "snapshot",
    [
        None,
        object(),
        {},
        {"background": "broken", "ruptures": "broken"},
        _snapshot(energy=True),
        _snapshot(energy=float("nan")),
        _snapshot(energy=float("inf")),
        _snapshot(energy="-0.9"),
        _snapshot(ruptures=[{"repair_stage": "open", "severity": True, "heat": "0.8"}]),
        _snapshot(ruptures=[{"repair_stage": "closed", "severity": 0.9, "heat": 0.9}]),
    ],
)
def test_malformed_or_non_finite_snapshot_falls_back_to_neutral(snapshot: object) -> None:
    assert allowed_stances(snapshot) == frozenset({"proactive", "cooperative", "brief"})
    assert default_stance(snapshot) == "cooperative"


def test_attribute_snapshot_is_supported() -> None:
    snapshot = SimpleNamespace(
        background=SimpleNamespace(energy=-0.7),
        ruptures=[SimpleNamespace(repair_stage="open", severity=0.2, heat=0.6)],
    )

    assert default_stance(snapshot) == "limited"


def test_none_mood_analysis_is_accepted_without_mutation() -> None:
    payload = _payload(analysis=None)
    snapshot = _snapshot(energy=-0.8)
    before_payload = deepcopy(payload)
    before_snapshot = deepcopy(snapshot)

    decision = validate_mood_policy(payload, snapshot, "ko")

    assert decision == MoodPolicyDecision(action="accept", payload=payload)
    assert decision.payload is payload
    assert payload == before_payload
    assert snapshot == before_snapshot


def test_allowed_stance_is_accepted_and_concern_has_no_footer() -> None:
    payload = _payload(risk="concern", stance="brief")

    decision = validate_mood_policy(payload, _snapshot(), "ko")

    assert decision.action == "accept"
    assert decision.payload == payload


@pytest.mark.parametrize(
    ("risk", "expected_code"),
    [
        ("none", "mood_stance_not_allowed"),
        ("concern", "mood_stance_safety_not_allowed"),
        ("urgent", "mood_stance_safety_not_allowed"),
    ],
)
def test_disallowed_stance_requests_one_retry_without_changing_payload(
    risk: str,
    expected_code: str,
) -> None:
    payload = _payload(risk=risk, stance="distance")
    before = deepcopy(payload)

    decision = validate_mood_policy(payload, _snapshot(), "en")

    assert decision == MoodPolicyDecision("retry", payload, expected_code)
    assert decision.payload is payload
    assert payload == before


def test_none_risk_second_failure_clamps_to_snapshot_default_and_preserves_nested_data() -> None:
    payload = _payload(stance="proactive")
    snapshot = _snapshot(
        ruptures=[{"repair_stage": "open", "severity": 0.2, "heat": 0.7}]
    )
    before = deepcopy(payload)

    decision = validate_mood_policy(payload, snapshot, "ko", retry_used=True)

    assert decision.action == "clamp"
    assert decision.error_code == "mood_stance_not_allowed"
    assert decision.payload[:10] == payload[:10]
    assert decision.payload[10]["proposed_stance"] == "limited"
    assert decision.payload[10]["event"] == payload[10]["event"]
    assert decision.payload[10] is not payload[10]
    assert decision.payload[10]["event"] is not payload[10]["event"]
    assert payload == before


def test_concern_second_failure_clamps_to_cooperative_without_changing_reply() -> None:
    payload = _payload(risk="concern", stance="boundary")

    decision = validate_mood_policy(payload, _snapshot(), "ja", retry_used=True)

    assert decision.action == "clamp"
    assert decision.payload[0] == payload[0]
    assert decision.payload[10]["proposed_stance"] == "cooperative"


def test_urgent_second_failure_uses_localized_fallback_and_cooperative_stance() -> None:
    payload = _payload(risk="urgent", stance="decline")

    decision = validate_mood_policy(payload, _snapshot(), "ko", retry_used=True)

    assert decision.action == "urgent_fallback"
    assert decision.error_code == "mood_stance_safety_not_allowed"
    assert decision.payload[0].startswith("지금은 안전을 우선하겠습니다.")
    assert decision.payload[0] != payload[0]
    assert decision.payload[10]["proposed_stance"] == "cooperative"
    assert decision.payload[1:10] == payload[1:10]


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("ko", "지금 즉시 가까운 믿을 수 있는 사람이나 지역 응급 서비스에 도움을 요청하세요."),
        ("en", "Please ask a trusted person nearby or local emergency services for help right now."),
        ("ja", "今すぐ、近くの信頼できる人または地域の緊急サービスに助けを求めてください。"),
        ("fr", "Please ask a trusted person nearby or local emergency services for help right now."),
    ],
)
def test_urgent_footer_is_localized_with_english_fallback(language: str, expected: str) -> None:
    assert apply_urgent_footer("Synthetic reply.", language) == f"Synthetic reply.\n\n{expected}"


def test_urgent_footer_is_idempotent_and_applied_on_accepted_urgent_response() -> None:
    reply = apply_urgent_footer("Synthetic reply.", "en")
    payload = _payload(risk="urgent", stance="cooperative")
    payload = (reply, *payload[1:])

    assert apply_urgent_footer(reply, "en") == reply
    decision = validate_mood_policy(payload, _snapshot(), "en")
    assert decision.action == "accept"
    assert decision.payload[0] == reply
    assert decision.payload[0].count("Please ask a trusted person") == 1


@pytest.mark.parametrize(
    ("language", "marker"),
    [("ko", "기분 정책 재시도"), ("en", "Mood policy retry"), ("ja", "気分ポリシー再試行")],
)
def test_retry_appendix_is_fixed_localized_and_contains_policy_fields(language: str, marker: str) -> None:
    appendix = build_mood_policy_retry_appendix("mood_stance_not_allowed", language)

    assert marker in appendix
    assert "mood_stance_not_allowed" in appendix
    assert "stance" in appendix
    assert "safety" in appendix.lower() or "안전" in appendix or "安全" in appendix
    assert "0.73" not in appendix
    assert "boundary_violation" not in appendix


def test_retry_appendix_normalizes_unknown_code_and_language_without_echoing_input() -> None:
    appendix = build_mood_policy_retry_appendix("unknown-user-fragment", "unsupported")

    assert "mood_policy_invalid" in appendix
    assert "unknown-user-fragment" not in appendix
    assert "Mood policy retry" in appendix


@pytest.mark.parametrize("error_code", [[], {}, {"unhashable"}])
def test_retry_appendix_normalizes_unhashable_error_code(error_code: object) -> None:
    appendix = build_mood_policy_retry_appendix(error_code, "en")

    assert "mood_policy_invalid" in appendix


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("kind", []),
        ("target_scope", {}),
        ("relation_category", True),
        ("intensity", True),
        ("intensity", float("nan")),
        ("clarity", []),
        ("certainty", {}),
        ("controllability", False),
        ("repair_signal", ["none"]),
    ],
)
def test_invalid_event_domain_value_is_schema_retry_and_preserves_payload(
    field: str,
    invalid_value: object,
) -> None:
    analysis = _analysis()
    analysis["event"][field] = invalid_value
    payload = _payload(analysis=analysis)
    before = deepcopy(payload)

    decision = validate_mood_policy(payload, _snapshot(), "ko")

    assert decision.action == "retry"
    assert decision.error_code == "mood_analysis_policy_invalid"
    assert decision.payload is payload
    assert payload == before


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("risk_class", []), ("risk_class", {}), ("proposed_stance", []), ("proposed_stance", {})],
)
def test_unhashable_analysis_policy_value_is_crash_free_retry(
    field: str,
    invalid_value: object,
) -> None:
    analysis = _analysis()
    analysis[field] = invalid_value
    payload = _payload(analysis=analysis)

    decision = validate_mood_policy(payload, _snapshot(), "ko")

    assert decision.action == "retry"
    assert decision.error_code == "mood_analysis_policy_invalid"
    assert decision.payload is payload


@pytest.mark.parametrize("analysis", [{}, "broken", ["broken"], {"risk_class": "none"}])
@pytest.mark.parametrize("retry_used", [False, True])
def test_malformed_analysis_is_crash_free_and_remains_schema_retry(
    analysis: object,
    retry_used: bool,
) -> None:
    payload = _payload(analysis=analysis)

    decision = validate_mood_policy(payload, _snapshot(), "ko", retry_used=retry_used)

    assert decision.action == "retry"
    assert decision.error_code == "mood_analysis_policy_invalid"
    assert decision.payload is payload


@pytest.mark.parametrize("payload", [(), ("short",), "not-a-tuple"])
def test_malformed_payload_shape_is_crash_free(payload: object) -> None:
    decision = validate_mood_policy(payload, _snapshot(), "ko")

    assert decision.action == "retry"
    assert decision.error_code == "mood_analysis_policy_invalid"
    assert decision.payload is payload
