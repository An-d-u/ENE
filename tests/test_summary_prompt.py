from src.ai.markdown_document_prompt import build_markdown_document_prompt
from src.ai.summary_prompt import _format_now_for_language, build_summary_prompt_from_text
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
    assert "aliases: alternate name 1, alternate name 2" in prompt
    assert "trigger_terms: keyword1, keyword2" in prompt
    assert "entity_names are distinctive subjects, projects, tools, people, or places only" in prompt
    assert "aliases are short nicknames or noun phrases, not summaries" in prompt
    assert "trigger_terms are search cues, not subjects" in prompt
    assert "Do not use one-off dates, times, weekdays, or relative dates as trigger_terms" in prompt
    assert "Do not use durations, elapsed times, countdown periods, or numeric-only time cues as trigger_terms" in prompt


def test_summary_prompt_uses_custom_prompt_names_but_keeps_parser_tokens():
    prompt = build_summary_prompt_from_text(
        "user: Please remember this.",
        language="en",
        time_str="April 25, 2026 10:30",
        assistant_name="Luna",
        user_name="Captain",
    ).prompt

    assert "extract Captain information and Luna information" in prompt
    assert "goals the user or Luna wants to achieve" in prompt
    assert "[MASTER_INFO]" in prompt
    assert "[ENE_INFO]" in prompt
    assert "Master" not in prompt


def test_summary_prompt_formats_non_english_time_without_locale_sensitive_strftime():
    class LocaleSensitiveNow:
        year = 2026
        month = 5
        day = 12
        hour = 9
        minute = 7

        def strftime(self, format_text: str) -> str:
            for index, char in enumerate(format_text):
                if ord(char) > 127:
                    raise UnicodeEncodeError("locale", format_text, index, index + 1, "encoding error")
            return "May 12, 2026 09:07"

    _, ko_time = _format_now_for_language("ko", LocaleSensitiveNow())
    _, ja_time = _format_now_for_language("ja", LocaleSensitiveNow())
    _, en_time = _format_now_for_language("en", LocaleSensitiveNow())

    assert ko_time == "2026년 05월 12일 09시 07분"
    assert ja_time == "2026年05月12日 09時07分"
    assert en_time == "May 12, 2026 09:07"


def test_markdown_document_prompt_uses_selected_language():
    prompt = build_markdown_document_prompt("日記を書いて", language="ja")

    assert "次の依頼に合わせてMarkdown文書を書いてください。" in prompt
    assert "感情タグ" in prompt
    assert "TTSブロック" in prompt
    assert "日本語訳" not in prompt
    assert "日記を書いて" in prompt


def test_markdown_document_prompt_blocks_tts_metadata_not_translation_labels():
    ko_prompt = build_markdown_document_prompt("회의록을 정리해줘", language="ko")
    en_prompt = build_markdown_document_prompt("Write meeting notes", language="en")

    assert "TTS 블록" in ko_prompt
    assert "일본어 번역" not in ko_prompt
    assert "TTS block" in en_prompt
    assert "Japanese translation" not in en_prompt
