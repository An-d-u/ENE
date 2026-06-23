from datetime import datetime

from src.core.proactive_conversation_runtime import (
    build_proactive_conversation_prompt,
    proactive_fire_signature,
    should_suppress_duplicate_proactive_fire,
)


def test_proactive_fire_signature_uses_cooldown_key_title_and_minute_precision():
    assert (
        proactive_fire_signature(
            {
                "cooldown_key": "short-followup",
                "title": "가벼운 확인",
                "trigger_at": "2026-05-26T21:20:33+09:00",
            }
        )
        == "short-followup|가벼운 확인|2026-05-26T21:20"
    )
    assert proactive_fire_signature({"cooldown_key": "", "title": "확인", "trigger_at": "2026-05-26T21:20:00+09:00"}) == ""


def test_should_suppress_duplicate_proactive_fire_checks_queue_and_recent_history():
    payload = {
        "cooldown_key": "short-followup",
        "title": "가벼운 확인",
        "trigger_at": "2026-05-26T21:20:00+09:00",
    }

    assert should_suppress_duplicate_proactive_fire(
        payload,
        active_signature="",
        queued_payloads=[payload],
        recent_signatures={},
        now_dt=datetime(2026, 5, 26, 21, 20, 0),
    ) is True
    assert should_suppress_duplicate_proactive_fire(
        payload,
        active_signature="",
        queued_payloads=[],
        recent_signatures={"short-followup|가벼운 확인|2026-05-26T21:20": datetime(2026, 5, 26, 21, 16, 0)},
        now_dt=datetime(2026, 5, 26, 21, 20, 0),
    ) is True
    assert should_suppress_duplicate_proactive_fire(
        payload,
        active_signature="",
        queued_payloads=[],
        recent_signatures={"short-followup|가벼운 확인|2026-05-26T21:20": datetime(2026, 5, 26, 21, 0, 0)},
        now_dt=datetime(2026, 5, 26, 21, 20, 0),
    ) is False


def test_build_proactive_conversation_prompt_localizes_korean_message():
    prompt = build_proactive_conversation_prompt(
        language="ko",
        title="가벼운 확인",
        generation_prompt="합성 대화 흐름을 짧게 다시 이어가세요.",
        reason="대화가 잠시 조용해진 합성 상황",
        user_name="선장",
    )

    assert "선장에게 먼저 말을 걸 타이밍" in prompt
    assert "가벼운 확인" in prompt
    assert "합성 대화 흐름을 짧게 다시 이어가세요." in prompt
    assert "한두 문장" in prompt
    assert "새 선제 대화 예약" in prompt
