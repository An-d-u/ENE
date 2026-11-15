import json
from datetime import datetime, timedelta
from unittest.mock import Mock

from src.core.bridge_mixins.away import AwayNudgeBridgeMixin
from tests.test_companion_bridge_transcript import bridge  # noqa: F401


def test_away_repeats_only_after_configured_interval_and_without_capture(monkeypatch):
    class Bridge(AwayNudgeBridgeMixin):
        def _prompt_language(self):
            return "ko"

    bridge = Bridge()
    bridge.settings = None
    bridge.worker = None
    bridge._display_away_greeting = Mock()
    bridge.refresh_away_settings()
    bridge.away_additional_retry_limit = 1
    bridge.user_message_count = 1
    bridge.away_trigger_count_since_last_user_msg = 0
    bridge.away_check_in_progress = False
    bridge.last_user_message_at = datetime.now() - timedelta(hours=2)
    bridge.last_away_trigger_at = None
    monkeypatch.setattr("src.core.bridge_mixins.away.get_system_idle_seconds", lambda: 600)
    bridge._start_away_capture_pipeline = Mock(side_effect=AssertionError("화면 접근"))
    bridge._check_away_nudge_condition()
    bridge._check_away_nudge_condition()
    assert bridge._display_away_greeting.call_count == 1
    bridge.last_away_trigger_at -= timedelta(hours=2)
    bridge._check_away_nudge_condition()
    assert bridge._display_away_greeting.call_count == 2
    bridge.last_away_trigger_at -= timedelta(hours=2)
    bridge._check_away_nudge_condition()
    assert bridge._display_away_greeting.call_count == 2
    bridge._start_away_capture_pipeline.assert_not_called()


def test_away_greeting_survives_pc_transcript_refresh(bridge, monkeypatch):
    bridge.last_user_message_at = datetime.now() - timedelta(hours=2)
    bridge.user_message_count = 1
    monkeypatch.setattr("src.core.bridge_mixins.away.get_system_idle_seconds", lambda: 900)
    bridge._check_away_nudge_condition()
    saved = json.loads(bridge.get_companion_chat_state())["messages"]
    assert len(saved) == 1 and saved[0]["role"] == "assistant"
    assert saved[0]["local_only"] and saved[0]["attachments"] == []
    assert bridge._last_request_payload is None
