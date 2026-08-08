import asyncio
from types import SimpleNamespace

from PyQt6.QtCore import QCoreApplication

from src.core.bridge_mixins.memory_summary import (
    MemorySummaryBridgeMixin,
    SummaryReviewWorker,
)
from src.core.bridge_mixins.obsidian import ObsidianBridgeMixin
from src.core.bridge_workers import (
    AIWorker,
    ObsidianCheckedFilesWorker,
    ObsidianTreeWorker,
)


def _ensure_qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


class _Signal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _PrivateBaseFailure(BaseException):
    string_calls = 0
    repr_calls = 0

    def __str__(self):
        type(self).string_calls += 1
        return "SYNTHETIC-PRIVATE-WORKER-DETAIL"

    def __repr__(self):
        type(self).repr_calls += 1
        return "SYNTHETIC-PRIVATE-WORKER-REPR"


def test_ai_worker_contains_provider_base_exception_with_fixed_safe_error(capsys):
    _ensure_qt_app()
    _PrivateBaseFailure.string_calls = 0
    _PrivateBaseFailure.repr_calls = 0

    class Client:
        async def send_message_with_memory(self, *_args, **_kwargs):
            raise _PrivateBaseFailure()

    errors = []
    worker = AIWorker(Client(), "Synthetic request.")
    worker.error_occurred.connect(errors.append)

    worker.run()

    captured = capsys.readouterr()
    assert errors == ["provider_error"]
    assert "SYNTHETIC-PRIVATE" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err
    assert _PrivateBaseFailure.string_calls == 0
    assert _PrivateBaseFailure.repr_calls == 0


def test_ai_worker_provider_cancelled_error_is_silent_after_interruption():
    _ensure_qt_app()
    worker = None

    class Client:
        async def send_message_with_memory(self, *_args, **_kwargs):
            worker.requestInterruption()
            raise asyncio.CancelledError("SYNTHETIC-PRIVATE-CANCEL")

    errors = []
    worker = AIWorker(Client(), "Synthetic request.")
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert errors == []


def test_summary_review_worker_cancellation_before_start_skips_builder():
    _ensure_qt_app()

    class Bridge:
        async def _build_summary_review_state(self, _messages):
            raise AssertionError("취소된 요약 워커가 실행되면 안 됩니다.")

    prepared = []
    failed = []
    worker = SummaryReviewWorker(Bridge(), [("user", "Synthetic input.")])
    worker.prepared.connect(prepared.append)
    worker.failed.connect(failed.append)
    worker.requestInterruption()

    worker.run()

    assert prepared == []
    assert failed == []


def test_summary_review_worker_cancellation_after_await_skips_signal():
    _ensure_qt_app()
    worker = None

    class Bridge:
        async def _build_summary_review_state(self, _messages):
            worker.requestInterruption()
            return {"summary": "Synthetic summary."}

    prepared = []
    failed = []
    worker = SummaryReviewWorker(Bridge(), [("user", "Synthetic input.")])
    worker.prepared.connect(prepared.append)
    worker.failed.connect(failed.append)

    worker.run()

    assert prepared == []
    assert failed == []


def test_summary_review_worker_contains_base_exception_with_fixed_safe_error(capsys):
    _ensure_qt_app()
    _PrivateBaseFailure.string_calls = 0
    _PrivateBaseFailure.repr_calls = 0

    class Bridge:
        async def _build_summary_review_state(self, _messages):
            raise _PrivateBaseFailure()

    failed = []
    worker = SummaryReviewWorker(Bridge(), [("user", "Synthetic input.")])
    worker.failed.connect(failed.append)

    worker.run()

    captured = capsys.readouterr()
    assert failed == ["summary_review_error"]
    assert "SYNTHETIC-PRIVATE" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err
    assert _PrivateBaseFailure.string_calls == 0
    assert _PrivateBaseFailure.repr_calls == 0


def test_summary_review_handlers_ignore_late_callbacks_during_shutdown():
    bridge = SimpleNamespace(
        life_record_state=SimpleNamespace(phase="shutting_down"),
        _pending_summary_review=None,
        summary_notice=_Signal(),
        summary_review_ready=_Signal(),
        _emit_summary_review=lambda: (_ for _ in ()).throw(
            AssertionError("종료 중 요약 UI를 갱신하면 안 됩니다.")
        ),
    )

    MemorySummaryBridgeMixin._on_summary_review_prepared(
        bridge,
        {"summary": "Synthetic summary."},
    )
    MemorySummaryBridgeMixin._on_summary_review_failed(
        bridge,
        "SYNTHETIC-PRIVATE-SUMMARY-ERROR",
    )

    assert bridge._pending_summary_review is None
    assert bridge.summary_notice.emitted == []
    assert bridge.summary_review_ready.emitted == []


def test_obsidian_tree_worker_cancellation_after_network_skips_signal():
    _ensure_qt_app()
    worker = None

    class Manager:
        def get_tree_json(self, **_kwargs):
            worker.requestInterruption()
            return '{"ok": true, "nodes": []}'

    ready = []
    errors = []
    worker = ObsidianTreeWorker(Manager())
    worker.tree_ready.connect(ready.append)
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert ready == []
    assert errors == []


def test_obsidian_checked_worker_cancellation_after_network_skips_signal():
    _ensure_qt_app()
    worker = None

    class Manager:
        def get_checked_file_contents(self, **_kwargs):
            worker.requestInterruption()
            return [("notes/example.md", "Synthetic body.")]

    ready = []
    errors = []
    worker = ObsidianCheckedFilesWorker(Manager(), ["notes/example.md"])
    worker.context_ready.connect(lambda *args: ready.append(args))
    worker.error_occurred.connect(lambda *args: errors.append(args))

    worker.run()

    assert ready == []
    assert errors == []


def test_obsidian_workers_contain_base_exception_without_raw_error(capsys):
    _ensure_qt_app()

    class Manager:
        def get_tree_json(self, **_kwargs):
            raise _PrivateBaseFailure()

        def get_checked_file_contents(self, **_kwargs):
            raise _PrivateBaseFailure()

    tree_errors = []
    checked_errors = []
    tree_worker = ObsidianTreeWorker(Manager())
    checked_worker = ObsidianCheckedFilesWorker(Manager(), ["notes/example.md"])
    tree_worker.error_occurred.connect(tree_errors.append)
    checked_worker.error_occurred.connect(lambda *args: checked_errors.append(args))

    tree_worker.run()
    checked_worker.run()

    captured = capsys.readouterr()
    assert tree_errors == ["obsidian_tree_error"]
    assert checked_errors == [("obsidian_checked_files_error", "")]
    assert "SYNTHETIC-PRIVATE" not in captured.out + captured.err
    assert "Traceback" not in captured.out + captured.err


def test_obsidian_late_callbacks_do_nothing_during_shutdown():
    signal = _Signal()
    timer = SimpleNamespace(
        stop=lambda: (_ for _ in ()).throw(AssertionError("타이머를 건드리면 안 됩니다.")),
        start=lambda *_args: (_ for _ in ()).throw(AssertionError("타이머를 시작하면 안 됩니다.")),
    )
    bridge = SimpleNamespace(
        life_record_state=SimpleNamespace(phase="shutting_down"),
        _cached_obs_tree_json="unchanged",
        _cached_checked_files_context="unchanged",
        _cached_checked_files_signature=("notes/example.md",),
        obs_tree_updated=signal,
        obs_tree_retry_timer=timer,
        _obs_tree_retry_remaining=2,
        _get_checked_files_signature=lambda: ("notes/example.md",),
        _decode_checked_files_signature=lambda _payload: ("notes/example.md",),
        _schedule_checked_files_context_refresh=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("후속 체크 파일 워커를 만들면 안 됩니다.")
        ),
        _schedule_obs_tree_retry_if_needed=lambda: (_ for _ in ()).throw(
            AssertionError("후속 재시도를 예약하면 안 됩니다.")
        ),
    )

    ObsidianBridgeMixin._on_obs_tree_ready(bridge, '{"ok": true, "nodes": []}')
    ObsidianBridgeMixin._on_obs_tree_error(bridge, "SYNTHETIC-PRIVATE-ERROR")
    ObsidianBridgeMixin._on_checked_files_context_ready(
        bridge,
        "Synthetic context.",
        '["notes/example.md"]',
    )
    ObsidianBridgeMixin._on_checked_files_context_error(
        bridge,
        "SYNTHETIC-PRIVATE-ERROR",
        '["notes/example.md"]',
    )

    assert bridge._cached_obs_tree_json == "unchanged"
    assert bridge._cached_checked_files_context == "unchanged"
    assert bridge._cached_checked_files_signature == ("notes/example.md",)
    assert signal.emitted == []


def test_obsidian_worker_creators_and_retry_timer_ignore_shutdown(monkeypatch):
    class ForbiddenWorker:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("종료 중 Obsidian 워커를 만들면 안 됩니다.")

    monkeypatch.setattr(
        "src.core.bridge_mixins.obsidian.ObsidianTreeWorker",
        ForbiddenWorker,
    )
    monkeypatch.setattr(
        "src.core.bridge_mixins.obsidian.ObsidianCheckedFilesWorker",
        ForbiddenWorker,
    )
    timer = SimpleNamespace(
        isActive=lambda: False,
        start=lambda *_args: (_ for _ in ()).throw(AssertionError("재시도 타이머를 시작하면 안 됩니다.")),
    )
    bridge = SimpleNamespace(
        life_record_state=SimpleNamespace(phase="shutting_down"),
        _obsidian_integration_activated=True,
        _cached_checked_files_context="unchanged",
        _cached_checked_files_signature=("notes/example.md",),
        _get_checked_files_signature=lambda: ("notes/example.md",),
        obs_checked_files_worker=None,
        obs_tree_worker=None,
        obs_tree_retry_timer=timer,
        _obs_tree_retry_remaining=2,
        obsidian_manager=object(),
        obs_panel_window=SimpleNamespace(isVisible=lambda: True),
        _prompt_language=lambda: "ko",
    )

    ObsidianBridgeMixin._schedule_checked_files_context_refresh(bridge, force=True)
    ObsidianBridgeMixin._start_obs_tree_refresh(bridge, retry_sequence=True)
    ObsidianBridgeMixin._retry_obs_tree_refresh(bridge)
    ObsidianBridgeMixin._schedule_obs_tree_retry_if_needed(bridge)

    assert bridge._cached_checked_files_context == "unchanged"
    assert bridge._cached_checked_files_signature == ("notes/example.md",)
    assert bridge._obs_tree_retry_remaining == 2
