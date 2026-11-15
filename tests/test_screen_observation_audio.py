"""자동 관찰의 공개 메시지, 음성 라우팅과 사용자 입력 우선순위를 검증한다."""

from threading import Event
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

from tests.test_companion_tts_routing import (
    routed_bridge, start_reply, synthetic_bridge, wav, wire,
)


def deliver(bridge, raw='{"reply":"합성 격자의 순서가 바뀌었습니다.","tts":"격자 순서 변경"}'):
    bridge._screen_share = SimpleNamespace(
        question=False, observe=True, observe_epoch=1, generation=3, validate=lambda: True
    )
    bridge.audio_player.stream_sink = None
    bridge.audio_player.player = SimpleNamespace(isPlaying=lambda: False)
    bridge._observation_pending = bridge._ambient_context()
    bridge._finish_screen_observation(bridge._observation_pending, raw)


@pytest.mark.parametrize("target", ["pc", "auto", "phone"])
def test_observation_routes_using_its_single_public_message(routed_bridge, target):
    bridge, context, jobs, transfers, played = routed_bridge
    bridge.tts_output_target = target
    local, legacy = [], []
    bridge.chat_display_event.connect(local.append)
    bridge.message_received.connect(lambda *args: legacy.append(args))
    deliver(bridge)
    messages = bridge.chat_state.public_transcript.capture().messages
    assert len(messages) == 1
    assert (messages[0].role, messages[0].text) == ("assistant", "합성 격자의 순서가 바뀌었습니다.")
    assert len(local) == 1 and not legacy
    assert not bridge.conversation_buffer and bridge.life_record_state.phase == "idle"
    raw = wav()
    jobs[0].ready(raw)
    offers = [item for item in transfers if item.kind == "offer"]
    if target == "pc":
        assert played == [raw] and not offers
    else:
        assert len(offers) == 1 and offers[0].ref.message_id == messages[0].id
        assert not played and bridge._ambient_busy()
        bridge.submit_extension(context, wire(offers[0].ref, "audio_prepared", buffered_frames=100))
        assert bridge._ambient_busy()
        bridge.submit_extension(context, wire(offers[0].ref, "audio_finished", played_frames=100))
        assert not bridge._ambient_busy()


def test_silent_judgment_does_not_publish_or_route(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    deliver(bridge, '{"reply":"","tts":""}')
    assert not bridge.chat_state.public_transcript.capture().messages
    assert not jobs and not transfers and not played and not bridge.conversation_buffer


def test_completed_observation_callback_cannot_replay(routed_bridge):
    bridge, _, jobs, _, played = routed_bridge
    bridge.tts_output_target = "pc"
    deliver(bridge)
    raw = wav()
    jobs[0].ready(raw)
    jobs[0].tts_ready.emit(raw, [])
    assert played == [raw]


def test_user_interrupts_observation_phone_stream_before_normal_admission(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    bridge.tts_streaming_enabled = True
    bridge.tts_output_target = "phone"
    deliver(bridge)
    jobs[0].stream_format_ready.emit(24000, 1, 2)
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=2400))
    bridge.tts_streaming_enabled = False
    bridge.tts_output_target = "pc"
    start_reply(bridge)
    assert bridge._companion_audio.coordinator.active_ref is None
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 1200, [])
    jobs[0].stream_finished.emit()
    bridge.submit_extension(context, wire(offer.ref, "audio_finished", played_frames=2400))
    assert bridge.pending_response and not played
    raw = wav()
    jobs[1].ready(raw)
    assert played == [raw] and bridge.life_record_state.phase == "idle"


def test_slow_observation_worker_drains_without_holding_user_reply(routed_bridge, monkeypatch):
    from src.core.app import ENEApplication
    from src.core.bridge_mixins import tts

    bridge, _, jobs, _, played = routed_bridge
    entered, release = Event(), Event()
    gui_waits = []
    regular_worker = tts.TTSWorker

    class SlowWorker(QThread):
        tts_ready = pyqtSignal(bytes, list)
        error_occurred = pyqtSignal(str)

        def __init__(self, *args):
            super().__init__()

        def run(self):
            entered.set()
            release.wait(5)

        def wait(self, *args):
            gui_waits.append(True)
            return False

    monkeypatch.setattr(tts, "TTSWorker", SlowWorker)
    bridge.tts_output_target = "pc"
    deliver(bridge)
    old = bridge.tts_worker
    try:
        assert entered.wait(2)
        monkeypatch.setattr(tts, "TTSWorker", regular_worker)
        start_reply(bridge)
        assert not gui_waits
        assert old.isRunning() and old.isInterruptionRequested()
        app = ENEApplication.__new__(ENEApplication)
        assert old in app._collect_shutdown_workers(bridge)
        old.tts_ready.emit(wav(), [])
        old.error_occurred.emit("synthetic_error")
        assert bridge.pending_response and not played
        raw = wav()
        jobs[0].ready(raw)
        assert played == [raw] and bridge.life_record_state.phase == "idle"
    finally:
        release.set()
        assert QThread.wait(old, 3000)
        QApplication.processEvents()
    assert old not in bridge._observation_tts_workers
