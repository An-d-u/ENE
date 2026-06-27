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
        return f"PROMPT::{message}::PRIVATE_CONTEXT"

    def _with_prompt_time(self, timestamp, prompt):
        return f"[TIME {timestamp}]\n{prompt}"

    def _mark_user_activity(self):
        pass

    def _append_conversation(self, role, message, timestamp=None):
        self.conversation_buffer.append((role, message, timestamp))


class _ManualSummaryBridge(MemorySummaryBridgeMixin):
    def __init__(self):
        self.worker = None
        self.llm_client = object()
        self.memory_manager = object()
        self.conversation_buffer = [("user", "테스트 대화", "2026-05-26 10:00")]
        self.request_pending_changed = _DummySignal()
        self.summary_notice = _DummySignal()
        self.summarized = False

    async def _auto_summarize(self):
        self.summarized = True

    async def _prepare_summary_review(self):
        self.summarized = True


def test_start_ai_worker_emits_request_pending_changed(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()

    bridge._start_ai_worker("안녕")

    assert bridge.request_pending_changed.emitted == [(True,)]
    assert bridge.request_pending_stage_changed.emitted == [("thinking",)]
    assert bridge.worker.kwargs["progress_callback"] == bridge._emit_request_pending_stage_changed
    assert bridge.worker.started is True


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


def test_send_to_ai_does_not_log_raw_message_or_timestamped_prompt(monkeypatch, capsys):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _SendToAiBridge()
    raw_message = "synthetic-private-prompt-alpha"
    timestamped_prompt = "[TIME 2026-06-27 09:30]\nPROMPT::synthetic-private-prompt-alpha::PRIVATE_CONTEXT"

    bridge.send_to_ai(raw_message)

    captured = capsys.readouterr()
    assert "Received message from JS chars=" in captured.out
    assert "Message with timestamp chars=" in captured.out
    assert raw_message not in captured.out
    assert timestamped_prompt not in captured.out
    assert "PRIVATE_CONTEXT" not in captured.out


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


def test_on_error_emits_request_pending_false():
    dummy = type("BridgeDummy", (), {})()
    dummy._active_promise_id = ""
    dummy._active_promise_signature = None
    dummy.promise_manager = None
    dummy._is_rerolling = False
    dummy.request_pending_changed = _DummySignal()
    dummy.request_pending_stage_changed = _DummySignal()
    dummy.message_received = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()

    WebBridge._on_error(dummy, "API timeout")

    assert dummy.request_pending_changed.emitted == [(False,)]
    assert dummy.request_pending_stage_changed.emitted == [("thinking",)]
    assert dummy.message_received.emitted == [("음... 무슨 일이 있었나봐요.", "confused", "")]


def test_manual_summary_does_not_emit_request_pending_while_llm_summary_runs():
    bridge = _ManualSummaryBridge()

    bridge.summarize_now()

    assert bridge.request_pending_changed.emitted == []
    assert bridge.summarized is True


def test_manual_summary_early_return_does_not_emit_request_pending():
    bridge = _ManualSummaryBridge()
    bridge.conversation_buffer = []

    bridge.summarize_now()

    assert bridge.request_pending_changed.emitted == []
    assert bridge.summarized is False
