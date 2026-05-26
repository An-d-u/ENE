from src.ai.response_parser import parse_llm_response
from src.core.bridge_workers import AIWorker


def test_parse_response_extracts_proactive_conversation_block():
    parsed = parse_llm_response(
        """좋아요. [smile]
[proactive_conversation]
trigger_at=2026-05-26T21:20:00+09:00
title=가벼운 확인
generation_prompt=사용자가 잠시 확인할 일이 있다고 했고 아직 답장이 없다. 부담스럽지 않게 끝났는지 짧게 물어봐.
source_excerpt=잠시 확인하고 돌아온다는 흐름
reason=대화가 잠시 끊겼고 짧은 확인 발화가 자연스러움
cooldown_key=short-followup
[/proactive_conversation]""",
        available_emotions={"smile"},
    )

    text, emotion, _tts, _events, _analysis, _promises, _thought, _goal, proactive = parsed

    assert text == "좋아요."
    assert emotion == "smile"
    assert proactive == [
        {
            "trigger_at": "2026-05-26T21:20:00+09:00",
            "title": "가벼운 확인",
            "generation_prompt": "사용자가 잠시 확인할 일이 있다고 했고 아직 답장이 없다. 부담스럽지 않게 끝났는지 짧게 물어봐.",
            "source_excerpt": "잠시 확인하고 돌아온다는 흐름",
            "reason": "대화가 잠시 끊겼고 짧은 확인 발화가 자연스러움",
            "cooldown_key": "short-followup",
        }
    ]


def test_parse_response_ignores_incomplete_proactive_conversation_block():
    parsed = parse_llm_response(
        """응답입니다.
[proactive_conversation]
trigger_at=2026-05-26T21:20:00+09:00
title=불완전
[/proactive_conversation]"""
    )

    text, _emotion, _tts, _events, _analysis, _promises, _thought, _goal, proactive = parsed

    assert text == "응답입니다."
    assert proactive == []


def test_ai_worker_normalize_response_payload_adds_empty_proactive_list_for_legacy_payload():
    worker = AIWorker.__new__(AIWorker)

    normalized = AIWorker._normalize_response_payload(
        worker,
        (
            "본문",
            "smile",
            "",
            [],
            {"user_intent": "synthetic"},
            [{"title": "대화 약속"}],
            "속마음",
            {"action": "none"},
        ),
    )

    assert normalized == (
        "본문",
        "smile",
        "",
        [],
        {"user_intent": "synthetic"},
        [{"title": "대화 약속"}],
        "속마음",
        {"action": "none"},
        [],
    )


def test_ai_worker_normalize_response_payload_preserves_proactive_list():
    worker = AIWorker.__new__(AIWorker)
    proactive = [{"title": "가벼운 확인"}]

    normalized = AIWorker._normalize_response_payload(
        worker,
        (
            "본문",
            "smile",
            "",
            [],
            {},
            [],
            "",
            {},
            proactive,
        ),
    )

    assert normalized[-1] is proactive
