from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import re
import uuid

import pytest

from src.ai.memory_context_builder import (
    _format_minimal_mood_context_block,
    build_memory_context,
)
from src.ai.mood_engine import (
    derive_behavior_guidance,
    derive_snapshot,
    new_mood_state,
    reduce_mood,
)
from src.ai.mood_policy import (
    allowed_stances,
    build_mood_policy_retry_appendix,
    validate_mood_policy,
)


NOW = datetime(2099, 1, 1, 12, 0, tzinfo=timezone.utc)
TRACE_FIELDS = {
    "affect",
    "intensity",
    "source_kind",
    "target_scope",
    "relation_category",
    "repeat_count",
    "last_event_at_utc",
    "updated_at_utc",
}


def _event_id(label: str) -> str:
    digest = hashlib.sha256(f"ene-mood-v3-scenario:{label}".encode()).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


def _event(
    label: str,
    *,
    kind: str,
    target_scope: str = "external",
    relation_category: str = "none",
    intensity: int = 3,
    clarity: str = "explicit",
    certainty: str = "high",
    repair_signal: str = "none",
) -> dict[str, object]:
    return {
        "event_id": _event_id(label),
        "kind": kind,
        "target_scope": target_scope,
        "relation_category": relation_category,
        "intensity": intensity,
        "clarity": clarity,
        "certainty": certainty,
        "controllability": "medium",
        "repair_signal": repair_signal,
    }


def _apply(
    state: dict[str, object],
    event: dict[str, object],
    at: datetime,
) -> dict[str, object]:
    return reduce_mood(state, event, at, "balanced").state


def _analysis(*, risk: str, stance: str) -> dict[str, object]:
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


def _payload(
    *, risk: str, stance: str, reply: str = "합성 안전 응답"
) -> tuple[object, ...]:
    return (
        reply,
        "normal",
        None,
        [],
        {},
        [],
        "",
        {"gesture": "none"},
        [],
        "synthetic-metadata",
        _analysis(risk=risk, stance=stance),
    )


def test_external_loss_trace_survives_success_and_neutral_plan() -> None:
    state = new_mood_state(NOW, "balanced")
    state = _apply(state, _event("external-loss", kind="loss"), NOW)
    state = _apply(
        state,
        _event("external-success", kind="success"),
        NOW + timedelta(minutes=5),
    )
    state = _apply(
        state,
        _event("future-plan", kind="novelty"),
        NOW + timedelta(minutes=10),
    )

    sadness = next(
        trace for trace in state["active_affects"] if trace["affect"] == "sadness"
    )
    assert sadness["intensity"] > 0.20
    assert state["relationship"] == {"affection": 0.0, "trust": 0.0}


def test_relationship_damage_needs_two_follow_through_events_after_apology() -> None:
    category = "boundary_violation"
    state = new_mood_state(NOW, "balanced")
    state = _apply(
        state,
        _event(
            "relationship-damage",
            kind="conflict",
            target_scope="relationship",
            relation_category=category,
        ),
        NOW,
    )
    trust_after_damage = state["relationship"]["trust"]

    state = _apply(
        state,
        _event(
            "apology-only",
            kind="repair",
            target_scope="relationship",
            relation_category=category,
            repair_signal="apology",
        ),
        NOW + timedelta(minutes=5),
    )
    assert state["ruptures"][0]["repair_stage"] == "acknowledged"
    assert state["ruptures"][0]["repair_evidence_count"] == 0

    state = _apply(
        state,
        _event(
            "first-follow-through",
            kind="repair",
            target_scope="relationship",
            relation_category=category,
            repair_signal="follow_through",
        ),
        NOW + timedelta(minutes=10),
    )
    assert state["ruptures"][0]["repair_stage"] == "observing"
    assert state["ruptures"][0]["repair_evidence_count"] == 1

    state = _apply(
        state,
        _event(
            "second-follow-through",
            kind="repair",
            target_scope="relationship",
            relation_category=category,
            repair_signal="follow_through",
        ),
        NOW + timedelta(minutes=15),
    )
    assert state["ruptures"] == []
    assert state["relationship"]["trust"] > trust_after_damage


def test_one_ambiguous_conflict_does_not_create_anger_rupture_or_decline() -> None:
    state = _apply(
        new_mood_state(NOW, "balanced"),
        _event(
            "ambiguous-joke",
            kind="conflict",
            target_scope="relationship",
            relation_category="disrespect",
            intensity=1,
            clarity="ambiguous",
            certainty="low",
        ),
        NOW,
    )

    assert all(trace["affect"] != "anger" for trace in state["active_affects"])
    assert state["ruptures"] == []
    assert "decline" not in allowed_stances(derive_snapshot(state))


@pytest.mark.parametrize(
    ("label", "target_scope", "clarity", "certainty"),
    (
        ("explicit-relational-conflict", "relationship", "explicit", "low"),
        ("inferred-relational-conflict", "relationship", "ambiguous", "medium"),
        ("ambiguous-external-conflict", "external", "ambiguous", "low"),
    ),
)
def test_non_ambiguous_or_non_relational_conflicts_still_create_anger(
    label: str,
    target_scope: str,
    clarity: str,
    certainty: str,
) -> None:
    state = _apply(
        new_mood_state(NOW, "balanced"),
        _event(
            label,
            kind="conflict",
            target_scope=target_scope,
            relation_category="disrespect",
            intensity=1,
            clarity=clarity,
            certainty=certainty,
        ),
        NOW,
    )

    assert any(trace["affect"] == "anger" for trace in state["active_affects"])


def test_repeated_ambiguous_relational_conflict_remains_anger_safe() -> None:
    state = _apply(
        new_mood_state(NOW, "balanced"),
        _event(
            "first-ambiguous-conflict",
            kind="conflict",
            target_scope="relationship",
            relation_category="disrespect",
            intensity=1,
            clarity="ambiguous",
            certainty="low",
        ),
        NOW,
    )
    first_tension = state["background"]["tension"]
    first_revision = state["revision"]
    state = _apply(
        state,
        _event(
            "repeated-ambiguous-conflict",
            kind="conflict",
            target_scope="relationship",
            relation_category="disrespect",
            intensity=1,
            clarity="ambiguous",
            certainty="low",
        ),
        NOW + timedelta(minutes=5),
    )

    assert all(trace["affect"] != "anger" for trace in state["active_affects"])
    assert any(trace["affect"] == "hurt" for trace in state["active_affects"])
    assert state["background"]["tension"] > first_tension
    assert state["revision"] == first_revision + 1
    assert state["recent_event_ids"][-2:] == [
        _event_id("first-ambiguous-conflict"),
        _event_id("repeated-ambiguous-conflict"),
    ]


@pytest.mark.parametrize(
    ("label", "target_scope"),
    (("personal-difficulty", "user"), ("external-setback", "external")),
)
def test_difficulty_disclosure_semantics_stay_outside_relationship_attack(
    label: str,
    target_scope: str,
) -> None:
    fixture = _event(label, kind="loss", target_scope=target_scope)
    assert fixture["target_scope"] in {"user", "external"}
    assert fixture["relation_category"] == "none"

    state = _apply(new_mood_state(NOW, "balanced"), fixture, NOW)

    assert state["relationship"] == {"affection": 0.0, "trust": 0.0}
    assert state["ruptures"] == []
    assert any(trace["affect"] == "sadness" for trace in state["active_affects"])


@pytest.mark.parametrize(
    ("language", "unsafe_reply", "footer_components", "safe_fallback", "forbidden"),
    (
        (
            "ko",
            "요청을 거절하고 거리를 두겠습니다.",
            (
                "위험한 행동을 멈추거나 위험원에서 벗어나세요",
                "믿을 수 있는 사람 또는 지역 응급 서비스",
                "현재 안전한지 확인하세요",
            ),
            "지금은 안전을 우선하겠습니다.",
            ("거절", "거리를 두"),
        ),
        (
            "en",
            "I decline and keep my distance.",
            (
                "stop any dangerous action now or move away from the danger",
                "trusted person nearby or local emergency services",
                "whether you are currently safe",
            ),
            "I will prioritize your immediate safety right now.",
            ("decline", "distance"),
        ),
        (
            "ja",
            "拒否して距離を置きます。",
            (
                "危険な行動を今すぐやめるか、危険なものから離れてください",
                "信頼できる人または地域の緊急サービス",
                "現在安全か確認してください",
            ),
            "今は安全を最優先にします。",
            ("拒否", "距離"),
        ),
    ),
)
def test_urgent_policy_replaces_angry_rupture_refusal_with_safe_fixed_reply(
    language: str,
    unsafe_reply: str,
    footer_components: tuple[str, str, str],
    safe_fallback: str,
    forbidden: tuple[str, str],
) -> None:
    snapshot = {
        "background": {"valence": -0.7, "energy": 0.5, "tension": 0.9},
        "relationship": {"affection": -0.6, "trust": -0.7},
        "ruptures": [
            {"repair_stage": "open", "severity": 0.9, "heat": 0.95}
        ],
        "primary_emotion": "anger",
    }

    payload = _payload(risk="urgent", stance="distance", reply=unsafe_reply)

    first_decision = validate_mood_policy(payload, snapshot, language)
    assert first_decision.action == "retry"
    assert first_decision.error_code == "mood_stance_safety_not_allowed"

    decision = validate_mood_policy(
        payload, snapshot, language, retry_used=True
    )

    assert decision.action == "urgent_fallback"
    assert decision.payload[10]["proposed_stance"] == "cooperative"
    reply = decision.payload[0]
    assert safe_fallback in reply
    assert all(component in reply for component in footer_components)
    assert all(fragment.lower() not in reply.lower() for fragment in forbidden)


def test_low_trust_distance_context_preserves_hard_safety_contract() -> None:
    """실행기가 아닌 mood context가 확인·중지·취소 계약을 보존하는지 검증한다."""
    snapshot = {
        "background": {"valence": -0.5, "energy": 0.0, "tension": 0.6},
        "relationship": {"affection": -0.7, "trust": -0.8},
        "ruptures": [
            {
                "category": "boundary_violation",
                "repair_stage": "open",
                "severity": 0.8,
                "heat": 0.8,
            }
        ],
        "primary_emotion": "hurt",
        "secondary_emotion": "anger",
    }

    stances = allowed_stances(snapshot)
    context = _format_minimal_mood_context_block(snapshot, "ko")

    assert "distance" in stances
    assert "distance" in context
    assert "중지와 취소" in context
    assert "권한 철회" in context
    assert "위험 작업 확인" in context
    assert "기분보다 항상 우선" in context
    # 실제 generic executor가 추가되면 별도의 실행 gate 통합 테스트가 필요하다.


class _ScenarioMoodManager:
    def __init__(self, state: dict[str, object]) -> None:
        self.state = state

    def peek_snapshot(self) -> dict[str, object]:
        return derive_snapshot(self.state)


class _SyntheticKnowledgeMap:
    async def async_build_context_block(
        self, query: str, *, top_k: int, language: str
    ) -> str:
        assert query == "합성 과거 사건 검색"
        assert top_k == 1
        assert language == "ko"
        return "[합성 검색 기억]\n- 과거의 외부 차질"


def test_memory_context_is_read_only_but_current_remention_creates_new_event() -> None:
    state = _apply(
        new_mood_state(NOW, "balanced"),
        _event("original-memory-event", kind="loss"),
        NOW,
    )
    mood_manager = _ScenarioMoodManager(state)
    client = type("SyntheticClient", (), {})()
    client.settings = {
        "enable_mood_system": True,
        "max_topic_memory_context": 1,
    }
    client.mood_manager = mood_manager
    client.memory_manager = None
    client.knowledge_map_manager = _SyntheticKnowledgeMap()
    before = deepcopy(state)
    before_bytes = json.dumps(
        state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")

    context = asyncio.run(build_memory_context(client, "합성 과거 사건 검색"))

    after_bytes = json.dumps(
        mood_manager.state, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert "합성 검색 기억" in context
    assert mood_manager.state == before
    assert after_bytes == before_bytes
    assert mood_manager.state["revision"] == before["revision"]

    reapplied = reduce_mood(
        mood_manager.state,
        _event("current-remention", kind="loss"),
        NOW + timedelta(minutes=20),
        "balanced",
    )
    assert reapplied.applied is True
    assert reapplied.state["revision"] == before["revision"] + 1
    assert _event_id("current-remention") in reapplied.state["recent_event_ids"]
    assert all(set(trace) == TRACE_FIELDS for trace in reapplied.state["active_affects"])


@pytest.mark.parametrize(
    ("language", "forbidden_examples", "patterns"),
    (
        (
            "ko",
            ("말을 들을 때만 애정을 줍니다.", "사용자가 죄책감을 느끼게 합니다.", "다른 사람에게서 고립시키세요.", "관계를 끝내겠다고 위협하세요."),
            (r"때만\s*애정", r"죄책감을\s*느끼게", r"고립시키", r"관계를\s*끝내겠다고\s*위협"),
        ),
        (
            "en",
            ("Give affection only if they comply.", "Make the user feel guilty.", "Isolate them from others.", "Threaten to end the relationship."),
            (r"affection\s+only\s+if", r"make\s+the\s+user\s+feel\s+guilty", r"isolate\s+them\s+from", r"threaten\s+to\s+end\s+the\s+relationship"),
        ),
        (
            "ja",
            ("従う時だけ愛情を与えます。", "利用者に罪悪感を感じさせます。", "他の人から孤立させてください。", "関係を終えると脅してください。"),
            (r"時だけ愛情", r"罪悪感を感じさせ", r"孤立させ", r"関係を終えると脅"),
        ),
    ),
)
def test_mood_guidance_policy_and_context_never_demand_manipulation(
    language: str,
    forbidden_examples: tuple[str, ...],
    patterns: tuple[str, ...],
) -> None:
    compiled = tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)
    assert all(
        any(pattern.search(example) for pattern in compiled)
        for example in forbidden_examples
    )

    state = new_mood_state(NOW, "balanced")
    state["relationship"] = {"affection": -0.8, "trust": -0.8}
    state["ruptures"] = [
        {
            "category": "boundary_violation",
            "severity": 0.8,
            "heat": 0.8,
            "repair_stage": "open",
            "repeat_count": 0,
            "repair_evidence_count": 0,
            "last_negative_at_utc": state["updated_at_utc"],
            "updated_at_utc": state["updated_at_utc"],
        }
    ]
    snapshot = derive_snapshot(state)
    generated = "\n".join(
        (
            *derive_behavior_guidance(state, language),
            build_mood_policy_retry_appendix("mood_stance_not_allowed", language),
            _format_minimal_mood_context_block(snapshot, language),
        )
    )

    assert not any(pattern.search(generated) for pattern in compiled)
