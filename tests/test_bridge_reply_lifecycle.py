from types import SimpleNamespace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from PyQt6.QtCore import QCoreApplication

from src.ai.response_protocol import ResponseDeliveryMetadata
from src.ai.life_record_prompt import LifeMoodSnapshot
from src.core.bridge import WebBridge
from src.core.bridge_mixins import tts
from src.core.bridge_mixins import chat_flow
from src.core.bridge_mixins.chat_flow import ChatFlowBridgeMixin
from src.core.bridge_mixins.life_records import PreparedChatRequest
from src.core.bridge_mixins.tts import TTSBridgeMixin
from src.core.bridge_state import LifeRecordBridgeState


def _ensure_qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


class _Worker:
    def __init__(self, *, running: bool = True):
        self.running = running
        self.response_metadata = ResponseDeliveryMetadata.empty()

    def isRunning(self):
        return self.running


def _begin_normal_reply(bridge: WebBridge, worker: _Worker) -> int:
    operation_id = bridge.life_record_state.try_begin_operation("normal_reply")
    assert type(operation_id) is int
    bridge.worker = worker
    return operation_id


def test_stale_and_shutdown_reply_callbacks_have_no_side_effects():
    _ensure_qt_app()
    bridge = WebBridge()
    current_worker = _Worker()
    stale_worker = _Worker()
    operation_id = _begin_normal_reply(bridge, current_worker)
    messages = []
    pending = []
    bridge.message_received.connect(lambda *args: messages.append(args))
    bridge.request_pending_changed.connect(lambda active: pending.append(bool(active)))

    bridge._on_response_ready(
        "Synthetic stale reply",
        "normal",
        "",
        [],
        response_worker=stale_worker,
        operation_id=operation_id,
    )
    bridge._on_error(
        "synthetic stale error",
        response_worker=stale_worker,
        operation_id=operation_id,
    )

    assert messages == []
    assert pending == []
    assert bridge.life_record_state.phase == "normal_reply"

    bridge.life_record_state.begin_shutdown()
    bridge._on_response_ready(
        "Synthetic shutdown reply",
        "normal",
        "",
        [],
        response_worker=current_worker,
        operation_id=operation_id,
    )
    bridge._on_error(
        "synthetic shutdown error",
        response_worker=current_worker,
        operation_id=operation_id,
    )

    assert messages == []
    assert pending == []


def test_reply_queue_drains_once_only_after_worker_finished():
    _ensure_qt_app()
    bridge = WebBridge()
    worker = _Worker(running=True)
    operation_id = _begin_normal_reply(bridge, worker)
    drained = []
    bridge._drain_promise_queue_if_idle = lambda: drained.append("promise")
    bridge._drain_proactive_queue_if_idle = lambda: drained.append("proactive")

    bridge._on_response_ready(
        "Synthetic complete reply",
        "normal",
        "",
        [],
        response_worker=worker,
        operation_id=operation_id,
    )

    assert bridge.life_record_state.phase == "idle"
    assert drained == []

    worker.running = False
    bridge._on_normal_reply_worker_finished(operation_id, worker)
    bridge._on_normal_reply_worker_finished(operation_id, worker)

    assert drained == ["promise", "proactive"]
    assert bridge.worker is None


def test_duplicate_reply_signal_is_committed_only_once_while_tts_is_pending():
    _ensure_qt_app()
    bridge = WebBridge()
    bridge.enable_tts = True
    bridge.tts_client = object()
    bridge.audio_player = object()
    bridge._play_tts = lambda _text: None
    worker = _Worker(running=True)
    operation_id = _begin_normal_reply(bridge, worker)
    received = []
    bridge.message_received.connect(lambda *args: received.append(args))

    for _ in range(2):
        bridge._on_response_ready(
            "Synthetic duplicate reply",
            "normal",
            "Synthetic spoken text",
            [],
            response_worker=worker,
            operation_id=operation_id,
        )

    assistant_entries = [
        item for item in bridge.conversation_buffer if item[0] == "assistant"
    ]
    assert len(assistant_entries) == 1
    assert received == []

    bridge._on_tts_error("synthetic failure", operation_id=operation_id)

    assert received == [("Synthetic duplicate reply", "normal", "")]
    assert bridge.life_record_state.phase == "idle"


def test_disabled_proactive_reply_releases_normal_operation():
    _ensure_qt_app()
    bridge = WebBridge(settings={"enable_proactive_conversation": False})
    worker = _Worker(running=True)
    operation_id = _begin_normal_reply(bridge, worker)
    bridge._active_proactive_id = "synthetic-proactive-id"
    bridge._active_proactive_signature = "synthetic-signature"

    class _Manager:
        def __init__(self):
            self.deleted = []

        def delete_item(self, item_id):
            self.deleted.append(item_id)

    bridge.proactive_manager = _Manager()

    bridge._on_response_ready(
        "Synthetic disabled proactive reply",
        "normal",
        "",
        [],
        response_worker=worker,
        operation_id=operation_id,
    )

    assert bridge.life_record_state.phase == "idle"
    assert bridge.proactive_manager.deleted == ["synthetic-proactive-id"]
    assert bridge._active_proactive_id is None


class _ConnectSignal:
    def connect(self, _callback):
        return None


class _StartFailingTTSWorker:
    def __init__(self, *_args, **_kwargs):
        self.tts_ready = _ConnectSignal()
        self.error_occurred = _ConnectSignal()

    def start(self):
        raise RuntimeError("synthetic start failure")


@pytest.mark.parametrize("failure_kind", ["constructor", "start"])
def test_tts_worker_start_failure_falls_back_to_text_and_finalizes(monkeypatch, failure_kind):
    _ensure_qt_app()
    bridge = WebBridge()
    bridge.enable_tts = True
    bridge.tts_streaming_enabled = False
    bridge.tts_client = object()
    bridge.audio_player = object()
    worker = _Worker(running=True)
    operation_id = _begin_normal_reply(bridge, worker)
    received = []
    bridge.message_received.connect(lambda *args: received.append(args))

    if failure_kind == "constructor":
        def _raise_constructor(*_args, **_kwargs):
            raise RuntimeError("synthetic constructor failure")

        monkeypatch.setattr(tts, "TTSWorker", _raise_constructor)
    else:
        monkeypatch.setattr(tts, "TTSWorker", _StartFailingTTSWorker)

    bridge._on_response_ready(
        "Synthetic text fallback",
        "normal",
        "Synthetic spoken text",
        [],
        response_worker=worker,
        operation_id=operation_id,
    )

    assert received == [("Synthetic text fallback", "normal", "")]
    assert bridge.pending_response is None
    assert bridge._pending_response_completion is None
    assert bridge.life_record_state.phase == "idle"
    assert bridge.tts_worker is None


def test_streaming_tts_ownership_survives_text_completion_then_rejects_late_chunks():
    _ensure_qt_app()
    bridge = WebBridge()
    worker = object()
    operation_id = 41
    bridge._active_tts_operation = (operation_id, worker)
    bridge._pending_response_completion = None

    bridge._on_tts_stream_format(
        16000,
        1,
        2,
        operation_id=operation_id,
        tts_worker=worker,
    )

    assert bridge._stream_audio_format == (16000, 1, 2)

    bridge._clear_tts_operation(operation_id, worker)
    bridge._on_tts_stream_format(
        24000,
        2,
        2,
        operation_id=operation_id,
        tts_worker=worker,
    )

    assert bridge._stream_audio_format == (16000, 1, 2)


class _RaisingSignal:
    def emit(self, *_args):
        raise RuntimeError("synthetic signal failure")


class _Signal:
    def emit(self, *_args):
        return None


class _RaisingManager:
    def set_status(self, *_args):
        raise RuntimeError("synthetic manager failure")


class _RecordingManager:
    def __init__(self):
        self.calls = []

    def delete_promise(self, *args):
        self.calls.append(("delete_promise", args))

    def set_status(self, *args):
        self.calls.append(("set_status", args))


class _AudioRecorder:
    def __init__(self):
        self.played = []
        self.finished = 0

    def play(self, audio_data):
        self.played.append(audio_data)

    def finish_stream(self):
        self.finished += 1


def test_pending_response_signal_failure_still_clears_and_finalizes():
    state = LifeRecordBridgeState()
    operation_id = state.try_begin_operation("normal_reply")
    assert type(operation_id) is int
    dummy = SimpleNamespace(
        pending_response=("Synthetic pending reply", "normal"),
        pending_token_usage_payload="",
        _pending_response_completion={
            "promise_id": "",
            "proactive_id": "",
            "normal_operation_id": operation_id,
        },
        _is_rerolling=False,
        life_record_state=state,
        worker=_Worker(running=False),
        message_received=_RaisingSignal(),
        token_usage_ready=_Signal(),
        reroll_state_changed=_Signal(),
        _resolve_token_usage_payload=lambda _payload: "{}",
        _emit_gesture_requested=lambda _gesture: None,
    )
    dummy._finish_normal_operation = lambda op: ChatFlowBridgeMixin._finish_normal_operation(dummy, op)
    dummy._finalize_pending_response_completion_if_any = (
        lambda: ChatFlowBridgeMixin._finalize_pending_response_completion_if_any(dummy)
    )

    with pytest.raises(RuntimeError, match="synthetic signal failure"):
        TTSBridgeMixin._flush_pending_response_if_any(dummy)

    assert dummy.pending_response is None
    assert dummy.pending_token_usage_payload == ""
    assert dummy._pending_response_completion is None
    assert state.phase == "idle"


def test_error_finalizer_releases_operation_when_manager_and_signal_fail(capsys):
    state = LifeRecordBridgeState()
    operation_id = state.try_begin_operation("normal_reply")
    assert type(operation_id) is int
    worker = _Worker(running=False)
    dummy = SimpleNamespace(
        life_record_state=state,
        worker=worker,
        _active_promise_id="synthetic-promise-id",
        _active_promise_signature="synthetic-signature",
        _active_proactive_id=None,
        _active_proactive_signature=None,
        promise_manager=_RaisingManager(),
        proactive_manager=None,
        message_received=_RaisingSignal(),
        _is_rerolling=False,
    )
    dummy._finish_normal_operation = lambda op: ChatFlowBridgeMixin._finish_normal_operation(dummy, op)

    ChatFlowBridgeMixin._on_error(
        dummy,
        "synthetic provider failure",
        response_worker=worker,
        operation_id=operation_id,
    )

    assert state.phase == "idle"
    assert dummy._active_promise_id is None
    assert dummy._active_promise_signature is None
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "synthetic manager failure" not in combined
    assert "synthetic signal failure" not in combined
    assert "exception_class=RuntimeError" in combined


def test_response_callback_swallows_local_exception_after_cleanup(monkeypatch, capsys):
    _ensure_qt_app()
    bridge = WebBridge()
    worker = _Worker(running=False)
    operation_id = _begin_normal_reply(bridge, worker)

    def _raise_local_error(*_args, **_kwargs):
        raise RuntimeError("SYNTHETIC-RESPONSE-CALLBACK-SENTINEL")

    monkeypatch.setattr(
        ChatFlowBridgeMixin,
        "_handle_response_ready",
        _raise_local_error,
    )

    bridge._on_response_ready(
        "Synthetic reply",
        "normal",
        "",
        [],
        response_worker=worker,
        operation_id=operation_id,
    )

    assert bridge.life_record_state.phase == "idle"
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "SYNTHETIC-RESPONSE-CALLBACK-SENTINEL" not in combined
    assert "exception_class=RuntimeError" in combined


@pytest.mark.parametrize("callback_name", ["ready", "error", "stream_finished"])
def test_tts_callback_swallows_flush_exception_and_finalizes(
    monkeypatch,
    capsys,
    callback_name,
):
    _ensure_qt_app()
    bridge = WebBridge()
    response_worker = _Worker(running=False)
    operation_id = _begin_normal_reply(bridge, response_worker)
    tts_worker = object()
    bridge.tts_worker = tts_worker
    bridge._active_tts_operation = (operation_id, tts_worker)
    bridge.pending_response = ("Synthetic fallback reply", "normal")
    bridge.pending_token_usage_payload = ""
    bridge._pending_response_completion = {
        "promise_id": "",
        "proactive_id": "",
        "normal_operation_id": operation_id,
    }
    received = []
    bridge.message_received.connect(lambda *args: received.append(args))

    def _raise_callback_error(*_args, **_kwargs):
        raise RuntimeError("SYNTHETIC-TTS-CALLBACK-SENTINEL")

    if callback_name == "ready":
        monkeypatch.setattr(bridge, "_complete_tts_ready", _raise_callback_error)
        bridge._on_tts_ready(
            b"synthetic-audio",
            [],
            operation_id=operation_id,
            tts_worker=tts_worker,
        )
    elif callback_name == "error":
        monkeypatch.setattr(bridge, "_complete_tts_error", _raise_callback_error)
        bridge._on_tts_error(
            "synthetic provider detail",
            operation_id=operation_id,
            tts_worker=tts_worker,
        )
    else:
        monkeypatch.setattr(bridge, "_complete_tts_stream", _raise_callback_error)
        bridge._on_tts_stream_finished(
            operation_id=operation_id,
            tts_worker=tts_worker,
        )

    assert received == [("Synthetic fallback reply", "normal", "")]
    assert bridge.pending_response is None
    assert bridge._pending_response_completion is None
    assert bridge.life_record_state.phase == "idle"
    assert bridge._active_tts_operation is None
    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "SYNTHETIC-TTS-CALLBACK-SENTINEL" not in combined
    assert "synthetic provider detail" not in combined
    assert "exception_class=RuntimeError" in combined


@pytest.mark.parametrize("callback_name", ["ready", "error", "stream_finished"])
def test_tts_callback_during_shutdown_discards_without_external_side_effects(callback_name):
    _ensure_qt_app()
    bridge = WebBridge()
    response_worker = _Worker(running=False)
    operation_id = _begin_normal_reply(bridge, response_worker)
    tts_worker = object()
    bridge.tts_worker = tts_worker
    bridge._active_tts_operation = (operation_id, tts_worker)
    bridge.pending_response = ("Synthetic shutdown reply", "normal")
    bridge.pending_token_usage_payload = "{}"
    bridge._pending_response_completion = {
        "promise_id": "synthetic-promise-id",
        "proactive_id": "synthetic-proactive-id",
        "normal_operation_id": operation_id,
    }
    bridge._active_promise_id = "synthetic-promise-id"
    bridge._active_proactive_id = "synthetic-proactive-id"
    bridge.promise_manager = _RecordingManager()
    bridge.proactive_manager = _RecordingManager()
    bridge.audio_player = _AudioRecorder()
    messages = []
    pending = []
    tokens = []
    drained = []
    bridge.message_received.connect(lambda *args: messages.append(args))
    bridge.request_pending_changed.connect(lambda active: pending.append(bool(active)))
    bridge.token_usage_ready.connect(lambda payload: tokens.append(payload))
    bridge._drain_promise_queue_if_idle = lambda: drained.append("promise")
    bridge._drain_proactive_queue_if_idle = lambda: drained.append("proactive")
    bridge.life_record_state.begin_shutdown()

    if callback_name == "ready":
        bridge._on_tts_ready(
            b"synthetic-audio",
            [],
            operation_id=operation_id,
            tts_worker=tts_worker,
        )
    elif callback_name == "error":
        bridge._on_tts_error(
            "synthetic provider detail",
            operation_id=operation_id,
            tts_worker=tts_worker,
        )
    else:
        bridge._on_tts_stream_finished(
            operation_id=operation_id,
            tts_worker=tts_worker,
        )

    assert messages == []
    assert pending == []
    assert tokens == []
    assert drained == []
    assert bridge.promise_manager.calls == []
    assert bridge.proactive_manager.calls == []
    assert bridge.audio_player.played == []
    assert bridge.audio_player.finished == 0
    assert bridge.pending_response is None
    assert bridge._pending_response_completion is None
    assert bridge._active_tts_operation is None


def test_tts_ready_audio_tail_is_allowed_after_normal_operation_is_idle():
    _ensure_qt_app()
    bridge = WebBridge()
    tts_worker = object()
    operation_id = 73
    bridge.tts_worker = tts_worker
    bridge._active_tts_operation = (operation_id, tts_worker)
    bridge.audio_player = _AudioRecorder()

    bridge._on_tts_ready(
        b"synthetic-audio-tail",
        [],
        operation_id=operation_id,
        tts_worker=tts_worker,
    )

    assert bridge.audio_player.played == [b"synthetic-audio-tail"]
    assert bridge._active_tts_operation is None


def test_start_ai_worker_can_suppress_duplicate_pending_signals(monkeypatch):
    _ensure_qt_app()
    bridge = WebBridge()
    bridge.llm_client = object()
    operation_id = bridge.life_record_state.try_begin_operation("resuming_reply")
    assert type(operation_id) is int
    emitted = []
    bridge.request_pending_stage_changed.connect(lambda stage: emitted.append(("stage", stage)))
    bridge.request_pending_changed.connect(lambda active: emitted.append(("pending", bool(active))))

    class _AIWorker:
        def __init__(self, *_args, **_kwargs):
            self.response_ready = _ConnectSignal()
            self.error_occurred = _ConnectSignal()
            self.finished = _ConnectSignal()

        def isRunning(self):
            return False

        def start(self):
            return None

    monkeypatch.setattr("src.core.bridge_mixins.chat_flow.AIWorker", _AIWorker)

    assert bridge._start_ai_worker("Synthetic request", emit_pending_state=False) is True

    assert emitted == []
    assert bridge.life_record_state.phase == "normal_reply"


def test_resumed_attachment_starts_worker_without_duplicate_pending_signals(monkeypatch):
    _ensure_qt_app()
    bridge = WebBridge()
    bridge.llm_client = object()
    operation_id = bridge.life_record_state.try_begin_operation("resuming_reply")
    assert type(operation_id) is int
    emitted = []
    bridge.request_pending_stage_changed.connect(
        lambda stage: emitted.append(("stage", stage))
    )
    bridge.request_pending_changed.connect(
        lambda active: emitted.append(("pending", bool(active)))
    )
    bridge._emit_request_pending_stage_changed("life_record")
    bridge._emit_request_pending_changed(True)
    bridge._emit_request_pending_stage_changed("thinking")
    expected = list(emitted)

    class _AIWorker:
        def __init__(self, *_args, **_kwargs):
            self.response_ready = _ConnectSignal()
            self.error_occurred = _ConnectSignal()
            self.finished = _ConnectSignal()

        def isRunning(self):
            return False

        def start(self):
            return None

    monkeypatch.setattr(chat_flow, "AIWorker", _AIWorker)
    request = PreparedChatRequest(
        received_at=datetime(2099, 8, 7, 10, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        language="ko",
        mood_snapshot=LifeMoodSnapshot("calm", 0.1, 0.2, 0.3, 0.4, "steady"),
        request_type="attachments",
        message="합성 첨부 재개 요청",
    )

    ChatFlowBridgeMixin._commit_prepared_chat_request(
        bridge,
        request,
        emit_pending_state=False,
    )

    assert emitted == expected
    assert bridge.life_record_state.phase == "normal_reply"
