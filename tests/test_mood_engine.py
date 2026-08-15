from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import math
import uuid

import pytest

from src.ai.mood_engine import (
    AFFECT_HALF_LIFE_CLASS,
    HALF_LIFE_SECONDS,
    MoodEvent,
    MoodTransition,
    advance_time,
    affect_half_life_seconds,
    derive_behavior_guidance,
    derive_snapshot,
    new_mood_state,
    normalize_event,
    reduce_mood,
    validate_state,
)


NOW = datetime(2099, 1, 1, tzinfo=timezone.utc)


def synthetic_event_id(label: str) -> str:
    digest = hashlib.sha256(f"ene-mood-test:{label}".encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest[:16], version=4))


def valid_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
        "event_id": synthetic_event_id("valid"),
        "kind": "connection",
        "target_scope": "relationship",
        "relation_category": "none",
        "intensity": 2,
        "clarity": "explicit",
        "certainty": "high",
        "controllability": "medium",
        "repair_signal": "none",
    }
    event.update(overrides)
    return event


def valid_active_affect(**overrides: object) -> dict[str, object]:
    trace: dict[str, object] = {
        "affect": "tenderness",
        "intensity": 0.4,
        "source_kind": "connection",
        "target_scope": "relationship",
        "relation_category": "none",
        "repeat_count": 0,
        "last_event_at_utc": "2099-01-01T00:00:00+00:00",
        "updated_at_utc": "2099-01-01T00:00:00+00:00",
    }
    trace.update(overrides)
    return trace


def relationship_event(label: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "event_id": synthetic_event_id(label),
        "intensity": 3,
        "clarity": "explicit",
        "certainty": "high",
    }
    values.update(overrides)
    return valid_event(**values)


def seeded_rupture(
    category: str = "broken_commitment",
    severity: float = 0.18,
    heat: float = 0.18,
) -> dict[str, object]:
    return {
        "category": category,
        "severity": severity,
        "heat": heat,
        "repair_stage": "open",
        "repeat_count": 0,
        "repair_evidence_count": 0,
        "last_negative_at_utc": NOW.isoformat(timespec="seconds"),
        "updated_at_utc": NOW.isoformat(timespec="seconds"),
    }


def test_new_state_has_v3_structure_and_neutral_relationship() -> None:
    state = new_mood_state(NOW, "affectionate")

    assert state == {
        "version": 3,
        "revision": 0,
        "preset": "balanced",
        "updated_at_utc": "2099-01-01T00:00:00+00:00",
        "background": {"valence": 0.0, "energy": 0.0, "tension": 0.0},
        "relationship": {"affection": 0.0, "trust": 0.0},
        "active_affects": [],
        "ruptures": [],
        "recent_event_ids": [],
        "spontaneous": {"last_at_utc": None, "seed_revision": 0},
    }


def test_mood_event_is_frozen_and_has_only_structured_fields() -> None:
    event = normalize_event(valid_event(), NOW)

    assert [field.name for field in fields(MoodEvent)] == [
        "event_id",
        "occurred_at_utc",
        "kind",
        "target_scope",
        "relation_category",
        "intensity",
        "clarity",
        "certainty",
        "controllability",
        "repair_signal",
    ]
    with pytest.raises(FrozenInstanceError):
        event.kind = "neutral"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("kind", "unknown"),
        ("target_scope", "other"),
        ("relation_category", "misc"),
        ("intensity", True),
        ("intensity", 4),
        ("clarity", "unclear"),
        ("certainty", "certain"),
        ("controllability", "none"),
        ("repair_signal", "promise"),
    ],
)
def test_invalid_event_normalizes_to_relationship_safe_neutral(field: str, invalid: object) -> None:
    event = normalize_event(valid_event(**{field: invalid}), NOW)

    assert event == MoodEvent(
        event_id=synthetic_event_id("valid"),
        occurred_at_utc=NOW,
        kind="neutral",
        target_scope="unknown",
        relation_category="none",
        intensity=0,
        clarity="ambiguous",
        certainty="low",
        controllability="low",
        repair_signal="none",
    )


def test_event_id_must_be_uuid_v4() -> None:
    valid = normalize_event(valid_event(), NOW)
    invalid = normalize_event(valid_event(event_id=str(uuid.uuid1())), NOW)

    assert uuid.UUID(valid.event_id).version == 4
    assert uuid.UUID(invalid.event_id).version == 4
    assert invalid.kind == "neutral"


def test_uuid_v4_text_is_normalized_to_canonical_form() -> None:
    event_id = synthetic_event_id("uppercase")

    event = normalize_event(valid_event(event_id=event_id.upper()), NOW)

    assert event.event_id == event_id
    assert event.kind == "connection"


def test_repair_signal_outside_relationship_repair_is_neutralized() -> None:
    event = normalize_event(
        valid_event(kind="connection", target_scope="external", repair_signal="apology"),
        NOW,
    )

    assert event.kind == "neutral"
    assert event.target_scope == "unknown"


def test_validate_state_returns_deep_copy_without_mutating_input() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"].append(valid_active_affect())

    validated = validate_state(state)
    validated["background"]["valence"] = 0.5
    validated["active_affects"][0]["intensity"] = 0.8

    assert state["background"]["valence"] == 0.0
    assert state["active_affects"][0]["intensity"] == 0.4


@pytest.mark.parametrize("invalid", [True, math.nan, math.inf, -math.inf])
def test_validate_state_rejects_bool_and_non_finite_numbers(invalid: object) -> None:
    state = new_mood_state(NOW, "balanced")
    state["background"]["valence"] = invalid

    with pytest.raises(ValueError):
        validate_state(state)


@pytest.mark.parametrize(
    ("key", "limit", "factory"),
    [
        ("active_affects", 5, lambda index: valid_active_affect(affect="joy")),
        (
            "ruptures",
            3,
            lambda index: {
                "category": "broken_commitment",
                "severity": 0.2,
                "heat": 0.1,
                "repair_stage": "open",
                "repeat_count": 0,
                "repair_evidence_count": 0,
                "last_negative_at_utc": "2099-01-01T00:00:00+00:00",
                "updated_at_utc": "2099-01-01T00:00:00+00:00",
            },
        ),
        ("recent_event_ids", 64, lambda index: synthetic_event_id(f"recent-{index}")),
    ],
)
def test_validate_state_rejects_arrays_over_their_limits(
    key: str,
    limit: int,
    factory: object,
) -> None:
    state = new_mood_state(NOW, "balanced")
    state[key] = [factory(index) for index in range(limit + 1)]  # type: ignore[operator]

    with pytest.raises(ValueError):
        validate_state(state)


def test_active_affect_accepts_only_bounded_trace_schema() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [valid_active_affect()]
    assert validate_state(state)["active_affects"] == state["active_affects"]

    for invalid_trace in (
        valid_active_affect(summary="금지된 합성 요약"),
        valid_active_affect(repeat_count=-1),
        valid_active_affect(repeat_count=4),
        valid_active_affect(repeat_count=True),
        valid_active_affect(last_event_at_utc="2099-01-01T00:00:00"),
        valid_active_affect(updated_at_utc="2099-01-01T09:00:00+09:00"),
    ):
        state["active_affects"] = [invalid_trace]
        with pytest.raises(ValueError):
            validate_state(state)


def test_validate_state_rejects_non_utc_updated_at_and_non_v4_recent_id() -> None:
    state = new_mood_state(NOW, "balanced")
    state["updated_at_utc"] = "2099-01-01T09:00:00+09:00"
    with pytest.raises(ValueError):
        validate_state(state)

    state = new_mood_state(NOW, "balanced")
    state["recent_event_ids"] = [str(uuid.uuid1())]
    with pytest.raises(ValueError):
        validate_state(state)


def test_validate_state_requires_exact_integer_version() -> None:
    state = new_mood_state(NOW, "balanced")
    state["version"] = 3.0

    with pytest.raises(ValueError):
        validate_state(state)


def test_validate_state_reports_invalid_unhashable_recent_id_as_value_error() -> None:
    state = new_mood_state(NOW, "balanced")
    state["recent_event_ids"] = [[]]

    with pytest.raises(ValueError):
        validate_state(state)


def test_validate_state_reports_unhashable_preset_as_value_error() -> None:
    state = new_mood_state(NOW, "balanced")
    state["preset"] = []

    with pytest.raises(ValueError):
        validate_state(state)


def test_validate_state_reports_unhashable_repair_stage_as_value_error() -> None:
    state = new_mood_state(NOW, "balanced")
    state["ruptures"] = [
        {
            "category": "broken_commitment",
            "severity": 0.2,
            "heat": 0.1,
            "repair_stage": [],
            "repeat_count": 0,
            "repair_evidence_count": 0,
            "last_negative_at_utc": "2099-01-01T00:00:00+00:00",
            "updated_at_utc": "2099-01-01T00:00:00+00:00",
        }
    ]

    with pytest.raises(ValueError):
        validate_state(state)


def test_loss_event_applies_golden_background_and_affect() -> None:
    transition = reduce_mood(
        new_mood_state(NOW, "balanced"),
        valid_event(
            event_id=synthetic_event_id("golden-loss"),
            kind="loss",
            target_scope="external",
            intensity=3,
        ),
        NOW,
        "balanced",
    )

    assert isinstance(transition, MoodTransition)
    assert transition.applied is True
    assert transition.rule_ids == ("event.background", "event.affect", "event.recorded")
    with pytest.raises(FrozenInstanceError):
        transition.applied = False  # type: ignore[misc]
    assert transition.state["background"] == {
        "valence": pytest.approx(-0.05),
        "energy": pytest.approx(-0.03),
        "tension": pytest.approx(0.02),
    }
    assert transition.state["active_affects"] == [
        {
            "affect": "sadness",
            "intensity": pytest.approx(0.24),
            "source_kind": "loss",
            "target_scope": "external",
            "relation_category": "none",
            "repeat_count": 0,
            "last_event_at_utc": "2099-01-01T00:00:00+00:00",
            "updated_at_utc": "2099-01-01T00:00:00+00:00",
        }
    ]


def test_loss_trace_survives_unrelated_external_events_without_relationship_change() -> None:
    state = new_mood_state(NOW, "balanced")
    for label, kind in (("loss", "loss"), ("success", "success"), ("plan", "novelty")):
        state = reduce_mood(
            state,
            valid_event(
                event_id=synthetic_event_id(label),
                kind=kind,
                target_scope="external",
                intensity=3,
            ),
            NOW,
            "balanced",
        ).state

    sadness = next(item for item in state["active_affects"] if item["affect"] == "sadness")
    assert sadness["intensity"] > 0.20
    assert state["relationship"] == {"affection": 0.0, "trust": 0.0}


def test_same_affect_trace_merges_with_saturation_resistance() -> None:
    state = new_mood_state(NOW, "balanced")
    first = valid_event(
        event_id=synthetic_event_id("loss-first"),
        kind="loss",
        target_scope="external",
        intensity=3,
    )
    second = valid_event(
        event_id=synthetic_event_id("loss-second"),
        kind="loss",
        target_scope="external",
        intensity=3,
    )

    state = reduce_mood(state, first, NOW, "balanced").state
    state = reduce_mood(state, second, NOW + timedelta(minutes=10), "balanced").state

    assert len(state["active_affects"]) == 1
    decayed = 0.24 * 2 ** (-600 / affect_half_life_seconds("sadness"))
    assert state["active_affects"][0]["intensity"] == pytest.approx(
        decayed + 0.24 * (1.0 - decayed)
    )
    assert state["active_affects"][0]["repeat_count"] == 1


def test_affect_repeat_count_saturates_at_three() -> None:
    state = new_mood_state(NOW, "balanced")
    for index in range(5):
        state = reduce_mood(
            state,
            valid_event(
                event_id=synthetic_event_id(f"repeat-cap-{index}"),
                kind="loss",
                target_scope="external",
            ),
            NOW + timedelta(minutes=index),
            "balanced",
        ).state

    assert state["active_affects"][0]["repeat_count"] == 3


@pytest.mark.parametrize(
    ("elapsed", "expected_repeat_count"),
    [(timedelta(minutes=30), 1), (timedelta(minutes=30, seconds=1), 0)],
)
def test_affect_repeat_count_uses_inclusive_thirty_minute_boundary(
    elapsed: timedelta,
    expected_repeat_count: int,
) -> None:
    state = reduce_mood(
        new_mood_state(NOW, "balanced"),
        valid_event(event_id=synthetic_event_id("repeat-first"), kind="loss", target_scope="external"),
        NOW,
        "balanced",
    ).state

    state = reduce_mood(
        state,
        valid_event(event_id=synthetic_event_id(str(elapsed)), kind="loss", target_scope="external"),
        NOW + elapsed,
        "balanced",
    ).state

    trace = state["active_affects"][0]
    assert trace["repeat_count"] == expected_repeat_count
    assert trace["last_event_at_utc"] == (NOW + elapsed).isoformat(timespec="seconds")


def test_active_affect_limit_evicts_lowest_priority_deterministically() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(affect="amusement", source_kind="connection", intensity=0.1),
        valid_active_affect(affect="amusement", source_kind="novelty", intensity=0.1),
        valid_active_affect(affect="joy", source_kind="success", intensity=0.2),
        valid_active_affect(affect="hurt", source_kind="conflict", intensity=0.2),
        valid_active_affect(affect="anxiety", source_kind="threat", intensity=0.2),
    ]

    transition = reduce_mood(
        state,
        valid_event(
            event_id=synthetic_event_id("sixth-trace"),
            kind="loss",
            target_scope="external",
            intensity=3,
        ),
        NOW,
        "balanced",
    )

    remaining = {(item["affect"], item["source_kind"]) for item in transition.state["active_affects"]}
    assert ("amusement", "connection") not in remaining
    assert ("amusement", "novelty") in remaining
    assert len(remaining) == 5
    assert "state.active_affects.limit" in transition.rule_ids


def test_active_affect_limit_uses_canonical_half_life_score() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(affect="amusement", source_kind="novelty", intensity=0.9),
        valid_active_affect(affect="sadness", source_kind="loss", intensity=0.01),
        valid_active_affect(affect="hurt", source_kind="conflict", intensity=1.0),
        valid_active_affect(affect="anxiety", source_kind="threat", intensity=1.0),
        valid_active_affect(affect="tenderness", source_kind="repair", intensity=1.0),
    ]

    transition = reduce_mood(
        state,
        valid_event(
            event_id=synthetic_event_id("half-life-pruning"),
            kind="success",
            target_scope="external",
            intensity=3,
        ),
        NOW,
        "balanced",
    )

    affects = {item["affect"] for item in transition.state["active_affects"]}
    assert "amusement" not in affects
    assert "sadness" in affects
    assert affect_half_life_seconds("amusement") == 600
    assert affect_half_life_seconds("sadness") == 86400
    assert AFFECT_HALF_LIFE_CLASS == {
        "joy": "short",
        "tenderness": "medium",
        "amusement": "very_short",
        "interest": "short",
        "sadness": "long",
        "hurt": "long",
        "anger": "medium",
        "anxiety": "medium",
    }
    assert HALF_LIFE_SECONDS == {
        "very_short": 600,
        "short": 3600,
        "medium": 21600,
        "long": 86400,
    }


def test_active_affect_limit_evicts_older_update_when_scores_tie() -> None:
    older = (NOW - timedelta(hours=1)).isoformat(timespec="seconds")
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(
            affect="amusement",
            source_kind="novelty",
            intensity=0.1,
            last_event_at_utc=older,
            updated_at_utc=older,
        ),
        valid_active_affect(affect="amusement", source_kind="connection", intensity=0.1),
        valid_active_affect(affect="hurt", source_kind="conflict", intensity=1.0),
        valid_active_affect(affect="anxiety", source_kind="threat", intensity=1.0),
        valid_active_affect(affect="tenderness", source_kind="repair", intensity=1.0),
    ]

    transition = reduce_mood(
        state,
        valid_event(
            event_id=synthetic_event_id("oldest-pruning"),
            kind="success",
            target_scope="external",
            intensity=3,
        ),
        NOW,
        "balanced",
    )

    amusement_sources = {
        item["source_kind"]
        for item in transition.state["active_affects"]
        if item["affect"] == "amusement"
    }
    assert amusement_sources == {"connection"}


def test_active_affect_limit_uses_affect_enum_order_after_time_tie() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(affect="amusement", source_kind="novelty", intensity=1.0),
        valid_active_affect(affect="joy", source_kind="connection", intensity=1.0 / 6.0),
        valid_active_affect(affect="hurt", source_kind="conflict", intensity=1.0),
        valid_active_affect(affect="anxiety", source_kind="threat", intensity=1.0),
        valid_active_affect(affect="tenderness", source_kind="repair", intensity=1.0),
    ]

    transition = reduce_mood(
        state,
        valid_event(
            event_id=synthetic_event_id("enum-pruning"),
            kind="loss",
            target_scope="external",
            intensity=3,
        ),
        NOW,
        "balanced",
    )

    affects = {item["affect"] for item in transition.state["active_affects"]}
    assert "joy" not in affects
    assert "amusement" in affects


def test_repeat_metadata_is_shared_by_all_affects_in_same_event_group() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(affect="sadness", source_kind="loss", intensity=1.0),
        valid_active_affect(affect="hurt", source_kind="conflict", intensity=1.0),
        valid_active_affect(affect="anxiety", source_kind="threat", intensity=1.0),
        valid_active_affect(affect="anger", source_kind="conflict", intensity=1.0),
    ]
    state = reduce_mood(
        state,
        valid_event(
            event_id=synthetic_event_id("connection-before-pruning"),
            kind="connection",
            target_scope="external",
            intensity=3,
        ),
        NOW,
        "balanced",
    ).state
    assert {
        item["affect"] for item in state["active_affects"] if item["source_kind"] == "connection"
    } == {"tenderness"}
    state["active_affects"] = [
        item for item in state["active_affects"] if item["affect"] != "anxiety"
    ]
    event_time = NOW + timedelta(minutes=10)

    transition = reduce_mood(
        state,
        valid_event(
            event_id=synthetic_event_id("connection-after-pruning"),
            kind="connection",
            target_scope="external",
            intensity=3,
        ),
        event_time,
        "balanced",
    )

    connection_traces = [
        item for item in transition.state["active_affects"] if item["source_kind"] == "connection"
    ]
    assert {item["affect"] for item in connection_traces} == {"joy", "tenderness"}
    assert {item["repeat_count"] for item in connection_traces} == {1}
    assert {item["last_event_at_utc"] for item in connection_traces} == {
        event_time.isoformat(timespec="seconds")
    }


def test_duplicate_event_id_is_complete_no_op() -> None:
    event = valid_event(event_id=synthetic_event_id("duplicate"), kind="success", target_scope="external")
    state = reduce_mood(new_mood_state(NOW, "balanced"), event, NOW, "balanced").state
    snapshot = deepcopy(state)

    transition = reduce_mood(state, event, NOW + timedelta(days=1), "expressive")

    assert transition == MoodTransition(state=snapshot, applied=False, rule_ids=("event.duplicate",))
    assert state == snapshot


@pytest.mark.parametrize("event_type", ["mapping", "mood_event"])
def test_duplicate_event_id_skips_event_and_time_normalization(event_type: str) -> None:
    event_id = synthetic_event_id("duplicate-before-normalization")
    state = reduce_mood(
        new_mood_state(NOW, "balanced"),
        valid_event(event_id=event_id, kind="success", target_scope="external"),
        NOW,
        "balanced",
    ).state
    snapshot = deepcopy(state)
    if event_type == "mapping":
        duplicate: object = {
            "event_id": event_id,
            "kind": [],
            "intensity": "invalid",
        }
    else:
        duplicate = normalize_event(valid_event(event_id=event_id), NOW)

    transition = reduce_mood(
        state,
        duplicate,
        datetime(2099, 1, 2),
        "expressive",
    )

    assert transition == MoodTransition(state=snapshot, applied=False, rule_ids=("event.duplicate",))
    assert state == snapshot


def test_invalid_event_id_does_not_bypass_new_event_normalization() -> None:
    state = new_mood_state(NOW, "balanced")

    with pytest.raises(ValueError):
        reduce_mood(
            state,
            {"event_id": "invalid-event-id"},
            datetime(2099, 1, 2),
            "balanced",
        )


def test_repeated_fallback_event_id_is_complete_no_op() -> None:
    raw_event = {"kind": "loss", "event_id": None}
    state = reduce_mood(new_mood_state(NOW, "balanced"), raw_event, NOW, "balanced").state
    snapshot = deepcopy(state)

    transition = reduce_mood(state, raw_event, NOW, "balanced")

    assert transition == MoodTransition(state=snapshot, applied=False, rule_ids=("event.duplicate",))
    assert state == snapshot


def test_recent_event_ids_keep_latest_sixty_four_ids() -> None:
    state = new_mood_state(NOW, "balanced")
    ids = [synthetic_event_id(f"ring-{index}") for index in range(65)]
    for index, event_id in enumerate(ids):
        state = reduce_mood(
            state,
            valid_event(
                event_id=event_id,
                kind="neutral",
                target_scope="external",
                intensity=0,
            ),
            NOW + timedelta(minutes=index),
            "balanced",
        ).state

    assert state["recent_event_ids"] == ids[-64:]
    assert state["revision"] == 65


def test_reduce_mood_does_not_mutate_input_state() -> None:
    state = new_mood_state(NOW, "balanced")
    snapshot = deepcopy(state)

    reduce_mood(
        state,
        valid_event(event_id=synthetic_event_id("immutable-input"), kind="loss", target_scope="external"),
        NOW,
        "balanced",
    )

    assert state == snapshot


def test_valid_zero_impact_event_is_recorded_without_numeric_or_relationship_change() -> None:
    state = new_mood_state(NOW, "balanced")
    event_id = synthetic_event_id("neutral-zero")

    transition = reduce_mood(
        state,
        valid_event(
            event_id=event_id,
            kind="neutral",
            target_scope="relationship",
            intensity=0,
        ),
        NOW + timedelta(minutes=1),
        "balanced",
    )

    assert transition.applied is True
    assert transition.rule_ids == ("event.recorded",)
    assert transition.state["background"] == state["background"]
    assert transition.state["active_affects"] == []
    assert transition.state["relationship"] == state["relationship"]
    assert transition.state["revision"] == 1
    assert transition.state["recent_event_ids"] == [event_id]


def test_presets_keep_direction_and_clamp_numeric_ranges() -> None:
    deltas = []
    for preset in ("calm", "balanced", "expressive"):
        transition = reduce_mood(
            new_mood_state(NOW, preset),
            valid_event(
                event_id=synthetic_event_id(f"preset-{preset}"),
                kind="success",
                target_scope="external",
                intensity=3,
            ),
            NOW,
            preset,
        )
        deltas.append(transition.state["background"]["valence"])

    assert 0.0 < deltas[0] < deltas[1] < deltas[2]

    state = new_mood_state(NOW, "expressive")
    state["background"] = {"valence": 0.99, "energy": 0.99, "tension": -0.99}
    clamped = reduce_mood(
        state,
        valid_event(
            event_id=synthetic_event_id("clamp"),
            kind="success",
            target_scope="external",
            intensity=3,
        ),
        NOW,
        "expressive",
    ).state

    assert clamped["background"]["valence"] == 1.0
    assert all(-1.0 <= value <= 1.0 for value in clamped["background"].values())
    assert all(0.0 <= item["intensity"] <= 1.0 for item in clamped["active_affects"])


@pytest.mark.parametrize(
    ("label", "event"),
    [
        (
            "external-negative",
            relationship_event(
                "external-negative",
                kind="conflict",
                target_scope="external",
                relation_category="disrespect",
            ),
        ),
        (
            "user-fatigue",
            relationship_event("user-fatigue", kind="loss", target_scope="user"),
        ),
        (
            "user-help-request",
            relationship_event("user-help-request", kind="threat", target_scope="user"),
        ),
        (
            "legitimate-refusal",
            relationship_event(
                "legitimate-refusal",
                kind="conflict",
                target_scope="user",
                relation_category="boundary_violation",
            ),
        ),
    ],
)
def test_non_relationship_events_do_not_change_relationship_or_ruptures(
    label: str,
    event: dict[str, object],
) -> None:
    del label
    state = new_mood_state(NOW, "balanced")

    transition = reduce_mood(state, event, NOW, "balanced")

    assert transition.state["relationship"] == state["relationship"]
    assert transition.state["ruptures"] == []
    assert "event.relationship" not in transition.rule_ids
    assert "event.rupture" not in transition.rule_ids


@pytest.mark.parametrize(
    ("label", "event", "expected"),
    [
        (
            "connection",
            relationship_event("golden-connection", kind="connection", relation_category="none"),
            {"affection": 0.018, "trust": 0.010},
        ),
        (
            "success",
            relationship_event("golden-success", kind="success", relation_category="none"),
            {"affection": 0.006, "trust": 0.012},
        ),
        (
            "broken-commitment",
            relationship_event(
                "golden-broken-commitment",
                kind="conflict",
                relation_category="broken_commitment",
            ),
            {"affection": -0.008, "trust": -0.040},
        ),
        (
            "follow-through",
            relationship_event(
                "golden-follow-through",
                kind="repair",
                relation_category="broken_commitment",
                repair_signal="follow_through",
            ),
            {"affection": 0.006, "trust": 0.016},
        ),
    ],
)
def test_relationship_golden_deltas(
    label: str,
    event: dict[str, object],
    expected: dict[str, float],
) -> None:
    del label
    transition = reduce_mood(new_mood_state(NOW, "balanced"), event, NOW, "balanced")

    assert transition.state["relationship"] == pytest.approx(expected)
    assert "event.relationship" in transition.rule_ids


def test_relationship_delta_uses_saturation_event_caps_and_final_clamp() -> None:
    positive = new_mood_state(NOW, "expressive")
    positive["relationship"] = {"affection": 0.99, "trust": 0.99}
    positive_result = reduce_mood(
        positive,
        relationship_event("saturated-positive", kind="connection", relation_category="none"),
        NOW,
        "expressive",
    ).state["relationship"]
    assert positive_result == pytest.approx(
        {"affection": 0.99 + 0.018 * 1.25 * 0.01, "trust": 0.99 + 0.010 * 1.25 * 0.01}
    )

    negative = new_mood_state(NOW, "expressive")
    negative["relationship"] = {"affection": 0.0, "trust": 0.0}
    negative_result = reduce_mood(
        negative,
        relationship_event(
            "capped-negative",
            kind="conflict",
            relation_category="broken_commitment",
        ),
        NOW,
        "expressive",
    ).state["relationship"]
    assert negative_result == pytest.approx({"affection": -0.010, "trust": -0.040})

    clamped = new_mood_state(NOW, "balanced")
    clamped["relationship"] = {"affection": 1.0, "trust": -1.0}
    clamped_result = reduce_mood(
        clamped,
        relationship_event("final-clamp", kind="connection", relation_category="none"),
        NOW,
        "balanced",
    ).state["relationship"]
    assert clamped_result == {"affection": 1.0, "trust": -1.0}


@pytest.mark.parametrize(
    "overrides",
    [
        {"clarity": "ambiguous"},
        {"certainty": "low"},
        {"target_scope": "unknown"},
        {"target_scope": "external"},
    ],
)
def test_uncertain_or_unrelated_events_are_relationship_safe(overrides: dict[str, object]) -> None:
    state = new_mood_state(NOW, "balanced")
    event = relationship_event(
        f"safe-{overrides}",
        kind="conflict",
        relation_category="boundary_violation",
        **overrides,
    )

    transition = reduce_mood(state, event, NOW, "balanced")

    assert transition.state["relationship"] == state["relationship"]
    assert transition.state["ruptures"] == []


def test_repeated_connection_uses_repeat_weight_and_relationship_saturation() -> None:
    state = new_mood_state(NOW, "balanced")
    expected_affection = 0.0
    actual_increments = []
    expected_increments = []
    for index, repeat_weight in enumerate((1.0, 0.85, 0.70, 0.55)):
        previous = state["relationship"]["affection"]
        expected_increment = 0.018 * repeat_weight * (1.0 - abs(expected_affection))
        expected_increments.append(expected_increment)
        expected_affection += expected_increment
        state = reduce_mood(
            state,
            relationship_event(
                f"repeat-connection-{index}",
                kind="connection",
                relation_category="none",
            ),
            NOW + timedelta(minutes=index),
            "balanced",
        ).state
        actual_increments.append(state["relationship"]["affection"] - previous)
        assert state["relationship"]["affection"] == pytest.approx(expected_affection)

    assert actual_increments == pytest.approx(expected_increments)


def test_only_clear_relationship_boundary_violation_opens_rupture() -> None:
    transition = reduce_mood(
        new_mood_state(NOW, "balanced"),
        relationship_event(
            "clear-boundary",
            kind="conflict",
            relation_category="boundary_violation",
        ),
        NOW,
        "balanced",
    )

    assert transition.state["ruptures"] == [
        {
            "category": "boundary_violation",
            "severity": pytest.approx(0.20),
            "heat": pytest.approx(0.20),
            "repair_stage": "open",
            "repeat_count": 0,
            "repair_evidence_count": 0,
            "last_negative_at_utc": NOW.isoformat(timespec="seconds"),
            "updated_at_utc": NOW.isoformat(timespec="seconds"),
        }
    ]
    assert "event.rupture" in transition.rule_ids


@pytest.mark.parametrize(
    ("signal", "severity_delta", "heat_delta"),
    [
        ("acknowledgment", -0.01, -0.04),
        ("apology", -0.06, -0.08),
        ("explanation", -0.02, -0.03),
    ],
)
def test_acknowledgment_apology_and_explanation_have_distinct_recovery(
    signal: str,
    severity_delta: float,
    heat_delta: float,
) -> None:
    state = new_mood_state(NOW, "balanced")
    state["ruptures"] = [seeded_rupture(severity=0.30, heat=0.30)]

    transition = reduce_mood(
        state,
        relationship_event(
            f"repair-{signal}",
            kind="repair",
            relation_category="broken_commitment",
            repair_signal=signal,
        ),
        NOW + timedelta(minutes=1),
        "balanced",
    )

    rupture = transition.state["ruptures"][0]
    assert rupture["severity"] == pytest.approx(0.30 + severity_delta)
    decayed_heat = 0.30 * 2 ** (-60 / (6 * 3600))
    assert rupture["heat"] == pytest.approx(decayed_heat + heat_delta)
    assert rupture["repair_stage"] == "acknowledged"
    assert rupture["repair_evidence_count"] == 0


@pytest.mark.parametrize(
    ("clarity", "certainty"),
    [
        ("inferred", "high"),
        ("explicit", "medium"),
        ("inferred", "medium"),
    ],
)
def test_explanation_requires_explicit_clarity_and_high_certainty_for_relationship_repair(
    clarity: str,
    certainty: str,
) -> None:
    state = new_mood_state(NOW, "balanced")
    state["relationship"] = {"affection": 0.20, "trust": -0.20}
    state["ruptures"] = [seeded_rupture(severity=0.30, heat=0.30)]
    relationship_snapshot = deepcopy(state["relationship"])
    rupture_snapshot = deepcopy(state["ruptures"])

    transition = reduce_mood(
        state,
        relationship_event(
            f"restricted-explanation-{clarity}-{certainty}",
            kind="repair",
            relation_category="broken_commitment",
            repair_signal="explanation",
            clarity=clarity,
            certainty=certainty,
        ),
        NOW + timedelta(minutes=1),
        "balanced",
    )

    assert transition.state["relationship"] == relationship_snapshot
    rupture = transition.state["ruptures"][0]
    assert rupture["severity"] == rupture_snapshot[0]["severity"]
    assert rupture["heat"] == pytest.approx(0.30 * 2 ** (-60 / (6 * 3600)))
    assert rupture["repair_stage"] == rupture_snapshot[0]["repair_stage"]
    assert rupture["repair_evidence_count"] == rupture_snapshot[0]["repair_evidence_count"]


def test_correction_then_distinct_follow_through_resolves_moderate_rupture() -> None:
    state = new_mood_state(NOW, "balanced")
    state["ruptures"] = [seeded_rupture()]
    state = reduce_mood(
        state,
        relationship_event(
            "correction-one",
            kind="repair",
            relation_category="broken_commitment",
            repair_signal="correction",
        ),
        NOW + timedelta(minutes=1),
        "balanced",
    ).state

    assert state["ruptures"][0]["repair_stage"] == "observing"
    assert state["ruptures"][0]["repair_evidence_count"] == 1
    assert state["ruptures"][0]["severity"] == pytest.approx(0.14)

    state = reduce_mood(
        state,
        relationship_event(
            "follow-through-two",
            kind="repair",
            relation_category="broken_commitment",
            repair_signal="follow_through",
        ),
        NOW + timedelta(minutes=2),
        "balanced",
    ).state
    assert state["ruptures"] == []


def test_duplicate_repair_id_does_not_increase_evidence() -> None:
    state = new_mood_state(NOW, "balanced")
    state["ruptures"] = [seeded_rupture(severity=0.30)]
    event = relationship_event(
        "duplicate-repair",
        kind="repair",
        relation_category="broken_commitment",
        repair_signal="correction",
    )
    state = reduce_mood(state, event, NOW + timedelta(minutes=1), "balanced").state
    snapshot = deepcopy(state)

    duplicate = reduce_mood(state, event, NOW + timedelta(minutes=2), "balanced")

    assert duplicate.applied is False
    assert duplicate.state == snapshot
    assert duplicate.state["ruptures"][0]["repair_evidence_count"] == 1


def test_valid_zero_impact_correction_still_counts_as_repair_evidence() -> None:
    state = new_mood_state(NOW, "balanced")
    state["ruptures"] = [seeded_rupture(severity=0.30, heat=0.30)]

    transition = reduce_mood(
        state,
        relationship_event(
            "zero-impact-correction",
            kind="repair",
            relation_category="broken_commitment",
            repair_signal="correction",
            intensity=0,
        ),
        NOW + timedelta(minutes=1),
        "balanced",
    )

    rupture = transition.state["ruptures"][0]
    assert rupture["severity"] == pytest.approx(0.30)
    assert rupture["heat"] == pytest.approx(0.30 * 2 ** (-60 / (6 * 3600)))
    assert rupture["repair_stage"] == "observing"
    assert rupture["repair_evidence_count"] == 1


def test_same_category_recurrence_resets_repair_and_increments_repeat() -> None:
    state = new_mood_state(NOW, "balanced")
    rupture = seeded_rupture(severity=0.18, heat=0.10)
    rupture["repair_stage"] = "observing"
    rupture["repair_evidence_count"] = 1
    state["ruptures"] = [rupture]
    event_time = NOW + timedelta(minutes=5)

    transition = reduce_mood(
        state,
        relationship_event(
            "recurring-broken-commitment",
            kind="conflict",
            relation_category="broken_commitment",
        ),
        event_time,
        "balanced",
    )

    recurrent = transition.state["ruptures"][0]
    assert recurrent["repeat_count"] == 1
    assert recurrent["repair_evidence_count"] == 0
    assert recurrent["repair_stage"] == "open"
    assert recurrent["severity"] == pytest.approx(0.18 + 0.18 * (1.0 - 0.18))
    decayed_heat = 0.10 * 2 ** (-300 / (6 * 3600))
    assert recurrent["heat"] == pytest.approx(decayed_heat + 0.18 * (1.0 - decayed_heat))
    assert recurrent["last_negative_at_utc"] == event_time.isoformat(timespec="seconds")
    assert recurrent["updated_at_utc"] == event_time.isoformat(timespec="seconds")


def test_unrelated_positive_event_is_not_repair_evidence() -> None:
    state = new_mood_state(NOW, "balanced")
    state["ruptures"] = [seeded_rupture()]

    transition = reduce_mood(
        state,
        relationship_event("unrelated-affection", kind="connection", relation_category="none"),
        NOW + timedelta(minutes=1),
        "balanced",
    )

    rupture = transition.state["ruptures"][0]
    assert rupture["severity"] == state["ruptures"][0]["severity"]
    assert rupture["heat"] == pytest.approx(0.18 * 2 ** (-60 / (6 * 3600)))
    assert rupture["repair_stage"] == state["ruptures"][0]["repair_stage"]


def test_apology_resolves_light_rupture_but_not_large_rupture() -> None:
    light = new_mood_state(NOW, "balanced")
    light["ruptures"] = [seeded_rupture(severity=0.08, heat=0.10)]
    apology = relationship_event(
        "light-apology",
        kind="repair",
        relation_category="broken_commitment",
        repair_signal="apology",
    )
    assert reduce_mood(light, apology, NOW + timedelta(minutes=1), "balanced").state["ruptures"] == []

    large = new_mood_state(NOW, "balanced")
    large["ruptures"] = [seeded_rupture(severity=0.30, heat=0.30)]
    remaining = reduce_mood(
        large,
        relationship_event(
            "large-apology",
            kind="repair",
            relation_category="broken_commitment",
            repair_signal="apology",
        ),
        NOW + timedelta(minutes=1),
        "balanced",
    ).state["ruptures"]
    assert len(remaining) == 1
    assert remaining[0]["severity"] == pytest.approx(0.24)


def test_repair_resolution_includes_exact_float_thresholds() -> None:
    apology_state = new_mood_state(NOW, "balanced")
    apology_state["ruptures"] = [seeded_rupture(severity=0.14, heat=0.20)]
    apology = relationship_event(
        "exact-apology-threshold",
        kind="repair",
        relation_category="broken_commitment",
        repair_signal="apology",
    )
    assert (
        reduce_mood(apology_state, apology, NOW + timedelta(minutes=1), "balanced").state[
            "ruptures"
        ]
        == []
    )

    evidence_state = new_mood_state(NOW, "balanced")
    evidence_state["ruptures"] = [seeded_rupture(severity=0.22, heat=0.22)]
    evidence_state = reduce_mood(
        evidence_state,
        relationship_event(
            "exact-threshold-correction",
            kind="repair",
            relation_category="broken_commitment",
            repair_signal="correction",
        ),
        NOW + timedelta(minutes=1),
        "balanced",
    ).state
    evidence_state = reduce_mood(
        evidence_state,
        relationship_event(
            "exact-threshold-follow-through",
            kind="repair",
            relation_category="broken_commitment",
            repair_signal="follow_through",
        ),
        NOW + timedelta(minutes=32),
        "balanced",
    ).state
    assert evidence_state["ruptures"] == []


def test_relationship_and_rupture_rules_are_stable_and_input_is_immutable() -> None:
    state = new_mood_state(NOW, "balanced")
    snapshot = deepcopy(state)

    transition = reduce_mood(
        state,
        relationship_event(
            "stable-rules",
            kind="conflict",
            relation_category="disrespect",
        ),
        NOW,
        "balanced",
    )

    assert state == snapshot
    assert transition.rule_ids == (
        "event.background",
        "event.affect",
        "event.relationship",
        "event.rupture",
        "event.recorded",
    )


def test_advance_time_is_deterministic_and_does_not_mutate_input() -> None:
    state = new_mood_state(NOW, "balanced")
    state["background"] = {"valence": 0.8, "energy": -0.6, "tension": 0.4}
    snapshot = deepcopy(state)
    now = NOW + timedelta(hours=3)

    first = advance_time(state, now, "balanced")
    second = advance_time(state, now, "balanced")

    assert first == second
    assert repr(first) == repr(second)
    assert state == snapshot
    assert first.applied is True
    assert first.state["updated_at_utc"] == now.isoformat(timespec="seconds")
    assert first.state["revision"] == 1
    assert first.state["recent_event_ids"] == state["recent_event_ids"]


def test_advance_time_applies_each_background_half_life_once() -> None:
    cases = (("valence", 12), ("energy", 4), ("tension", 6))
    for field, hours in cases:
        state = new_mood_state(NOW, "balanced")
        state["background"][field] = 0.8

        result = advance_time(state, NOW + timedelta(hours=hours), "balanced").state

        assert result["background"][field] == pytest.approx(0.4)


def test_advance_time_uses_canonical_affect_half_life_and_removes_faint_trace() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(affect="amusement", intensity=0.6),
        valid_active_affect(affect="sadness", intensity=0.01, source_kind="loss"),
    ]

    result = advance_time(state, NOW + timedelta(seconds=600), "balanced").state

    assert result["active_affects"][0]["affect"] == "amusement"
    assert result["active_affects"][0]["intensity"] == pytest.approx(0.3)
    assert all(item["affect"] != "sadness" for item in result["active_affects"])
    assert affect_half_life_seconds("amusement") == 600


def test_advance_time_decays_only_rupture_heat_and_preserves_relationship() -> None:
    state = new_mood_state(NOW, "balanced")
    state["relationship"] = {"affection": 0.31, "trust": -0.27}
    rupture = seeded_rupture(severity=0.7, heat=0.6)
    rupture["repair_stage"] = "observing"
    rupture["repeat_count"] = 2
    rupture["repair_evidence_count"] = 1
    state["ruptures"] = [rupture]
    expected = deepcopy(rupture)

    result = advance_time(state, NOW + timedelta(hours=6), "balanced").state
    actual = result["ruptures"][0]

    assert result["relationship"] == state["relationship"]
    assert actual["heat"] == pytest.approx(0.3)
    assert actual["updated_at_utc"] == (NOW + timedelta(hours=6)).isoformat(timespec="seconds")
    for field in (
        "category",
        "severity",
        "repair_stage",
        "repeat_count",
        "repair_evidence_count",
        "last_negative_at_utc",
    ):
        assert actual[field] == expected[field]


@pytest.mark.parametrize("now", [NOW, NOW - timedelta(seconds=1)])
def test_advance_time_same_or_past_is_complete_no_op(now: datetime) -> None:
    state = new_mood_state(NOW, "balanced")
    snapshot = deepcopy(state)

    result = advance_time(state, now, "expressive")

    assert result == MoodTransition(state=snapshot, applied=False, rule_ids=())
    assert state == snapshot


def test_advance_time_preserves_microseconds_and_same_now_is_no_op() -> None:
    state = new_mood_state(NOW, "balanced")
    now = NOW + timedelta(microseconds=500_000)

    first = advance_time(state, now, "balanced")
    second = advance_time(first.state, now, "balanced")

    assert first.applied is True
    assert first.state["updated_at_utc"] == "2099-01-01T00:00:00.500000+00:00"
    assert second == MoodTransition(state=first.state, applied=False, rule_ids=())
    assert second.state["revision"] == first.state["revision"]


def test_advance_time_rejects_non_utc_aware_datetime() -> None:
    state = new_mood_state(NOW, "balanced")
    with pytest.raises(ValueError):
        advance_time(state, datetime(2099, 1, 2), "balanced")


def test_reduce_mood_decays_before_event_and_increments_revision_once() -> None:
    state = new_mood_state(NOW, "balanced")
    state["background"]["valence"] = 0.8

    transition = reduce_mood(
        state,
        valid_event(
            event_id=synthetic_event_id("decay-before-event"),
            kind="success",
            target_scope="external",
            intensity=3,
        ),
        NOW + timedelta(hours=12),
        "balanced",
    )

    assert transition.state["background"]["valence"] == pytest.approx(0.4 + 0.04)
    assert transition.state["revision"] == 1
    assert transition.rule_ids.index("time.background") < transition.rule_ids.index("event.background")


def test_duplicate_event_does_not_apply_time_decay() -> None:
    event = valid_event(event_id=synthetic_event_id("duplicate-no-decay"))
    state = reduce_mood(new_mood_state(NOW, "balanced"), event, NOW, "balanced").state
    state["background"]["valence"] = 0.8
    snapshot = deepcopy(state)

    result = reduce_mood(state, event, NOW + timedelta(days=1), "balanced")

    assert result == MoodTransition(state=snapshot, applied=False, rule_ids=("event.duplicate",))


def _first_spontaneous_bucket(seed_revision: int = 0, preset: str = "balanced") -> int:
    for bucket in range(1, 1000):
        material = f"mood-v3|{preset}|{seed_revision}|{bucket}".encode("utf-8")
        sample = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") / 2**64
        if sample > 0.92:
            return bucket
    raise AssertionError("합성 탐색 범위에서 자발 변화 bucket을 찾지 못했습니다.")


def test_spontaneous_impulse_uses_exact_hash_bucket_and_fixed_digest_bytes() -> None:
    bucket = _first_spontaneous_bucket()
    now = datetime.fromtimestamp(bucket * 21600, tz=timezone.utc)
    state = new_mood_state(now - timedelta(hours=6), "balanced")
    digest = hashlib.sha256(f"mood-v3|balanced|0|{bucket}".encode("utf-8")).digest()
    expected_valence = int.from_bytes(digest[8:16], "big") / 2**64 * 0.03 - 0.015
    expected_energy = int.from_bytes(digest[16:24], "big") / 2**64 * 0.03 - 0.015

    result = advance_time(state, now, "affectionate")

    assert result.state["background"]["valence"] == pytest.approx(expected_valence)
    assert result.state["background"]["energy"] == pytest.approx(expected_energy)
    assert abs(result.state["background"]["valence"]) <= 0.015
    assert abs(result.state["background"]["energy"]) <= 0.015
    assert result.state["spontaneous"] == {
        "last_at_utc": now.isoformat(timespec="seconds"),
        "seed_revision": 1,
    }
    assert "time.spontaneous" in result.rule_ids


def test_spontaneous_cooldown_and_threshold_leave_metadata_unchanged() -> None:
    state = new_mood_state(NOW, "balanced")
    state["spontaneous"] = {
        "last_at_utc": (NOW - timedelta(hours=5, minutes=58)).isoformat(timespec="seconds"),
        "seed_revision": 4,
    }
    cooldown = advance_time(state, NOW + timedelta(minutes=1), "balanced").state
    assert cooldown["spontaneous"] == state["spontaneous"]

    for bucket in range(1, 1000):
        digest = hashlib.sha256(f"mood-v3|balanced|0|{bucket}".encode("utf-8")).digest()
        if int.from_bytes(digest[:8], "big") / 2**64 <= 0.92:
            now = datetime.fromtimestamp(bucket * 21600, tz=timezone.utc)
            quiet = new_mood_state(now - timedelta(hours=6), "balanced")
            result = advance_time(quiet, now, "balanced").state
            assert result["spontaneous"] == quiet["spontaneous"]
            break


def test_spontaneous_does_not_change_relationship_rupture_tension_or_guidance() -> None:
    bucket = _first_spontaneous_bucket()
    now = datetime.fromtimestamp(bucket * 21600, tz=timezone.utc)
    state = new_mood_state(now - timedelta(hours=6), "balanced")
    state["relationship"] = {"affection": -0.6, "trust": -0.5}
    state["ruptures"] = [seeded_rupture(severity=0.8, heat=0.0)]
    before_guidance = derive_behavior_guidance(state, "ko")

    result = advance_time(state, now, "balanced").state

    assert result["relationship"] == state["relationship"]
    assert result["ruptures"][0]["severity"] == state["ruptures"][0]["severity"]
    assert result["background"]["tension"] == state["background"]["tension"]
    assert derive_behavior_guidance(result, "ko") == before_guidance


def test_snapshot_primary_threshold_tie_secondary_and_input_immutability() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(affect="anger", intensity=0.3, source_kind="conflict"),
        valid_active_affect(affect="joy", intensity=0.3, source_kind="success"),
        valid_active_affect(affect="hurt", intensity=0.23, source_kind="conflict"),
    ]
    original = deepcopy(state)

    snapshot = derive_snapshot(state)

    assert snapshot["primary_emotion"] == "joy"
    assert snapshot["secondary_emotion"] == "anger"
    assert isinstance(snapshot["behavior_guidance"], tuple)
    assert state == original
    assert set(snapshot) == {
        "state",
        "primary_emotion",
        "secondary_emotion",
        "behavior_guidance",
    }
    assert snapshot["state"] == state
    snapshot["state"]["relationship"]["trust"] = -0.9
    assert state == original


def test_snapshot_threshold_secondary_ratio_hysteresis_and_invalid_previous() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(affect="joy", intensity=0.20, source_kind="success"),
        valid_active_affect(affect="sadness", intensity=0.16, source_kind="loss"),
    ]
    assert derive_snapshot(state)["secondary_emotion"] == "sadness"
    assert derive_snapshot(state, "sadness")["primary_emotion"] == "sadness"
    assert derive_snapshot(state, "unknown")["primary_emotion"] == "joy"

    state["active_affects"][1]["intensity"] = 0.14
    assert derive_snapshot(state)["secondary_emotion"] is None
    state["active_affects"][0]["intensity"] = 0.15
    assert derive_snapshot(state)["primary_emotion"] is None


def test_snapshot_uses_max_not_sum_for_duplicate_affect_traces() -> None:
    state = new_mood_state(NOW, "balanced")
    state["active_affects"] = [
        valid_active_affect(affect="joy", intensity=0.12, source_kind="success"),
        valid_active_affect(affect="joy", intensity=0.11, source_kind="success"),
        valid_active_affect(affect="anger", intensity=0.18, source_kind="conflict"),
    ]
    assert derive_snapshot(state)["primary_emotion"] == "anger"


@pytest.mark.parametrize("language", ["ko", "en", "ja", "unsupported"])
def test_behavior_guidance_is_localized_safe_and_contains_no_raw_state(language: str) -> None:
    state = new_mood_state(NOW, "balanced")
    state["background"]["energy"] = -0.7
    state["relationship"] = {"affection": -0.6, "trust": -0.5}
    state["ruptures"] = [seeded_rupture(severity=0.8, heat=0.7)]
    state["recent_event_ids"] = [synthetic_event_id("private-id")]

    guidance = derive_behavior_guidance(state, language)

    assert isinstance(guidance, tuple)
    assert guidance
    assert synthetic_event_id("private-id") not in " ".join(guidance)
    assert "0.7" not in " ".join(guidance)
    assert derive_behavior_guidance(state, "unsupported") == derive_behavior_guidance(state, "ko")
    safety_words = {
        "ko": "안전",
        "en": "Safety",
        "ja": "安全",
        "unsupported": "안전",
    }
    assert safety_words[language] in guidance[-1]


@pytest.mark.parametrize(
    ("affect", "source_kind"),
    [("joy", "success"), ("anger", "conflict")],
)
def test_behavior_guidance_does_not_use_active_affects(affect: str, source_kind: str) -> None:
    neutral = new_mood_state(NOW, "balanced")
    affect_only = deepcopy(neutral)
    affect_only["active_affects"] = [
        valid_active_affect(affect=affect, intensity=0.8, source_kind=source_kind)
    ]

    assert derive_behavior_guidance(affect_only, "ko") == derive_behavior_guidance(neutral, "ko")
