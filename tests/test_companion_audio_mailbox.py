"""생산자와 Qt 사이의 대기량·종료 순서를 가상 음성으로 검사한다."""

import threading

import pytest
from PyQt6.QtWidgets import QApplication
from PyQt6.QtTest import QTest

from src.core.companion.audio_mailbox import BoundedTtsMailbox
from tests.test_companion_audio_coordinator import setup as audio_setup  # noqa: F401


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


def test_downstream_wait_retains_bytes_and_delays_tail_and_completion(app):
    seen, guards, wakes = [], [], []
    ready = [False]

    def guard(data):
        guards.append(data)
        return ready[0]

    box = BoundedTtsMailbox(
        lambda data, mouth: seen.append((data, mouth)),
        lambda: seen.append("end"), seen.append, can_deliver=guard,
    )
    box.configure(8000, 1, 2)
    box.wake.connect(lambda: wakes.append(True))
    box.push(b"\1\2", [0.5])
    app.processEvents()
    box.push(b"", [0.0])
    box.finish()
    QTest.qWait(35)
    assert seen == [] and box.buffered_bytes == 2
    assert len(wakes) == 1 and 1 <= len(guards) <= 5
    ready[0] = True
    QTest.qWait(35)
    assert seen == [(b"\1\2", [0.5]), (b"", [0.0]), "end"]
    assert box.buffered_bytes == 0
    assert b"" not in guards


@pytest.mark.parametrize("action", ["cancel", "fail"])
def test_waiting_mailbox_releases_producer_on_cross_thread_close(app, action):
    seen, result = [], []
    entered = threading.Event()
    box = BoundedTtsMailbox(
        lambda *args: seen.append("chunk"), lambda: seen.append("end"),
        seen.append, can_deliver=lambda data: False,
    )
    box.configure(8000, 1, 2)
    box.push(b"\0" * 32000, [])
    app.processEvents()

    def produce():
        entered.set()
        result.append(box.push(b"\0\0", []))

    worker = threading.Thread(target=produce)
    worker.start()
    try:
        assert entered.wait(1)
        closer = threading.Thread(target=getattr(box, action))
        closer.start()
        closer.join(1)
        worker.join(1)
        assert not worker.is_alive() and result == [False]
        QTest.qWait(35)
        assert seen == (["tts_stream_error"] if action == "fail" else [])
        assert box.buffered_bytes == 0
    finally:
        box.cancel()
        worker.join(1)


@pytest.mark.parametrize("action", ["cancel", "raise"])
def test_guard_reentrant_cancel_or_exception_never_delivers_head(app, action):
    seen = []

    def guard(data):
        if action == "raise":
            raise RuntimeError("synthetic")
        box.cancel()
        return True

    box = BoundedTtsMailbox(
        lambda *args: seen.append("chunk"), lambda: seen.append("end"),
        seen.append, can_deliver=guard,
    )
    box.configure(8000, 1, 2)
    box.push(b"\0\0", [])
    box.finish()
    QTest.qWait(35)
    assert seen == (["tts_stream_error"] if action == "raise" else [])
    assert box.buffered_bytes == 0


def test_wait_preserves_chunk_count_limit_and_resumes_producer(app):
    seen, result = [], []
    entered, done = threading.Event(), threading.Event()
    ready = [False]
    box = BoundedTtsMailbox(
        lambda data, mouth: seen.append(data), lambda: seen.append("end"),
        seen.append, can_deliver=lambda data: ready[0],
    )
    box.configure(8000, 1, 2)
    for _ in range(128):
        box.push(b"\1\2", [])
    app.processEvents()

    def produce():
        entered.set()
        result.append(box.push(b"\3\4", []))
        box.finish()
        done.set()

    worker = threading.Thread(target=produce)
    worker.start()
    try:
        assert entered.wait(1) and not done.wait(0.03)
        assert box.buffered_bytes == 256 and seen == []
        ready[0] = True
        for _ in range(100):
            QTest.qWait(5)
            if "end" in seen:
                break
        assert result == [True]
        assert seen == [b"\1\2"] * 128 + [b"\3\4", "end"]
        assert box.buffered_bytes == 0
    finally:
        box.cancel()
        worker.join(1)


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


@pytest.mark.parametrize("truncated", [False, True])
def test_real_worker_keeps_split_frames_valid_through_phone_route(app, request, truncated):
    import time
    from src.core.bridge_workers import StreamingTTSWorker
    from src.core.companion.audio_buffer import PcmFormat
    from tests.test_companion_audio_buffer import wav
    from tests.test_companion_audio_coordinator import command, prepare

    coordinator, ref, transport, sink, completed, _ = request.getfixturevalue("audio_setup")
    pcm = b"\x01\x23" * 24000
    raw = wav(pcm)
    if truncated:
        raw = raw[:-1]

    class Provider:
        async def stream_speech(self, text):
            for offset in range(0, len(raw), 4095):
                yield raw[offset:offset + 4095]

    received, errors, ends = [], [], []
    worker = StreamingTTSWorker(Provider(), "구의 회전 방향을 안내합니다.")
    worker.enable_bounded_delivery()
    worker.stream_format_ready.connect(lambda rate, channels, width: coordinator.begin_stream(
        ref, PcmFormat(rate, channels, width), allow_pc_fallback=False))

    def chunk(data, mouth):
        coordinator.offer_pcm(ref, data)
        source = transport.source
        if coordinator.active_ref and source.total_frames >= 4800 and coordinator.target != "phone":
            prepare(coordinator, ref)
        if coordinator.target == "phone":
            while part := source.peek():
                received.append(bytes(part))
                source.consume(len(part))

    def finished():
        ends.append(True)
        coordinator.source_end(ref)
        coordinator.receive(command(ref, "audio_finished", played_frames=24000))

    worker.stream_chunk_ready.connect(chunk)
    worker.stream_finished.connect(finished)
    worker.error_occurred.connect(errors.append)
    worker.start()
    try:
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not ends and not errors:
            app.processEvents()
        if truncated:
            assert errors == ["tts_stream_error"] and not ends
        else:
            assert not errors and ends == [True]
            assert completed == [(ref, "finished")]
            assert b"".join(received) == pcm
        assert sink.waves == sink.formats == sink.chunks == []
    finally:
        worker.request_stop()
        assert worker.wait(1000)
        coordinator.cancel(ref, "interrupted")
