from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from src.core.bridge_mixins.away import AwayNudgeBridgeMixin


class AwayBridge(AwayNudgeBridgeMixin):
    def __init__(self):
        self.settings = None
        self.worker = None
        self._display_away_greeting = Mock()
        self._prompt_language = lambda: "ko"
        self.refresh_away_settings()
        self.user_message_count = 1
        self.away_check_in_progress = False
        self.away_trigger_count_since_last_user_msg = 0
        self.last_away_trigger_at = None
        self.last_user_message_at = datetime.now() - timedelta(hours=2)


@pytest.mark.parametrize("system_idle, expected", [(None, 0), (299, 0), (300, 1)])
def test_away_leaves_at_most_one_chat_message(monkeypatch, system_idle, expected):
    bridge = AwayBridge()
    monkeypatch.setattr("src.core.bridge_mixins.away.get_system_idle_seconds", lambda: system_idle)
    bridge._check_away_nudge_condition()
    bridge._check_away_nudge_condition()
    assert bridge._display_away_greeting.call_count == expected
    assert bridge.away_trigger_count_since_last_user_msg == expected
    assert bridge.worker is None


def test_away_waits_for_first_conversation_and_resets_on_activity(monkeypatch):
    bridge = AwayBridge()
    monkeypatch.setattr("src.core.bridge_mixins.away.get_system_idle_seconds", lambda: 9999)
    bridge.user_message_count = 0
    bridge._check_away_nudge_condition()
    bridge._mark_user_activity()
    bridge._check_away_nudge_condition()
    bridge._display_away_greeting.assert_not_called()
