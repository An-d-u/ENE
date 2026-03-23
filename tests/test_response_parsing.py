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

좋은 저녁이에요, 마스터. [smile]
こんばんは、マスター。
""".strip()

    text, emotion, japanese_text, events, analysis = client._parse_response(response_text)

    assert text == "좋은 저녁이에요, 마스터."
    assert emotion == "smile"
    assert japanese_text == "こんばんは、マスター。"
    assert events == []
    assert analysis["user_emotion"] == "calm"
    assert analysis["flags"] == "greeting"


def test_parse_response_removes_japanese_lines_even_when_not_at_end():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
좋은 저녁이에요, 마스터. [smile]
こんばんは、マスター。

커버 주식회사 엔트리 시트, 아까 옵시디언에서 살짝 봤는데... 내용은 이제 거의 다 정리된 건가요?
""".strip()

    text, emotion, japanese_text, events, analysis = client._parse_response(response_text)

    assert text == (
        "좋은 저녁이에요, 마스터.\n\n"
        "커버 주식회사 엔트리 시트, 아까 옵시디언에서 살짝 봤는데... 내용은 이제 거의 다 정리된 건가요?"
    )
    assert emotion == "smile"
    assert japanese_text == "こんばんは、マスター。"
    assert events == []
    assert analysis == {}
