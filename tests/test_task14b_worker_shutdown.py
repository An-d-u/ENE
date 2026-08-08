import asyncio
import os
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
    TTSWorker,
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


class _ExplosiveArgsFailure(BaseException):
    args_reads = 0

    @property
    def args(self):
        type(self).args_reads += 1
        print("SYNTHETIC-PRIVATE-ARGS-DETAIL")
        raise RuntimeError("SYNTHETIC-PRIVATE-ARGS-ESCAPE")


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


def test_ai_worker_never_reads_provider_exception_args_or_chain(capsys):
    _ensure_qt_app()
    _ExplosiveArgsFailure.args_reads = 0
    failure = _ExplosiveArgsFailure()
    failure.__cause__ = RuntimeError("SYNTHETIC-PRIVATE-CAUSE")
    failure.__context__ = RuntimeError("SYNTHETIC-PRIVATE-CONTEXT")

    class Client:
        async def send_message_with_memory(self, *_args, **_kwargs):
            raise failure

    errors = []
    worker = AIWorker(Client(), "Synthetic request.")
    worker.error_occurred.connect(errors.append)

    worker.run()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert errors == ["provider_error"]
    assert _ExplosiveArgsFailure.args_reads == 0
    assert "SYNTHETIC-PRIVATE" not in combined
    assert "Traceback" not in combined


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


def test_tts_worker_cancellation_before_start_has_no_provider_or_temp_side_effect(monkeypatch):
    _ensure_qt_app()

    class Client:
        async def generate_speech(self, _text):
            raise AssertionError("취소된 TTS 워커가 공급자를 호출하면 안 됩니다.")

    monkeypatch.setattr(
        "tempfile.mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("취소된 TTS 워커가 임시 파일을 만들면 안 됩니다.")
        ),
    )
    ready = []
    errors = []
    worker = TTSWorker(Client(), "Synthetic speech.")
    worker.tts_ready.connect(lambda *args: ready.append(args))
    worker.error_occurred.connect(errors.append)
    worker.requestInterruption()

    worker.run()

    assert ready == []
    assert errors == []


def test_tts_worker_cancellation_after_provider_skips_temp_and_signals(monkeypatch):
    _ensure_qt_app()
    worker = None

    class Client:
        async def generate_speech(self, _text):
            worker.requestInterruption()
            return b"synthetic-wave"

    monkeypatch.setattr(
        "tempfile.mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("공급자 이후 취소된 TTS가 임시 파일을 만들면 안 됩니다.")
        ),
    )
    ready = []
    errors = []
    worker = TTSWorker(Client(), "Synthetic speech.")
    worker.tts_ready.connect(lambda *args: ready.append(args))
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert ready == []
    assert errors == []


def test_tts_worker_cancellation_after_temp_creation_cleans_file_before_analysis(
    monkeypatch,
    tmp_path,
):
    _ensure_qt_app()
    worker = None
    temp_path = tmp_path / "synthetic-audio.wav"

    class Client:
        async def generate_speech(self, _text):
            return b"synthetic-wave"

    def create_then_cancel(**_kwargs):
        descriptor = os.open(temp_path, os.O_CREAT | os.O_RDWR)
        worker.requestInterruption()
        return descriptor, str(temp_path)

    class ForbiddenAnalyzer:
        def __init__(self, **_kwargs):
            raise AssertionError("취소된 TTS가 오디오 분석을 시작하면 안 됩니다.")

    monkeypatch.setattr("tempfile.mkstemp", create_then_cancel)
    monkeypatch.setattr("src.ai.audio_analyzer.AudioAnalyzer", ForbiddenAnalyzer)
    ready = []
    errors = []
    worker = TTSWorker(Client(), "Synthetic speech.")
    worker.tts_ready.connect(lambda *args: ready.append(args))
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert ready == []
    assert errors == []
    assert not temp_path.exists()


def test_tts_worker_cancellation_during_analysis_cleans_temp_and_skips_ready(
    monkeypatch,
    tmp_path,
):
    _ensure_qt_app()
    worker = None
    temp_path = tmp_path / "synthetic-analysis.wav"

    class Client:
        async def generate_speech(self, _text):
            return b"synthetic-wave"

    def create_temp(**_kwargs):
        descriptor = os.open(temp_path, os.O_CREAT | os.O_RDWR)
        return descriptor, str(temp_path)

    class CancellingAnalyzer:
        def __init__(self, **_kwargs):
            pass

        def analyze(self, _path):
            worker.requestInterruption()
            return [0.2]

    monkeypatch.setattr("tempfile.mkstemp", create_temp)
    monkeypatch.setattr("src.ai.audio_analyzer.AudioAnalyzer", CancellingAnalyzer)
    ready = []
    errors = []
    worker = TTSWorker(Client(), "Synthetic speech.")
    worker.tts_ready.connect(lambda *args: ready.append(args))
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert ready == []
    assert errors == []
    assert not temp_path.exists()


def test_tts_worker_contains_provider_base_exception_without_reading_attrs(
    capsys,
    monkeypatch,
):
    _ensure_qt_app()
    _ExplosiveArgsFailure.args_reads = 0
    failure = _ExplosiveArgsFailure()
    failure.__cause__ = RuntimeError("SYNTHETIC-PRIVATE-TTS-CAUSE")
    failure.__context__ = RuntimeError("SYNTHETIC-PRIVATE-TTS-CONTEXT")

    class Client:
        async def generate_speech(self, _text):
            raise failure

    monkeypatch.setattr(
        "tempfile.mkstemp",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("실패한 TTS가 임시 파일을 만들면 안 됩니다.")
        ),
    )
    errors = []
    worker = TTSWorker(Client(), "Synthetic speech.")
    worker.error_occurred.connect(errors.append)

    worker.run()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert errors == ["tts_error"]
    assert _ExplosiveArgsFailure.args_reads == 0
    assert "SYNTHETIC-PRIVATE" not in combined
    assert "Traceback" not in combined


def test_tts_worker_contains_unrequested_provider_cancelled_error(capsys):
    _ensure_qt_app()

    class Client:
        async def generate_speech(self, _text):
            raise asyncio.CancelledError("SYNTHETIC-PRIVATE-TTS-CANCEL")

    errors = []
    worker = TTSWorker(Client(), "Synthetic speech.")
    worker.error_occurred.connect(errors.append)

    worker.run()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert errors == ["tts_error"]
    assert "SYNTHETIC-PRIVATE" not in combined
    assert "Traceback" not in combined
    assert "exception_class=CancelledError" in combined


def test_tts_worker_provider_cancelled_error_is_silent_after_interruption():
    _ensure_qt_app()
    worker = None

    class Client:
        async def generate_speech(self, _text):
            worker.requestInterruption()
            raise asyncio.CancelledError("SYNTHETIC-PRIVATE-TTS-CANCEL")

    ready = []
    errors = []
    worker = TTSWorker(Client(), "Synthetic speech.")
    worker.tts_ready.connect(lambda *args: ready.append(args))
    worker.error_occurred.connect(errors.append)

    worker.run()

    assert ready == []
    assert errors == []


def test_tts_worker_interruption_before_error_signal_is_silent(monkeypatch):
    _ensure_qt_app()

    class Client:
        async def generate_speech(self, _text):
            raise RuntimeError("SYNTHETIC-PRIVATE-TTS-FAILURE")

    errors = []
    worker = TTSWorker(Client(), "Synthetic speech.")
    worker.error_occurred.connect(errors.append)
    original_print = print

    def interrupting_print(*args, **kwargs):
        if args and "generation_failed" in str(args[0]):
            worker.requestInterruption()
        original_print(*args, **kwargs)

    monkeypatch.setattr("builtins.print", interrupting_print)

    worker.run()

    assert errors == []
