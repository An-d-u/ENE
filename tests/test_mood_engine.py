from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
import hashlib
import math
import uuid

import pytest

from src.ai.mood_engine import MoodEvent, new_mood_state, normalize_event, validate_state


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
