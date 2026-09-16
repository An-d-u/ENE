"""가상 출력 위치로 기기별 입모양과 공개 발화 수명을 확인한다."""

import json

import pytest

from tests.test_companion_tts_routing import (  # noqa: F401
    routed_bridge, synthetic_bridge, start_reply, stream_reply, wire, wav,
)


@pytest.fixture
def playback(request, monkeypatch):
    routed = request.getfixturevalue("routed_bridge")
    bridge, context, jobs, transfers, played = routed
    now, position, events, mouths = [0], [0], [], []
    monkeypatch.setattr(bridge._companion_adapter, "publish_extension",
                        lambda kind, fields: events.append((kind, dict(fields))))
    bridge.audio_player.position_ms = lambda: position[0]
    bridge.lip_sync_update.connect(mouths.append)
    bridge._companion_audio.playback.now_ms = lambda: now[0]
    return routed, now, position, events, mouths


def test_phone_uses_consumed_frames_and_closes_after_750ms(playback):
    (bridge, context, jobs, transfers, played), now, _, events, mouths = playback
    start_reply(bridge)
    jobs[0].ready(wav(b"\0\0" * 24000))
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(context, wire(offer.ref, "audio_prepared", buffered_frames=4800))
    bridge.submit_extension(context, wire(offer.ref, "audio_started", played_frames=0))
    bridge.submit_extension(context, wire(offer.ref, "audio_progress", played_frames=6000, mouth_open=0.6))
    assert mouths[-1] == 0.6 and played == []
    now[0] = 100
    bridge._companion_audio._tick()
    assert events[-1][1]["played_ms"] == 250
    assert events[-1][1]["output"] == "phone"
    bridge._emit_mouth_signals(0.9)
    assert mouths[-1] == 0.6
    now[0] = 750
    bridge._companion_audio._tick()
    assert mouths[-1] == 0.0
    bridge.submit_extension(context, wire(offer.ref, "audio_progress", played_frames=7200, mouth_open=0.4))
    assert mouths[-1] == 0.4
    bridge.submit_extension(context, wire(offer.ref, "audio_finished", played_frames=24000))
    assert mouths[-1] == 0.0 and not events[-1][1]["active"]
    assert not bridge._companion_audio.timer.isActive()


def test_pc_wave_survives_reply_completion_and_uses_actual_position(playback):
    (bridge, context, jobs, transfers, played), now, position, events, _ = playback
    start_reply(bridge)
    jobs[0].tts_ready.emit(wav(), [(0, 0.2), (0.1, 0.7), (1, 0)])
    offer = next(item for item in transfers if item.kind == "offer")
    bridge.submit_extension(context, wire(offer.ref, "audio_rejected", reason="focus_denied"))
    assert bridge.life_record_state.phase == "idle" and len(played) == 1
    position[0] = 123
    now[0] = 100
    bridge._update_lip_sync()
    bridge._companion_audio._tick()
    assert events[-1][1]["output"] == "pc"
    assert events[-1][1]["played_ms"] == 123
    assert events[-1][1]["mouth_open"] == 0.7
    assert events[-1][1]["message_id"] == offer.ref.message_id
    assert bridge._companion_audio.timer.isActive()


def test_pc_route_needs_no_audio_availability_or_audio_capability(playback):
    (bridge, _, jobs, _, played), now, position, events, _ = playback
    bridge._companion_audio.coordinator.context = None
    bridge._companion_audio.coordinator.available = False
    result = start_reply(bridge)
    jobs[0].ready(wav())
    position[0] = 91
    now[0] = 100
    bridge._companion_audio._tick()
    assert played and events[-1][1]["output"] == "pc"
    assert events[-1][1]["message_id"] == bridge.chat_state.public_assistant_ids[result.request_ref.key]
    assert events[-1][1]["played_ms"] == 91


def test_unpublished_stream_starts_character_only_after_public_text(playback):
    routed, now, position, events, _ = playback
    bridge, _, jobs, _, _ = routed
    stream_reply(routed, published=False)
    assert not events
    jobs[0].stream_chunk_ready.emit(b"\0\0" * 2400, [])
    jobs[0].stream_finished.emit()
    position[0] = 44
    now[0] = 100
    bridge._companion_audio._tick()
    assert events[-1][1]["output"] == "pc"
    assert events[-1][1]["played_ms"] == 44


def test_private_file_and_cancelled_reply_never_publish_playback(playback):
    (bridge, _, jobs, _, _), _, _, events, _ = playback
    start_reply(bridge)
    payload = dict(bridge._pending_response_completion, companion_file_result=True)
    bridge._companion_audio.bind_worker(jobs[0], payload)
    jobs[0].ready(wav())
    bridge._companion_audio._tick()
    assert not events


def test_disconnection_and_new_output_do_not_replay_old_mouth(playback):
    (bridge, _, jobs, _, _), _, _, events, mouths = playback
    bridge._companion_audio.coordinator.available = False
    start_reply(bridge)
    jobs[0].ready(wav())
    assert bridge._companion_audio.playback.active
    bridge._companion_connection_closed()
    assert not bridge._companion_audio.playback.active
    assert not events[-1][1]["active"] and mouths[-1] == 0


def test_character_publish_exception_does_not_interrupt_audio(playback, monkeypatch):
    (bridge, _, jobs, _, played), _, _, _, _ = playback
    bridge._companion_audio.coordinator.available = False
    monkeypatch.setattr(bridge._companion_adapter, "publish_extension",
                        lambda *args: (_ for _ in ()).throw(RuntimeError("합성 표시 오류")))
    start_reply(bridge)
    jobs[0].ready(wav())
    assert len(played) == 1 and bridge.life_record_state.phase == "idle"


def test_pc_lips_use_position_not_wall_clock_and_close_when_stalled(playback, monkeypatch):
    (bridge, _, jobs, _, _), _, position, _, mouths = playback
    bridge._companion_audio.coordinator.available = False
    clock = [0.0]
    monkeypatch.setattr("src.core.bridge_mixins.tts.time.monotonic", lambda: clock[0])
    start_reply(bridge)
    jobs[0].tts_ready.emit(wav(), [(0, 0.2), (0.1, 0.7), (1, 0)])
    position[0] = 120
    bridge._update_lip_sync()
    assert mouths[-1] == 0.7
    clock[0] = 0.8
    bridge._update_lip_sync()
    assert mouths[-1] == 0.0
    position[0] = 140
    bridge._update_lip_sync()
    assert mouths[-1] == 0.7
    pose = []
    bridge.mouth_pose_update.connect(pose.append)
    bridge._companion_audio.cancel("test_complete")
    assert json.loads(pose[-1])["open"] == 0


def test_pc_status_is_at_most_ten_per_second_and_finishes_on_player_signal(playback):
    from PyQt6.QtCore import QObject, pyqtSignal

    class Player(QObject):
        playback_finished = pyqtSignal()
        playback_error = pyqtSignal(str)
        def play(self, _raw):
            pass
        def position_ms(self):
            return now[0]

    (bridge, _, jobs, _, _), now, _, events, _ = playback
    bridge._companion_audio.coordinator.available = False
    bridge.audio_player = Player()
    start_reply(bridge)
    jobs[0].ready(wav())
    for number in range(1, 20):
        now[0] = number * 50
        bridge._companion_audio._tick()
    assert len(events) == 10
    bridge.audio_player.playback_finished.emit()
    assert not events[-1][1]["active"]
    bridge._companion_audio._tick()
    assert not bridge._companion_audio.timer.isActive()
    assert not bridge._companion_audio.playback._connections


def test_unresponsive_pc_player_cannot_keep_character_timer_forever(playback):
    (bridge, _, jobs, _, _), now, _, events, _ = playback
    bridge._companion_audio.coordinator.available = False
    start_reply(bridge)
    jobs[0].ready(wav())
    now[0] = 180751
    bridge._companion_audio._tick()
    assert not bridge._companion_audio.timer.isActive()
    assert not events[-1][1]["active"]
