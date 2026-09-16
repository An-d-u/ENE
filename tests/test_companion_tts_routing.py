"""TTS와 연결 수명 사이의 순서·Qt 깨우기·실제 출력 경계를 확인한다."""

import asyncio

import pytest

from src.core.companion.audio_buffer import WavSource
from src.core.companion.audio_coordinator import AudioRef, AudioTransfer
from src.core.companion.protocol import decode_message, encode_message
from tests.companion_helpers import sample_id
from tests.test_companion_audio_buffer import wav
from tests.test_companion_gateway import harness
from tests.test_companion_media_http import media_connection
from tests.test_companion_bridge_transcript import bridge as synthetic_bridge  # noqa: F401


@pytest.fixture
def routed_bridge(request, monkeypatch):
    from types import SimpleNamespace
    from PyQt6.QtCore import QObject, pyqtSignal
    from src.core.companion.adapter import (
        QtGatewayAdapter,
        AdmissionContext,
        AdapterCommand,
    )
    from src.core.bridge_mixins import tts

    bridge = request.getfixturevalue("synthetic_bridge")
    jobs, transfers, played = [], [], []

    class TTSJob(QObject):
        tts_ready = pyqtSignal(bytes, list)
        error_occurred = pyqtSignal(str)
        stream_format_ready = pyqtSignal(int, int, int)
        stream_chunk_ready = pyqtSignal(bytes, list)
        stream_finished = pyqtSignal()

        def __init__(self, *args):
            super().__init__()
            self.running = False
            jobs.append(self)

        def start(self):
            self.running = True

        def isRunning(self):
            return self.running

        def request_stop(self):
            self.running = False

        def quit(self):
            self.running = False

        def wait(self):
            return True

        def ready(self, raw):
            self.running = False
            self.tts_ready.emit(raw, [])

    monkeypatch.setattr(tts, "TTSWorker", TTSJob)
    monkeypatch.setattr(tts, "StreamingTTSWorker", TTSJob)
    bridge.enable_tts = True
    bridge.tts_client = SimpleNamespace(
        supports_streaming=True, uses_browser_playback=False
    )
    bridge.audio_player = SimpleNamespace(play=played.append, stop=lambda: None)
    adapter = QtGatewayAdapter(bridge)
    context = AdmissionContext(sample_id(500), 1, sample_id(600))
    adapter.configure(context.gateway_generation, 1)
    adapter._execute(AdapterCommand(sample_id(800), "connect", context, float("inf")))
    monkeypatch.setattr(
        adapter, "publish_audio", lambda command: transfers.append(command) or True
    )
    head = bridge.head()
    availability = decode_message(
        encode_message(
            {
                "type": "audio_availability",
                "protocol_version": 1,
                "registration_generation": 1,
                "server_epoch": head.server_epoch,
                "conversation_id": head.conversation_id,
                "connection_generation": context.connection_generation,
                "available": True,
                "reason": "ready",
            }
        )
    )
    bridge.submit_extension(context, availability)
    return bridge, context, jobs, transfers, played


def start_reply(bridge):
    result = bridge.submit_chat_request("가상 정육면체의 배치를 설명합니다.")
    assert result.state == "accepted"
    bridge.worker.reply(
        "가상 도형 두 개를 나란히 놓았습니다.", spoken="가상의 음성 안내입니다."
    )
    return result


def test_actual_tts_generates_once_and_phone_completion_owns_reply_gate(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    result = start_reply(bridge)
    assert len(bridge.chat_state.public_transcript.capture().messages) == 1
    raw = wav()
    jobs[0].ready(raw)
    assert len(jobs) == 1 and played == []
    assert len(bridge.chat_state.public_transcript.capture().messages) == 2
    assert bridge.life_record_state.phase == "normal_reply"
    offer = next(item for item in transfers if item.kind == "offer")
    assert offer.source.raw is raw
    bridge.submit_extension(
        context, wire(offer.ref, "audio_prepared", buffered_frames=100)
    )
    assert (
        sum(
            item.message is not None and item.message.type == "audio_start"
            for item in transfers
        )
        == 1
    )
    bridge.submit_extension(
        context, wire(offer.ref, "audio_finished", played_frames=100)
    )
    assert bridge.life_record_state.phase == "idle"
    assert (
        bridge.chat_state.request_ledger.lookup(result.request_ref.key).state
        == "completed"
    )
    assert played == []


def test_actual_tts_rejection_uses_same_wave_and_releases_gate_once(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    start_reply(bridge)
    raw = wav()
    jobs[0].ready(raw)
    offer = next(item for item in transfers if item.kind == "offer")
    rejected = wire(offer.ref, "audio_rejected", reason="focus_denied")
    bridge.submit_extension(context, rejected)
    bridge.submit_extension(context, rejected)
    assert len(played) == 1 and played[0] is raw
    assert len(jobs) == 1 and bridge.life_record_state.phase == "idle"


def test_unsupported_completed_audio_keeps_existing_pc_path(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    start_reply(bridge)
    raw = b"synthetic-unsupported-audio"
    jobs[0].ready(raw)
    assert played == [raw]
    assert not any(item.kind == "offer" for item in transfers)
    assert bridge.life_record_state.phase == "idle"


def stream_reply(routed_bridge, *, published):
    bridge, context, jobs, transfers, played = routed_bridge
    bridge.tts_streaming_enabled = True
    bridge.audio_player.start_stream = lambda *args: played.append(("format", args))
    bridge.audio_player.append_stream_pcm = lambda data: played.append(data)
    bridge.audio_player.finish_stream = lambda: played.append("end")
    result = start_reply(bridge)
    if published:
        # 이미 공개된 메시지를 가정한다. 실제 PC의 표시 시점은 변경하지 않는다.
        event = bridge.chat_state.public_transcript.publish_assistant("가상 도형 안내")
        bridge.chat_state.public_assistant_ids[result.request_ref.key] = (
            event.message.id
        )
        bridge.pending_response = None
    jobs[0].stream_format_ready.emit(24000, 1, 2)
    return result


def test_hidden_stream_stays_pc_even_after_message_becomes_public(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=False)
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    jobs[0].stream_finished.emit()
    assert played[0][0] == "format" and played[-1] == "end"
    assert not any(item.kind == "offer" for item in transfers)
    assert bridge.life_record_state.phase == "idle"


def test_public_stream_waits_for_phone_drain_without_starting_pc_sink(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=True)
    assert played == [] and transfers == []
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(
        context, wire(offer.ref, "audio_prepared", buffered_frames=2400)
    )
    jobs[0].stream_finished.emit()
    assert bridge.life_record_state.phase == "normal_reply" and played == []
    bridge.submit_extension(
        context, wire(offer.ref, "audio_finished", played_frames=2400)
    )
    assert bridge.life_record_state.phase == "idle" and played == []


def test_stream_rejected_prefix_and_future_chunks_use_pc_once(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=True)
    prefix, tail = b"\0\0" * 2400, b"\1\0" * 100
    jobs[0].stream_chunk_ready.emit(prefix, [])
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(
        context, wire(offer.ref, "audio_rejected", reason="focus_denied")
    )
    jobs[0].stream_chunk_ready.emit(tail, [])
    jobs[0].stream_finished.emit()
    assert [item for item in played if isinstance(item, bytes)] == [prefix, tail]
    assert sum(isinstance(item, tuple) for item in played) == 1
    assert played[-1] == "end"


def test_stream_disconnect_after_permission_drops_late_chunks(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=True)
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(
        context, wire(offer.ref, "audio_prepared", buffered_frames=2400)
    )
    bridge._companion_connection_closed()
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    jobs[0].stream_finished.emit()
    assert played == [] and not jobs[0].isRunning()
    assert bridge.life_record_state.phase == "idle"


@pytest.mark.parametrize("immediate", [True, False])
def test_wave_fallback_preserves_existing_pc_lip_sync(
    routed_bridge, monkeypatch, immediate
):
    bridge, context, jobs, transfers, played = routed_bridge
    lips = [(0.0, 0.2), (0.05, 0.3)]
    starts = []
    monkeypatch.setattr(
        bridge, "_start_lip_sync", lambda: starts.append(bridge.lip_sync_data)
    )
    if immediate:
        monkeypatch.setattr(
            bridge._companion_adapter, "publish_audio", lambda command: False
        )
    start_reply(bridge)
    raw = wav()
    jobs[0].tts_ready.emit(raw, lips)
    if not immediate:
        offer = next(item for item in transfers if item.kind == "offer")
        bridge.submit_extension(
            context, wire(offer.ref, "audio_rejected", reason="focus_denied")
        )
    assert played == [raw]
    assert starts == [lips] and bridge.lip_sync_data == lips


def test_phone_permission_never_replays_pc_after_wave_disconnect(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    start_reply(bridge)
    jobs[0].ready(wav())
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(
        context, wire(offer.ref, "audio_prepared", buffered_frames=100)
    )
    bridge._companion_connection_closed()
    bridge.submit_extension(
        context, wire(offer.ref, "audio_rejected", reason="focus_denied")
    )
    assert played == [] and bridge.life_record_state.phase == "idle"


def test_browser_and_disabled_tts_do_not_offer_phone(routed_bridge, monkeypatch):
    bridge, _, jobs, transfers, played = routed_bridge
    browser = []
    bridge.tts_client.uses_browser_playback = True
    monkeypatch.setattr(bridge, "_play_browser_tts", browser.append)
    start_reply(bridge)
    assert len(browser) == 1 and jobs == [] and transfers == [] and played == []
    bridge.enable_tts = False
    start_reply(bridge)
    assert len(browser) == 1 and jobs == [] and transfers == []


def test_private_file_result_cannot_offer_its_audio(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    start_reply(bridge)
    payload = dict(bridge._pending_response_completion, companion_file_result=True)
    bridge._companion_audio.bind_worker(jobs[0], payload)
    raw = wav()
    jobs[0].ready(raw)
    assert played == [raw] and not any(item.kind == "offer" for item in transfers)


def test_ptt_cancels_phone_without_pc_replay_and_finishes_gate(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    start_reply(bridge)
    jobs[0].ready(wav())
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(
        context, wire(offer.ref, "audio_prepared", buffered_frames=100)
    )
    bridge.interrupt_tts_for_ptt()
    assert played == [] and bridge.life_record_state.phase == "idle"
    assert bridge._companion_audio.coordinator.active_ref is None


def test_controller_only_advertises_installed_audio_boundary(routed_bridge):
    from src.core.companion.controller import CompanionController

    bridge, _, _, _, _ = routed_bridge
    controller = CompanionController(bridge)
    assert controller._capabilities == ("audio_pcm_v1",)


def test_settings_disable_cancels_phone_and_reenable_reuses_current_availability(
    routed_bridge,
):
    bridge, context, jobs, transfers, played = routed_bridge
    start_reply(bridge)
    jobs[0].ready(wav())
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(
        context, wire(offer.ref, "audio_prepared", buffered_frames=100)
    )
    bridge.enable_tts = False
    bridge._companion_tts_settings_changed()
    assert played == [] and bridge.life_record_state.phase == "idle"
    assert not bridge._companion_audio.coordinator.available
    bridge.enable_tts = True
    bridge._companion_tts_settings_changed()
    assert bridge._companion_audio.coordinator.available
    start_reply(bridge)
    jobs[1].ready(wav())
    assert len([item for item in transfers if item.kind == "offer"]) == 2
    bridge._companion_audio.cancel("test_complete")


def test_browser_provider_change_refreshes_status_and_disconnection_forgets_availability(
    routed_bridge,
):
    from types import SimpleNamespace

    bridge, _, _, _, _ = routed_bridge
    bridge.set_tts(SimpleNamespace(uses_browser_playback=True), bridge.audio_player)
    assert not bridge._companion_audio.coordinator.available
    bridge.set_tts(SimpleNamespace(uses_browser_playback=False), bridge.audio_player)
    assert bridge._companion_audio.coordinator.available
    bridge._companion_connection_closed()
    bridge._companion_tts_settings_changed()
    assert not bridge._companion_audio.coordinator.available


def test_stream_failure_after_permission_releases_gate_without_pc(routed_bridge):
    bridge, context, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=True)
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(
        context, wire(offer.ref, "audio_prepared", buffered_frames=2400)
    )
    jobs[0].error_occurred.emit("tts_stream_error")
    assert played == [] and bridge.life_record_state.phase == "idle"


def test_timer_fallback_sink_exception_still_releases_reply_gate(routed_bridge):
    bridge, _, jobs, _, _ = routed_bridge
    audio = bridge._companion_audio
    now = [0]
    audio.coordinator._now_ms = lambda: now[0]
    bridge.audio_player.play = lambda data: (_ for _ in ()).throw(
        RuntimeError("synthetic")
    )
    start_reply(bridge)
    jobs[0].ready(wav())
    now[0] = 2001
    audio._tick()
    assert audio.coordinator.active_ref is None and not audio.timer.isActive()
    assert bridge.life_record_state.phase == "idle"


def test_queued_start_is_discarded_when_the_utterance_is_cancelled(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            gateway,
            client,
            base,
            token,
            _,
            _,
        ):
            ws, ready, extension, _ = await media_connection(client, base, token)
            ref = AudioRef(
                ready["registration_generation"],
                ready["server_epoch"],
                extension["connection_generation"],
                ready["conversation_id"],
                sample_id(901),
                sample_id(902),
                sample_id(903),
            )
            session = gateway._active
            session.resources.add_audio(ref.utterance_id, WavSource(wav()))
            gateway.publish_audio(
                AudioTransfer("control", ref, wire(ref, "audio_start"))
            )
            gateway.publish_audio(AudioTransfer("cancel", ref))
            await ws.send_json(
                {"type": "ping", "protocol_version": 1, "nonce": sample_id(800)}
            )
            assert (await ws.receive_json(timeout=2))["type"] == "pong"
            await ws.close()

    asyncio.run(scenario())


def wire(ref, kind, **extra):
    return decode_message(
        encode_message(
            {"type": kind, "protocol_version": 1, **ref.to_fields(), **extra}
        )
    )


def test_audio_offer_and_source_end_follow_the_actual_public_message(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            gateway,
            client,
            base,
            token,
            port,
            _,
        ):
            ws, ready, extension, _ = await media_connection(client, base, token)
            event = port.transcript.publish_assistant("도형을 세는 가상 안내입니다.")
            ref = AudioRef(
                ready["registration_generation"],
                ready["server_epoch"],
                extension["connection_generation"],
                ready["conversation_id"],
                event.message.id,
                sample_id(600),
                sample_id(601),
            )
            source = WavSource(wav())
            gateway.publish(decode_message(encode_message(event.to_wire())))
            offer = wire(
                ref,
                "audio_offer",
                sample_rate=24000,
                channels=1,
                sample_width=2,
                prepare_timeout_ms=2000,
            )
            gateway.publish_audio(AudioTransfer("offer", ref, offer, source))
            gateway.publish_audio(
                AudioTransfer(
                    "control", ref, wire(ref, "audio_source_end", total_frames=100)
                )
            )
            frames = [await ws.receive_json(timeout=2) for _ in range(3)]
            assert [frame["type"] for frame in frames] == [
                "event",
                "audio_offer",
                "audio_source_end",
            ]
            assert frames[0]["payload"]["id"] == frames[1]["message_id"]
            await ws.close()

    asyncio.run(scenario())


@pytest.fixture
def qt_app(monkeypatch):
    from PyQt6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_audio_wake_is_coalesced_and_disabled_adapter_cannot_deliver(
    qt_app, monkeypatch
):
    from src.core.companion.adapter import QtGatewayAdapter
    from tests.test_companion_adapter import SyntheticOwner

    adapter = QtGatewayAdapter(SyntheticOwner())
    adapter.configure(sample_id(500), 1)
    loop = asyncio.new_event_loop()
    scheduled, delivered = [], []
    monkeypatch.setattr(
        loop, "call_soon_threadsafe", lambda fn, *args: scheduled.append((fn, args))
    )
    adapter.attach(loop, lambda _: None, media_sink=delivered.append)
    ref = AudioRef(
        1,
        sample_id(1),
        sample_id(2),
        sample_id(3),
        sample_id(4),
        sample_id(5),
        sample_id(6),
    )
    try:
        for _ in range(100):
            assert adapter.publish_audio(AudioTransfer("notify", ref))
        assert len(scheduled) == 1
        fn, args = scheduled.pop()
        fn(*args)
        assert len(delivered) == 1
        adapter.publish_audio(AudioTransfer("notify", ref))
        adapter.disable()
        fn, args = scheduled.pop()
        fn(*args)
        assert len(delivered) == 1
        assert not adapter.publish_audio(AudioTransfer("notify", ref))
    finally:
        adapter.detach()
        loop.close()
