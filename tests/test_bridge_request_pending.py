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
    def __init__(self, *_args, **_kwargs):
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

    def _with_ene_thought_context(self, message):
        return message

    def _with_tts_output_reminder(self, message):
        return message

    def _on_response_ready(self, *_args):
        pass

    def _on_error(self, *_args):
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

    async def _auto_summarize(self):
        self.summarized = True

    async def _prepare_summary_review(self):
        self.summarized = True


def test_start_ai_worker_emits_request_pending_changed(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()

    bridge._start_ai_worker("안녕")

    assert bridge.request_pending_changed.emitted == [(True,)]
    assert bridge.worker.started is True


def test_start_diary_worker_emits_request_pending_changed(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()
    bridge.diary_service = object()

    bridge._start_diary_worker("오늘 기록", "프롬프트")

    assert bridge.request_pending_changed.emitted == [(True,)]
    assert bridge.worker.started is True


def test_start_note_worker_emits_request_pending_changed(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()
    bridge.note_service = object()
    bridge.obsidian_manager = object()

    bridge._start_note_worker("노트 작성", "프롬프트")

    assert bridge.request_pending_changed.emitted == [(True,)]
    assert bridge.worker.started is True


def test_reset_pending_ui_state_emits_request_pending_false():
    dummy = type("BridgeDummy", (), {})()
    dummy._is_rerolling = True
    dummy.request_pending_changed = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()
    dummy.summary_notice = _DummySignal()

    WebBridge._reset_pending_ui_state(dummy, "처리할 수 없어요.")

    assert dummy.request_pending_changed.emitted == [(False,)]
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
    dummy.message_received = _DummySignal()
    dummy.reroll_state_changed = _DummySignal()

    WebBridge._on_error(dummy, "API timeout")

    assert dummy.request_pending_changed.emitted == [(False,)]
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
