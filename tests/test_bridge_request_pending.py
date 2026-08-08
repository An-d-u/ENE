from src.core.bridge_mixins import chat_flow
from src.core.bridge import WebBridge
from src.core.bridge_mixins.chat_flow import ChatFlowBridgeMixin
from src.core.bridge_mixins.memory_summary import MemorySummaryBridgeMixin


class _DummySignal:
    def __init__(self):
        self.emitted = []
        self.connected = []

    def connect(self, callback):
        self.connected.append(callback)

    def emit(self, *args):
        self.emitted.append(args)


class _DummyWorker:
    def __init__(self, *_args, **kwargs):
        self.kwargs = kwargs
        self.response_ready = _DummySignal()
        self.error_occurred = _DummySignal()
        self.started = False

    def start(self):
        self.started = True


class _DummyBridge(ChatFlowBridgeMixin):
    def __init__(self):
        self.worker = None
        self.llm_client = object()
        self.request_pending_changed = _DummySignal()
        self.request_pending_stage_changed = _DummySignal()

    def _with_ene_thought_context(self, message):
        return message

    def _with_tts_output_reminder(self, message):
        return message

    def _on_response_ready(self, *_args):
        pass

    def _on_error(self, *_args):
        pass


class _SendToAiBridge(_DummyBridge):
    def __init__(self):
        super().__init__()
        self.settings = None
        self.conversation_buffer = []
        self.mood_manager = None
        self.message_received = _DummySignal()
        self._is_rerolling = False
        self._last_request_payload = None

    def _handle_note_command(self, _message):
        return False

    def _handle_obs_command(self, _message):
        return False

    def _handle_diary_command(self, _message):
        return False

    def _now_timestamp(self):
        return "2026-06-27 09:30"

    def _build_general_chat_prompt(self, message, attachment_context=""):
        return f"PROMPT::{message}::VISIBLE_CONTEXT"

    def _with_prompt_time(self, timestamp, prompt):
        return f"[TIME {timestamp}]\n{prompt}"

    def _mark_user_activity(self):
        pass

    def _append_conversation(self, role, message, timestamp=None):
        self.conversation_buffer.append((role, message, timestamp))


class _ScheduleEvent:
    def __init__(self, date, title):
        self.date = date
        self.title = title


class _CalendarManager:
    def __init__(self, error_message=None):
        self.error_message = error_message

    def add_event(self, date, title, description="", source=""):
        if self.error_message:
            raise RuntimeError(self.error_message)
        return _ScheduleEvent(date, title)


class _ResponseReadyBridge:
    def __init__(self, calendar_manager):
        self._last_assistant_response = None
        self.mood_manager = None
        self.settings = {"enable_schedule_recognition": True}
        self.goal_manager = None
        self.calendar_manager = calendar_manager
        self.conversation_buffer = []
        self.enable_tts = False
        self.tts_client = None
        self.audio_player = None
        self.pending_response = None
        self.pending_token_usage_payload = ""
        self._is_rerolling = False
        self.request_pending_changed = _DummySignal()
        self.request_pending_stage_changed = _DummySignal()
        self.message_received = _DummySignal()
        self.token_usage_ready = _DummySignal()
        self.reroll_state_changed = _DummySignal()

    def _sanitize_visible_response_text(self, text):
        return WebBridge._sanitize_visible_response_text(self, text)

    def _are_ene_thoughts_enabled(self):
        return False

    def _append_conversation(self, role, message, timestamp=None):
        self.conversation_buffer.append((role, message, timestamp))

    def _remember_ene_thought_for_context(self, _thought):
        pass

    def _refresh_llm_history_from_visible_conversation(self):
        pass

    def _resolve_token_usage_payload(self, payload=""):
        return payload or "{}"

    def _collect_promise_ids(self, stored):
        return WebBridge._collect_promise_ids(self, stored)

    def _remember_tracked_promise_ids(self, _promise_ids):
        pass

    def _check_auto_summarize(self):
        pass


class _ManualSummaryBridge(MemorySummaryBridgeMixin):
    def __init__(self):
        self.worker = None
        self.llm_client = object()
        self.memory_manager = object()
        self.conversation_buffer = [("user", "테스트 대화", "2026-05-26 10:00")]
        self.request_pending_changed = _DummySignal()
        self.summary_notice = _DummySignal()
        self.summarized = False
        self.summary_worker_started = []

    async def _auto_summarize(self):
        self.summarized = True

    async def _prepare_summary_review(self):
        self.summarized = True

    def _start_summary_review_worker(self, messages, success_notice=None):
        self.summary_worker_started.append((list(messages), success_notice))


def test_start_ai_worker_emits_request_pending_changed(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()

    bridge._start_ai_worker("안녕")

    assert bridge.request_pending_changed.emitted == [(True,)]
    assert bridge.request_pending_stage_changed.emitted == [("thinking",)]
    assert bridge.worker.kwargs["progress_callback"] == bridge._emit_request_pending_stage_changed
    assert bridge.worker.kwargs["include_life_record_context"] is False
    assert bridge.worker.started is True


def test_start_ai_worker_preserves_explicit_life_record_scope(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()

    bridge._start_ai_worker("합성 요청", include_life_record_context=True)

    assert bridge.worker.kwargs["include_life_record_context"] is True


def test_ai_worker_progress_callback_emits_searching_stage(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()

    bridge._start_ai_worker("hello")
    bridge.worker.kwargs["progress_callback"]("searching")

    assert bridge.request_pending_stage_changed.emitted == [("thinking",), ("searching",)]


def test_request_pending_stage_normalizes_unknown_stage_to_thinking():
    bridge = _DummyBridge()

    bridge._emit_request_pending_stage_changed("")
    bridge._emit_request_pending_stage_changed("unknown")
    bridge._emit_request_pending_stage_changed(" searching ")

    assert bridge.request_pending_stage_changed.emitted == [
        ("thinking",),
        ("thinking",),
        ("searching",),
    ]


def test_send_to_ai_logs_only_prompt_lengths(monkeypatch, capsys):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _SendToAiBridge()
    raw_message = "synthetic prompt alpha"
    timestamped_prompt = "[TIME 2026-06-27 09:30]\nPROMPT::synthetic prompt alpha::VISIBLE_CONTEXT"

    bridge.send_to_ai(raw_message)

    assert bridge.worker.kwargs["include_life_record_context"] is True
    assert bridge._last_request_payload["include_life_record_context"] is True

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert raw_message not in combined
    assert timestamped_prompt not in combined
    assert "VISIBLE_CONTEXT" not in combined
    assert f"message_chars={len(raw_message)}" in combined
    assert f"prompt_chars={len(timestamped_prompt)}" in combined


def test_response_ready_schedule_success_log_omits_event_content(capsys):
    bridge = _ResponseReadyBridge(_CalendarManager())
    event_title = "Synthetic schedule title"
    event_date = "2099-12-31"

    WebBridge._handle_response_ready(
        bridge,
        "Synthetic reply.",
        "normal",
        "",
        [{"date": event_date, "title": event_title, "description": "Synthetic note."}],
    )

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert event_title not in combined
    assert event_date not in combined
    assert "category=schedule_add_success" in combined


def test_response_ready_schedule_failure_log_omits_event_and_exception_content(capsys):
    error_message = "Synthetic exception message"
    bridge = _ResponseReadyBridge(_CalendarManager(error_message=error_message))
    event_title = "Synthetic failed title"
    event_date = "2099-11-30"

    WebBridge._handle_response_ready(
        bridge,
        "Synthetic reply.",
        "normal",
        "",
        [{"date": event_date, "title": event_title, "description": ""}],
    )

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert event_title not in combined
    assert event_date not in combined
    assert error_message not in combined
    assert "category=schedule_add_failed" in combined
    assert "exception_class=RuntimeError" in combined


def test_log_from_js_logs_only_message_length(capsys):
    raw_message = "Synthetic JS console message"

    WebBridge.log_from_js(object(), raw_message)

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert raw_message not in combined
    assert f"message_chars={len(raw_message)}" in combined


def test_log_from_js_does_not_invoke_custom_bool_or_string_hooks(capsys):
    secret = "SYNTHETIC-JS-LOG-HOOK-SENTINEL"
    calls = {"bool": 0, "str": 0, "len": 0}

    class LeakyMessage(str):
        def __bool__(self):
            calls["bool"] += 1
            print(secret)
            return True

        def __str__(self):
            calls["str"] += 1
            print(secret)
            return secret

        def __len__(self):
            calls["len"] += 1
            print(secret)
            return super().__len__()

    WebBridge.log_from_js(object(), LeakyMessage("synthetic safe value"))

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert secret not in combined
    assert calls == {"bool": 0, "str": 0, "len": 0}
    assert "message_chars=0" in combined


def test_start_diary_worker_emits_request_pending_changed(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()
    bridge.diary_service = object()

    bridge._start_diary_worker("오늘 기록", "프롬프트")

    assert bridge.request_pending_changed.emitted == [(True,)]
    assert bridge.request_pending_stage_changed.emitted == [("thinking",)]
    assert bridge.worker.started is True


def test_start_note_worker_emits_request_pending_changed(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()
    bridge.note_service = object()
    bridge.obsidian_manager = object()

    bridge._start_note_worker("노트 작성", "프롬프트")

    assert bridge.request_pending_changed.emitted == [(True,)]
    assert bridge.request_pending_stage_changed.emitted == [("thinking",)]
    assert bridge.worker.started is True


def test_request_pending_false_resets_stage_to_thinking():
    bridge = _DummyBridge()
    bridge._emit_request_pending_stage_changed("searching")

    bridge._emit_request_pending_changed(False)

    assert bridge.request_pending_changed.emitted == [(False,)]
    assert bridge.request_pending_stage_changed.emitted == [("searching",), ("thinking",)]


def test_reset_pending_ui_state_emits_request_pending_false():
    dummy = type("BridgeDummy", (), {})()
    dummy._is_rerolling = True
    dummy.request_pending_changed = _DummySignal()
    dummy.request_pending_stage_changed = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.summary_notice = _DummySignal()

    WebBridge._reset_pending_ui_state(dummy, "처리할 수 없어요.")

    assert dummy.request_pending_changed.emitted == [(False,)]
    assert dummy.request_pending_stage_changed.emitted == [("thinking",)]
    assert dummy.reroll_state_changed.emitted == [(False,)]
    assert dummy.summary_notice.emitted == [("처리할 수 없어요.", "info")]
    assert dummy._is_rerolling is False


def test_on_error_emits_request_pending_false(capsys):
    dummy = type("BridgeDummy", (), {})()
    dummy._active_promise_id = ""
    dummy._active_promise_signature = None
    dummy.promise_manager = None
    dummy._is_rerolling = False
    dummy.request_pending_changed = _DummySignal()
    dummy.request_pending_stage_changed = _DummySignal()
    dummy.message_received = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()

    raw_error = "SYNTHETIC-BRIDGE-PROVIDER-ERROR-SENTINEL"
    WebBridge._on_error(dummy, raw_error)

    assert dummy.request_pending_changed.emitted == [(False,)]
    assert dummy.request_pending_stage_changed.emitted == [("thinking",)]
    assert dummy.message_received.emitted == [("음... 무슨 일이 있었나봐요.", "confused", "")]
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert raw_error not in combined
    assert "category=provider_error" in combined


def test_manual_summary_does_not_emit_request_pending_while_llm_summary_runs():
    bridge = _ManualSummaryBridge()

    bridge.summarize_now()

    assert bridge.request_pending_changed.emitted == []
    assert bridge.summarized is False
    assert bridge.summary_worker_started == [
        ([("user", "테스트 대화", "2026-05-26 10:00")], "요약을 확인해 주세요.")
    ]


def test_manual_summary_early_return_does_not_emit_request_pending():
    bridge = _ManualSummaryBridge()
    bridge.conversation_buffer = []

    bridge.summarize_now()

    assert bridge.request_pending_changed.emitted == []
    assert bridge.summarized is False
