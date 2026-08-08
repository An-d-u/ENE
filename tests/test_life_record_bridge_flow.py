from __future__ import annotations

from datetime import datetime
import json
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.ai.life_record_manager import LifeRecordManager
from src.ai.life_record_types import parse_and_validate_life_record_output
from src.ai.response_protocol import OneShotTokenUsage, ResponseStatus
from src.core.bridge_mixins.life_records import (
    LifeRecordBridgeMixin,
    PreparedChatRequest,
)
from src.core.bridge import WebBridge
from src.core.bridge_state import LifeRecordBridgeState
from src.core.bridge_workers import LifeRecordWorkerResult
from src.core.life_session_tracker import InactiveStartCandidate
from src.core.local_time import resolve_local_time_context


SEOUL = ZoneInfo("Asia/Seoul")
START = datetime(2099, 8, 6, 23, 0, tzinfo=SEOUL)
END = datetime(2099, 8, 7, 10, 0, tzinfo=SEOUL)


class _Signal:
    def __init__(self, events=None, name=""):
        self._callbacks = []
        self.events = events
        self.name = name

    def connect(self, callback):
        self._callbacks.append(callback)

    def emit(self, *args):
        if self.events is not None:
            self.events.append((self.name, *args))
        for callback in tuple(self._callbacks):
            callback(*args)


class _Worker:
    instances = []

    def __init__(self, llm_client, request):
        self.llm_client = llm_client
        self.request = request
        self.result_ready = _Signal()
        self.error_occurred = _Signal()
        self.finished = _Signal()
        self.started = False
        self.interrupted = False
        type(self).instances.append(self)

    def start(self):
        self.started = True

    def requestInterruption(self):
        self.interrupted = True


class _Profile:
    def export_life_record_profile(self, max_facts=10):
        assert max_facts == 3
        return {
            "ene_identity": {"identity": ("합성 마을의 기록 담당자다.",)},
            "relationship_tone": ("방문객을 정중하게 맞이한다.",),
            "profile_facts": ({"category": "habit", "content": "아침 산책을 한다."},),
        }


class _Bridge(LifeRecordBridgeMixin):
    def __init__(self, manager, events):
        self.life_record_state = LifeRecordBridgeState(
            candidate=InactiveStartCandidate(START, "graceful_exit"),
            auto_decision_completed=True,
            life_records_writable=True,
            time_context=resolve_local_time_context("Asia/Seoul").context,
            view_timezone="Asia/Seoul",
        )
        self.life_record_manager = manager
        self.llm_client = SimpleNamespace()
        self.ene_profile = _Profile()
        self.settings = {
            "max_profile_facts_in_context": 3,
            "assistant_display_name": "루미",
            "user_address_name": "여행자",
        }
        self.life_record_notice = _Signal(events, "notice")
        self.life_record_items_updated = _Signal(events, "items")
        self.request_pending_stage_changed = _Signal(events, "stage")
        self.request_pending_changed = _Signal(events, "pending")
        self.commits = []
        self.events = events

    def _commit_prepared_chat_request(self, request, *, emit_pending_state=True):
        self.events.append(("commit", request.message, self.life_record_state.phase))
        self.commits.append(request)
        if emit_pending_state:
            self._emit_life_record_stage("thinking")
            self._emit_life_record_pending(True)
        self.life_record_state.transition_operation(
            self.life_record_state.operation_id, "normal_reply"
        )

    def _defer_life_record_worker_finalization(self, callback):
        callback()


class _DeferredBridge(_Bridge):
    def __init__(self, manager, events):
        super().__init__(manager, events)
        self.deferred_finalizers = []

    def _defer_life_record_worker_finalization(self, callback):
        self.deferred_finalizers.append(callback)

    def flush_life_finalizers(self):
        callbacks = tuple(self.deferred_finalizers)
        self.deferred_finalizers.clear()
        for callback in callbacks:
            callback()


def _prepared(message="합성 복귀 인사"):
    from src.ai.life_record_prompt import LifeMoodSnapshot

    return PreparedChatRequest(
        received_at=END,
        language="ko",
        mood_snapshot=LifeMoodSnapshot("calm", 0.1, 0.2, 0.3, 0.4, "steady"),
        request_type="text",
        message=message,
    )


def _output():
    raw = json.dumps(
        {
            "entries": [
                {
                    "started_at": START.isoformat(),
                    "ended_at": END.isoformat(),
                    "place": "광장",
                    "activity": "밤에는 쉬고 아침에는 산책했다.",
                }
            ],
            "ending_state": {"place": "광장", "summary": "산책을 마쳤다."},
        },
        ensure_ascii=False,
    )
    return parse_and_validate_life_record_output(
        raw,
        inactive_started_at=START,
        returned_at=END,
        timezone_name="Asia/Seoul",
    )


def _begin(bridge):
    request = _prepared()
    operation_id = bridge.life_record_state.try_begin_operation(
        "auto_generating", pending_request=request
    )
    bridge.life_record_state.pending_world_markdown = "# 합성 마을\n- 광장\n- 도서관"
    return operation_id


def test_auto_start_uses_exact_snapshots_and_never_includes_pending_message(
    monkeypatch, tmp_path
):
    events = []
    bridge = _Bridge(LifeRecordManager(tmp_path / "life_records.json"), events)
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)

    bridge._start_auto_life_record_generation(operation_id)

    worker = _Worker.instances[-1]
    assert worker.started is True
    assert bridge.life_record_state.worker is worker
    assert worker.request.inactive_started_at == START
    assert worker.request.returned_at == END
    assert worker.request.timezone == "Asia/Seoul"
    assert "합성 복귀 인사" not in worker.request.prompt
    assert "합성 마을" in worker.request.prompt
    assert "아침 산책을 한다." in worker.request.prompt
    assert "루미" in worker.request.prompt
    assert "여행자" in worker.request.prompt


def test_success_saves_before_update_then_resumes_once_and_accumulates_usage(
    monkeypatch, tmp_path
):
    events = []

    class OrderedManager(LifeRecordManager):
        def add(self, record):
            events.append(("save", record.id))
            return super().add(record)

    manager = OrderedManager(tmp_path / "life_records.json")
    bridge = _Bridge(manager, events)
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge._start_auto_life_record_generation(operation_id)
    worker = _Worker.instances[-1]
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_output(),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(8, 5, 13),
        attempt_count=2,
    )

    worker.result_ready.emit(operation_id, result)
    assert bridge.commits == []
    assert bridge.life_record_state.worker is worker
    worker.finished.emit()

    names = [event[0] for event in events]
    assert (
        names.index("save")
        < names.index("items")
        < names.index("stage")
        < names.index("commit")
    )
    payload = json.loads(next(event[1] for event in events if event[0] == "items"))
    assert payload["record"]["id"] == manager.latest().id
    assert payload["latest_id"] == manager.latest().id
    assert payload["affected_dates"] == ["2099-08-06", "2099-08-07"]
    assert bridge.life_record_state.prior_token_usage == {
        "input_tokens": 8,
        "output_tokens": 5,
        "total_tokens": 13,
    }
    assert bridge.commits == [_prepared()]
    assert bridge.life_record_state.phase == "normal_reply"

    worker.finished.emit()
    worker.result_ready.emit(operation_id, result)
    assert len(bridge.commits) == 1
    assert [event[0] for event in events].count("save") == 1


@pytest.mark.parametrize("terminal_kind", ["result", "error"])
def test_finished_first_defers_until_queued_terminal_signal(
    monkeypatch, tmp_path, terminal_kind
):
    events = []
    manager = LifeRecordManager(tmp_path / "life_records.json")
    bridge = _DeferredBridge(manager, events)
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge._start_auto_life_record_generation(operation_id)
    worker = _Worker.instances[-1]
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_output() if terminal_kind == "result" else None,
        status=ResponseStatus.COMPLETE if terminal_kind == "result" else None,
        token_usage=OneShotTokenUsage(2, 3, 5),
        attempt_count=1,
        error_code=None if terminal_kind == "result" else "generation_failed",
    )

    worker.finished.emit()

    assert bridge.life_record_state.worker is worker
    assert bridge.commits == []
    assert len(bridge.deferred_finalizers) == 1

    signal = worker.result_ready if terminal_kind == "result" else worker.error_occurred
    signal.emit(operation_id, result)
    bridge.flush_life_finalizers()

    assert bridge.life_record_state.worker is None
    assert bridge.commits == [_prepared()]
    if terminal_kind == "result":
        assert manager.latest() is not None
        assert not any(event[:2] == ("notice", "generation_failed") for event in events)
    else:
        assert manager.latest() is None
        assert ("notice", "generation_failed") in events


def test_first_valid_result_cannot_be_overwritten_by_later_malformed_or_error_signal(
    monkeypatch, tmp_path
):
    events = []
    manager = LifeRecordManager(tmp_path / "life_records.json")
    bridge = _DeferredBridge(manager, events)
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge._start_auto_life_record_generation(operation_id)
    worker = _Worker.instances[-1]
    valid = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_output(),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(2, 3, 5),
        attempt_count=1,
    )

    worker.finished.emit()
    worker.result_ready.emit(operation_id, valid)
    worker.result_ready.emit(operation_id, object())
    worker.error_occurred.emit(operation_id, "generation_failed")
    bridge.flush_life_finalizers()

    assert manager.latest() is not None
    assert not any(event[:2] == ("notice", "generation_failed") for event in events)
    assert bridge.commits == [_prepared()]


def test_life_record_resume_emits_exact_stage_and_pending_sequence(
    monkeypatch, tmp_path
):
    events = []
    bridge = _Bridge(LifeRecordManager(tmp_path / "life_records.json"), events)
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge._emit_life_record_stage("life_record")
    bridge._emit_life_record_pending(True)
    bridge._start_auto_life_record_generation(operation_id)
    worker = _Worker.instances[-1]
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_output(),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(2, 3, 5),
        attempt_count=1,
    )

    worker.result_ready.emit(operation_id, result)
    worker.finished.emit()

    assert [event for event in events if event[0] in {"stage", "pending"}] == [
        ("stage", "life_record"),
        ("pending", True),
        ("stage", "thinking"),
    ]


def test_saved_update_uses_current_view_timezone_dates(monkeypatch, tmp_path):
    events = []
    manager = LifeRecordManager(tmp_path / "life_records.json")
    bridge = _Bridge(manager, events)
    bridge.life_record_state.view_timezone = "America/Los_Angeles"
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge._start_auto_life_record_generation(operation_id)
    worker = _Worker.instances[-1]
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_output(),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(1, 1, 2),
        attempt_count=1,
    )
    worker.result_ready.emit(operation_id, result)
    worker.finished.emit()

    payload = json.loads(next(event[1] for event in events if event[0] == "items"))
    assert payload["affected_dates"] == ["2099-08-06"]


def test_public_bridge_declares_life_record_update_signal():
    assert hasattr(WebBridge, "life_record_items_updated")


@pytest.mark.parametrize("failure_kind", ["generation", "save"])
def test_failure_emits_safe_notice_and_resumes_without_replacing_latest(
    monkeypatch, tmp_path, failure_kind
):
    events = []
    manager = LifeRecordManager(tmp_path / "life_records.json")
    bridge = _Bridge(manager, events)
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge._start_auto_life_record_generation(operation_id)
    worker = _Worker.instances[-1]
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_output() if failure_kind == "save" else None,
        status=ResponseStatus.COMPLETE if failure_kind == "save" else None,
        token_usage=OneShotTokenUsage(None, None, None),
        attempt_count=1,
        error_code=None if failure_kind == "save" else "private-provider-detail",
    )
    if failure_kind == "save":
        monkeypatch.setattr(
            manager,
            "add",
            lambda _record: (_ for _ in ()).throw(RuntimeError("비밀 원문")),
        )
        worker.result_ready.emit(operation_id, result)
    else:
        worker.error_occurred.emit(operation_id, result)
    worker.finished.emit()

    assert manager.latest() is None
    assert (
        "notice",
        "save_failed" if failure_kind == "save" else "generation_failed",
    ) in events
    assert bridge.commits == [_prepared()]
    assert "비밀 원문" not in repr(events)


def test_stale_callback_never_saves_emits_or_resumes(monkeypatch, tmp_path):
    events = []
    manager = LifeRecordManager(tmp_path / "life_records.json")
    bridge = _Bridge(manager, events)
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge._start_auto_life_record_generation(operation_id)
    worker = _Worker.instances[-1]
    bridge.life_record_state.begin_shutdown()
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=_output(),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(1, 1, 2),
        attempt_count=1,
    )

    worker.result_ready.emit(operation_id, result)
    worker.finished.emit()

    assert manager.latest() is None
    assert bridge.commits == []
    assert events == []


def test_result_payload_operation_id_must_match_signal_operation(monkeypatch, tmp_path):
    events = []
    manager = LifeRecordManager(tmp_path / "life_records.json")
    bridge = _Bridge(manager, events)
    operation_id = _begin(bridge)
    _Worker.instances.clear()
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _Worker)
    bridge._start_auto_life_record_generation(operation_id)
    worker = _Worker.instances[-1]
    mismatched = LifeRecordWorkerResult(
        operation_id=operation_id + 1,
        output=_output(),
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(1, 1, 2),
        attempt_count=1,
    )

    worker.result_ready.emit(operation_id, mismatched)
    worker.finished.emit()

    assert manager.latest() is None
    assert ("notice", "generation_failed") in events


def _normal_reply_bridge():
    from PyQt6.QtCore import QCoreApplication
    from src.ai.response_protocol import ResponseDeliveryMetadata

    if QCoreApplication.instance() is None:
        QCoreApplication([])
    bridge = WebBridge()
    worker = SimpleNamespace(
        response_metadata=ResponseDeliveryMetadata.empty(),
        isRunning=lambda: False,
    )
    bridge.worker = worker
    operation_id = bridge.life_record_state.try_begin_operation("normal_reply")
    return bridge, worker, operation_id


def test_non_tts_finalizer_releases_pending_and_drains_once_after_message(monkeypatch):
    bridge, worker, operation_id = _normal_reply_bridge()
    events = []
    bridge.message_received.connect(lambda *_args: events.append("message"))
    bridge.request_pending_changed.connect(
        lambda active: events.append(f"pending:{active}")
    )
    monkeypatch.setattr(
        bridge, "_drain_queues_after_worker_finished", lambda: events.append("drain")
    )

    bridge._on_response_ready("합성 답변", "normal", "", [], response_worker=worker)

    assert bridge.life_record_state.phase == "idle"
    assert bridge.life_record_state.operation_id == operation_id
    assert events.count("drain") == 1
    assert (
        events.index("message") < events.index("pending:False") < events.index("drain")
    )


def test_tts_finalizer_keeps_lock_until_text_is_recovered(monkeypatch):
    bridge, worker, operation_id = _normal_reply_bridge()
    events = []
    bridge.enable_tts = True
    bridge.tts_client = object()
    bridge.audio_player = object()
    bridge.message_received.connect(lambda *_args: events.append("message"))
    bridge.request_pending_changed.connect(
        lambda active: events.append(f"pending:{active}")
    )
    monkeypatch.setattr(bridge, "_play_tts", lambda _text: events.append("tts-start"))
    monkeypatch.setattr(
        bridge, "_drain_queues_after_worker_finished", lambda: events.append("drain")
    )

    bridge._on_response_ready(
        "합성 음성 답변", "normal", "읽을 합성 문장", [], response_worker=worker
    )

    assert bridge.life_record_state.phase == "normal_reply"
    assert "pending:False" not in events
    bridge._on_tts_error("private-detail")

    assert bridge.life_record_state.phase == "idle"
    assert bridge.life_record_state.operation_id == operation_id
    assert events.count("drain") == 1
    assert (
        events.index("message") < events.index("pending:False") < events.index("drain")
    )


def test_stale_tts_error_cannot_finalize_newer_normal_operation(monkeypatch):
    bridge, worker, operation_id = _normal_reply_bridge()
    bridge.enable_tts = True
    bridge.tts_client = object()
    bridge.audio_player = object()
    monkeypatch.setattr(bridge, "_play_tts", lambda _text: None)
    bridge._on_response_ready(
        "합성 음성 답변", "normal", "읽을 합성 문장", [], response_worker=worker
    )

    bridge._on_tts_error("tts_error", operation_id=operation_id + 1)

    assert bridge.life_record_state.phase == "normal_reply"
    assert bridge.pending_response is not None
    bridge._on_tts_error("tts_error", operation_id=operation_id)
    assert bridge.life_record_state.phase == "idle"
