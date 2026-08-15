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


def test_on_response_ready_applies_user_analysis_and_ignores_new_mood_payload(capsys):
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
        "",
        [],
        "",
        "",
        [],
        "",
        "SYNTHETIC-MOOD-RAW",
    )

    assert dummy.mood_manager.calls == [
        ("user_analysis", {"user_intent": "affection", "confidence": "0.9"}),
        ("assistant_emotion", "smile"),
    ]
    captured = capsys.readouterr()
    assert "SYNTHETIC-MOOD-RAW" not in captured.out + captured.err


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
        ("좋은 저녁이에요. 오늘 하루는 어떻게 보내셨나요?", "smile", "")
    ]
    assert dummy.appended == ("assistant", "좋은 저녁이에요. 오늘 하루는 어떻게 보내셨나요?")


def test_on_response_ready_sanitizes_leaked_thought_block_alias_before_emitting():
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
        "[생각]\n"
        "마스터가 조금 답답해하는 것 같다. 먼저 안심시켜야겠다.\n"
        "[/생각]\n"
        "네, 그 부분부터 다시 잡아볼게요. [smile]"
    )

    WebBridge._on_response_ready(dummy, leaked_text, "smile", "", [])

    assert dummy.message_received.emitted == [
        ("네, 그 부분부터 다시 잡아볼게요.", "smile", "")
    ]
    assert dummy.appended == ("assistant", "네, 그 부분부터 다시 잡아볼게요.")


def test_on_response_ready_emits_thought_without_adding_it_to_context():
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

    WebBridge._on_response_ready(
        dummy,
        "오늘은 짧게 쉬어도 괜찮아요.",
        "smile",
        "",
        [],
        "",
        "",
        [],
        "무리시키고 싶지는 않다. 그래도 곁에 있어야겠다.",
    )

    assert dummy.message_received.emitted == [
        (
            "오늘은 짧게 쉬어도 괜찮아요.",
            "smile",
            "무리시키고 싶지는 않다. 그래도 곁에 있어야겠다.",
        )
    ]
    assert dummy.appended == ("assistant", "오늘은 짧게 쉬어도 괜찮아요.")


def test_on_response_ready_remembers_thought_for_optional_context_without_visible_leak():
    dummy = type("BridgeDummy", (), {})()
    dummy.settings = {
        "enable_ene_thoughts": True,
        "include_ene_thoughts_in_context": True,
        "ene_thought_context_limit": 2,
    }
    dummy._last_assistant_response = None
    dummy.mood_manager = None
    dummy._emit_mood_changed = lambda snapshot: None
    dummy.conversation_buffer = [("user", "조금 피곤해", "2026-03-24 10:00")]
    dummy._append_conversation = lambda role, text: dummy.conversation_buffer.append((role, text, "2026-03-24 10:01"))
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
    dummy._sanitize_visible_thought_text = lambda thought: WebBridge._sanitize_visible_thought_text(dummy, thought)
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._collect_promise_ids = lambda items=None: []
    dummy._clear_active_promise_tracking = lambda promise_id="": None
    dummy._mark_promise_completed = lambda promise_id="": None

    WebBridge._on_response_ready(
        dummy,
        "오늘은 짧게 쉬어도 괜찮아요.",
        "smile",
        "",
        [],
        "",
        "",
        [],
        "무리시키고 싶지는 않다. 그래도 곁에 있어야겠다.",
    )

    assert dummy.message_received.emitted == [
        (
            "오늘은 짧게 쉬어도 괜찮아요.",
            "smile",
            "무리시키고 싶지는 않다. 그래도 곁에 있어야겠다.",
        )
    ]
    assert dummy.conversation_buffer[-1] == ("assistant", "오늘은 짧게 쉬어도 괜찮아요.", "2026-03-24 10:01")
    assert dummy._ene_thought_context_buffer == [
        {
            "conversation_index": 1,
            "timestamp": "2026-03-24 10:01",
            "thought": "무리시키고 싶지는 않다. 그래도 곁에 있어야겠다.",
        }
    ]


def test_build_ene_thought_context_uses_recent_limit_and_requires_both_settings():
    dummy = type("BridgeDummy", (), {})()
    dummy.settings = {
        "enable_ene_thoughts": True,
        "include_ene_thoughts_in_context": True,
        "ene_thought_context_limit": 2,
        "ui_language": "ko",
    }
    dummy._ene_thought_context_buffer = [
        {"thought": "첫 생각"},
        {"thought": "두 번째 생각"},
        {"thought": "세 번째 생각"},
    ]

    context = WebBridge._build_ene_thought_context(dummy)

    assert "첫 생각" not in context
    assert "[에네의 이전 내심 메모]" in context
    assert "- 직전 생각: 세 번째 생각" in context
    assert "- 이전 생각 2: 두 번째 생각" in context
    assert "[/에네의 이전 내심 메모]" in context

    dummy.settings["include_ene_thoughts_in_context"] = False
    assert WebBridge._build_ene_thought_context(dummy) == ""

    dummy.settings["include_ene_thoughts_in_context"] = True
    dummy.settings["enable_ene_thoughts"] = False
    assert WebBridge._build_ene_thought_context(dummy) == ""


def test_build_ene_thought_context_uses_custom_assistant_name():
    dummy = type("BridgeDummy", (), {})()
    dummy.settings = {
        "ui_language": "en",
        "enable_ene_thoughts": True,
        "include_ene_thoughts_in_context": True,
        "ene_thought_context_limit": 1,
        "assistant_display_name": "Luna",
    }
    dummy._ene_thought_context_buffer = [{"thought": "stay concise", "conversation_index": 1}]

    context = WebBridge._build_ene_thought_context(dummy)

    assert "[Luna Previous Inner Notes]" in context
    assert "[ENE Previous Inner Notes]" not in context


def test_on_response_ready_hides_thought_when_setting_is_disabled():
    dummy = type("BridgeDummy", (), {})()
    dummy.settings = {"enable_ene_thoughts": False}
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
    dummy._sanitize_visible_thought_text = lambda thought: WebBridge._sanitize_visible_thought_text(dummy, thought)
    dummy._refresh_llm_history_from_visible_conversation = lambda: None
    dummy._remember_tracked_promise_ids = lambda ids=None: None
    dummy._collect_promise_ids = lambda items=None: []
    dummy._clear_active_promise_tracking = lambda promise_id="": None
    dummy._mark_promise_completed = lambda promise_id="": None

    WebBridge._on_response_ready(
        dummy,
        "생각은 숨기고 답변만 보여줄게요.",
        "normal",
        "",
        [],
        "",
        "",
        [],
        "이건 설정이 꺼져 있으면 보여주면 안 된다.",
    )

    assert dummy.message_received.emitted == [
        ("생각은 숨기고 답변만 보여줄게요.", "normal", "")
    ]
    assert dummy.appended == ("assistant", "생각은 숨기고 답변만 보여줄게요.")


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
