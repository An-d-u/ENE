from types import SimpleNamespace
from unittest.mock import Mock
from PyQt6.QtGui import QImage, QColor
from tests.test_companion_bridge_transcript import bridge  # noqa: F401


def scene(color):
    image = QImage(96, 64, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    return image


def test_static_silence_changes_and_budget():
    from src.core.screen_observation import ObservationSchedule
    schedule = ObservationSchedule()
    first, second = scene("navy"), scene("white")
    assert not schedule.candidate(first, 0)
    assert not schedule.candidate(first, 29)
    assert schedule.candidate(second, 30)
    schedule.mark_requested(30)
    assert not schedule.candidate(first, 45)
    assert not schedule.candidate(first, 90)
    assert schedule.candidate(first, 330)


def test_only_explicit_spoken_reply_is_displayable():
    from src.core.screen_observation import parse_observation
    assert parse_observation('{"reply":"", "tts":""}') == ("", "")
    assert parse_observation('broken') == ("", "")
    assert parse_observation('{"reply":"\\ud800","tts":""}') == ("", "")
    assert parse_observation("[" * 1300 + "]" * 1300) == ("", "")
    assert parse_observation('{"reply":"A","tts":false}') == ("", "")
    assert parse_observation('{"reply":"A"}') == ("", "")
    assert parse_observation('{"reply":"A", "tts":"B"}') == ("A", "B")


def test_late_observation_has_no_delivery_after_input_or_toggle():
    from src.core.bridge_mixins.screen_observation import ObservationBridgeMixin

    class Bridge(ObservationBridgeMixin):
        def _ambient_busy(self):
            return False
    bridge = Bridge()
    share = SimpleNamespace(observe=True, observe_epoch=3, generation=7, validate=lambda: True)
    bridge._screen_share = share
    bridge._ambient_input_epoch = 2
    bridge.message_received = Mock()
    context = (7, 3, 2)
    bridge._observation_pending = context
    bridge._invalidate_automatic_reply()
    bridge._finish_screen_observation(context, '{"reply":"A","tts":"B"}')
    bridge.message_received.emit.assert_not_called()
    bridge._observation_pending = (7, 3, 3)
    share.observe_epoch += 2
    bridge._finish_screen_observation((7, 3, 3), '{"reply":"A","tts":"B"}')
    bridge.message_received.emit.assert_not_called()


def test_due_reservation_and_ptt_have_priority_over_both_automatic_features():
    from src.core.bridge_mixins.screen_observation import ObservationBridgeMixin

    class Bridge(ObservationBridgeMixin):
        def _life_operation_accepts_input(self):
            return True
        def _is_proactive_conversation_enabled(self):
            return True

    bridge = Bridge()
    bridge.pending_response = bridge.tts_worker = bridge.worker = bridge.audio_player = None
    bridge.proactive_run_queue = []
    bridge.proactive_manager = SimpleNamespace(has_due=lambda: True)
    bridge._start_screen_observation = Mock(return_value=False)
    bridge._check_away_nudge_condition = Mock()
    bridge.away_trigger_count_since_last_user_msg = 0
    bridge._poll_ambient_conversations()
    bridge.proactive_manager = None
    bridge._screen_ptt_busy = True
    bridge._poll_ambient_conversations()
    bridge._start_screen_observation.assert_not_called()
    bridge._check_away_nudge_condition.assert_not_called()


def test_completed_observation_tts_worker_cannot_play_in_new_conversation():
    from src.core.bridge_mixins.tts import TTSBridgeMixin
    old = SimpleNamespace(screen_observation_context=(3, 2, 1))
    bridge = SimpleNamespace(_observation_voice=None, _active_tts_operation=(None, old))
    assert not TTSBridgeMixin._matches_tts_operation(bridge, None, old)
    bridge._observation_voice = (3, 2, 1)
    assert TTSBridgeMixin._matches_tts_operation(bridge, None, old)


def test_revoked_observer_does_not_hold_independent_away_greeting():
    from src.core.bridge_mixins.screen_observation import ObservationBridgeMixin

    class Bridge(ObservationBridgeMixin):
        def _ambient_busy(self):
            return False

    bridge = Bridge()
    bridge._observation_pending = (1, 1, 0)
    bridge._screen_share = None
    bridge._check_away_nudge_condition = Mock()
    bridge.away_trigger_count_since_last_user_msg = 0
    bridge._poll_ambient_conversations()
    bridge._check_away_nudge_condition.assert_called_once()


def test_capture_to_background_judgment_to_single_visible_message(bridge):
    import json
    from PyQt6.QtTest import QSignalSpy

    images = iter([scene("navy"), scene("white")])
    bridge._screen_share = SimpleNamespace(observe=True, observe_epoch=1, generation=1,
        snapshot=lambda: next(images), can_send=lambda value: value == 1, validate=lambda: True)
    sent = []
    def observe(prompt, frame):
        sent.append(frame.read())
        return '{"reply":"합성 격자가 바뀌었습니다.","tts":""}'
    bridge.llm_client = SimpleNamespace(observe_screen_once=observe)
    changed = QSignalSpy(bridge.chat_display_event)
    assert not bridge._start_screen_observation(0)
    assert bridge._start_screen_observation(30)
    assert len(changed) or changed.wait(2000)
    messages = json.loads(bridge.get_companion_chat_state())["messages"]
    assert len(messages) == len(sent) == 1
    assert sent[0].startswith(bytes.fromhex("ffd8"))
    assert messages[0]["text"] == "합성 격자가 바뀌었습니다."
    assert not messages[0].get("attachments")
    assert bridge._ambient_quiet_until > 0
