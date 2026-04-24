from src.ai.http_llm_clients import _build_summary_prompt


def test_http_summary_prompt_uses_gemini_style_memory_rules():
    prompt = _build_summary_prompt("user: 테스트 대화")

    assert "[CURRENT_PROFILE]" in prompt
    assert "[TIME_RANGE]" in prompt
    assert "[ELAPSED_HINT]" in prompt
    assert "[ALLOW]" in prompt
    assert "[DISALLOW]" in prompt
    assert "[DEDUP]" in prompt
    assert "[STYLE]" in prompt
    assert "[CONVERSATION]\nuser: 테스트 대화" in prompt
    assert "타임스탬프를 우선 기준" in prompt
