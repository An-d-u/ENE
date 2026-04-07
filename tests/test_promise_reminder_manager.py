from src.ai.promise_reminder_manager import PromiseReminderManager, extract_promise_candidates


def test_add_promise_persists_and_returns_sorted_items(tmp_path):
    manager = PromiseReminderManager(tmp_path / "promises.json")

    created = manager.add_promise(
        title="쉬는 시간",
        trigger_at="2026-04-06T21:10:00+09:00",
        source="user",
        source_excerpt="10분만 쉬고 다시 할게",
    )

    items = manager.list_promises()

    assert len(items) == 1
    assert items[0].id == created.id
    assert items[0].title == "쉬는 시간"
    assert items[0].status == "scheduled"


def test_mark_overdue_promises_uses_10_and_60_minute_policy(tmp_path):
    manager = PromiseReminderManager(tmp_path / "promises.json")

    manager.add_promise(
        title="곧 다시 하기",
        trigger_at="2026-04-06T21:05:00+09:00",
        source="user",
        source_excerpt="5분 뒤에 다시 하자",
    )
    manager.add_promise(
        title="쉬는 시간",
        trigger_at="2026-04-06T20:40:00+09:00",
        source="user",
        source_excerpt="30분만 쉬겠다",
    )
    manager.add_promise(
        title="오래 지난 약속",
        trigger_at="2026-04-06T19:40:00+09:00",
        source="assistant",
        source_excerpt="한 시간 넘게 지남",
    )

    due_items, missed_items, expired_items = manager.refresh_overdue_statuses(
        "2026-04-06T21:10:00+09:00"
    )

    assert [item.title for item in due_items] == ["곧 다시 하기"]
    assert [item.title for item in missed_items] == ["쉬는 시간"]
    assert [item.title for item in expired_items] == ["오래 지난 약속"]
    assert missed_items[0].status == "missed"
    assert expired_items[0].status == "expired"


def test_list_promise_dicts_can_filter_visible_statuses(tmp_path):
    manager = PromiseReminderManager(tmp_path / "promises.json")

    scheduled = manager.add_promise(
        title="쉬는 시간",
        trigger_at="2026-04-06T21:10:00+09:00",
        source="user",
        source_excerpt="10분만 쉬고 다시 할게",
    )
    hidden = manager.add_promise(
        title="이미 보낸 약속",
        trigger_at="2026-04-06T20:10:00+09:00",
        source="assistant",
        source_excerpt="이미 발화가 끝남",
    )
    manager.set_status(hidden.id, "triggered")

    visible_items = manager.list_promise_dicts(include_statuses=("scheduled", "queued", "missed"))

    assert [item["id"] for item in visible_items] == [scheduled.id]


def test_extract_promise_candidates_parses_relative_diary_expression():
    items = extract_promise_candidates("3분 뒤 일기 써야지", now="2026-04-06 21:00", source="user")

    assert items == [
        {
            "title": "대화 약속",
            "trigger_at": "2026-04-06T21:03:00+09:00",
            "source": "user",
            "source_excerpt": "3분 뒤 일기 써야지",
        }
    ]


def test_extract_promise_candidates_parses_assistant_head_pat_suggestion():
    items = extract_promise_candidates(
        "음, 그럼 10분 뒤에 다시 한 번 쓰다듬어 주는 건 어때요?",
        now="2026-04-07 10:00",
        source="assistant",
    )

    assert items == [
        {
            "title": "대화 약속",
            "trigger_at": "2026-04-07T10:10:00+09:00",
            "source": "assistant",
            "source_excerpt": "음, 그럼 10분 뒤에 다시 한 번 쓰다듬어 주는 건 어때요",
        }
    ]


def test_extract_promise_candidates_assigns_clean_bedtime_title():
    items = extract_promise_candidates(
        "그럼 제가 정할 테니까, 10분 뒤에 침대에 눕는 거예요.",
        now="2026-04-07 10:00",
        source="assistant",
    )

    assert items == [
        {
            "title": "대화 약속",
            "trigger_at": "2026-04-07T10:10:00+09:00",
            "source": "assistant",
            "source_excerpt": "그럼 제가 정할 테니까, 10분 뒤에 침대에 눕는 거예요",
        }
    ]


def test_extract_promise_candidates_prefers_future_interpretation_for_ambiguous_clock_time():
    items = extract_promise_candidates(
        "응.. 9시 20분에 딱 하자...",
        now="2026-04-07 21:15",
        source="user",
    )

    assert items == [
        {
            "title": "대화 약속",
            "trigger_at": "2026-04-07T21:20:00+09:00",
            "source": "user",
            "source_excerpt": "응.. 9시 20분에 딱 하자",
        }
    ]


def test_find_similar_promise_matches_nearby_same_excerpt(tmp_path):
    manager = PromiseReminderManager(tmp_path / "promises.json")
    manager.add_promise(
        title="일기 쓰기",
        trigger_at="2026-04-06T21:03:00+09:00",
        source="user",
        source_excerpt="3분 뒤 일기 써야지",
    )

    matched = manager.find_similar_promise(
        title="일기",
        trigger_at="2026-04-06T21:04:00+09:00",
        source_excerpt="3분 뒤 일기 써야지",
        include_statuses=("scheduled",),
    )

    assert matched is not None
    assert matched.title == "일기 쓰기"
