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


@pytest.mark.parametrize("failure", ["unavailable", "unsupported", "private", "rejected"])
def test_manual_phone_wave_failure_stays_silent(routed_bridge, failure):
    bridge, context, jobs, transfers, played = routed_bridge
    bridge.tts_output_target = "phone"
    if failure == "unavailable":
        bridge._companion_audio.disconnected()
    start_reply(bridge)
    if failure == "private":
        bridge._companion_audio.bind_worker(jobs[0], dict(bridge._pending_response_completion, companion_file_result=True))
    jobs[0].ready(b"synthetic-unsupported-audio" if failure == "unsupported" else wav())
    if failure == "rejected":
        offer = next(item for item in transfers if item.kind == "offer")
        bridge.submit_extension(context, wire(offer.ref, "audio_rejected", reason="focus_denied"))
    else:
        assert not any(item.kind == "offer" for item in transfers)
    assert played == [] and bridge.life_record_state.phase == "idle"


def test_manual_pc_skips_phone_and_policy_is_captured_before_generation(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    bridge.tts_output_target = "pc"
    start_reply(bridge)
    bridge.tts_output_target = "phone"
    bridge._companion_tts_settings_changed()
    raw = wav()
    jobs[0].ready(raw)
    assert played == [raw] and not any(item.kind == "offer" for item in transfers)


@pytest.mark.parametrize("change_at", ["generation", "preparing", "playing"])
def test_phone_choice_change_applies_only_to_next_utterance(routed_bridge, change_at):
    bridge, context, jobs, transfers, played = routed_bridge
    bridge.tts_output_target = "phone"
    start_reply(bridge)
    if change_at == "generation":
        bridge.tts_output_target = "pc"
        bridge._companion_tts_settings_changed()
    jobs[0].ready(wav())
    offer = next(item for item in transfers if item.kind == "offer")
    if change_at == "preparing":
        bridge.tts_output_target = "pc"
        bridge._companion_tts_settings_changed()
    bridge.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=100))
    if change_at == "playing":
        bridge.tts_output_target = "pc"
        bridge._companion_tts_settings_changed()
    bridge.submit_extension(context, wire(offer.ref, "audio_finished", played_frames=100))
    assert played == [] and bridge.life_record_state.phase == "idle"
    start_reply(bridge)
    raw = wav()
    jobs[1].ready(raw)
    assert played == [raw]
    assert len([item for item in transfers if item.kind == "offer"]) == 1


@pytest.mark.parametrize("failure", ["unavailable", "pending_disconnect", "unsupported", "rejected"])
def test_manual_phone_stream_failure_stays_silent(routed_bridge, failure):
    bridge, context, jobs, transfers, played = routed_bridge
    bridge.tts_output_target = "phone"
    if failure == "unavailable":
        bridge._companion_audio.disconnected()
    if failure == "unsupported":
        bridge.tts_streaming_enabled = True
        bridge.audio_player.start_stream = lambda *args: played.append(args)
        bridge.audio_player.append_stream_pcm = played.append
        bridge.audio_player.finish_stream = lambda: played.append("end")
        start_reply(bridge)
        jobs[0].stream_format_ready.emit(96000, 1, 2)
    else:
        stream_reply(routed_bridge, published=False)
    if failure == "pending_disconnect":
        bridge._companion_audio.disconnected()
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    if failure == "rejected":
        offer = next(item for item in transfers if item.kind == "offer")
        bridge.submit_extension(context, wire(offer.ref, "audio_rejected", reason="focus_denied"))
    jobs[0].stream_finished.emit()
    assert played == [] and bridge.life_record_state.phase == "idle"


def test_manual_phone_browser_never_builds_or_plays_request(routed_bridge, monkeypatch):
    bridge, _, jobs, transfers, played = routed_bridge
    bridge.tts_output_target = "phone"
    bridge.tts_client.uses_browser_playback = True
    browser = []
    monkeypatch.setattr(bridge, "_play_browser_tts", browser.append)
    start_reply(bridge)
    assert browser == jobs == transfers == played == []
    assert bridge.life_record_state.phase == "idle"


def test_local_diagnostics_work_without_phone_and_report_blocked_browser(routed_bridge):
    bridge, _, _, _, _ = routed_bridge
    bridge._companion_audio.disconnected()
    bridge.tts_output_target = "phone"
    bridge._companion_tts_settings_changed()
    assert bridge.companion_audio_status()["reason"] == "phone_not_connected"
    bridge.tts_client.uses_browser_playback = True
    start_reply(bridge)
    assert bridge.companion_audio_status() == {
        "preference": "phone", "output": "none", "state": "stopped", "reason": "browser_tts"
    }


def test_rejection_reason_survives_unchanged_availability(routed_bridge):
    bridge, context, jobs, transfers, _ = routed_bridge
    bridge.tts_output_target = "phone"
    start_reply(bridge)
    jobs[0].ready(wav())
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(context, wire(offer.ref, "audio_rejected", reason="focus_denied"))
    before = bridge.companion_audio_status()
    assert before["reason"] == "focus_denied" and before["state"] == "stopped"
    availability = {key: value for key, value in offer.ref.to_fields().items()
                    if key in {"registration_generation", "server_epoch", "connection_generation", "conversation_id"}}
    status = bridge.submit_extension(context, decode_message(encode_message({
        **availability, "type": "audio_availability", "protocol_version": 1, "available": True, "reason": "ready"
    })))
    assert bridge.companion_audio_status() == before
    assert status.fields["reason"] == "focus_denied"


def test_next_pc_choice_keeps_legacy_auto_until_phone_finishes(routed_bridge):
    bridge, context, jobs, transfers, _ = routed_bridge
    bridge.tts_output_target = "phone"
    start_reply(bridge)
    bridge.tts_output_target = "pc"
    bridge._companion_tts_settings_changed()
    assert bridge._companion_audio._refresh_status().fields["mode"] == "auto"
    jobs[0].ready(wav())
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=100))
    status = bridge._companion_audio._refresh_status().fields
    assert (status["mode"], status["preference"], status["output"]) == ("auto", "pc", "phone")
    bridge.submit_extension(context, wire(offer.ref, "audio_finished", played_frames=100))
    assert bridge._companion_audio._refresh_status().fields["mode"] == "pc_only"


def test_auto_fallback_reports_original_reason_and_stale_event_is_ignored(routed_bridge):
    from dataclasses import replace
    bridge, context, jobs, transfers, _ = routed_bridge
    start_reply(bridge)
    jobs[0].ready(wav())
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(context, wire(offer.ref, "audio_rejected", reason="audio_download_failed"))
    status = bridge.companion_audio_status()
    assert (status["output"], status["reason"]) == ("pc", "audio_download_failed")
    bridge._companion_audio._route_status(replace(offer.ref, utterance_id=sample_id(991)), "none", "stopped", "focus_denied")
    assert bridge.companion_audio_status() == status


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


def test_pending_stream_publishes_before_offer_and_waits_for_phone(routed_bridge, monkeypatch):
    bridge, context, jobs, transfers, played = routed_bridge
    events = []
    bridge.companion_event.connect(lambda event: events.append("message"))
    original_publish = bridge._companion_adapter.publish_audio
    monkeypatch.setattr(bridge._companion_adapter, "publish_audio", lambda command: (
        events.append(command.kind), original_publish(command)
    )[1])
    result = stream_reply(routed_bridge, published=False)
    assert played == [] and transfers == []
    assert result.request_ref.key not in bridge.chat_state.public_assistant_ids
    events.clear()
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    offer = next(item for item in transfers if item.kind == "offer")
    assert events.index("message") < events.index("offer")
    assert offer.ref.message_id == bridge.chat_state.public_assistant_ids[result.request_ref.key]
    assert offer.source.total_frames == 2400
    assert bridge.life_record_state.phase == "normal_reply"
    bridge.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=2400))
    jobs[0].stream_finished.emit()
    assert bridge.life_record_state.phase == "normal_reply" and played == []
    bridge.submit_extension(context, wire(offer.ref, "audio_finished", played_frames=2400))
    assert bridge.life_record_state.phase == "idle" and played == []


def test_format_without_pcm_finishes_text_without_starting_audio(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=False)
    jobs[0].stream_chunk_ready.emit(b"", [])
    jobs[0].stream_finished.emit()
    assert played == [] and transfers == []
    assert bridge.life_record_state.phase == "idle"
    assert len(bridge.chat_state.public_transcript.capture().messages) == 2


def test_cancel_before_first_pcm_drops_late_data(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=False)
    bridge.interrupt_tts_for_ptt()
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    jobs[0].stream_finished.emit()
    assert played == [] and transfers == []
    assert bridge.life_record_state.phase == "idle"


def test_invalid_first_pcm_does_not_start_either_sink(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=False)
    jobs[0].stream_chunk_ready.emit(b"\0", [])
    assert not jobs[0].isRunning()
    jobs[0].stream_finished.emit()
    assert played == [] and transfers == []
    assert bridge.life_record_state.phase == "idle"


def test_pending_stream_disconnect_uses_same_pcm_on_pc(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=False)
    bridge._companion_audio.disconnected()
    pcm = b"\0\0" * 2400
    jobs[0].stream_chunk_ready.emit(pcm, [])
    jobs[0].stream_finished.emit()
    assert [item for item in played if isinstance(item, bytes)] == [pcm]
    assert sum(isinstance(item, tuple) for item in played) == 1
    assert played[-1] == "end" and transfers == []
    assert bridge.life_record_state.phase == "idle"


def test_pending_stream_generation_failure_releases_without_audio(routed_bridge):
    bridge, _, jobs, transfers, played = routed_bridge
    stream_reply(routed_bridge, published=False)
    jobs[0].error_occurred.emit("synthetic_failure")
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    jobs[0].stream_finished.emit()
    assert played == [] and transfers == []
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


def test_controller_only_advertises_installed_media_boundaries(routed_bridge):
    from src.core.companion.controller import CompanionController

    bridge, _, _, _, _ = routed_bridge
    controller = CompanionController(bridge)
    assert controller._capabilities == ("audio_pcm_v1", "character_v1", "character_controls_v1")
    assert controller._character is bridge._companion_character


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
