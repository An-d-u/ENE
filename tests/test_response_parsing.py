import pytest

pytest.importorskip("google.genai")

from src.ai import response_cleanup
from src.ai.llm_client import GeminiClient
from src.ai.response_parser import parse_llm_response


def test_parse_response_keeps_multiline_japanese_for_tts():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
한국어 본문입니다. [smile]
一行目です。
二行目です。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "한국어 본문입니다."
    assert emotion == "smile"
    assert tts_text == "一行目です。\n二行目です。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


def test_parse_response_extracts_analysis_block_without_leaking_to_text():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[analysis]
user_emotion=affectionate
user_intent=affection
confidence=0.86
[/analysis]
네, 알겠어요. [smile]
はい、わかりました。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "네, 알겠어요."
    assert emotion == "smile"
    assert tts_text == "はい、わかりました。"
    assert events == []
    assert analysis == {
        "user_emotion": "affectionate",
        "user_intent": "affection",
        "confidence": "0.86",
    }
    assert promises == []
    assert thought == ""


def test_parse_response_extracts_spaced_mixed_case_analysis_block_without_leak():
    analysis_body = "synthetic_intent"
    parsed = parse_llm_response(
        "[ AnAlYsIs ]\n"
        f"user_intent={analysis_body}\n"
        "[ / analysis ]\n"
        "VISIBLE [normal]",
        settings_source={"ui_language": "ko", "tts_language": "ko"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "VISIBLE"
    assert parsed[2] == "VISIBLE"
    assert parsed[4] == {"user_intent": analysis_body}
    assert analysis_body not in parsed[0]
    assert analysis_body not in parsed[2]


def test_parse_response_extracts_thought_block_without_leaking_to_text_or_tts():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[analysis]
user_emotion=calm
user_intent=greeting
confidence=0.8
[/analysis]
[thought]
마스터가 조금 지쳐 보인다. 부담 주지 말고 짧게 받아주자.
[/thought]
괜찮아요. 천천히 해도 돼요. [smile]
大丈夫です。ゆっくりでいいですよ。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "괜찮아요. 천천히 해도 돼요."
    assert emotion == "smile"
    assert tts_text == "大丈夫です。ゆっくりでいいですよ。"
    assert events == []
    assert analysis["user_intent"] == "greeting"
    assert promises == []
    assert thought == "마스터가 조금 지쳐 보인다. 부담 주지 말고 짧게 받아주자."


def test_parse_response_extracts_ene_thought_block_without_leaking_to_text_or_tts():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[analysis]
user_emotion=calm
user_intent=greeting
confidence=0.8
[/analysis]
[ene_thought]
마스터가 조금 지쳐 보인다. 부담 주지 말고 짧게 받아주자.
[/ene_thought]
괜찮아요. 천천히 해도 돼요. [smile]
大丈夫です。ゆっくりでいいですよ。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "괜찮아요. 천천히 해도 돼요."
    assert emotion == "smile"
    assert tts_text == "大丈夫です。ゆっくりでいいですよ。"
    assert events == []
    assert analysis["user_intent"] == "greeting"
    assert promises == []
    assert thought == "마스터가 조금 지쳐 보인다. 부담 주지 말고 짧게 받아주자."


def test_parse_response_extracts_subconscious_block_without_leaking_to_text_or_tts():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[analysis]
user_emotion=calm
user_intent=greeting
confidence=0.8
[/analysis]
[subconscious]
마스터가 조금 지쳐 보인다. 부담 주지 말고 짧게 받아주자.
[/subconscious]
괜찮아요. 천천히 해도 돼요. [smile]
大丈夫です。ゆっくりでいいですよ。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "괜찮아요. 천천히 해도 돼요."
    assert emotion == "smile"
    assert tts_text == "大丈夫です。ゆっくりでいいですよ。"
    assert events == []
    assert analysis["user_intent"] == "greeting"
    assert promises == []
    assert thought == "마스터가 조금 지쳐 보인다. 부담 주지 말고 짧게 받아주자."


def test_parse_response_extracts_korean_thought_block_alias():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[생각]
마스터가 서운해하지 않게 짧게 달래자.
[/생각]
알겠어요. 제가 다시 확인해볼게요. [smile]
わかりました。もう一度確認してみます。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "알겠어요. 제가 다시 확인해볼게요."
    assert emotion == "smile"
    assert tts_text == "わかりました。もう一度確認してみます。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == "마스터가 서운해하지 않게 짧게 달래자."


def test_parse_response_extracts_leading_thought_metadata_line():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
생각: 마스터가 답답해하는 것 같다. 먼저 안심시켜야겠다.

네, 그 부분부터 다시 잡아볼게요. [smile]
はい、そこからもう一度見直します。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "네, 그 부분부터 다시 잡아볼게요."
    assert emotion == "smile"
    assert tts_text == "はい、そこからもう一度見直します。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == "마스터가 답답해하는 것 같다. 먼저 안심시켜야겠다."


def test_parse_response_does_not_promote_thought_only_block_to_reply():
    parsed = parse_llm_response(
        "[thought]\n가상 내면 반응\n[/thought]",
        settings_source={"ui_language": "ko", "tts_language": "ko"},
    )

    assert parsed[0] == ""
    assert parsed[2] == ""
    assert parsed[6] == "가상 내면 반응"


@pytest.mark.parametrize(
    "start_tag",
    [
        "[analysis]",
        "[subconscious]",
        "[thought]",
        "[ene_thought]",
        "[inner_thought]",
        "[생각]",
        "[속마음]",
        "[에네생각]",
        "[ 에네   생각 ]",
        "[ TtS ]",
        "[ ene_goal_update ]",
        "[ ProActive_Conversation ]",
    ],
)
def test_parse_response_strips_unclosed_reserved_control_blocks(start_tag):
    leak = "노출되면 안 되는 가상 메타"
    parsed = parse_llm_response(
        f"표시 가능한 가상 답변 [normal]\n{start_tag}\n{leak}",
        settings_source={"ui_language": "ko", "tts_language": "ko"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "표시 가능한 가상 답변"
    assert parsed[2] == "표시 가능한 가상 답변"
    assert leak not in repr(parsed)


def test_parse_response_keeps_closed_thought_before_unclosed_same_type():
    leak = "노출 금지 가상 생각"
    parsed = parse_llm_response(
        "[thought]\n유효한 가상 생각\n[/thought]\n"
        "표시 가능한 가상 답변 [normal]\n"
        f"[thought]\n{leak}",
        settings_source={"ui_language": "ko", "tts_language": "ko"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "표시 가능한 가상 답변"
    assert parsed[6] == "유효한 가상 생각"
    assert leak not in repr(parsed)


def test_parse_response_strips_nested_unclosed_reserved_control_block():
    leak = "노출 금지 바깥 가상 생각"
    parsed = parse_llm_response(
        "표시 가능한 가상 답변 [normal]\n"
        f"[thought]\n{leak}\n"
        "[thought]\n안쪽 가상 생각\n[/thought]",
        settings_source={"ui_language": "ko", "tts_language": "ko"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "표시 가능한 가상 답변"
    assert leak not in repr(parsed)


def test_parse_response_strips_from_first_unclosed_control_block_in_combination():
    first_leak = "노출 금지 가상 분석"
    second_leak = "노출 금지 가상 TTS"
    parsed = parse_llm_response(
        "표시 가능한 가상 답변 [normal]\n"
        f"[analysis]\n{first_leak}\n[tts]\n{second_leak}",
        settings_source={"ui_language": "ko", "tts_language": "ko"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "표시 가능한 가상 답변"
    assert parsed[2] == "표시 가능한 가상 답변"
    assert first_leak not in repr(parsed)
    assert second_leak not in repr(parsed)


def test_parse_response_discards_interleaved_malformed_reserved_blocks():
    response_text = """VISIBLE [normal]
[tts]
LEAK_A
[ene_goal_update]
LEAK_B
[/tts]
[analysis]
LEAK_C
[/ene_goal_update]
[proactive_conversation]
LEAK_D
[/analysis]"""

    parsed = parse_llm_response(
        response_text,
        settings_source={"ui_language": "ko", "tts_language": "ko"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "VISIBLE"
    assert parsed[2] == "VISIBLE"
    rendered = repr(parsed)
    for secret in ("LEAK_A", "LEAK_B", "LEAK_C", "LEAK_D"):
        assert secret not in rendered
    for marker in ("[tts]", "[ene_goal_update]", "[analysis]", "[proactive_conversation]"):
        assert marker not in rendered.lower()


def test_reserved_control_sanitizer_discards_crossed_block_from_outer_start():
    cleaned = response_cleanup.sanitize_reserved_control_blocks(
        "VISIBLE [thought]OUTER [analysis]LEAK[/thought] AFTER[/analysis] END"
    )

    assert cleaned == "VISIBLE"
    assert "[thought]OUTER" not in cleaned


@pytest.mark.parametrize(
    ("response_text", "secrets"),
    [
        (
            "VISIBLE [thought]OUTER [thought]INNER[/thought] TAIL[/thought] END [normal]",
            ("OUTER", "INNER", "TAIL"),
        ),
        (
            "VISIBLE [thought]OUTER [analysis]user_intent=x[/thought] AFTER[/analysis] END [normal]",
            ("OUTER", "user_intent=x", "AFTER"),
        ),
    ],
)
def test_parse_response_discards_nested_or_crossed_reserved_blocks(response_text, secrets):
    parsed = parse_llm_response(
        response_text,
        settings_source={"ui_language": "ko", "tts_language": "ko"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "VISIBLE"
    assert parsed[2] == "VISIBLE"
    assert parsed[4] == {}
    assert parsed[6] == ""
    rendered = repr(parsed)
    for secret in secrets:
        assert secret not in rendered
    assert "[/thought]" not in rendered.lower()
    assert "[/analysis]" not in rendered.lower()


def test_parse_response_strips_orphan_reserved_close_markers():
    parsed = parse_llm_response(
        "[/analysis] VISIBLE [normal] AFTER [/thought]",
        settings_source={"ui_language": "ko", "tts_language": "ko"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "VISIBLE  AFTER"
    assert parsed[2] == "VISIBLE  AFTER"
    assert "[/analysis]" not in repr(parsed).lower()
    assert "[/thought]" not in repr(parsed).lower()


def test_parse_response_preserves_flat_sequential_control_blocks():
    parsed = parse_llm_response(
        "[analysis]\nuser_intent=synthetic_intent\n[/analysis]\n"
        "[thought]\nsynthetic_thought\n[/thought]\n"
        "[tts]\nSYNTHETIC_TTS\n[/tts]\n"
        "VISIBLE [normal]",
        settings_source={"ui_language": "ko", "tts_language": "ja"},
        available_emotions={"normal"},
    )

    assert parsed[0] == "VISIBLE"
    assert parsed[2] == "SYNTHETIC_TTS"
    assert parsed[4] == {"user_intent": "synthetic_intent"}
    assert parsed[6] == "synthetic_thought"


def test_parse_response_extracts_plain_analysis_lines_at_top():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
user_emotion=calm
user_intent=greeting, social_interaction
interaction_effect=positive
bond_delta_hint=low_positive
stress_delta_hint=none
energy_delta_hint=none
valence_delta_hint=none
confidence=0.9
flags=greeting

좋은 저녁이에요. [smile]
こんばんは。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert events == []
    assert analysis["user_emotion"] == "calm"
    assert analysis["flags"] == "greeting"
    assert promises == []
    assert thought == ""


def test_parse_response_extracts_explicit_tts_block_without_leaking_to_text():
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {"ui_language": "ko", "tts_language": "ja"}
    response_text = """
좋은 저녁이에요. [smile]
[tts]
こんばんは。
[/tts]
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


def test_parse_response_keeps_japanese_visible_when_tts_language_matches_response_language():
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {"ui_language": "ja", "tts_language": "ja"}
    response_text = "こんばんは。もう少しだけ確認します。 [smile]"

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "こんばんは。もう少しだけ確認します。"
    assert emotion == "smile"
    assert tts_text == "こんばんは。もう少しだけ確認します。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


def test_parse_response_uses_visible_text_for_tts_when_korean_tts_matches_response_language():
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {"ui_language": "ko", "tts_language": "ko"}
    response_text = "좋은 저녁이에요. [smile]"

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "좋은 저녁이에요."
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


def test_parse_response_removes_japanese_lines_even_when_not_at_end():
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {"ui_language": "ko", "tts_language": "ja"}
    response_text = """
좋은 저녁이에요. [smile]
こんばんは。

아까 정리하던 문서, 지금은 거의 마무리된 상태인가요?
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == (
        "좋은 저녁이에요.\n\n"
        "아까 정리하던 문서, 지금은 거의 마무리된 상태인가요?"
    )
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


def test_parse_response_removes_thinking_tags_before_extracting_tts_text():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
<think>
응답 형식을 점검한다.
</think>
좋은 저녁이에요. [smile]
こんばんは。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


def test_parse_response_removes_leading_orphan_thinking_close_tag():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
</think>
좋은 저녁이에요. [smile]
こんばんは。
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture, _mood = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


def test_parse_response_logs_schedule_event_payload():
    logs = []
    response_text = (
        "Noted. [event:2099-01-02|Synthetic Private Launch|Synthetic room details] "
        "[normal]"
    )

    parsed = parse_llm_response(
        response_text,
        settings_source={"ui_language": "en", "tts_language": "en"},
        available_emotions={"normal"},
        log_event=logs.append,
    )

    _text, _emotion, _tts_text, events, *_rest = parsed
    assert events == [
        {
            "date": "2099-01-02",
            "title": "Synthetic Private Launch",
            "description": "Synthetic room details",
        }
    ]
    assert len(logs) == 1
    log_output = "\n".join(logs)
    assert "2099-01-02" in log_output
    assert "Synthetic Private Launch" in log_output
    assert "Synthetic room details" in log_output


def test_gemini_parse_response_logs_schedule_event_metadata_without_content(capsys):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {"ui_language": "en", "tts_language": "en"}
    response_text = (
        "Noted. [event:2099-04-05|Synthetic Board Review|Synthetic suite note] "
        "[normal]"
    )

    _text, _emotion, _tts_text, events, *_rest = client._parse_response(response_text)

    captured = capsys.readouterr()
    assert events == [
        {
            "date": "2099-04-05",
            "title": "Synthetic Board Review",
            "description": "Synthetic suite note",
        }
    ]
    assert "2099-04-05" not in captured.out
    assert "Synthetic Board Review" not in captured.out
    assert "Synthetic suite note" not in captured.out
    assert "category=schedule_event_extracted" in captured.out
    assert "event_count=1" in captured.out
    assert captured.err == ""
def test_parse_response_extracts_valid_legacy_mood_analysis():
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {"enable_mood_system": True, "enable_response_analysis": True}
    response_text = """[mood_analysis]
kind=loss
target_scope=external
relation_category=none
intensity=2
clarity=explicit
certainty=high
controllability=low
repair_signal=none
risk_class=concern
proposed_stance=brief
[/mood_analysis]
합성 답변 [normal]"""
    result = client._parse_response(response_text)
    assert len(result) == 11
    assert result[10]["event"]["kind"] == "loss"
    assert "mood_analysis" not in result[0]


def test_parse_response_legacy_mood_analysis_invalid_falls_back_to_neutral():
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {"enable_mood_system": True, "enable_response_analysis": True}
    result = client._parse_response("[mood_analysis]\nreason=금지 키\n[/mood_analysis]\n합성 답변 [normal]")
    assert result[10]["event"] == {
        "kind": "neutral", "target_scope": "unknown", "relation_category": "none",
        "intensity": 0, "clarity": "ambiguous", "certainty": "low",
        "controllability": "low", "repair_signal": "none",
    }
    assert result[10]["risk_class"] == "none"
    assert result[10]["proposed_stance"] == "cooperative"


def test_parse_response_strips_unclosed_legacy_mood_analysis_metadata():
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {"enable_mood_system": True, "enable_response_analysis": True}
    result = client._parse_response(
        "합성 답변 [normal]\n[mood_analysis]\nkind=loss\nreason=숨겨야 할 합성 메타"
    )
    assert result[0] == "합성 답변"
    assert result[10] == {
        "event": {
            "kind": "neutral", "target_scope": "unknown", "relation_category": "none",
            "intensity": 0, "clarity": "ambiguous", "certainty": "low",
            "controllability": "low", "repair_signal": "none",
        },
        "risk_class": "none",
        "proposed_stance": "cooperative",
    }


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize(
    "metadata",
    [
        "reason=hidden_meta",
        "kind=loss\nreason=hidden_meta\nrisk_class=urgent",
    ],
)
def test_parse_response_strips_orphan_mood_close_and_connected_metadata(
    enabled, metadata
):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {
        "enable_mood_system": enabled,
        "enable_response_analysis": enabled,
    }
    result = client._parse_response(
        f"합성 답변 [normal]\n{metadata}\n[/mood_analysis]"
    )
    assert result[0] == "합성 답변"
    assert "hidden_meta" not in (result[2] or "")
    assert result[10] is not None if enabled else result[10] is None


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize(
    ("newline", "blank_gap"),
    [
        ("\n", "\n"),
        ("\n", "\n   \n"),
        ("\n", "\n\n \t\n"),
        ("\r\n", "\r\n"),
        ("\r\n", "\r\n  \t\r\n"),
        ("\r\n", "\r\n\r\n \t\r\n"),
    ],
)
def test_parse_response_strips_orphan_mood_metadata_across_blank_lines(
    enabled, newline, blank_gap
):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {
        "enable_mood_system": enabled,
        "enable_response_analysis": enabled,
    }
    response = (
        f"합성 답변 [normal]{newline}"
        f"kind=loss{newline}reason=hidden_meta{blank_gap}[/mood_analysis]"
    )
    result = client._parse_response(response)
    assert result[0] == "합성 답변"
    assert "hidden_meta" not in (result[2] or "")
    assert result[10] is not None if enabled else result[10] is None


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize(
    ("newline", "metadata", "close_marker"),
    [
        ("\n", "reason=hidden_meta", "[/mood_analysis]"),
        ("\r\n", "kind=loss\t", "[ / MOOD_ANALYSIS ]"),
        (
            "\n",
            "kind=loss\nextra_key=hidden_meta\t",
            "[  /  Mood_Analysis  ]",
        ),
        (
            "\r\n",
            "kind=loss\r\nreason=hidden_meta\r\ncustom-field=synthetic\t",
            "[ / mood_analysis ]",
        ),
    ],
)
def test_parse_response_strips_same_line_orphan_mood_close_metadata(
    enabled, newline, metadata, close_marker
):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {
        "enable_mood_system": enabled,
        "enable_response_analysis": enabled,
    }
    result = client._parse_response(
        f"합성 답변 [normal]{newline}{metadata}{close_marker}"
    )
    assert result[0] == "합성 답변"
    assert "hidden_meta" not in (result[2] or "")
    assert result[10] is not None if enabled else result[10] is None


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize(
    ("open_marker", "close_marker"),
    [
        ("[mood_analysis extra]", "[/mood_analysis]"),
        ("[mood_analysis_extra]", "[/mood_analysis_extra]"),
        ("[ Mood_Analysis-debug ]", "[ / MOOD_ANALYSIS-debug ]"),
    ],
)
def test_parse_response_strips_paired_malformed_mood_marker_region_only(
    enabled, open_marker, close_marker
):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {
        "enable_mood_system": enabled,
        "enable_response_analysis": enabled,
    }
    result = client._parse_response(
        f"앞쪽 합성 문장\n{open_marker}\nkind=loss\nreason=hidden_meta\n"
        f"{close_marker}\n뒤쪽 합성 답변 [normal]"
    )
    assert result[0] == "앞쪽 합성 문장\n뒤쪽 합성 답변"
    assert "hidden_meta" not in (result[2] or "")
    if enabled:
        assert result[10]["event"]["kind"] == "neutral"
    else:
        assert result[10] is None


@pytest.mark.parametrize("enabled", [True, False])
def test_parse_response_mixed_exact_and_malformed_mood_blocks_is_safe(enabled):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {
        "enable_mood_system": enabled,
        "enable_response_analysis": enabled,
    }
    result = client._parse_response(
        "[mood_analysis]\nkind=loss\ntarget_scope=external\n"
        "relation_category=none\nintensity=2\nclarity=explicit\ncertainty=high\n"
        "controllability=low\nrepair_signal=none\nrisk_class=concern\n"
        "proposed_stance=brief\n[/mood_analysis]\n"
        "[mood_analysis extra]\nreason=hidden_meta\n[/mood_analysis]\n"
        "합성 답변 [normal]"
    )
    assert result[0] == "합성 답변"
    if enabled:
        assert result[10]["event"]["kind"] == "neutral"
    else:
        assert result[10] is None


_MOOD_OPEN_VARIANTS = (
    ("exact", "[mood_analysis]"),
    ("extra", "[ Mood_Analysis extra ]"),
    ("underscore", "[MOOD_ANALYSIS_extra]"),
    ("hyphen", "[ mood_analysis-extra ]"),
)
_MOOD_CLOSE_VARIANTS = (
    ("exact", "[/mood_analysis]"),
    ("extra", "[ / Mood_Analysis extra ]"),
    ("underscore", "[ / MOOD_ANALYSIS_extra ]"),
    ("hyphen", "[ / mood_analysis-extra ]"),
)


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("open_kind,open_marker", _MOOD_OPEN_VARIANTS)
@pytest.mark.parametrize("close_kind,close_marker", _MOOD_CLOSE_VARIANTS)
def test_parse_response_bounds_all_mood_marker_suffix_combinations(
    enabled, open_kind, open_marker, close_kind, close_marker
):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {
        "enable_mood_system": enabled,
        "enable_response_analysis": enabled,
    }
    result = client._parse_response(
        f"{open_marker}\nkind=loss\ntarget_scope=external\n"
        "relation_category=none\nintensity=2\nclarity=explicit\ncertainty=high\n"
        "controllability=low\nrepair_signal=none\nrisk_class=concern\n"
        f"proposed_stance=brief\n{close_marker}\n합성 답변 [normal]"
    )
    assert result[0] == "합성 답변"
    assert "proposed_stance" not in (result[2] or "")
    if not enabled:
        assert result[10] is None
    elif open_kind == close_kind == "exact":
        assert result[10]["event"]["kind"] == "loss"
    else:
        assert result[10]["event"]["kind"] == "neutral"


@pytest.mark.parametrize("enabled", [True, False])
def test_parse_response_strips_malformed_mood_open_fragment_and_tail(enabled):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {
        "enable_mood_system": enabled,
        "enable_response_analysis": enabled,
    }
    result = client._parse_response(
        "합성 답변 [normal]\n[mood_analysis\nkind=loss\nrisk_class=urgent"
    )
    assert result[0] == "합성 답변"
    assert "risk_class" not in (result[2] or "")
    assert result[10] is not None if enabled else result[10] is None


def test_parse_response_preserves_plain_known_key_value_without_mood_marker():
    parsed = parse_llm_response(
        "kind=loss 문법을 설명하는 합성 문장 [normal]",
        settings_source={"enable_mood_system": False},
    )
    assert parsed[0] == "kind=loss 문법을 설명하는 합성 문장"
