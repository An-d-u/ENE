from src.ai.llm_client import GeminiClient


class _DummyChat:
    def __init__(self, response):
        self.response = response
        self.messages = []

    def send_message(self, message):
        self.messages.append(message)
        return self.response


class _DummyResponse:
    text = None
    prompt_feedback = "blocked-for-test"
    candidates = []
    usage_metadata = None


def test_send_message_returns_fallback_when_gemini_text_is_none(capsys):
    client = GeminiClient.__new__(GeminiClient)
    client.chat = _DummyChat(_DummyResponse())
    client.settings = {
        "enable_ene_thoughts": True,
        "include_ene_thoughts_in_context": True,
    }
    client._last_token_usage = {}

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client.send_message("안녕")

    assert text == "음... 무슨 일이 있었나봐요."
    assert emotion == "confused"
    assert tts_text is None
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""

    captured = capsys.readouterr().out
    assert "빈 텍스트 응답" in captured
    assert "prompt_feedback" in captured
    assert "enable_ene_thoughts=True" in captured


def test_send_message_returns_fallback_when_gemini_text_is_blank(capsys):
    client = GeminiClient.__new__(GeminiClient)
    response = _DummyResponse()
    response.text = "   "
    client.chat = _DummyChat(response)
    client.settings = {"enable_ene_thoughts": False}
    client._last_token_usage = {}

    text, emotion, tts_text, events, analysis, promises, thought, _goal_update, _proactive, _gesture = client.send_message("안녕")

    assert text == "음... 무슨 일이 있었나봐요."
    assert emotion == "confused"
    assert tts_text is None
    assert events == []
    assert analysis == {}
    assert promises == []
    assert thought == ""

    captured = capsys.readouterr().out
    assert "빈 텍스트 응답" in captured
    assert "enable_ene_thoughts=False" in captured
