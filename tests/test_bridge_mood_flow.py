import json
from datetime import datetime
from uuid import UUID

from src.core.bridge import WebBridge


class _DummySignal:
    def __init__(self):
        self.emitted = []

    def emit(self, *args):
        self.emitted.append(args)


class _DummyMoodManager:
    def __init__(self, *, fail_apply=False):
        self.calls = []
        self.fail_apply = fail_apply

    def apply_event(self, event_id, analysis, occurred_at_utc):
        self.calls.append(("apply", event_id, analysis, occurred_at_utc))
        if self.fail_apply:
            raise RuntimeError("synthetic mood save failure")
        return {
            "current_mood": "calm",
            "valence": 0.1,
            "energy": 0.0,
            "bond": 0.2,
            "stress": -0.1,
        }

    def advance_time_and_save(self, occurred_at_utc):
        self.calls.append(("advance", occurred_at_utc))
        return {"current_mood": "calm"}


def _valid_mood_analysis():
    return {
        "event": {
            "kind": "connection",
            "target_scope": "relationship",
            "relation_category": "none",
            "intensity": 2,
            "clarity": "explicit",
            "certainty": "high",
            "controllability": "medium",
            "repair_signal": "none",
        },
        "risk_class": "none",
        "proposed_stance": "cooperative",
    }


def test_on_response_ready_applies_owned_mood_event_once_and_ignores_legacy_analysis(capsys):
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
    dummy.settings = {
        "enable_mood_system": True,
        "enable_response_analysis": True,
    }
    event_id = "9a317237-bbb9-42c9-8f67-823c4e84c6a6"
    occurred_at = "2099-01-01T00:00:00+00:00"
    dummy._last_request_payload = {
        "type": "text",
        "mood_event_id": event_id,
        "mood_occurred_at": occurred_at,
        "mood_finalized": False,
    }

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
        json.dumps(_valid_mood_analysis()),
        expected_mood_event_id=event_id,
        expected_mood_occurred_at=occurred_at,
    )

    assert dummy.mood_manager.calls == [
        ("apply", event_id, _valid_mood_analysis(), occurred_at),
    ]
    assert dummy._last_request_payload["mood_finalized"] is True
    captured = capsys.readouterr()
    assert event_id not in captured.out + captured.err


def test_mood_event_context_is_uuid4_and_canonical_utc_seconds():
    first = WebBridge._new_mood_event_context()
    second = WebBridge._new_mood_event_context()

    assert UUID(first["event_id"]).version == 4
    assert UUID(second["event_id"]).version == 4
    assert first["event_id"] != second["event_id"]
    parsed = datetime.fromisoformat(first["occurred_at_utc"])
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.microsecond == 0
    assert first["occurred_at_utc"].endswith("+00:00")
    assert "Z" not in first["occurred_at_utc"]


def test_mood_event_context_generation_failure_is_fail_safe(monkeypatch):
    monkeypatch.setattr(
        "src.core.bridge_mixins.chat_flow.uuid4",
        lambda: (_ for _ in ()).throw(RuntimeError("synthetic uuid failure")),
    )

    assert WebBridge._new_mood_event_context() == {}


def test_stale_or_duplicate_mood_callback_does_not_apply_again():
    dummy = type("BridgeDummy", (), {})()
    manager = _DummyMoodManager()
    dummy.mood_manager = manager
    dummy.settings = {"enable_mood_system": True, "enable_response_analysis": True}
    old_id = "e407c175-5952-49b2-85a8-c1b1aaf2269e"
    old_time = "2099-01-01T00:00:00+00:00"
    dummy._last_request_payload = {
        "type": "text",
        "mood_event_id": "e7c7117e-f4b1-4821-b145-63ae49e152fa",
        "mood_occurred_at": old_time,
        "mood_finalized": False,
    }

    WebBridge._finalize_owned_mood_event(
        dummy,
        json.dumps(_valid_mood_analysis()),
        expected_mood_event_id=old_id,
        expected_mood_occurred_at=old_time,
    )
    assert manager.calls == []

    dummy._last_request_payload["mood_event_id"] = old_id
    WebBridge._finalize_owned_mood_event(
        dummy,
        json.dumps(_valid_mood_analysis()),
        expected_mood_event_id=old_id,
        expected_mood_occurred_at=old_time,
    )
    WebBridge._finalize_owned_mood_event(
        dummy,
        json.dumps(_valid_mood_analysis()),
        expected_mood_event_id=old_id,
        expected_mood_occurred_at=old_time,
    )
    assert len(manager.calls) == 1


def test_invalid_analysis_is_finalized_without_apply_or_advance():
    dummy = type("BridgeDummy", (), {})()
    dummy.mood_manager = _DummyMoodManager()
    dummy.settings = {"enable_mood_system": True, "enable_response_analysis": True}
    event_id = "1529b839-53fd-44db-be36-0fa87caad31a"
    occurred_at = "2099-01-01T00:00:00+00:00"
    dummy._last_request_payload = {
        "type": "attachments",
        "mood_event_id": event_id,
        "mood_occurred_at": occurred_at,
        "mood_finalized": False,
    }
    invalid = _valid_mood_analysis()
    invalid["event"]["event_id"] = event_id

    WebBridge._finalize_owned_mood_event(
        dummy,
        json.dumps(invalid),
        expected_mood_event_id=event_id,
        expected_mood_occurred_at=occurred_at,
    )

    assert dummy.mood_manager.calls == []
    assert dummy._last_request_payload["mood_finalized"] is True


def test_analysis_disabled_advances_once_and_apply_failure_is_fail_safe(capsys):
    event_id = "20fce916-94f4-44cb-9ad4-16aa69238cbb"
    occurred_at = "2099-01-01T00:00:00+00:00"
    dummy = type("BridgeDummy", (), {})()
    dummy.mood_manager = _DummyMoodManager()
    dummy.settings = {"enable_mood_system": True, "enable_response_analysis": False}
    dummy._last_request_payload = {
        "type": "text",
        "mood_event_id": event_id,
        "mood_occurred_at": occurred_at,
        "mood_finalized": False,
    }
    dummy._emit_mood_changed = lambda snapshot: None

    WebBridge._finalize_owned_mood_event(
        dummy,
        "",
        expected_mood_event_id=event_id,
        expected_mood_occurred_at=occurred_at,
    )
    WebBridge._finalize_owned_mood_event(
        dummy,
        "",
        expected_mood_event_id=event_id,
        expected_mood_occurred_at=occurred_at,
    )
    assert dummy.mood_manager.calls == [("advance", occurred_at)]

    failing = type("BridgeDummy", (), {})()
    failing.mood_manager = _DummyMoodManager(fail_apply=True)
    failing.settings = {"enable_mood_system": True, "enable_response_analysis": True}
    failing._last_request_payload = {
        "type": "text",
        "mood_event_id": event_id,
        "mood_occurred_at": occurred_at,
        "mood_finalized": False,
    }
    failing._emit_mood_changed = lambda snapshot: None
    WebBridge._finalize_owned_mood_event(
        failing,
        json.dumps(_valid_mood_analysis()),
        expected_mood_event_id=event_id,
        expected_mood_occurred_at=occurred_at,
    )
    assert failing._last_request_payload["mood_finalized"] is True
    captured = capsys.readouterr()
    assert "synthetic mood save failure" not in captured.out + captured.err


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
    event_id = dummy._last_request_payload["mood_event_id"]
    occurred_at = dummy._last_request_payload["mood_occurred_at"]
    assert UUID(event_id).version == 4
    assert datetime.fromisoformat(occurred_at).microsecond == 0
    assert dummy._last_request_payload["mood_finalized"] is False
    assert captured["kwargs"]["mood_event_id"] == event_id
    assert captured["kwargs"]["mood_occurred_at"] == occurred_at
