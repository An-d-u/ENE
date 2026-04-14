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
    dummy.pending_token_usage_payload = ""
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy._is_rerolling = False
    dummy.reroll_state_changed = _DummySignal()
    dummy._check_auto_summarize = lambda: None
    dummy._resolve_token_usage_payload = lambda payload="": payload or "{}"
    dummy._sanitize_visible_response_text = lambda text: WebBridge._sanitize_visible_response_text(dummy, text)
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._collect_promise_ids = lambda items=None: []
    dummy._clear_active_promise_tracking = lambda promise_id="": None
    dummy._mark_promise_completed = lambda promise_id="": None

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


def test_on_response_ready_sanitizes_leaked_analysis_lines_before_emitting():
    dummy = type("BridgeDummy", (), {})()
    dummy._last_assistant_response = None
    dummy.mood_manager = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._append_conversation = lambda role, text: setattr(dummy, "appended", (role, text))
    dummy.enable_tts = False
    dummy.tts_client = None
    dummy.audio_player = None
    dummy.pending_response = None
    dummy.pending_token_usage_payload = ""
    dummy.message_received = _DummySignal()
    dummy.token_usage_ready = _DummySignal()
    dummy._is_rerolling = False
    dummy.reroll_state_changed = _DummySignal()
    dummy._check_auto_summarize = lambda: None
    dummy._resolve_token_usage_payload = lambda payload="": payload or "{}"
    dummy._sanitize_visible_response_text = lambda text: WebBridge._sanitize_visible_response_text(dummy, text)
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._collect_promise_ids = lambda items=None: []
    dummy._clear_active_promise_tracking = lambda promise_id="": None
    dummy._mark_promise_completed = lambda promise_id="": None

    leaked_text = (
        "user_emotion=calm\n"
        "user_intent=greeting_and_check_status\n"
        "interaction_effect=positive\n"
        "bond_delta_hint=low_positive\n"
        "stress_delta_hint=none\n"
        "energy_delta_hint=none\n"
        "valence_delta_hint=low_positive\n"
        "confidence=high\n"
        "flags=interaction_start\n\n"
        "좋은 저녁이에요. 오늘 하루는 어떻게 보내셨나요? [smile]"
    )

    WebBridge._on_response_ready(dummy, leaked_text, "smile", "", [])

    assert dummy.message_received.emitted == [
        ("좋은 저녁이에요. 오늘 하루는 어떻게 보내셨나요?", "smile")
    ]
    assert dummy.appended == ("assistant", "좋은 저녁이에요. 오늘 하루는 어떻게 보내셨나요?")


def test_send_to_ai_captures_pending_head_pat_count_and_resets_it():
    class _CalendarManager:
        def __init__(self):
            self.pending = 3
            self.conversation_count_calls = 0

        def increment_conversation_count(self):
            self.conversation_count_calls += 1

        def drain_pending_head_pat_count(self):
            value = self.pending
            self.pending = 0
            return value

    dummy = type("BridgeDummy", (), {})()
    dummy.calendar_manager = _CalendarManager()
    dummy.llm_client = object()
    dummy.mood_manager = None
    dummy._handle_note_command = lambda message: False
    dummy._handle_obs_command = lambda message: False
    dummy._handle_diary_command = lambda message: False
    dummy._now_timestamp = lambda: "2026-04-14 23:59"
    dummy._build_general_chat_prompt = lambda message, attachment_context="": message
    dummy._build_memory_search_inputs = lambda message, timestamp: {
        "memory_search_text": message,
        "latest_user_message": message,
        "recent_context_text": "",
    }
    dummy._mark_user_activity = lambda: None
    dummy._append_conversation = lambda role, text, timestamp: None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy._last_request_payload = None
    dummy._is_rerolling = False

    captured = {}

    def _capture_start_ai_worker(message_with_time, images=None, **kwargs):
        captured["message_with_time"] = message_with_time
        captured["images"] = images
        captured["kwargs"] = kwargs

    dummy._start_ai_worker = _capture_start_ai_worker

    WebBridge.send_to_ai(dummy, "안녕")

    assert dummy.calendar_manager.conversation_count_calls == 1
    assert dummy.calendar_manager.pending == 0
    assert dummy._last_request_payload["head_pat_count_before_message"] == 3
    assert captured["kwargs"]["head_pat_count_before_message"] == 3
