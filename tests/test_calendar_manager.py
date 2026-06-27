import json
from datetime import datetime, timedelta

from src.ai.calendar_manager import CalendarManager


def test_load_reads_existing_utf8_bom_calendar_file(tmp_path):
    calendar_file = tmp_path / "calendar.json"
    payload = {
        "events": [],
        "conversation_counts": {"2026-06-23": 3},
        "head_pat_counts": {"2026-06-23": 2},
    }
    calendar_file.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8-sig"))

    manager = CalendarManager(calendar_file=str(calendar_file))

    assert manager.conversation_counts == {"2026-06-23": 3}
    assert manager.head_pat_counts == {"2026-06-23": 2}


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


def test_head_pat_pending_count_accumulates_separately_from_daily_total(tmp_path):
    manager = CalendarManager(calendar_file=str(tmp_path / "calendar.json"))
    today = datetime.now().strftime("%Y-%m-%d")

    manager.increment_head_pat_count(today)
    manager.increment_head_pat_count(today)

    assert manager.get_head_pat_count(today) == 2
    assert manager.get_pending_head_pat_count() == 2
    assert manager.drain_pending_head_pat_count() == 2
    assert manager.get_pending_head_pat_count() == 0
    assert manager.get_head_pat_count(today) == 2


def test_add_event_log_redacts_private_event_fields(tmp_path, capsys):
    manager = CalendarManager(calendar_file=str(tmp_path / "calendar.json"))
    capsys.readouterr()

    private_title = "SYNTHETIC_CALENDAR_TITLE_PRIVATE_1357"
    private_date = "2099-10-24"
    private_description = "SYNTHETIC_CALENDAR_DESCRIPTION_PRIVATE_9753"

    manager.add_event(
        date=private_date,
        title=private_title,
        description=private_description,
        source="user",
    )

    captured = capsys.readouterr().out

    assert private_title not in captured
    assert private_date not in captured
    assert private_description not in captured
    assert f"title_chars={len(private_title)}" in captured
    assert f"date_chars={len(private_date)}" in captured
    assert "has_description=True" in captured
