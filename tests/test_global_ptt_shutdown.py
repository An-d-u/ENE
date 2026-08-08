from __future__ import annotations

import threading
import time

import pytest
from PyQt6.QtCore import QCoreApplication

from src.core import global_ptt as global_ptt_module
from src.core.global_ptt import GlobalPTTController, _STTWorker


@pytest.fixture(scope="module")
def qapp() -> QCoreApplication:
    return QCoreApplication.instance() or QCoreApplication([])


class _BlockingSTTService:
    def __init__(self, result: str = "가상의 음성 입력") -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.result = result

    def transcribe_pcm16(self, _pcm_bytes: bytes) -> str:
        self.entered.set()
        assert self.release.wait(timeout=3)
        return self.result


def _running_controller() -> tuple[
    GlobalPTTController, _STTWorker, _BlockingSTTService
]:
    controller = GlobalPTTController({"enable_global_ptt": False})
    service = _BlockingSTTService()
    worker = _STTWorker(service, b"\x00\x01" * 1600)
    controller._stt_worker = worker
    controller._is_transcribing = True
    worker.finished_text.connect(controller._on_transcription_ready)
    worker.failed.connect(controller._on_transcription_failed)
    worker.start()
    assert service.entered.wait(timeout=1)
    return controller, worker, service


def _process_events_until(
    qapp: QCoreApplication, predicate, timeout: float = 2.0
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    qapp.processEvents()
    assert predicate()


def test_shutdown_does_not_call_qthread_wait_and_returns_promptly(qapp, monkeypatch):
    controller, worker, service = _running_controller()
    original_wait = worker.wait
    wait_calls: list[tuple] = []

    def forbidden_wait(*args, **kwargs):
        wait_calls.append((args, kwargs))
        raise AssertionError("GUI 종료 경로에서 QThread.wait를 호출하면 안 됩니다.")

    monkeypatch.setattr(worker, "wait", forbidden_wait)
    started_at = time.monotonic()
    try:
        controller.shutdown()
        elapsed = time.monotonic() - started_at
        assert elapsed < 0.2
        assert wait_calls == []
        assert worker.isInterruptionRequested()
    finally:
        service.release.set()
        original_wait(2000)
        qapp.processEvents()


def test_shutdown_retains_running_worker_until_cleanup_and_ignores_late_result(qapp):
    controller, worker, service = _running_controller()
    emitted: list[str] = []
    controller.transcription_ready.connect(emitted.append)

    controller.shutdown()

    assert worker in global_ptt_module._DRAINING_STT_WORKERS
    assert controller._stt_worker is None
    assert controller._is_transcribing is False

    service.release.set()
    _process_events_until(
        qapp,
        lambda: worker not in global_ptt_module._DRAINING_STT_WORKERS,
    )

    assert emitted == []
    assert worker.pcm_bytes == b""


def test_shutdown_is_idempotent_for_running_worker(qapp, monkeypatch):
    controller, worker, service = _running_controller()
    interruption_calls = 0
    quit_calls = 0
    original_request_interruption = worker.requestInterruption
    original_quit = worker.quit

    def request_interruption_once():
        nonlocal interruption_calls
        interruption_calls += 1
        original_request_interruption()

    def quit_once():
        nonlocal quit_calls
        quit_calls += 1
        original_quit()

    monkeypatch.setattr(worker, "requestInterruption", request_interruption_once)
    monkeypatch.setattr(worker, "quit", quit_once)

    controller.shutdown()
    controller.shutdown()

    assert interruption_calls == 1
    assert quit_calls == 1

    service.release.set()
    _process_events_until(
        qapp,
        lambda: worker not in global_ptt_module._DRAINING_STT_WORKERS,
    )
