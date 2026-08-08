from __future__ import annotations

from datetime import datetime, timedelta, timezone
from itertools import pairwise
import json
from types import MethodType, SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from PyQt6.QtCore import QCoreApplication

from src.ai.life_record_manager import LifeRecordManager
from src.ai.life_record_types import (
    create_life_record,
    parse_and_validate_life_record_output,
    stable_life_record_id,
)
from src.ai.response_protocol import OneShotTokenUsage, ResponseStatus
from src.core.app_paths import save_json_data
from src.core.bridge import WebBridge
from src.core.bridge_state import LifeRecordBridgeState
from src.core.bridge_workers import LifeRecordWorkerResult
from src.core.life_session_tracker import AppSessionTracker, InactiveStartCandidate
from src.core.local_time import LocalTimeContext


SEOUL = ZoneInfo("Asia/Seoul")
STOPPED_AT = datetime(2099, 8, 6, 23, 0, tzinfo=SEOUL)
RETURNED_AT = datetime(2099, 8, 7, 10, 0, tzinfo=SEOUL)


class _Signal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class _LifeWorker:
    instances: list[_LifeWorker] = []

    def __init__(self, llm_client, request) -> None:
        self.llm_client = llm_client
        self.request = request
        self.result_ready = _Signal()
        self.error_occurred = _Signal()
        self.finished = _Signal()
        self.started = False
        self.interrupted = False
        type(self).instances.append(self)

    def start(self) -> None:
        self.started = True

    def requestInterruption(self) -> None:
        self.interrupted = True

    def isInterruptionRequested(self) -> bool:
        return self.interrupted


class _Profile:
    def export_life_record_profile(self, max_facts=10):
        assert max_facts == 3
        return {
            "ene_identity": {"identity": ("합성 마을의 기록 안내자",)},
            "relationship_tone": ("방문객에게 차분하게 인사한다.",),
            "profile_facts": (
                {"category": "habit", "content": "온실의 식물을 살핀다."},
            ),
        }


class _Client:
    def __init__(self, manager: LifeRecordManager) -> None:
        self.life_record_manager = manager
        self.rollback_calls = 0

    def rollback_last_assistant_turn(self) -> bool:
        self.rollback_calls += 1
        return True


@pytest.fixture(autouse=True)
def _isolated_runtime(monkeypatch, tmp_path):
    runtime_root = tmp_path / "runtime"
    bundle_root = tmp_path / "bundle"
    (bundle_root / "prompts" / "defaults").mkdir(parents=True)
    monkeypatch.setenv("ENE_USER_DATA_DIR", str(runtime_root))
    monkeypatch.setenv("ENE_BUNDLE_DIR", str(bundle_root))
    app = QCoreApplication.instance() or QCoreApplication([])
    _LifeWorker.instances.clear()
    yield app
    app.processEvents()
    _LifeWorker.instances.clear()


def _process_deferred_life_finalizers() -> None:
    app = QCoreApplication.instance()
    assert app is not None
    app.processEvents()


def _time_context(now: datetime = RETURNED_AT) -> LocalTimeContext:
    return LocalTimeContext("Asia/Seoul", SEOUL, lambda: now)


def _seed_session(path, source: str) -> None:
    stopped = source == "graceful_exit"
    save_json_data(
        path,
        {
            "version": 1,
            "session_id": str(uuid4()),
            "status": "stopped" if stopped else "running",
            "started_at": (STOPPED_AT - timedelta(hours=2)).isoformat(),
            "last_seen_at": STOPPED_AT.isoformat(),
            "stopped_at": STOPPED_AT.isoformat() if stopped else None,
        },
    )


def _output(start: datetime = STOPPED_AT, end: datetime = RETURNED_AT, *, suffix="v1"):
    points = (
        start,
        datetime(2099, 8, 7, 3, 0, tzinfo=SEOUL),
        datetime(2099, 8, 7, 7, 0, tzinfo=SEOUL),
        datetime(2099, 8, 7, 8, 30, tzinfo=SEOUL),
        end,
    )
    entries = [
        {
            "started_at": left.isoformat(),
            "ended_at": right.isoformat(),
            "place": f"합성 장소 {index}",
            "activity": f"중립적인 합성 활동 {suffix}-{index}를 했다.",
        }
        for index, (left, right) in enumerate(pairwise(points), start=1)
    ]
    return parse_and_validate_life_record_output(
        json.dumps(
            {
                "entries": entries,
                "ending_state": {
                    "place": "합성 장소 4",
                    "summary": f"합성 활동 {suffix}를 마쳤다.",
                },
            },
            ensure_ascii=False,
        ),
        inactive_started_at=start,
        returned_at=end,
        timezone_name="Asia/Seoul",
    )


def _old_record():
    start = datetime(2099, 8, 5, 20, 0, tzinfo=SEOUL)
    end = datetime(2099, 8, 5, 21, 0, tzinfo=SEOUL)
    return create_life_record(
        id=stable_life_record_id(start, end),
        inactive_started_at=start,
        returned_at=end,
        created_at=end,
        updated_at=end,
        revision=1,
        timezone="Asia/Seoul",
        inactive_start_source="graceful_exit",
        mood_snapshot={
            "label": "calm",
            "valence": 0.0,
            "energy": 0.0,
            "bond": 0.0,
            "stress": 0.0,
            "short_term_mood": "steady",
        },
        entries=[
            {
                "started_at": start,
                "ended_at": end,
                "place": "합성 기록실",
                "activity": "이전 합성 자료를 정리했다.",
            }
        ],
        ending_state={"place": "합성 기록실", "summary": "정리를 마쳤다."},
    )


def _bridge(monkeypatch, data_root, candidate, *, now: datetime = RETURNED_AT):
    settings = SimpleNamespace(
        config={
            "enable_life_records": True,
            "life_record_min_inactive_minutes": 60,
            "max_profile_facts_in_context": 3,
            "ui_language": "ko",
            "assistant_display_name": "루미",
            "user_address_name": "여행자",
        }
    )
    bridge = WebBridge(settings=settings)
    manager = LifeRecordManager(
        data_root / "life_records.json",
        time_context=_time_context(now),
    )
    bridge.life_record_manager = manager
    bridge.llm_client = _Client(manager)
    bridge.ene_profile = _Profile()
    bridge.life_record_state = LifeRecordBridgeState(
        candidate=candidate,
        life_records_writable=True,
        time_context=_time_context(now),
        view_timezone="Asia/Seoul",
    )
    bridge._capture_life_received_at = lambda: now
    bridge._load_life_world_for_gate = lambda: (
        "# 합성 마을\n\n- 기록실\n- 온실\n- 작은 광장"
    )
    bridge._resolve_prepared_attachments = lambda _items: [
        {
            "id": "synthetic-file",
            "name": "sample.txt",
            "type": "text/plain",
            "category": "document",
            "status": "ready",
            "extractedText": "Synthetic document content.",
            "tokenEstimate": 3,
        }
    ]
    bridge._handle_obs_command = lambda _message: False
    bridge._handle_diary_command = lambda _message: False
    bridge.command_messages = []
    bridge._handle_note_command = lambda message: (
        bridge.command_messages.append(message) or True
        if message.startswith("/note")
        else False
    )
    bridge.normal_worker_calls = []
    bridge.queue_drains = 0

    def start_normal(self, *args, **kwargs):
        self.normal_worker_calls.append((args, kwargs))
        return self._begin_normal_reply_operation() is not None

    def drain_queues(self):
        self.queue_drains += 1

    bridge._start_ai_worker = MethodType(start_normal, bridge)
    bridge._drain_queues_after_worker_finished = MethodType(drain_queues, bridge)
    monkeypatch.setattr("src.core.bridge_mixins.life_records.LifeRecordWorker", _LifeWorker)
    return bridge, manager


def _complete_worker(worker: _LifeWorker, output, *, order="result_finished") -> None:
    operation_id = worker.request.operation_id
    result = LifeRecordWorkerResult(
        operation_id=operation_id,
        output=output,
        status=ResponseStatus.COMPLETE,
        token_usage=OneShotTokenUsage(7, 5, 12),
        attempt_count=1,
    )
    if order == "result_finished":
        worker.result_ready.emit(operation_id, result)
        worker.finished.emit()
    else:
        worker.finished.emit()
        worker.result_ready.emit(operation_id, result)


@pytest.mark.parametrize(
    ("source", "first_request"),
    [
        ("graceful_exit", "text"),
        ("heartbeat_recovery", "attachments"),
    ],
)
def test_recovered_first_chat_covers_exact_eleven_hours_without_gaps(
    monkeypatch, tmp_path, source, first_request
):
    state_path = tmp_path / source / "life_session_state.json"
    _seed_session(state_path, source)
    tracker = AppSessionTracker(state_path, time_context=_time_context())
    candidate = tracker.start_session()
    try:
        assert candidate is not None
        assert candidate.source == source
        assert candidate.started_at == STOPPED_AT
        bridge, manager = _bridge(monkeypatch, state_path.parent, candidate)

        bridge.send_to_ai("/note synthetic-command")
        assert bridge.life_record_state.auto_decision_completed is False
        assert bridge.command_messages == ["/note synthetic-command"]

        if first_request == "text":
            bridge.send_to_ai("합성 복귀 인사")
        else:
            bridge.send_to_ai_with_attachments(
                "합성 첨부 확인",
                json.dumps([{"id": "synthetic-file", "name": "sample.txt"}]),
            )
        worker = _LifeWorker.instances[-1]
        assert worker.started is True
        assert worker.request.inactive_started_at == STOPPED_AT
        assert worker.request.returned_at == RETURNED_AT
        assert "합성 복귀 인사" not in worker.request.prompt
        assert "합성 첨부 확인" not in worker.request.prompt
        assert "sample.txt" not in worker.request.prompt

        _complete_worker(worker, _output())
        _process_deferred_life_finalizers()

        record = manager.latest()
        assert record is not None
        assert record.inactive_started_at == STOPPED_AT
        assert record.returned_at == RETURNED_AT
        assert (
            record.returned_at.astimezone(timezone.utc)
            - record.inactive_started_at.astimezone(timezone.utc)
            == timedelta(hours=11)
        )
        assert record.entries[0].started_at == STOPPED_AT
        assert record.entries[-1].ended_at == RETURNED_AT
        assert all(
            left.ended_at == right.started_at
            for left, right in pairwise(record.entries)
        )
        assert len(bridge.normal_worker_calls) == 1
        normal_args, normal_kwargs = bridge.normal_worker_calls[0]
        assert normal_kwargs["include_life_record_context"] is True
        assert normal_kwargs["prior_token_usage"] == {
            "input_tokens": 7,
            "output_tokens": 5,
            "total_tokens": 12,
        }
        assert normal_kwargs["emit_pending_state"] is False
        assert bridge._last_request_payload["type"] == first_request
        assert bridge.conversation_buffer[-1][0] == "user"
        assert len(normal_args) == (1 if first_request == "text" else 2)

        payloads = []
        bridge.life_record_items_updated.connect(payloads.append)
        bridge.request_life_records_for_date("2099-08-06", "query-previous")
        bridge.request_life_records_for_date("2099-08-07", "query-current")
        queried = [json.loads(payload) for payload in payloads[-2:]]
        assert [[item["id"] for item in payload["records"]] for payload in queried] == [
            [record.id],
            [record.id],
        ]
    finally:
        tracker.release_lease()


def test_generation_failure_falls_back_then_reroll_does_not_regenerate(
    monkeypatch, tmp_path
):
    bridge, manager = _bridge(
        monkeypatch,
        tmp_path,
        InactiveStartCandidate(STOPPED_AT, "graceful_exit"),
    )
    previous = _old_record()
    assert manager.add(previous)
    notices = []
    bridge.life_record_notice.connect(notices.append)

    bridge.send_to_ai("합성 복귀 질문")
    worker = _LifeWorker.instances[-1]
    operation_id = worker.request.operation_id
    worker.error_occurred.emit(
        operation_id,
        LifeRecordWorkerResult(
            operation_id=operation_id,
            output=None,
            status=None,
            token_usage=OneShotTokenUsage(None, None, None),
            attempt_count=1,
            error_code="synthetic_failure",
        ),
    )
    worker.finished.emit()
    _process_deferred_life_finalizers()

    assert manager.latest() == previous
    assert notices == ["generation_failed"]
    assert len(bridge.normal_worker_calls) == 1
    assert bridge.normal_worker_calls[0][1]["include_life_record_context"] is True
    life_worker_count = len(_LifeWorker.instances)

    bridge.life_record_state.finish_operation(bridge.life_record_state.operation_id)
    bridge._last_request_payload = {
        "type": "text",
        "message_with_time": "[합성 시각] 합성 복귀 질문",
        "memory_search_text": "합성 복귀 질문",
        "latest_user_message": "합성 복귀 질문",
        "recent_memory_context": "",
        "include_life_record_context": True,
    }
    bridge.conversation_buffer = [
        ("user", "합성 복귀 질문", "2099-08-07 10:00"),
        ("assistant", "합성 일반 답변", "2099-08-07 10:00"),
    ]
    bridge._delete_tracked_promises_for_retry = lambda: None
    bridge._delete_tracked_proactive_for_retry = lambda: None
    bridge.reroll_last_response()

    assert len(_LifeWorker.instances) == life_worker_count
    assert len(bridge.normal_worker_calls) == 2
    assert bridge.normal_worker_calls[-1][1]["include_life_record_context"] is True


@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_manual_regeneration_replaces_only_after_success(
    monkeypatch, tmp_path, outcome
):
    bridge, manager = _bridge(
        monkeypatch,
        tmp_path,
        InactiveStartCandidate(STOPPED_AT, "graceful_exit"),
        now=RETURNED_AT + timedelta(minutes=5),
    )
    original = create_life_record(
        id=stable_life_record_id(STOPPED_AT, RETURNED_AT),
        inactive_started_at=STOPPED_AT,
        returned_at=RETURNED_AT,
        created_at=RETURNED_AT,
        updated_at=RETURNED_AT,
        revision=1,
        timezone="Asia/Seoul",
        inactive_start_source="graceful_exit",
        mood_snapshot={
            "label": "calm",
            "valence": 0.0,
            "energy": 0.0,
            "bond": 0.0,
            "stress": 0.0,
            "short_term_mood": "steady",
        },
        entries=[
            {
                "started_at": STOPPED_AT,
                "ended_at": RETURNED_AT,
                "place": "합성 기록실",
                "activity": "원본 합성 일정을 보냈다.",
            }
        ],
        ending_state={"place": "합성 기록실", "summary": "원본을 마쳤다."},
    )
    assert manager.add(original)

    bridge.regenerate_latest_life_record(original.id)
    worker = _LifeWorker.instances[-1]
    operation_id = worker.request.operation_id
    if outcome == "success":
        _complete_worker(worker, _output(suffix="regenerated"))
    else:
        worker.error_occurred.emit(
            operation_id,
            LifeRecordWorkerResult(
                operation_id=operation_id,
                output=None,
                status=None,
                token_usage=OneShotTokenUsage(None, None, None),
                attempt_count=1,
                error_code="synthetic_failure",
            ),
        )
        worker.finished.emit()
    _process_deferred_life_finalizers()

    current = LifeRecordManager(tmp_path / "life_records.json").latest()
    assert current is not None
    assert current.id == original.id
    assert current.created_at == original.created_at
    assert current.inactive_started_at == original.inactive_started_at
    assert current.returned_at == original.returned_at
    if outcome == "success":
        assert current.revision == 2
        assert current.entries[0].activity != original.entries[0].activity
    else:
        assert current == original


def test_busy_auto_and_manual_operations_reject_competing_inputs_and_queue(
    monkeypatch, tmp_path
):
    bridge, manager = _bridge(
        monkeypatch,
        tmp_path,
        InactiveStartCandidate(STOPPED_AT, "graceful_exit"),
    )
    bridge.send_to_ai("첫 합성 요청")
    assert bridge.life_record_state.phase == "auto_generating"
    first_worker = _LifeWorker.instances[-1]

    bridge.send_to_ai("두 번째 합성 요청")
    bridge.send_to_ai_with_attachments("두 번째 합성 첨부", "not-json")
    bridge._start_proactive_ai_worker = lambda _payload: (_ for _ in ()).throw(
        AssertionError("자동 queue는 생활 기록 잠금 중 시작되면 안 됩니다.")
    )
    bridge.proactive_run_queue = []
    bridge._enqueue_due_proactive_conversation({"id": "synthetic-proactive"})

    assert _LifeWorker.instances == [first_worker]
    assert bridge.normal_worker_calls == []
    assert bridge.command_messages == []
    assert bridge.proactive_run_queue == []

    _complete_worker(first_worker, _output())
    _process_deferred_life_finalizers()
    bridge.life_record_state.finish_operation(bridge.life_record_state.operation_id)
    record = manager.latest()
    assert record is not None

    bridge.regenerate_latest_life_record(record.id)
    manual_worker = _LifeWorker.instances[-1]
    bridge.send_to_ai("수동 재생성 중 합성 요청")
    assert _LifeWorker.instances[-1] is manual_worker
    assert len(bridge.normal_worker_calls) == 1

    bridge.begin_shutdown()
    _process_deferred_life_finalizers()
    bridge.life_record_state = LifeRecordBridgeState(
        auto_decision_completed=True,
        life_records_writable=True,
        time_context=_time_context(),
        view_timezone="Asia/Seoul",
        phase="normal_reply",
    )
    before = len(_LifeWorker.instances)
    bridge.regenerate_latest_life_record(record.id)
    assert len(_LifeWorker.instances) == before


@pytest.mark.parametrize("signal_order", ["result_finished", "finished_result"])
def test_worker_result_and_finished_signal_orders_commit_once(
    monkeypatch, tmp_path, signal_order
):
    bridge, manager = _bridge(
        monkeypatch,
        tmp_path,
        InactiveStartCandidate(STOPPED_AT, "graceful_exit"),
    )
    bridge.send_to_ai("합성 신호 순서 확인")
    worker = _LifeWorker.instances[-1]

    _complete_worker(worker, _output(suffix=signal_order), order=signal_order)
    _process_deferred_life_finalizers()
    worker.finished.emit()
    _process_deferred_life_finalizers()

    assert manager.latest() is not None
    assert len(manager.records) == 1
    assert len(bridge.normal_worker_calls) == 1
