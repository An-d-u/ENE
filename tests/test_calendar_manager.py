from datetime import datetime, timedelta

from src.ai.calendar_manager import CalendarManager


def test_recent_or_latest_returns_recent_window_when_available(tmp_path):
    manager = CalendarManager(calendar_file=str(tmp_path / "calendar.json"))
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
    three_days_ago = (datetime.now().date() - timedelta(days=3)).isoformat()
    manager.conversation_counts = {
        "2026-03-01": 4,
        three_days_ago: 2,
        yesterday: 5,
    }

    result = manager.get_recent_or_latest_conversation_counts(days=7, exclude_today=True)

    assert result == {
        yesterday: 5,
        three_days_ago: 2,
    }


def test_recent_or_latest_falls_back_to_latest_history_when_recent_window_is_empty(tmp_path):
    manager = CalendarManager(calendar_file=str(tmp_path / "calendar.json"))
    manager.conversation_counts = {
        "2026-03-01": 4,
        "2026-02-27": 8,
        "2026-02-15": 1,
    }

    result = manager.get_recent_or_latest_conversation_counts(days=7, exclude_today=True)

    assert result == {"2026-03-01": 4}


def test_recent_or_latest_returns_empty_when_no_conversation_history_exists(tmp_path):
    manager = CalendarManager(calendar_file=str(tmp_path / "calendar.json"))
    manager.conversation_counts = {}

    result = manager.get_recent_or_latest_conversation_counts(days=7, exclude_today=True)

    assert result == {}
