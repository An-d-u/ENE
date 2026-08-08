from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from PyQt6.QtCore import QObject

from src.core.app import ENEApplication
from src.core.bridge_state import LifeRecordBridgeState
from src.core.life_session_tracker import InactiveStartCandidate
from src.core.local_time import LocalTimeContext, LocalTimeResolution


FIXED_NOW = datetime(2099, 4, 12, 9, 30, tzinfo=timezone.utc)


class _Signal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class _Timer:
    def __init__(self, _parent) -> None:
        self.timeout = _Signal()
        self.interval = None
        self.started = False

    def setInterval(self, interval: int) -> None:
        self.interval = interval

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.started = False


class _Tracker:
    def __init__(
        self,
        path: Path,
        *,
        time_context: LocalTimeContext,
        writable: bool = True,
        reason: str | None = None,
        session_id: str | None = "session-current",
    ) -> None:
        self.path = path
        self.time_context = time_context
        self.life_records_writable = writable
        self.reason = reason
        self.session_id = session_id
        self.heartbeat_calls = 0
        self.candidate = InactiveStartCandidate(
            started_at=datetime(2099, 4, 11, 22, 0, tzinfo=timezone.utc),
            source="graceful_exit",
        )

    def start_session(self):
        return self.candidate

    def heartbeat(self) -> bool:
        self.heartbeat_calls += 1
        return True


class _Bridge:
    def __init__(self) -> None:
        self.life_record_state = LifeRecordBridgeState()
        self.llm_client = None

    def _get_life_record_state(self):
        return self.life_record_state


def _valid_resolution() -> LocalTimeResolution:
    zone = ZoneInfo("Asia/Seoul")
    context = LocalTimeContext(
        timezone_name="Asia/Seoul",
        zone=zone,
        now_provider=lambda: FIXED_NOW,
    )
    return LocalTimeResolution(context=context, view_timezone=zone, reason=None)


def _bare_app(tmp_path, tracker_factory):
    app = ENEApplication.__new__(ENEApplication)
    QObject.__init__(app)
    app._life_time_resolver = _valid_resolution
    app._life_session_tracker_factory = tracker_factory
    app._life_record_manager_factory = lambda path: SimpleNamespace(store_path=Path(path))
    app._life_timer_factory = _Timer
    app._life_data_root = tmp_path
    app.llm_client = SimpleNamespace()
    return app


def test_startup_binds_one_time_context_manager_candidate_and_heartbeat(tmp_path):
    captured = {}

    def tracker_factory(path, *, time_context):
        tracker = _Tracker(Path(path), time_context=time_context)
        captured["tracker"] = tracker
        return tracker

    app = _bare_app(tmp_path, tracker_factory)
    bridge = _Bridge()
    app.overlay_window = SimpleNamespace(bridge=bridge)

    app._init_life_record_runtime()
    app._bind_life_record_runtime_to_bridge()
    app._start_life_session_heartbeat()

    state = bridge.life_record_state
    assert captured["tracker"].path == tmp_path / "life_session_state.json"
    assert captured["tracker"].time_context is app.life_time_context
    assert state.time_context is app.life_time_context
    assert state.view_timezone == "Asia/Seoul"
    assert state.candidate is captured["tracker"].candidate
    assert state.life_records_writable is True
    assert state.read_only_reason is None
    assert bridge.life_record_manager is app.life_record_manager
    assert app.llm_client.life_record_manager is app.life_record_manager
    assert app.life_heartbeat_timer.interval == 60_000
    assert app.life_heartbeat_timer.started is True

    app.life_heartbeat_timer.timeout.callback()

    assert captured["tracker"].heartbeat_calls == 1


@pytest.mark.parametrize(
    ("writable", "reason", "session_id", "expected"),
    [
        (False, "session_lease_unavailable", None, "session_lease_unavailable"),
        (False, "session_tracker_degraded", None, "session_tracker_degraded"),
        (True, None, None, "session_tracker_degraded"),
    ],
)
def test_startup_fails_closed_with_exact_tracker_reason_and_keeps_local_view_timezone(
    tmp_path, writable, reason, session_id, expected
):
    def tracker_factory(path, *, time_context):
        return _Tracker(
            Path(path),
            time_context=time_context,
            writable=writable,
            reason=reason,
            session_id=session_id,
        )

    app = _bare_app(tmp_path, tracker_factory)
    bridge = _Bridge()
    app.overlay_window = SimpleNamespace(bridge=bridge)

    app._init_life_record_runtime()
    app._bind_life_record_runtime_to_bridge()
    app._start_life_session_heartbeat()

    state = bridge.life_record_state
    assert state.life_records_writable is False
    assert state.read_only_reason == expected
    assert state.candidate is None
    assert state.view_timezone == "Asia/Seoul"
    assert app.life_heartbeat_timer is None


def test_timezone_failure_uses_utc_read_view_without_starting_tracker_or_timer(tmp_path):
    tracker_calls = []
    app = _bare_app(tmp_path, lambda *args, **kwargs: tracker_calls.append((args, kwargs)))
    app._life_time_resolver = lambda: LocalTimeResolution(
        context=None,
        view_timezone=ZoneInfo("UTC"),
        reason="timezone_unavailable",
    )
    bridge = _Bridge()
    app.overlay_window = SimpleNamespace(bridge=bridge)

    app._init_life_record_runtime()
    app._bind_life_record_runtime_to_bridge()
    app._start_life_session_heartbeat()

    assert tracker_calls == []
    assert bridge.life_record_state.view_timezone == "UTC"
    assert bridge.life_record_state.read_only_reason == "timezone_unavailable"
    assert bridge.life_record_state.life_records_writable is False
    assert app.life_heartbeat_timer is None

