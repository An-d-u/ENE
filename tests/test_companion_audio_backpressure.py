"""실제 TTS 워커와 Qt 연결부에서 느린 소비자의 음성 전달을 검증한다."""

import asyncio
import threading
import time

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from src.core.bridge_workers import StreamingTTSWorker
from tests.test_companion_audio_buffer import wav
from tests.test_companion_tts_routing import (  # noqa: F401
    routed_bridge, start_reply, synthetic_bridge, wire,
)


def pump_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        QApplication.processEvents()
        QTest.qWait(1)
    assert predicate()


@pytest.fixture
def real_stream(routed_bridge, monkeypatch):
    from src.core.bridge_mixins import tts

    bridge, context, _, transfers, played = routed_bridge
    bridge.tts_streaming_enabled = True
    bridge.tts_output_target = "phone"
    release = threading.Event()
    pcm = bytes(range(256)) * 500
    first_size = 4000
    raw = wav(pcm, rate=8000)
    workers = []

    class Provider:
        supports_streaming = True
        uses_browser_playback = False

        async def stream_speech(self, *args, **kwargs):
            yield raw[:44 + first_size]
            while not release.is_set():
                await asyncio.sleep(0.001)
            yield raw[44 + first_size:]

    class Worker(StreamingTTSWorker):
        def __init__(self, *args):
            super().__init__(*args)
            workers.append(self)

    monkeypatch.setattr(tts, "StreamingTTSWorker", Worker)
    bridge.tts_client = Provider()
    bridge.audio_player.start_stream = lambda *args: played.append(("format", args))
    bridge.audio_player.append_stream_pcm = played.append
    bridge.audio_player.finish_stream = lambda: played.append("end")
    try:
        yield bridge, context, transfers, played, release, pcm, workers
    finally:
        release.set()
        for worker in workers:
            worker.request_stop()
            assert worker.wait(2000)
        bridge._companion_audio.cancel("interrupted")
        QApplication.processEvents()


def test_real_stream_worker_waits_for_slow_phone_without_losing_pcm(real_stream):
    bridge, context, transfers, played, release, pcm, workers = real_stream
    received = bytearray()
    heartbeat = []
    ui_timer = QTimer()
    ui_timer.setInterval(1)
    ui_timer.timeout.connect(lambda: heartbeat.append(True))
    consumer = QTimer()
    consumer.setInterval(5)
    peak_bytes = [0, 0]
    try:
        start_reply(bridge)
        pump_until(lambda: any(item.kind == "offer" for item in transfers))
        offer = next(item for item in transfers if item.kind == "offer")
        source = offer.source

        def consume():
            peak_bytes[0] = max(peak_bytes[0], source.buffered_bytes)
            peak_bytes[1] = max(peak_bytes[1], workers[0]._delivery.buffered_bytes)
            chunk = source.peek(1000)
            if chunk is not None:
                received.extend(chunk)
                source.consume(len(chunk))

        consume()
        bridge.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=500))
        bridge.submit_extension(context, wire(offer.ref, "audio_started", played_frames=0))
        consumer.timeout.connect(consume)
        consumer.start()
        ui_timer.start()
        release.set()
        pump_until(lambda: source.closed or (source.source_ended and source.peek() is None))
        assert not source.closed, bridge._companion_audio._diagnostic
        assert bytes(received) == pcm
        assert peak_bytes[0] <= source.buffer_limit == 32000
        assert peak_bytes[1] <= workers[0]._delivery.capacity == 32000
        assert len(heartbeat) >= 10
        assert played == []
        assert sum(item.message is not None and item.message.type == "audio_source_end" for item in transfers) == 1
        bridge.submit_extension(context, wire(offer.ref, "audio_finished", played_frames=len(pcm) // 2))
        assert bridge.life_record_state.phase == "idle"
    finally:
        consumer.stop()
        ui_timer.stop()


@pytest.mark.parametrize("failure", ["disconnect", "ready_timeout"])
@pytest.mark.parametrize("target", ["auto", "phone"])
def test_waiting_before_phone_commit_obeys_output_policy(real_stream, target, failure):
    bridge, _, transfers, played, release, pcm, workers = real_stream
    bridge.tts_output_target = target
    start_reply(bridge)
    pump_until(lambda: any(item.kind == "offer" for item in transfers))
    offer = next(item for item in transfers if item.kind == "offer")
    box = workers[0]._delivery
    release.set()
    pump_until(lambda: box._retry.isActive() and box.buffered_bytes == box.capacity)
    assert offer.source.buffered_bytes == 4000
    assert played == [] and workers[0].isRunning()
    audio = bridge._companion_audio
    if failure == "disconnect":
        audio.disconnected()
    else:
        audio.coordinator._now_ms = lambda: 10**12
        audio._tick()
    if target == "auto":
        pump_until(lambda: "end" in played)
        assert b"".join(item for item in played if isinstance(item, bytes)) == pcm
        assert sum(isinstance(item, tuple) and item[0] == "format" for item in played) == 1
        assert played.count("end") == 1
    else:
        pump_until(lambda: not workers[0].isRunning())
        QTest.qWait(35)
        assert played == []
    assert offer.source.closed and box.buffered_bytes == 0
    assert bridge.life_record_state.phase == "idle"


@pytest.mark.parametrize("failure", ["disconnect", "cancel", "playback_timeout"])
def test_waiting_after_phone_commit_stops_worker_without_pc_fallback(real_stream, failure):
    bridge, context, transfers, played, release, _, workers = real_stream
    bridge.tts_output_target = "auto"
    start_reply(bridge)
    pump_until(lambda: any(item.kind == "offer" for item in transfers))
    offer = next(item for item in transfers if item.kind == "offer")
    offer.source.consume(4000)
    bridge.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=2000))
    bridge.submit_extension(context, wire(offer.ref, "audio_started", played_frames=0))
    release.set()
    box = workers[0]._delivery
    pump_until(lambda: box._retry.isActive() and box.buffered_bytes == box.capacity)
    audio = bridge._companion_audio
    if failure == "disconnect":
        audio.disconnected()
    elif failure == "cancel":
        audio.cancel("interrupted")
    else:
        audio.coordinator._now_ms = lambda: 10**12
        audio._tick()
    pump_until(lambda: not workers[0].isRunning())
    QTest.qWait(35)
    assert box.buffered_bytes == 0 and offer.source.closed
    assert played == []
    assert not any(item.message and item.message.type == "audio_source_end" for item in transfers)


def test_old_worker_guard_cannot_wait_on_new_worker_source(real_stream):
    bridge, _, transfers, played, release, _, workers = real_stream
    start_reply(bridge)
    pump_until(lambda: any(item.kind == "offer" for item in transfers))
    release.set()
    box = workers[0]._delivery
    pump_until(lambda: box._retry.isActive() and box.buffered_bytes == box.capacity)
    audio = bridge._companion_audio
    assert not audio._can_deliver_stream_chunk(workers[0], b"\0" * 32000)
    active = bridge._active_tts_operation
    try:
        bridge._active_tts_operation = (active[0], object())
        assert audio._can_deliver_stream_chunk(workers[0], b"\0" * 32000)
    finally:
        bridge._active_tts_operation = active
    # 이전 워커의 재시도를 다음 발화가 준비된 뒤 도착시킨다.
    box._retry.stop()
    audio.cancel("interrupted")
    pump_until(lambda: not workers[0].isRunning())
    release.clear()
    start_reply(bridge)
    pump_until(lambda: sum(item.kind == "offer" for item in transfers) == 2)
    new_offer = [item for item in transfers if item.kind == "offer"][-1]
    before = list(transfers)
    box._retry.start()
    QTest.qWait(35)
    assert transfers == before and played == []
    assert audio.coordinator.active_ref == new_offer.ref
    assert not new_offer.source.closed and new_offer.source.total_frames == 2000
    assert box.buffered_bytes == 0 and not box._retry.isActive()
