from src.ai.summary_prompt import build_markdown_document_prompt, build_summary_prompt_from_text
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


def test_summary_prompt_localizes_human_instructions_but_keeps_parser_tokens():
    prompt = build_summary_prompt_from_text(
        "user: Please remember this.",
        language="en",
        time_str="April 25, 2026 10:30",
    ).prompt

    assert "Summarize the conversation below" in prompt
    assert "Use the timestamps in [CONVERSATION]" in prompt
    assert "[SUMMARY]" in prompt
    assert "[MASTER_INFO]" in prompt
    assert "[ENE_INFO]" in prompt
    assert "[MEMORY_META]" in prompt
    assert "memory_type: fact | preference | promise | event | relationship | task | general" in prompt


def test_markdown_document_prompt_uses_selected_language():
    prompt = build_markdown_document_prompt("日記を書いて", language="ja")

    assert "次の依頼に合わせてMarkdown文書を書いてください。" in prompt
    assert "感情タグ" in prompt
    assert "日記を書いて" in prompt
