from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from PyQt6 import sip
from PyQt6.QtCore import QObject, QThread

from src.core.app import ENEApplication
from src.core.bridge_state import LifeRecordBridgeState
from src.core.life_session_tracker import InactiveStartCandidate
from src.core.local_time import LocalTimeContext, LocalTimeResolution


FIXED_NOW = datetime(2099, 4, 12, 9, 30, tzinfo=timezone.utc)


class _Signal:
    def __init__(self) -> None:
        self.callback = None
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callback = callback
        self.callbacks.append(callback)

    def emit(self) -> None:
        for callback in list(self.callbacks):
            callback()


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
    app._life_record_manager_factory = lambda path, *, time_context=None: SimpleNamespace(
        store_path=Path(path),
        time_context=time_context,
    )
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
    assert app.life_record_manager.time_context is app.life_time_context
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
    assert app.life_record_manager is not None
    assert app.life_record_manager.time_context is None
    assert bridge.life_record_manager is app.life_record_manager
    assert bridge.life_record_state.view_timezone == "UTC"
    assert bridge.life_record_state.read_only_reason == "timezone_unavailable"
    assert bridge.life_record_state.life_records_writable is False
    assert app.life_heartbeat_timer is None


class _ShutdownWorker:
    def __init__(self, order: list[str], name: str, *, running: bool = True) -> None:
        self.order = order
        self.name = name
        self.running = running
        self.finished = _Signal()
        self.stop_requests = 0

    def isRunning(self) -> bool:
        return self.running

    def requestInterruption(self) -> None:
        self.order.append(f"interrupt:{self.name}")

    def request_stop(self) -> None:
        self.stop_requests += 1

    def finish(self) -> None:
        self.running = False
        self.finished.emit()


class _ShutdownScheduler:
    def __init__(self, _parent) -> None:
        self.pending = []

    def schedule(self, _delay_ms: int, callback) -> None:
        self.pending.append(callback)

    def run_next(self) -> None:
        self.pending.pop(0)()


class _ShutdownTracker:
    def __init__(self, order: list[str], *, stop_result: bool = True) -> None:
        self.order = order
        self.stop_result = stop_result
        self.stop_calls = 0
        self.release_calls = 0

    def stop_session(self) -> bool:
        self.stop_calls += 1
        self.order.append("stop_session")
        return self.stop_result

    def release_lease(self) -> bool:
        self.release_calls += 1
        self.order.append("release_lease")
        return True


def _shutdown_app(monkeypatch, *, workers=(), stop_result=True, poll_limit=3):
    order = []
    scheduler = _ShutdownScheduler(None)
    app = ENEApplication.__new__(ENEApplication)
    QObject.__init__(app)
    bridge = _Bridge()
    bridge.worker = workers[0] if len(workers) > 0 else None
    bridge.tts_worker = workers[1] if len(workers) > 1 else None
    bridge._summary_review_worker = workers[2] if len(workers) > 2 else None
    bridge.stop_away_monitor = lambda: order.append("stop_away_monitor")
    bridge.begin_shutdown = lambda: (
        order.append("begin_shutdown"),
        bridge.life_record_state.begin_shutdown(),
    )[-1]
    bridge.promise_timer = SimpleNamespace(stop=lambda: order.append("promise_timer"))
    bridge.proactive_timer = SimpleNamespace(stop=lambda: order.append("proactive_timer"))
    bridge.obs_tree_retry_timer = SimpleNamespace(
        stop=lambda: order.append("obs_tree_retry_timer")
    )
    app.overlay_window = SimpleNamespace(
        bridge=bridge,
        shutdown=lambda: order.append("overlay_shutdown"),
        close=lambda: order.append("overlay_close"),
    )
    app.tray_icon = SimpleNamespace(
        tray_icon=SimpleNamespace(hide=lambda: order.append("tray_hide"))
    )
    app.obsidian_panel_window = SimpleNamespace(close=lambda: order.append("obsidian_close"))
    app.global_ptt = SimpleNamespace(shutdown=lambda: order.append("ptt_shutdown"))
    app.system_theme_timer = SimpleNamespace(stop=lambda: order.append("theme_timer"))
    app.life_heartbeat_timer = SimpleNamespace(stop=lambda: order.append("life_timer"))
    app.life_session_tracker = _ShutdownTracker(order, stop_result=stop_result)
    app._settings_dialog = None
    app._quit_in_progress = False
    app._quit_after_summary_review = False
    app._shutdown_drain_scheduler_factory = lambda _parent: scheduler
    app._shutdown_drain_poll_limit = poll_limit
    app._shutdown_drain_poll_interval_ms = 1
    monkeypatch.setattr(
        "src.core.app.QApplication.quit",
        lambda: order.append("qapplication_quit"),
    )
    return app, bridge, scheduler, order


def test_shutdown_without_workers_commits_before_teardown_and_releases_lease_last(monkeypatch):
    app, _bridge, _scheduler, order = _shutdown_app(monkeypatch)

    app._finish_quit_application()

    assert order.index("begin_shutdown") < order.index("life_timer")
    assert order.index("life_timer") < order.index("stop_session")
    assert order.index("stop_session") < order.index("overlay_shutdown")
    assert order.index("overlay_close") < order.index("tray_hide")
    assert order.index("tray_hide") < order.index("release_lease")
    assert order.index("release_lease") < order.index("qapplication_quit")


def test_shutdown_drains_normal_life_tts_and_summary_workers_without_gui_wait(monkeypatch):
    order = []
    workers = tuple(_ShutdownWorker(order, name) for name in ("reply", "tts", "summary"))
    app, bridge, scheduler, shutdown_order = _shutdown_app(monkeypatch, workers=workers)
    order.extend(shutdown_order)
    life_worker = _ShutdownWorker(order, "life")
    bridge.life_record_state.worker = life_worker

    app._finish_quit_application()

    assert all(f"interrupt:{name}" in order for name in ("reply", "life", "tts", "summary"))
    assert workers[1].stop_requests == 1
    assert "stop_session" not in order
    assert scheduler.pending

    for worker in (*workers, life_worker):
        worker.finish()
    assert len(scheduler.pending) == 1
    while scheduler.pending:
        scheduler.run_next()

    assert app.life_session_tracker.stop_calls == 1
    assert app.life_session_tracker.release_calls == 1


def test_shutdown_timeout_preserves_running_session_and_still_releases_lease(monkeypatch):
    worker_order = []
    worker = _ShutdownWorker(worker_order, "reply")
    app, _bridge, scheduler, order = _shutdown_app(
        monkeypatch,
        workers=(worker,),
        poll_limit=1,
    )

    app._finish_quit_application()

    assert "promise_timer" not in order
    assert "proactive_timer" not in order
    assert "obs_tree_retry_timer" not in order
    assert "life_timer" not in order
    scheduler.run_next()

    assert app.life_session_tracker.stop_calls == 0
    assert app.life_session_tracker.release_calls == 1
    assert order.index("promise_timer") < order.index("life_timer")
    assert order.index("life_timer") < order.index("overlay_shutdown")
    assert "overlay_shutdown" in order
    assert worker in app._shutdown_worker_refs


def test_shutdown_finalizer_is_idempotent_when_tray_and_fallback_both_fire(monkeypatch):
    app, bridge, _scheduler, order = _shutdown_app(monkeypatch)

    app._finish_quit_application()
    app._finish_quit_application(_about_to_quit=True)

    assert bridge.life_record_state.phase == "shutting_down"
    assert order.count("begin_shutdown") == 1
    assert app.life_session_tracker.stop_calls == 1
    assert app.life_session_tracker.release_calls == 1
    assert order.count("qapplication_quit") == 1


def test_shutdown_stop_failure_logs_only_safe_code_and_continues(monkeypatch, capsys):
    app, _bridge, _scheduler, order = _shutdown_app(monkeypatch, stop_result=False)

    app._finish_quit_application()

    captured = capsys.readouterr()
    assert "life_record_shutdown_failed code=session_stop_failed" in captured.out
    assert "release_lease" in order
    assert "qapplication_quit" in order


def test_about_to_quit_fallback_connection_is_idempotent(monkeypatch):
    signal = _Signal()
    monkeypatch.setattr(
        "src.core.app.QApplication.instance",
        lambda: SimpleNamespace(aboutToQuit=signal),
    )
    app = ENEApplication.__new__(ENEApplication)
    QObject.__init__(app)
    calls = []
    app._finish_quit_application = lambda **kwargs: calls.append(kwargs)

    app._connect_application_quit_fallback()
    app._connect_application_quit_fallback()
    signal.emit()

    assert calls == [{"_about_to_quit": True}]


def test_about_to_quit_with_running_worker_uses_forced_path_without_stop_commit(monkeypatch):
    worker = _ShutdownWorker([], "reply")
    app, _bridge, _scheduler, order = _shutdown_app(monkeypatch, workers=(worker,))

    app._finish_quit_application(_about_to_quit=True)

    assert app.life_session_tracker.stop_calls == 0
    assert app.life_session_tracker.release_calls == 1
    assert "qapplication_quit" not in order


def test_shutdown_scheduler_failure_uses_forced_path_without_stop_commit(monkeypatch):
    class FailingScheduler:
        def schedule(self, _delay_ms, _callback):
            raise RuntimeError("Synthetic scheduler detail")

    worker = _ShutdownWorker([], "reply")
    app, _bridge, _scheduler, order = _shutdown_app(monkeypatch, workers=(worker,))
    app._shutdown_drain_scheduler_factory = lambda _parent: FailingScheduler()

    app._finish_quit_application()

    assert app.life_session_tracker.stop_calls == 0
    assert app.life_session_tracker.release_calls == 1
    assert "qapplication_quit" in order


def test_shutdown_treats_deleted_qthread_wrapper_as_already_drained(monkeypatch):
    worker = QThread()
    sip.delete(worker)
    app, bridge, _scheduler, order = _shutdown_app(monkeypatch, workers=(worker,))
    bridge.tts_worker = worker
    bridge.life_record_state.worker = worker

    app._finish_quit_application()

    assert app.life_session_tracker.stop_calls == 1
    assert app.life_session_tracker.release_calls == 1
    assert "qapplication_quit" in order


def test_shutdown_status_failure_for_live_worker_preserves_running_session(monkeypatch):
    class StatusFailureWorker:
        def isRunning(self):
            raise RuntimeError("Synthetic status failure")

        @property
        def requestInterruption(self):
            raise RuntimeError("Synthetic interruption lookup failure")

        @property
        def request_stop(self):
            raise RuntimeError("Synthetic stop lookup failure")

        @property
        def finished(self):
            raise RuntimeError("Synthetic signal lookup failure")

    worker = StatusFailureWorker()
    app, _bridge, scheduler, _order = _shutdown_app(
        monkeypatch,
        workers=(worker,),
        poll_limit=1,
    )

    app._finish_quit_application()

    assert app.life_session_tracker.stop_calls == 0
    assert scheduler.pending
    scheduler.run_next()
    assert app.life_session_tracker.stop_calls == 0
    assert app.life_session_tracker.release_calls == 1


def test_shutdown_discovers_replacement_worker_and_keeps_it_until_drained(monkeypatch):
    worker_order = []
    original = _ShutdownWorker(worker_order, "original")
    replacement = _ShutdownWorker(worker_order, "replacement")
    app, bridge, scheduler, _order = _shutdown_app(
        monkeypatch,
        workers=(original,),
    )

    app._finish_quit_application()
    original.finish()
    bridge.worker = replacement
    scheduler.run_next()

    assert "interrupt:replacement" in worker_order
    assert replacement in app._shutdown_worker_refs
    assert app.life_session_tracker.stop_calls == 0
    bridge.worker = None
    scheduler.run_next()
    assert app.life_session_tracker.stop_calls == 0

    replacement.finish()
    while scheduler.pending:
        scheduler.run_next()

    assert app.life_session_tracker.stop_calls == 1


def test_shutdown_stops_timers_only_after_worker_drain(monkeypatch):
    app, bridge, scheduler, order = _shutdown_app(monkeypatch)
    worker = _ShutdownWorker(order, "reply")
    bridge.worker = worker
    spawned = _ShutdownWorker(order, "late")
    timer_callbacks = []

    def guarded_timer_callback():
        timer_callbacks.append("called")
        if bridge.life_record_state.phase != "shutting_down":
            bridge.obs_tree_worker = spawned

    app._finish_quit_application()
    guarded_timer_callback()

    assert timer_callbacks == ["called"]
    assert getattr(bridge, "obs_tree_worker", None) is None
    for event in (
        "stop_away_monitor",
        "promise_timer",
        "proactive_timer",
        "obs_tree_retry_timer",
        "life_timer",
    ):
        assert event not in order
    assert app.life_session_tracker.stop_calls == 0

    worker.finish()
    while scheduler.pending:
        scheduler.run_next()

    assert order.index("interrupt:reply") < order.index("stop_away_monitor")
    assert order.index("obs_tree_retry_timer") < order.index("life_timer")
    assert order.index("life_timer") < order.index("stop_session")


def test_shutdown_deduplicates_worker_aliases_when_discovered_during_drain(monkeypatch):
    worker_order = []
    original = _ShutdownWorker(worker_order, "original")
    discovered = _ShutdownWorker(worker_order, "discovered")
    app, bridge, scheduler, _order = _shutdown_app(
        monkeypatch,
        workers=(original,),
    )

    app._finish_quit_application()
    bridge.worker = discovered
    bridge.tts_worker = discovered
    bridge.obs_tree_worker = discovered
    scheduler.run_next()

    assert worker_order.count("interrupt:discovered") == 1
    assert app._shutdown_worker_refs.count(discovered) == 1
    assert len(discovered.finished.callbacks) == 1
