import pytest

pytest.importorskip("google.genai")

from src.ai.llm_client import GeminiClient


def test_parse_response_keeps_multiline_japanese_for_tts():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
한국어 본문입니다. [smile]
一行目です。
二行目です。
""".strip()

    text, emotion, japanese_text, events, analysis = client._parse_response(response_text)

    assert text == "한국어 본문입니다."
    assert emotion == "smile"
    assert japanese_text == "一行目です。\n二行目です。"
    assert events == []
    assert analysis == {}


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

    text, emotion, japanese_text, events, analysis = client._parse_response(response_text)

    assert text == "네, 알겠어요."
    assert emotion == "smile"
    assert japanese_text == "はい、わかりました。"
    assert events == []
    assert analysis == {
        "user_emotion": "affectionate",
        "user_intent": "affection",
        "confidence": "0.86",
    }


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

    text, emotion, japanese_text, events, analysis = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert japanese_text == "こんばんは。"
    assert events == []
    assert analysis["user_emotion"] == "calm"
    assert analysis["flags"] == "greeting"


def test_parse_response_removes_japanese_lines_even_when_not_at_end():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
좋은 저녁이에요. [smile]
こんばんは。

아까 정리하던 문서, 지금은 거의 마무리된 상태인가요?
""".strip()

    text, emotion, japanese_text, events, analysis = client._parse_response(response_text)

    assert text == (
        "좋은 저녁이에요.\n\n"
        "아까 정리하던 문서, 지금은 거의 마무리된 상태인가요?"
    )
    assert emotion == "smile"
    assert japanese_text == "こんばんは。"
    assert events == []
    assert analysis == {}
