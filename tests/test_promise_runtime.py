from datetime import datetime

from src.core.promise_runtime import (
    build_promise_nudge_prompt,
    collect_promise_ids,
    promise_fire_signature,
    should_suppress_duplicate_promise_fire,
)


def test_promise_fire_signature_uses_title_and_minute_precision():
    assert (
        promise_fire_signature(
            {
                "title": "기업 조사",
                "trigger_at": "2026-04-08T20:00:33+09:00",
            }
        )
        == "기업 조사|2026-04-08T20:00"
    )
    assert promise_fire_signature({"title": "", "trigger_at": "2026-04-08T20:00:00+09:00"}) == ""


def test_should_suppress_duplicate_promise_fire_checks_queue_and_recent_history():
    payload = {"title": "기업 조사", "trigger_at": "2026-04-08T20:00:00+09:00"}

    assert should_suppress_duplicate_promise_fire(
        payload,
        active_signature="",
        queued_payloads=[payload],
        recent_signatures={},
        now_dt=datetime(2026, 4, 8, 20, 0, 0),
    ) is True
    assert should_suppress_duplicate_promise_fire(
        payload,
        active_signature="",
        queued_payloads=[],
        recent_signatures={"기업 조사|2026-04-08T20:00": datetime(2026, 4, 8, 19, 49, 0)},
        now_dt=datetime(2026, 4, 8, 20, 0, 0),
    ) is False


def test_collect_promise_ids_accepts_dicts_and_objects():
    class Reminder:
        id = "object-1"

    assert collect_promise_ids([{"id": "dict-1"}, Reminder(), {"id": ""}]) == ["dict-1", "object-1"]


def test_build_promise_nudge_prompt_localizes_korean_message():
    prompt = build_promise_nudge_prompt(
        language="ko",
        title="기업 조사",
        source_excerpt="8시에 기업 조사 시작",
    )

    assert "마스터와의 대화 약속 시간이 되었어" in prompt
    assert "약속 제목은 '기업 조사'" in prompt
    assert "원래 맥락은 '8시에 기업 조사 시작'" in prompt
