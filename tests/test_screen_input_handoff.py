"""합성 프레임만 사용해 PC 사용자 요청의 귀속과 폐기 시점을 검증한다."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.core import global_ptt
from src.core.screen_frame import SCREEN_UNAVAILABLE_HINT, ScreenFrame
from tests.companion_helpers import sample_id
from tests.test_companion_admission import admission, mobile_message  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_edit_reroll import command
from tests.test_companion_pc_ui import run_case, run_pc_entry_case


def pc(bridge, number, *, voice=False, text="합성 격자의 칸을 셉니다.", attachments=None):
    payload = {**bridge._pc_chat_head(), "request_id": sample_id(number),
               "text": text, "attachments": attachments or []}
    if voice:
        payload["voice_token"] = payload["request_id"]
    return json.loads(bridge.submit_pc_chat(json.dumps(payload)))


@pytest.fixture
def handoff(admission):
    bridge, _, _, _ = admission
    captures, calls = [], []

    def capture():
        frame = ScreenFrame(bytes([len(captures) + 1]), lambda: True)
        captures.append(frame)
        return frame

    start = bridge._start_ai_worker

    def start_worker(message, *args, **kwargs):
        frame = kwargs.pop("screen_frame", None)
        calls.append((message, frame))
        start(message, *args, **kwargs)

    bridge._capture_question_frame = capture
    bridge._start_ai_worker = start_worker
    bridge._invalidate_automatic_reply = lambda: None
    return bridge, captures, calls


def test_typed_at_admission_voice_at_record_end_and_retry_once(handoff):
    bridge, captures, calls = handoff
    token = sample_id(72)
    bridge._begin_screen_voice(token)
    assert bridge._screen_ptt_busy
    bridge._freeze_screen_voice(token)
    assert bridge._screen_ptt_busy and len(captures) == 1
    assert pc(bridge, 71)["state"] == "accepted"
    assert calls[-1][1] is captures[1]
    bridge.worker.reply()
    assert pc(bridge, 72, voice=True)["state"] == "accepted"
    assert calls[-1][1] is captures[0]
    assert not bridge._screen_ptt_busy
    assert pc(bridge, 72, voice=True)["state"] == "accepted"
    assert len(captures) == len(calls) == 2
    assert bridge._last_request_payload["screen_used"] is True
    assert captures[0] not in bridge._last_request_payload.values()


def test_mobile_attachment_file_and_busy_voice_never_capture(handoff, admission):
    bridge, captures, calls = handoff
    _, _, context, _ = admission
    assert bridge.submit_mobile_text(context, mobile_message(bridge)).state == "accepted"
    bridge._begin_screen_voice(sample_id(73))
    bridge._freeze_screen_voice(sample_id(73))
    assert pc(bridge, 73, voice=True)["code"] == "busy"
    assert not bridge._screen_ptt_busy and captures[0].read() is None
    bridge.worker.reply()
    assert pc(bridge, 74, text="/note")["state"] == "rejected"
    assert bridge.send_to_ai_with_attachments("합성 도안", "[]").state == "accepted"
    assert len(captures) == 1 and all(frame is None for _, frame in calls)


def test_voice_ui_preserves_token_as_request_id():
    payload = run_case("""
chat.submit({text: '합성 격자 음성', voice: true, voiceToken: id(77)});
result = calls[0].payload;
""")
    assert payload["voice_token"] == payload["request_id"] == sample_id(77)


def test_hidden_overlay_submits_user_request_before_next_animation_frame():
    result = run_pc_entry_case("""
context.dispatchBridgeCall = () => {};
context.attachedAttachments = [];
vm.runInContext('sendMessage();', context);
context.result = calls.length;
""")
    assert result == 1


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_retry_gets_only_text_with_transient_explanation(handoff, kind):
    bridge, captures, calls = handoff
    notices = []
    bridge.summary_notice.connect(lambda message, _: notices.append(message))
    bridge.llm_client.rollback_last_assistant_turn = lambda: True
    assert pc(bridge, 75)["state"] == "accepted"
    bridge.worker.reply()
    if kind == "edit":
        result = bridge.edit_companion_message(command(bridge, "user", text="합성 모양을 수정합니다."))
    else:
        result = bridge.reroll_companion_message(command(bridge, "assistant"))
    assert json.loads(result)["state"] == "accepted"
    assert len(captures) == 1 and calls[-1][1] is None
    assert SCREEN_UNAVAILABLE_HINT in calls[-1][0] and notices
    assert SCREEN_UNAVAILABLE_HINT not in str(bridge._last_request_payload)


def test_invalid_frame_explained_without_keeping_it(handoff):
    bridge, _, calls = handoff
    bridge._capture_question_frame = lambda: ScreenFrame(None, lambda: True)
    notices = []
    bridge.summary_notice.connect(lambda message, _: notices.append(message))
    assert pc(bridge, 78)["state"] == "accepted"
    assert SCREEN_UNAVAILABLE_HINT in calls[0][0] and calls[0][1] is None and notices
    assert bridge._last_request_payload["screen_used"] is False


def test_reset_drops_stt_token_before_file_command(handoff):
    bridge, captures, _ = handoff
    bridge._begin_screen_voice(sample_id(79))
    bridge._freeze_screen_voice(sample_id(79))
    bridge._reset_companion_conversation()
    bridge._handle_note_command = lambda _: pytest.fail("초기화된 녹음으로 파일 명령을 실행했다")
    assert pc(bridge, 79, voice=True, text="/note 합성 바둑판")["code"] == "stale_session"
    assert captures[0].read() is None and not bridge._screen_ptt_busy


def test_conversation_clear_invalidates_previous_observation_and_voice(bridge):
    bridge._screen_share = SimpleNamespace(observe=True, generation=8, observe_epoch=3, validate=lambda: True)
    previous = bridge._ambient_context()
    bridge._observation_pending = previous
    bridge._observation_voice = previous
    bridge._ambient_busy = lambda: False
    bridge.interrupt_tts_for_ptt = Mock(wraps=bridge.interrupt_tts_for_ptt)
    bridge._play_tts = Mock()
    bridge.enable_tts = True
    bridge.tts_client = bridge.audio_player = object()
    displayed = []
    bridge.message_received.connect(lambda *args: displayed.append(args))
    bridge.clear_conversation()
    bridge._finish_screen_observation(previous, '{"reply":"합성 체크무늬","tts":"합성 체크무늬"}')
    assert not displayed and bridge._observation_voice is None
    bridge._play_tts.assert_not_called()
    bridge.interrupt_tts_for_ptt.assert_called_once_with()


def test_cleared_conversation_waits_for_new_input_before_away_greeting(bridge, monkeypatch):
    bridge.user_message_count = 4
    bridge.last_user_message_at = datetime.now() - timedelta(days=1)
    monkeypatch.setattr("src.core.bridge_mixins.away.get_system_idle_seconds", lambda: 99_999)
    displayed = []
    bridge.message_received.connect(lambda *args: displayed.append(args))
    bridge.clear_conversation()
    bridge._check_away_nudge_condition()
    assert not displayed and bridge.user_message_count == 0 and bridge.last_user_message_at is None
    bridge._mark_user_activity()
    assert bridge.user_message_count == 1 and bridge.last_user_message_at is not None


def test_life_gate_freezes_once_and_clears_frame_when_cancelled(handoff):
    bridge, captures, calls = handoff
    state = bridge.life_record_state

    def defer(prepared):
        state.try_begin_operation("auto_generating", pending_request=prepared)
        return True

    bridge._dispatch_general_request = defer
    assert pc(bridge, 80)["state"] == "reserved"
    assert state.pending_request.screen_frame is captures[0] and not calls
    bridge._finish_life_record_without_reply(state.operation_id)
    assert captures[0].read() is None


def test_declined_worker_releases_admitted_frame(handoff):
    bridge, captures, _ = handoff
    bridge._start_ai_worker = lambda *_, **__: False
    assert pc(bridge, 81)["state"] == "failed"
    assert captures[0].read() is None


@pytest.mark.parametrize("result", ["short", "blank", "failed", "success", "cancel"])
def test_ptt_freezes_only_after_valid_audio_and_releases_every_abandoned_token(bridge, monkeypatch, result):
    controller = global_ptt.GlobalPTTController()
    controller._enabled = True
    controller._recorder = SimpleNamespace(start=lambda: None, stop=lambda **_: SimpleNamespace(
        duration_sec=0.01 if result == "short" else 1, pcm_bytes=b"\0" * 5000))
    monkeypatch.setattr(global_ptt._STTWorker, "start", lambda self: None)
    events = []
    controller.recording_started.connect(lambda token: events.append(("start", token)))
    controller.recording_completed.connect(lambda token: events.append(("freeze", token)))
    controller.recording_discarded.connect(lambda token: events.append(("discard", token)))
    controller.transcription_ready.connect(lambda text, token: events.append(("text", token)))
    controller._start_recording()
    if result == "cancel":
        controller._safe_stop_recording()
    else:
        controller._stop_recording_and_transcribe()
    if result == "blank":
        controller._on_transcription_ready(" ")
    if result == "success":
        controller._on_transcription_ready("합성 격자 음성")
    if result == "failed":
        controller._on_transcription_failed("synthetic_error")
    expected = ["start"]
    if result not in {"short", "cancel"}:
        expected.append("freeze")
    expected.append("text" if result == "success" else "discard")
    assert [event for event, _ in events] == expected
    assert len({token for _, token in events}) == 1
