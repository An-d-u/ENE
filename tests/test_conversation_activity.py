from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from src.ai.memory import MemoryManager
from src.ai.memory_types import MemoryEntry
from src.core.conversation_activity import conversation_activity


LOCAL = timezone(timedelta(hours=9))
NOW = datetime(2024, 2, 2, 12, tzinfo=LOCAL)


def saved(rows, identifier="sample"):
    return MemoryEntry.from_dict({
        "id": identifier,
        "timestamp": "2024-02-02T12:00:00+09:00",
        "conversation_id": identifier,
        "original_messages": [
            {"role": role, "text": text, "timestamp": stamp,
             "conversation_id": identifier, "turn_index": index}
            for index, (role, text, stamp) in enumerate(rows)
        ],
    })


def test_stored_and_current_turns_share_one_local_calendar():
    memory = saved([
        ("user", "가나", "2024-01-30T15:02:00Z"),
        ("assistant", "다", "2024-01-30T15:03:00Z"),
        ("user", "라", "2024-02-01 00:11"),
        ("assistant", "마바", "2024-02-01 00:14"),
    ])
    bridge = SimpleNamespace(conversation_buffer=[
        ("assistant", "먼저 한 인사", "2024-02-02 09:00"),
        ("user", "이전 요청", "2024-02-02 09:01"),
        ("user", "사", "2024-02-02 09:02"),
        ("assistant", "아", "2024-02-02 09:02"),
        ("user", "답변 대기", "2024-02-02 09:03"),
    ])
    manager = SimpleNamespace(memories=[memory, memory])
    stats = conversation_activity(bridge, manager, now=NOW)

    assert stats.daily_turns == {date(2024, 1, 31): 1, date(2024, 2, 1): 1, date(2024, 2, 2): 1}
    assert stats.as_of == NOW.date()
    assert stats.total_turns == sum(stats.hourly_turns) == 3
    assert stats.hourly_turns[0] == 2 and stats.hourly_turns[9] == 1
    assert stats.characters == 8
    assert stats.first_day == stats.streak_start == date(2024, 1, 31)
    assert stats.streak_end == date(2024, 2, 2) and stats.streak_days == 3
    assert stats.longest.started_at == datetime(2024, 1, 31, 0, 2, tzinfo=LOCAL)
    assert stats.longest.minutes == 24 * 60 + 12 and stats.longest.turns == 2


def test_summary_retry_deletion_and_reopening_use_retained_records(tmp_path):
    reviewed = [("user", "색", "2024-02-01 08:00"), ("assistant", "청", "2024-02-01 08:01")]
    memory = saved(reviewed)
    path = tmp_path / "sample.json"
    manager = MemoryManager(path)
    manager.memories.append(memory)
    assert manager.save()
    manager = MemoryManager(path)
    bridge = SimpleNamespace(
        conversation_buffer=reviewed + [("user", "원", "2024-02-02 10:00"), ("assistant", "구", "2024-02-02 10:01")],
        _pending_summary_review={"messages": reviewed, "saved_memory": memory},
    )
    assert conversation_activity(bridge, manager, now=NOW).total_turns == 2
    assert conversation_activity(None, manager, now=NOW).total_turns == 1
    manager.delete(memory.id)
    assert conversation_activity(bridge, manager, now=NOW).total_turns == 2
    assert conversation_activity(None, MemoryManager(path), now=NOW).first_day is None


def test_explicit_message_time_can_match_memory_save_time():
    stamp = NOW.isoformat()
    memory = saved([
        ("user", "첫째", "2024-02-02T11:59:00+09:00"),
        ("assistant", "둘째", stamp),
        ("user", "셋째", stamp),
        ("assistant", "넷째", stamp),
    ])
    assert memory.timestamp == memory.original_messages[-1].timestamp
    stats = conversation_activity(None, SimpleNamespace(memories=[memory]), now=NOW)
    assert stats.total_turns == 2 and stats.characters == 8
    assert stats.hourly_turns[11] == stats.hourly_turns[12] == 1
    assert stats.longest.minutes == 1


def test_inferred_legacy_fields_invalid_dates_and_incomplete_pairs_are_excluded():
    legacy = MemoryEntry.from_dict({
        "id": "legacy-sample", "timestamp": "2024-01-01 09:10", "original_messages": ["도형", "원입니다."],
    })
    memory = saved([
        ("user", "물음", "2024-01-31"), ("assistant", "답", "2024-01-31 09:02"),
        ("user", "물음", "자료 없음"), ("assistant", "답", "2024-01-31 09:04"),
        ("user", "물음", "2024-01-31 09:06"), ("assistant", "답", "2024-01-31 09:05"),
        ("user", "물음", "2024-02-03 09:00"), ("assistant", "답", "2024-02-03 09:01"),
    ])
    old_panel_entry = SimpleNamespace(id="plain", original_messages=["종이", "연필"])
    stats = conversation_activity(None, SimpleNamespace(memories=[legacy, memory, old_panel_entry]), now=NOW)
    assert stats.daily_turns == {} and stats.hourly_turns == (0,) * 24
    assert stats.total_turns == stats.characters == stats.streak_days == 0
    assert stats.longest is stats.first_day is stats.streak_start is stats.streak_end is None


def test_midnight_turn_and_dst_overlap_use_question_day_and_elapsed_time():
    from zoneinfo import ZoneInfo

    view = ZoneInfo("America/New_York")
    bridge = SimpleNamespace(conversation_buffer=[
        ("user", "문", "2024-11-02T23:58:00-04:00"),
        ("assistant", "답", "2024-11-03T00:01:00-04:00"),
        ("user", "문", "2024-11-03T01:45:00-04:00"),
        ("assistant", "답", "2024-11-03T01:15:00-05:00"),
    ])
    stats = conversation_activity(bridge, now=datetime(2024, 11, 4, tzinfo=view))
    assert stats.daily_turns == {date(2024, 11, 2): 1, date(2024, 11, 3): 1}
    assert stats.hourly_turns[23] == stats.hourly_turns[1] == 1
    assert stats.longest.minutes == 137
