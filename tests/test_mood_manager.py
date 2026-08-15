from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import uuid

import pytest

from src.ai import mood_engine
from src.ai.mood_manager import MoodManager
from src.ai.mood_policy import allowed_stances
from src.ai.response_pipeline import execute_final_response
from src.ai.response_protocol import ProviderResponse, ResponseMode, ResponseStatus
from src.core import app_paths
from tests.structured_response_fixtures import make_requirements, valid_envelope_json


NOW = datetime(2026, 8, 15, 3, 0, tzinfo=timezone.utc)


def _clock() -> datetime:
    return NOW


def _event(**overrides):
    event = {
        "kind": "connection", "target_scope": "relationship",
        "relation_category": "none", "intensity": 2, "clarity": "explicit",
        "certainty": "high", "controllability": "high", "repair_signal": "none",
    }
    event.update(overrides)
    return event


def _manager(path: Path, **kwargs) -> MoodManager:
    return MoodManager(state_file=path, clock=_clock, **kwargs)


def test_bom_v2_migration_preserves_backup_and_maps_only_supported_fields(tmp_path):
    state_file = tmp_path / "mood_state.json"
    payload = {
        "version": 2, "profile": "affectionate",
        "axes": {"valence": 2.0, "energy": -0.2, "bond": 0.6, "stress": 0.3},
        "current_mood": "guarded", "temporary_state": "pout",
        "updated_at": "2026-08-15T12:00:00",
        "recent_events": [{"reason": "합성 과거 사건"}],
    }
    original = json.dumps(payload, ensure_ascii=False).encode("utf-8-sig")
    state_file.write_bytes(original)

    manager = _manager(state_file, local_timezone=timezone(timedelta(hours=9)))

    assert (tmp_path / "mood_state.json.v2.bak").read_bytes() == original
    assert not state_file.read_bytes().startswith(b"\xef\xbb\xbf")
    assert manager.state["version"] == 3
    assert manager.state["preset"] == "balanced"
    assert manager.state["background"] == {"valence": 1.0, "energy": -0.2, "tension": 0.3}
    assert manager.state["relationship"] == {"affection": 0.6, "trust": 0.0}
    assert manager.state["active_affects"] == []
    assert manager.state["ruptures"] == []
    assert manager.state["updated_at_utc"] == "2026-08-15T03:00:00+00:00"
    assert manager.get_load_status() == {"error_code": None, "write_locked": False}


def test_existing_v2_backup_is_not_replaced(tmp_path):
    state_file = tmp_path / "mood_state.json"
    payload = {"version": 2, "profile": "calm", "axes": {
        "valence": 0, "energy": 0, "bond": 0, "stress": 0,
    }, "updated_at": "2026-08-15T03:00:00+00:00"}
    state_file.write_text(json.dumps(payload), encoding="utf-8")
    backup = tmp_path / "mood_state.json.v2.bak"
    backup.write_bytes(b"first-backup")

    _manager(state_file)

    assert backup.read_bytes() == b"first-backup"


@pytest.mark.parametrize(("raw", "error_code"), [
    (json.dumps({"version": 99}).encode(), "future_version"),
    (b"{not-json", "corrupt_state"),
    (json.dumps({"version": 3}).encode(), "corrupt_state"),
])
def test_unusable_existing_state_is_locked_without_modifying_original(tmp_path, raw, error_code):
    state_file = tmp_path / "mood_state.json"
    state_file.write_bytes(raw)
    manager = _manager(state_file)
    before = deepcopy(manager.state)

    snapshot = manager.apply_event(str(uuid.uuid4()), _event())

    assert manager.get_load_status() == {"error_code": error_code, "write_locked": True}
    assert manager.state == before
    assert state_file.read_bytes() == raw
    assert snapshot == manager.get_snapshot()


def test_apply_event_save_failure_rolls_back_state_and_file(tmp_path, monkeypatch):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    manager.advance_time_and_save()
    before_state = deepcopy(manager.state)
    before_bytes = state_file.read_bytes()
    monkeypatch.setattr(
        "src.ai.mood_manager.app_paths.save_json_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk")),
    )

    snapshot = manager.apply_event(str(uuid.uuid4()), _event())

    assert manager.state == before_state
    assert state_file.read_bytes() == before_bytes
    assert snapshot == manager.get_snapshot()


def test_preview_matches_reducer_without_mutating_state_file_or_hysteresis(tmp_path):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    manager.advance_time_and_save()
    event_id = str(uuid.uuid4())
    analysis = _event()
    expected = mood_engine.reduce_mood(manager.state, {**analysis, "event_id": event_id}, NOW, "balanced")
    before_state = deepcopy(manager.state)
    before_bytes = state_file.read_bytes()
    before_primary = manager._last_primary_emotion

    preview = manager.preview_event(event_id, analysis)

    assert preview["background"] == expected.state["background"]
    assert manager.state == before_state
    assert state_file.read_bytes() == before_bytes
    assert manager._last_primary_emotion == before_primary


def test_first_explicit_disrespect_preview_allows_boundary_stance(tmp_path):
    manager = _manager(tmp_path / "mood_state.json")
    analysis = {
        "event": _event(
            kind="conflict",
            target_scope="relationship",
            relation_category="disrespect",
            intensity=3,
        ),
        "risk_class": "none",
        "proposed_stance": "boundary",
    }

    preview = manager.preview_event(str(uuid.uuid4()), analysis)

    assert preview["ruptures"][0]["severity"] == pytest.approx(0.16)
    assert "boundary" in allowed_stances(preview, "none")


@pytest.mark.parametrize("risk_class", ["concern", "urgent"])
def test_safety_risk_relationship_conflict_cannot_damage_persisted_relationship(
    tmp_path, risk_class
):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    manager.advance_time_and_save()
    before_relationship = deepcopy(manager.state["relationship"])
    analysis = {
        "event": _event(
            kind="conflict",
            target_scope="relationship",
            relation_category="boundary_violation",
            intensity=3,
        ),
        "risk_class": risk_class,
        "proposed_stance": "cooperative",
    }

    event_id = str(uuid.uuid4())
    preview = manager.preview_event(event_id, analysis)
    manager.apply_event(event_id, analysis)
    persisted = json.loads(state_file.read_text(encoding="utf-8"))
    applied_state = deepcopy(manager.state)
    applied_bytes = state_file.read_bytes()
    manager.apply_event(event_id, analysis)

    assert preview["relationship"] == before_relationship
    assert preview["ruptures"] == []
    assert preview["active_affects"]
    assert preview["background"] != {"valence": 0.0, "energy": 0.0, "tension": 0.0}
    assert manager.state["relationship"] == before_relationship
    assert manager.state["ruptures"] == []
    assert manager.state["active_affects"]
    assert persisted["relationship"] == before_relationship
    assert persisted["ruptures"] == []
    assert manager.state == applied_state
    assert state_file.read_bytes() == applied_bytes


def test_peek_snapshot_is_deep_and_does_not_mutate_state_file_or_hysteresis(tmp_path):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    manager.advance_time_and_save()
    manager._last_primary_emotion = "synthetic-hysteresis-marker"
    before_state = deepcopy(manager.state)
    before_bytes = state_file.read_bytes()
    before_primary = manager._last_primary_emotion

    snapshot = manager.peek_snapshot()
    snapshot["background"]["energy"] = 999

    assert manager.state == before_state
    assert state_file.read_bytes() == before_bytes
    assert manager._last_primary_emotion == before_primary


def test_policy_preview_failure_uses_one_pure_peek_without_manager_mutation(tmp_path):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    manager.advance_time_and_save()
    manager._last_primary_emotion = "synthetic-hysteresis-marker"
    before_state = deepcopy(manager.state)
    before_revision = manager.state["revision"]
    before_bytes = state_file.read_bytes()
    before_primary = manager._last_primary_emotion
    peek_calls = []

    def failing_preview(_analysis):
        raise RuntimeError("synthetic preview failure")

    def pure_peek():
        peek_calls.append("peek")
        return manager.peek_snapshot()

    analysis = {
        "event": _event(clarity="explicit"),
        "risk_class": "none",
        "proposed_stance": "cooperative",
    }
    responses = [
        ProviderResponse(
            carrier=valid_envelope_json(mood_analysis=analysis),
            status=ResponseStatus.COMPLETE,
            mode=ResponseMode.JSON_SCHEMA,
        )
    ]

    result = execute_final_response(
        lambda _attempt: responses.pop(0),
        requirements=make_requirements(
            enable_analysis=True,
            enable_mood=True,
            enable_mood_analysis=True,
        ),
        mood_snapshot_provider=pure_peek,
        mood_preview=failing_preview,
    )

    assert result.payload[10]["proposed_stance"] == "cooperative"
    assert peek_calls == ["peek"]
    assert manager.state == before_state
    assert manager.state["revision"] == before_revision
    assert state_file.read_bytes() == before_bytes
    assert manager._last_primary_emotion == before_primary


def test_deprecated_paths_are_complete_noops(tmp_path):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    manager.advance_time_and_save()
    before_state = deepcopy(manager.state)
    before_bytes = state_file.read_bytes()
    before_snapshot = manager.get_snapshot()

    assert manager.on_user_message("합성 메시지", image_count=2) == before_snapshot
    assert manager.on_user_analysis(_event()) == before_snapshot
    assert manager.on_assistant_emotion("joy") == before_snapshot
    assert manager.state == before_state
    assert state_file.read_bytes() == before_bytes


def test_head_pat_applies_valid_connection_without_raw_text(tmp_path):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    before = manager.get_snapshot()

    snapshot = manager.on_head_pat()

    assert snapshot["revision"] == before["revision"] + 1
    assert snapshot["relationship"]["affection"] > before["relationship"]["affection"]
    assert any(item["affect"] == "tenderness" for item in snapshot["active_affects"])
    assert len(manager.state["recent_event_ids"]) == 1
    assert uuid.UUID(manager.state["recent_event_ids"][0]).version == 4
    saved = state_file.read_text(encoding="utf-8")
    assert "head_pat" not in saved
    assert "쓰다듬" not in saved


def test_analysis_wrapper_forces_host_identity_and_ignores_freeform_hints(tmp_path):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    host_id, embedded_id = str(uuid.uuid4()), str(uuid.uuid4())
    analysis = {"event": {**_event(), "event_id": embedded_id,
        "reason": "저장하면 안 되는 합성 설명", "bond_delta_hint": "high_positive"}}

    manager.apply_event(host_id, analysis, "2026-08-15T03:00:00+00:00")
    saved_text = state_file.read_text(encoding="utf-8")

    assert host_id in manager.state["recent_event_ids"]
    assert embedded_id not in saved_text
    assert "reason" not in saved_text
    assert "delta_hint" not in saved_text


def test_snapshot_exposes_v3_and_legacy_facades_without_persisting_aliases(tmp_path):
    manager = _manager(tmp_path / "mood_state.json")

    first = manager.get_snapshot()
    second = manager.get_snapshot()

    assert first == second
    assert first["background"] == manager.state["background"]
    assert first["relationship"] == manager.state["relationship"]
    assert first["valence"] == first["background"]["valence"]
    assert first["bond"] == first["relationship"]["affection"]
    assert first["behavior_guidance"] == mood_engine.derive_snapshot(manager.state)["behavior_guidance"]
    assert set(first["expression_traits"]) == {"warmth", "initiative", "teasing",
        "guardedness", "sensitivity", "attachment_expression", "reply_length_bias"}
    assert all(0.0 <= value <= 1.0 for value in first["expression_traits"].values())
    assert "current_mood" not in manager.state
    assert "expression_traits" not in manager.state


def test_context_blocks_hide_raw_state_details_in_all_languages(tmp_path):
    manager = _manager(tmp_path / "mood_state.json")

    for language in ("ko", "en", "ja"):
        block = manager.build_context_block(language)
        assert block
        assert "revision" not in block
        assert "updated_at" not in block
        assert "recent_event_ids" not in block
        assert "0.0" not in block


def test_state_read_failure_locks_without_attempting_save(tmp_path, monkeypatch):
    state_file = tmp_path / "mood_state.json"
    state_file.write_bytes(b"original")
    monkeypatch.setattr(
        "src.ai.mood_manager.app_paths.read_bytes_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("read denied")),
    )
    manager = _manager(state_file)

    assert manager.get_load_status() == {"error_code": "state_read_failed", "write_locked": True}


def test_missing_authoritative_state_starts_unlocked(tmp_path):
    state_file = tmp_path / "mood_state.json"

    manager = _manager(state_file)

    assert manager.get_load_status() == {"error_code": None, "write_locked": False}


def test_migration_exception_locks_and_preserves_original(tmp_path, monkeypatch):
    state_file = tmp_path / "mood_state.json"
    payload = {"version": 2, "profile": "calm", "axes": {
        "valence": 0, "energy": 0, "bond": 0, "stress": 0,
    }, "updated_at": "2026-08-15T03:00:00+00:00"}
    original = json.dumps(payload).encode()
    state_file.write_bytes(original)
    monkeypatch.setattr(MoodManager, "_migrate_v2", lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")))

    manager = _manager(state_file)

    assert manager.get_load_status() == {"error_code": "migration_failed", "write_locked": True}
    assert state_file.read_bytes() == original


def test_backup_failure_prevents_migration_replace(tmp_path, monkeypatch):
    state_file = tmp_path / "mood_state.json"
    payload = {"version": 2, "profile": "calm", "axes": {
        "valence": 0, "energy": 0, "bond": 0, "stress": 0,
    }, "updated_at": "2026-08-15T03:00:00+00:00"}
    original = json.dumps(payload).encode()
    state_file.write_bytes(original)
    original_write = app_paths.write_bytes_data_atomic

    def fail_backup(destination, payload_bytes, **kwargs):
        if destination.name.endswith(".v2.bak"):
            raise OSError("backup denied")
        return original_write(destination, payload_bytes, **kwargs)

    monkeypatch.setattr(app_paths, "write_bytes_data_atomic", fail_backup)
    manager = _manager(state_file)

    assert manager.get_load_status() == {"error_code": "migration_failed", "write_locked": True}
    assert state_file.read_bytes() == original


def test_reset_locked_state_preserves_recovery_backup_and_unlocks(tmp_path):
    state_file = tmp_path / "mood_state.json"
    original = b"{broken"
    state_file.write_bytes(original)
    manager = _manager(state_file)
    assert manager.get_last_reset_status() == {"attempted": False, "ok": False}

    snapshot = manager.reset_state()

    backups = list(tmp_path.glob("mood_state.json.recovery.*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    assert snapshot["version"] == 3
    assert manager.get_load_status() == {"error_code": None, "write_locked": False}
    assert manager.get_last_reset_status() == {"attempted": True, "ok": True}
    assert "last_reset" not in state_file.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("original", "expected_error"),
    [
        (b"{broken", "corrupt_state"),
        (json.dumps({"version": 4}).encode("utf-8"), "future_version"),
    ],
)
def test_reset_failure_keeps_lock_state_and_original(
    tmp_path, monkeypatch, original, expected_error
):
    state_file = tmp_path / "mood_state.json"
    state_file.write_bytes(original)
    manager = _manager(state_file)
    before = deepcopy(manager.state)
    monkeypatch.setattr(
        "src.ai.mood_manager.app_paths.save_json_data",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("save denied")),
    )
    manager.reset_state()

    assert manager.state == before
    assert manager.get_load_status() == {"error_code": expected_error, "write_locked": True}
    assert manager.get_last_reset_status() == {"attempted": True, "ok": False}
    assert state_file.read_bytes() == original


def test_reset_failure_reports_false_for_unlocked_state(tmp_path, monkeypatch):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    before = deepcopy(manager.state)
    monkeypatch.setattr(
        manager,
        "_write_state",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("save denied")),
    )

    snapshot = manager.reset_state()

    assert snapshot == manager.get_snapshot()
    assert manager.state == before
    assert manager.get_load_status() == {"error_code": None, "write_locked": False}
    assert manager.get_last_reset_status() == {"attempted": True, "ok": False}


def test_repeated_resets_with_same_clock_create_distinct_recovery_backups(tmp_path):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    manager.reset_state()
    first_bytes = state_file.read_bytes()

    manager.reset_state()
    second_bytes = state_file.read_bytes()
    manager.reset_state()

    backups = list(tmp_path.glob("mood_state.json.recovery.*.bak"))
    assert len(backups) == 2
    assert {backup.read_bytes() for backup in backups} == {first_bytes, second_bytes}


def test_duplicate_event_does_not_save_again(tmp_path, monkeypatch):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    event_id = str(uuid.uuid4())
    manager.apply_event(event_id, _event())
    calls = 0
    original_write = manager._write_state

    def count_write(candidate):
        nonlocal calls
        calls += 1
        return original_write(candidate)

    monkeypatch.setattr(manager, "_write_state", count_write)
    before = deepcopy(manager.state)

    manager.apply_event(event_id, _event())

    assert calls == 0
    assert manager.state == before


def test_noop_advance_tolerates_state_path_metadata_failure(tmp_path, monkeypatch):
    state_file = tmp_path / "mood_state.json"
    manager = _manager(state_file)
    manager.reset_state()
    before = deepcopy(manager.state)
    before_bytes = state_file.read_bytes()
    original_exists = Path.exists

    def fail_target_exists(path):
        if path == state_file:
            raise OSError("metadata denied")
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fail_target_exists)

    snapshot = manager.advance_time_and_save()

    assert snapshot == manager.get_snapshot()
    assert manager.state == before
    assert state_file.read_bytes() == before_bytes
