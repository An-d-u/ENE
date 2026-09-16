"""생산자와 Qt 사이의 대기량·종료 순서를 가상 음성으로 검사한다."""

import threading

import pytest
from PyQt6.QtWidgets import QApplication

from src.core.companion.audio_mailbox import BoundedTtsMailbox


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_one_wake_and_end_follows_all_chunks(app):
    seen, wakes = [], []
    box = BoundedTtsMailbox(
        lambda data, mouth: seen.append(data),
        lambda: seen.append("end"),
        lambda code: seen.append(code),
    )
    box.configure(24000, 1, 2)
    box.wake.connect(lambda: wakes.append(1))
    for _ in range(10):
        assert box.push(b"\0" * 100, [])
    box.finish()
    assert len(wakes) == 1 and box.buffered_bytes == 1000
    for _ in range(4):
        app.processEvents()
    assert seen == [b"\0" * 100] * 10 + ["end"]
    assert box.buffered_bytes == 0


def test_full_queue_blocks_producer_and_cancel_releases_it(app):
    box = BoundedTtsMailbox(lambda *args: None, lambda: None, lambda code: None)
    box.configure(8000, 1, 2)
    assert box.capacity == 32000
    assert box.push(b"\0" * 32000, [])
    entered, done = threading.Event(), threading.Event()
    result = []

    def produce():
        entered.set()
        result.append(box.push(b"\0\0", []))
        done.set()

    worker = threading.Thread(target=produce)
    worker.start()
    try:
        assert entered.wait(1)
        assert not done.wait(0.03)
        assert box.buffered_bytes == 32000
        box.cancel()
        assert done.wait(1)
        assert result == [False] and box.buffered_bytes == 0
    finally:
        box.cancel()
        worker.join(1)


def test_failure_discards_pending_audio_and_delivers_fixed_error_once(app):
    seen = []
    box = BoundedTtsMailbox(
        lambda *args: seen.append("chunk"), lambda: seen.append("end"), seen.append
    )
    box.configure(24000, 1, 2)
    box.push(b"\0\0", [])
    box.fail()
    box.finish()
    app.processEvents()
    app.processEvents()
    assert seen == ["tts_stream_error"]
    assert not box.push(b"\0\0", [])


def test_callback_failure_does_not_leave_a_blocked_producer(app):
    errors = []

    def broken(*args):
        raise RuntimeError("synthetic")

    box = BoundedTtsMailbox(broken, lambda: None, errors.append)
    box.configure(24000, 1, 2)
    box.push(b"\0\0", [])
    app.processEvents()
    app.processEvents()
    assert errors == ["tts_stream_error"]
    assert box.buffered_bytes == 0
    assert not box.push(b"\0\0", [])


def test_real_stream_worker_delivers_bounded_chunks_before_finished(app):
    import time
    from src.core.bridge_workers import StreamingTTSWorker
    from tests.test_companion_audio_buffer import wav

    raw = wav(b"\0\0" * (24000 * 6))

    class Provider:
        async def stream_speech(self, text):
            yield raw[:48044]
            yield raw[48044:]

    seen, errors = [], []
    worker = StreamingTTSWorker(Provider(), "가상 음성")
    worker.enable_bounded_delivery()
    worker.stream_format_ready.connect(lambda *args: seen.append("format"))
    worker.stream_chunk_ready.connect(lambda data, mouth: seen.append(data))
    worker.stream_finished.connect(lambda: seen.append("end"))
    worker.error_occurred.connect(errors.append)
    worker.start()
    deadline = time.monotonic() + 3
    try:
        while time.monotonic() < deadline and "end" not in seen and not errors:
            app.processEvents()
        assert not errors
        assert seen[0] == "format" and seen[-1] == "end"
        chunks = [item for item in seen if isinstance(item, bytes)]
        assert all(len(item) <= 32768 for item in chunks)
        assert sum(map(len, chunks)) == 24000 * 6 * 2
    finally:
        worker.request_stop()
        assert worker.wait(1000)
