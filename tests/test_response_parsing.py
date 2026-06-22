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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

    assert text == "네, 그 부분부터 다시 잡아볼게요."
    assert emotion == "smile"
    assert tts_text == "はい、そこからもう一度見直します。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == "마스터가 답답해하는 것 같다. 먼저 안심시켜야겠다."


def test_parse_response_keeps_reply_when_model_wraps_everything_as_thought():
    client = GeminiClient.__new__(GeminiClient)
    response_text = """
[thought]
괜찮아요. 천천히 해도 돼요. [smile]
大丈夫です。ゆっくりでいいですよ。
[/thought]
""".strip()

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

    assert text == "괜찮아요. 천천히 해도 돼요."
    assert emotion == "smile"
    assert tts_text == "大丈夫です。ゆっくりでいいですよ。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""


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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

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

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client._parse_response(response_text)

    assert text == "좋은 저녁이에요."
    assert emotion == "smile"
    assert tts_text == "こんばんは。"
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""
