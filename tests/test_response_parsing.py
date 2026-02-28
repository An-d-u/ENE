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

    text, emotion, japanese_text, events = client._parse_response(response_text)

    assert text == "한국어 본문입니다."
    assert emotion == "smile"
    assert japanese_text == "一行目です。\n二行目です。"
    assert events == []