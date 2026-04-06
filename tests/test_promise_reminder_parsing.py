import sys
import types


google_module = types.ModuleType("google")
genai_module = types.ModuleType("google.genai")
genai_module.Client = object
google_module.genai = genai_module
sys.modules.setdefault("google", google_module)
sys.modules.setdefault("google.genai", genai_module)

from src.ai.llm_client import GeminiClient


def test_parse_response_extracts_scheduled_promises():
    client = object.__new__(GeminiClient)

    clean_text, emotion, japanese_text, events, analysis, promises = client._parse_response(
        "[analysis]\nuser_intent=plan\n[/analysis]\n"
        "[약속:2026-04-06T21:10:00+09:00|쉬는 시간|user|10분만 쉬고 다시 할게]\n"
        "[smile] 곧 다시 하자."
    )

    assert clean_text == "곧 다시 하자."
    assert emotion == "smile"
    assert japanese_text is None
    assert events == []
    assert analysis["user_intent"] == "plan"
    assert promises == [
        {
            "trigger_at": "2026-04-06T21:10:00+09:00",
            "title": "쉬는 시간",
            "source": "user",
            "source_excerpt": "10분만 쉬고 다시 할게",
        }
    ]
