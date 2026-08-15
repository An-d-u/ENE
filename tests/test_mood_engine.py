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
    affect_half_life_seconds,
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
    assert state["active_affects"][0]["intensity"] == pytest.approx(0.24 + 0.24 * (1.0 - 0.24))
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
