from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest

from src.core import life_session_tracker
from src.core.life_session_tracker import AppSessionTracker, InactiveStartCandidate
from src.core.local_time import (
    TIMEZONE_UNAVAILABLE,
    UTC_ZONE,
    LocalTimeContext,
    LocalTimeResolution,
)


UTC = timezone.utc
SESSION_KEYS = {
    "version",
    "session_id",
    "started_at",
    "last_seen_at",
    "status",
    "stopped_at",
}
SESSION_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_SESSION_ID = "123e4567-e89b-42d3-b456-426614174001"


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def _at(second: int, *, microsecond: int = 0) -> datetime:
    return datetime(2099, 1, 2, 3, 4, second, microsecond, tzinfo=UTC)


def _state(
    *,
    session_id: str = SESSION_ID,
    started_at: datetime | str = _at(1),
    last_seen_at: datetime | str = _at(2),
    status: str = "running",
    stopped_at: datetime | str | None = None,
) -> dict[str, object]:
    def encode(value: datetime | str | None) -> str | None:
        return value.isoformat() if isinstance(value, datetime) else value

    return {
        "version": 1,
        "session_id": session_id,
        "started_at": encode(started_at),
        "last_seen_at": encode(last_seen_at),
        "status": status,
        "stopped_at": encode(stopped_at),
    }


def _write_state(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read_state(path: Path) -> dict[str, object]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _assert_uuid4(value: object) -> None:
    assert isinstance(value, str)
    parsed = UUID(value)
    assert parsed.version == 4
    assert str(parsed) == value


@pytest.mark.parametrize("initial_content", [None, "{synthetic-corrupt-json-2099"])
def test_missing_or_corrupt_state_starts_fresh_running_session(
    tmp_path: Path,
    initial_content: str | None,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    if initial_content is not None:
        state_path.write_text(initial_content, encoding="utf-8")

    tracker = AppSessionTracker(state_path, now=lambda: _at(10, microsecond=999999))

    assert tracker.start_session() is None
    saved = _read_state(state_path)
    assert set(saved) == SESSION_KEYS
    assert saved["version"] == 1
    _assert_uuid4(saved["session_id"])
    assert saved["started_at"] == _at(10).isoformat()
    assert saved["last_seen_at"] == _at(10).isoformat()
    assert saved["status"] == "running"
    assert saved["stopped_at"] is None
    assert tracker.degraded is False
    assert tracker.life_records_writable is True
    assert tracker.reason is None
    tracker.release_lease()


@pytest.mark.parametrize(
    "read_error",
    [
        FileNotFoundError("synthetic-authoritative-missing-2099"),
        OSError("synthetic-authoritative-read-error-2099"),
    ],
)
def test_authoritative_missing_or_read_error_never_uses_stale_runtime_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    read_error: OSError,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    _write_state(
        state_path,
        _state(status="stopped", stopped_at=_at(3)),
    )

    def fail_authoritative_read(*_args: object, **_kwargs: object) -> object:
        raise read_error

    monkeypatch.setattr(life_session_tracker, "load_json_data", fail_authoritative_read)
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    assert tracker.start_session() is None
    assert _read_state(state_path)["session_id"] != SESSION_ID
    tracker.release_lease()


def test_stopped_state_recovers_graceful_exit_candidate(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    previous_stop = _at(3)
    _write_state(
        state_path,
        _state(status="stopped", stopped_at=previous_stop),
    )
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    candidate = tracker.start_session()

    assert candidate == InactiveStartCandidate(
        started_at=previous_stop,
        source="graceful_exit",
    )
    assert tracker.start_session() is None
    tracker.release_lease()


def test_running_state_recovers_heartbeat_candidate(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    previous_heartbeat = _at(4)
    _write_state(state_path, _state(last_seen_at=previous_heartbeat))
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    assert tracker.start_session() == InactiveStartCandidate(
        started_at=previous_heartbeat,
        source="heartbeat_recovery",
    )
    tracker.release_lease()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: {**value, "extra": "synthetic-2099"},
        lambda value: {key: item for key, item in value.items() if key != "status"},
        lambda value: {**value, "version": 2},
        lambda value: {**value, "version": True},
        lambda value: {**value, "session_id": "not-a-uuid"},
        lambda value: {**value, "session_id": "123e4567-e89b-12d3-a456-426614174000"},
        lambda value: {**value, "started_at": "2099-01-02T03:04:01"},
        lambda value: {**value, "last_seen_at": "not-an-iso-timestamp"},
        lambda value: {**value, "status": "paused"},
        lambda value: {**value, "stopped_at": _at(3).isoformat()},
        lambda value: {
            **value,
            "status": "stopped",
            "stopped_at": None,
        },
        lambda value: {**value, "last_seen_at": _at(0).isoformat()},
        lambda value: {
            **value,
            "status": "stopped",
            "last_seen_at": _at(4).isoformat(),
            "stopped_at": _at(3).isoformat(),
        },
    ],
    ids=[
        "extra-key",
        "missing-key",
        "wrong-version",
        "boolean-version",
        "invalid-uuid",
        "non-v4-uuid",
        "naive-start",
        "invalid-iso",
        "invalid-status",
        "running-with-stop",
        "stopped-without-stop",
        "last-seen-before-start",
        "stop-before-last-seen",
    ],
)
def test_invalid_envelope_is_discarded(
    tmp_path: Path,
    mutate,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    _write_state(state_path, mutate(_state()))
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    assert tracker.start_session() is None
    saved = _read_state(state_path)
    assert saved["session_id"] != SESSION_ID
    assert set(saved) == SESSION_KEYS
    tracker.release_lease()


@pytest.mark.parametrize(
    ("status", "endpoint_field"),
    [("running", "last_seen_at"), ("stopped", "stopped_at")],
)
def test_future_candidate_is_discarded(
    tmp_path: Path,
    status: str,
    endpoint_field: str,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    payload = _state(
        last_seen_at=_at(20),
        status=status,
        stopped_at=_at(20) if status == "stopped" else None,
    )
    assert payload[endpoint_field] == _at(20).isoformat()
    _write_state(state_path, payload)
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    assert tracker.start_session() is None
    tracker.release_lease()


def test_candidate_endpoint_is_canonicalized_to_integer_seconds(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    _write_state(
        state_path,
        _state(
            last_seen_at=_at(2, microsecond=123456),
            status="stopped",
            stopped_at=_at(3, microsecond=987654),
        ),
    )
    tracker = AppSessionTracker(state_path, now=lambda: _at(10, microsecond=555555))

    assert tracker.start_session() == InactiveStartCandidate(
        started_at=_at(3),
        source="graceful_exit",
    )
    assert _read_state(state_path)["started_at"] == _at(10).isoformat()
    tracker.release_lease()


def test_failed_authoritative_running_commit_discards_candidate_and_degrades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    original = _state(status="stopped", stopped_at=_at(3))
    _write_state(state_path, original)

    def fail_save(*_args: object, **_kwargs: object) -> object:
        raise OSError("synthetic-commit-failure-2099")

    monkeypatch.setattr(life_session_tracker, "save_json_data", fail_save)
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    assert tracker.start_session() is None
    assert tracker.degraded is True
    assert tracker.life_records_writable is False
    assert tracker.reason == "session_tracker_degraded"
    assert tracker.session_id is None
    assert _read_state(state_path) == original
    assert tracker.heartbeat() is False
    tracker.release_lease()


def test_heartbeat_only_updates_current_last_seen_at(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    clock = MutableClock(_at(10))
    tracker = AppSessionTracker(state_path, now=clock)
    tracker.start_session()
    before = _read_state(state_path)
    clock.current = _at(20)

    assert tracker.heartbeat() is True

    after = _read_state(state_path)
    assert after == {**before, "last_seen_at": _at(20).isoformat()}
    tracker.release_lease()


def test_stop_writes_stopped_state_in_one_atomic_save(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    clock = MutableClock(_at(10))
    tracker = AppSessionTracker(state_path, now=clock)
    tracker.start_session()
    clock.current = _at(20)

    assert tracker.stop_session() is True

    saved = _read_state(state_path)
    assert saved["status"] == "stopped"
    assert saved["last_seen_at"] == _at(20).isoformat()
    assert saved["stopped_at"] == _at(20).isoformat()
    tracker.release_lease()


@pytest.mark.parametrize("operation", ["heartbeat", "stop_session"])
def test_stale_disk_session_id_rejects_write(
    tmp_path: Path,
    operation: str,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    clock = MutableClock(_at(10))
    tracker = AppSessionTracker(state_path, now=clock)
    tracker.start_session()
    replacement = _state(
        session_id=OTHER_SESSION_ID,
        started_at=_at(11),
        last_seen_at=_at(12),
    )
    _write_state(state_path, replacement)
    clock.current = _at(20)

    assert getattr(tracker, operation)() is False
    assert _read_state(state_path) == replacement
    assert tracker.degraded is True
    assert tracker.life_records_writable is False
    assert tracker.reason == "session_tracker_degraded"
    tracker.release_lease()


@pytest.mark.parametrize("operation", ["heartbeat", "stop_session"])
def test_session_id_changed_during_clock_read_is_rejected_before_write(
    tmp_path: Path,
    operation: str,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    replacement = _state(
        session_id=OTHER_SESSION_ID,
        started_at=_at(11),
        last_seen_at=_at(12),
    )
    clock_reads = 0

    def replace_during_clock_read() -> datetime:
        nonlocal clock_reads
        clock_reads += 1
        if clock_reads == 2:
            _write_state(state_path, replacement)
            return _at(20)
        return _at(10)

    tracker = AppSessionTracker(state_path, now=replace_during_clock_read)
    tracker.start_session()

    assert getattr(tracker, operation)() is False
    assert _read_state(state_path) == replacement
    assert tracker.reason == "session_tracker_degraded"
    tracker.release_lease()


def test_competing_trackers_allow_only_one_process_lifetime_lease(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    owner = AppSessionTracker(state_path, now=lambda: _at(10))
    contender = AppSessionTracker(state_path, now=lambda: _at(11))
    owner.start_session()
    owner_state = _read_state(state_path)

    assert contender.start_session() is None
    assert contender.degraded is True
    assert contender.life_records_writable is False
    assert contender.reason == "session_lease_unavailable"
    assert contender.session_id is None
    assert _read_state(state_path) == owner_state

    owner.release_lease()
    contender.release_lease()


def test_lease_failure_does_not_read_or_write_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class UnavailableLock:
        def __init__(self, _path: str) -> None:
            pass

        def setStaleLockTime(self, _milliseconds: int) -> None:
            pass

        def tryLock(self, _timeout: int) -> bool:
            events.append("lease")
            return False

        def unlock(self) -> None:
            events.append("unlock")

    monkeypatch.setattr(life_session_tracker, "QLockFile", UnavailableLock)
    monkeypatch.setattr(
        life_session_tracker,
        "load_json_data",
        lambda *_args, **_kwargs: events.append("read"),
    )
    monkeypatch.setattr(
        life_session_tracker,
        "save_json_data",
        lambda *_args, **_kwargs: events.append("write"),
    )
    tracker = AppSessionTracker(
        tmp_path / "life_session_state.json",
        now=lambda: _at(10),
    )

    assert tracker.start_session() is None
    assert events == ["lease"]
    assert tracker.reason == "session_lease_unavailable"


def test_lease_is_acquired_before_authoritative_read_and_running_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class AvailableLock:
        def __init__(self, _path: str) -> None:
            pass

        def setStaleLockTime(self, _milliseconds: int) -> None:
            pass

        def tryLock(self, _timeout: int) -> bool:
            events.append("lease")
            return True

        def unlock(self) -> None:
            events.append("unlock")

    def missing(*_args: object, **_kwargs: object) -> object:
        events.append("read")
        raise FileNotFoundError("synthetic-missing-2099")

    def save(*_args: object, **_kwargs: object) -> object:
        events.append("write")
        return None

    monkeypatch.setattr(life_session_tracker, "QLockFile", AvailableLock)
    monkeypatch.setattr(life_session_tracker, "load_json_data", missing)
    monkeypatch.setattr(life_session_tracker, "save_json_data", save)
    tracker = AppSessionTracker(
        tmp_path / "life_session_state.json",
        now=lambda: _at(10),
    )

    assert tracker.start_session() is None
    assert events == ["lease", "read", "write"]
    tracker.release_lease()
    assert events == ["lease", "read", "write", "unlock"]


def test_dead_process_stale_qlockfile_is_recovered(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    lock_path = tmp_path / "life_session_state.lock"
    code = (
        "import os, sys; "
        "from PyQt6.QtCore import QLockFile; "
        "lock = QLockFile(sys.argv[1]); "
        "lock.setStaleLockTime(0); "
        "ok = lock.tryLock(0); "
        "os._exit(0 if ok else 9)"
    )
    subprocess.run(
        [sys.executable, "-c", code, os.fspath(lock_path)],
        check=True,
        timeout=10,
    )
    assert lock_path.exists()

    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    assert tracker.start_session() is None
    assert tracker.degraded is False
    assert tracker.life_records_writable is True
    tracker.release_lease()


def test_utc_overflow_timestamp_is_discarded_as_invalid_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    _write_state(state_path, _state())
    real_as_utc = life_session_tracker._as_utc

    def overflow_previous_state(value: datetime) -> datetime:
        if value.second in (1, 2):
            raise OverflowError("synthetic-utc-overflow-2099")
        return real_as_utc(value)

    monkeypatch.setattr(life_session_tracker, "_as_utc", overflow_previous_state)
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    assert tracker.start_session() is None
    assert _read_state(state_path)["session_id"] != SESSION_ID
    assert "session_state_invalid" in tracker.diagnostics
    tracker.release_lease()


def test_candidate_zone_overflow_is_discarded_without_blocking_fresh_session(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    _write_state(
        state_path,
        _state(
            status="stopped",
            stopped_at=_at(3),
        ),
    )

    class OverflowingCandidateContext(LocalTimeContext):
        def canonicalize_endpoint(self, value: datetime) -> datetime:
            if value.second == 3:
                raise OverflowError("synthetic-zone-overflow-2099")
            return super().canonicalize_endpoint(value)

    context = OverflowingCandidateContext(
        timezone_name="UTC",
        zone=UTC_ZONE,
        now_provider=lambda: _at(10),
    )
    tracker = AppSessionTracker(state_path, time_context=context)

    assert tracker.start_session() is None
    assert _read_state(state_path)["session_id"] != SESSION_ID
    assert "session_candidate_invalid" in tracker.diagnostics
    tracker.release_lease()


def test_timezone_resolution_failure_keeps_life_records_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    unavailable = LocalTimeResolution(
        context=None,
        view_timezone=UTC_ZONE,
        reason=TIMEZONE_UNAVAILABLE,
    )
    monkeypatch.setattr(
        life_session_tracker,
        "resolve_local_time_context",
        lambda: unavailable,
    )
    tracker = AppSessionTracker(state_path)

    assert tracker.start_session() is None
    assert tracker.degraded is True
    assert tracker.life_records_writable is False
    assert tracker.reason == TIMEZONE_UNAVAILABLE
    assert not state_path.exists()


def test_clock_rollback_never_moves_heartbeat_backwards(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    clock = MutableClock(_at(20))
    tracker = AppSessionTracker(state_path, now=clock)
    tracker.start_session()
    clock.current = _at(10)

    assert tracker.heartbeat() is True
    assert _read_state(state_path)["last_seen_at"] == _at(20).isoformat()
    tracker.release_lease()


def test_stop_is_idempotent_and_writes_authoritative_state_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    saves: list[dict[str, object]] = []
    real_save = life_session_tracker.save_json_data

    def count_save(path: Path, payload: object, **kwargs: object) -> Path:
        assert isinstance(payload, dict)
        saves.append(payload.copy())
        return real_save(path, payload, **kwargs)

    monkeypatch.setattr(life_session_tracker, "save_json_data", count_save)
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))
    tracker.start_session()

    assert tracker.stop_session() is True
    assert tracker.stop_session() is True
    assert len(saves) == 2
    assert [payload["status"] for payload in saves] == ["running", "stopped"]
    tracker.release_lease()


def test_stop_keeps_lease_until_idempotent_release(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    owner = AppSessionTracker(state_path, now=lambda: _at(10))
    blocked = AppSessionTracker(state_path, now=lambda: _at(11))
    owner.start_session()
    assert owner.stop_session() is True

    assert blocked.start_session() is None
    assert blocked.reason == "session_lease_unavailable"

    assert owner.release_lease() is True
    assert owner.release_lease() is False
    successor = AppSessionTracker(state_path, now=lambda: _at(12))
    assert successor.start_session() == InactiveStartCandidate(
        started_at=_at(10),
        source="graceful_exit",
    )
    successor.release_lease()
    blocked.release_lease()


def test_rollback_stop_uses_persisted_last_seen_as_shutdown_time(tmp_path: Path) -> None:
    state_path = tmp_path / "life_session_state.json"
    clock = MutableClock(_at(10))
    tracker = AppSessionTracker(state_path, now=clock)
    tracker.start_session()
    clock.current = _at(20)
    tracker.heartbeat()
    clock.current = _at(15)

    assert tracker.stop_session() is True
    saved = _read_state(state_path)
    assert saved["last_seen_at"] == _at(20).isoformat()
    assert saved["stopped_at"] == _at(20).isoformat()
    tracker.release_lease()


@pytest.mark.parametrize("operation", ["heartbeat", "stop_session"])
def test_persistence_failure_degrades_writable_capability(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))
    tracker.start_session()

    def fail_save(*_args: object, **_kwargs: object) -> object:
        raise OSError("synthetic-persistence-error-2099")

    monkeypatch.setattr(life_session_tracker, "save_json_data", fail_save)

    assert getattr(tracker, operation)() is False
    assert tracker.degraded is True
    assert tracker.life_records_writable is False
    assert tracker.reason == "session_tracker_degraded"
    tracker.release_lease()


def test_failure_diagnostics_never_expose_json_exception_or_absolute_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    state_path = tmp_path / "life_session_state.json"
    raw_marker = "SYNTHETIC_RAW_SESSION_2099"
    exception_marker = "SYNTHETIC_EXCEPTION_DETAIL_2099"
    state_path.write_text(raw_marker, encoding="utf-8")

    def fail_read(*_args: object, **_kwargs: object) -> object:
        raise OSError(exception_marker)

    monkeypatch.setattr(life_session_tracker, "load_json_data", fail_read)
    caplog.set_level(logging.WARNING, logger=life_session_tracker.__name__)
    tracker = AppSessionTracker(state_path, now=lambda: _at(10))

    tracker.start_session()

    rendered = caplog.text
    assert "session_state_read_error" in rendered
    assert "path_kind=session_state" in rendered
    assert raw_marker not in rendered
    assert exception_marker not in rendered
    assert os.fspath(tmp_path.resolve()) not in rendered
    tracker.release_lease()
