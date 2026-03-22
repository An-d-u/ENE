import json

from src.core.bridge import WebBridge


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _DummyMoodManager:
    def __init__(self):
        self.calls = []

    def on_user_analysis(self, analysis):
        self.calls.append(("user_analysis", analysis))
        return {
            "current_mood": "calm",
            "valence": 0.1,
            "energy": 0.0,
            "bond": 0.2,
            "stress": -0.1,
        }

    def on_assistant_emotion(self, emotion):
        self.calls.append(("assistant_emotion", emotion))
        return {
            "current_mood": "calm",
            "valence": 0.1,
            "energy": 0.0,
            "bond": 0.2,
            "stress": -0.1,
        }


def test_on_response_ready_applies_user_analysis_before_assistant_emotion():
    dummy = type("BridgeDummy", (), {})()
    dummy._last_assistant_response = None
    dummy.mood_manager = _DummyMoodManager()
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._append_conversation = lambda role, text: None
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.message_received = _DummySignal()
    dummy._is_rerolling = False
    dummy.reroll_state_changed = _DummySignal()
    dummy._check_auto_summarize = lambda: None

    WebBridge._on_response_ready(
        dummy,
        "본문",
        "smile",
        "",
        [],
        json.dumps({"user_intent": "affection", "confidence": "0.9"}, ensure_ascii=False),
    )

    assert dummy.mood_manager.calls == [
        ("user_analysis", {"user_intent": "affection", "confidence": "0.9"}),
        ("assistant_emotion", "smile"),
    ]
