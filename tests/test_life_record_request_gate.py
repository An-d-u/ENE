from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.core.bridge_mixins import chat_flow as chat_flow_module
from src.core.bridge_mixins.away import AwayNudgeBridgeMixin
from src.core.bridge_mixins.chat_flow import ChatFlowBridgeMixin
from src.core.bridge_mixins.life_records import (
    LifeRecordBridgeMixin,
    PreparedChatRequest,
)
from src.core.bridge_mixins.promise import PromiseBridgeMixin
from src.core.bridge_mixins.proactive import ProactiveBridgeMixin
from src.core.bridge import WebBridge
from src.core.bridge_state import LifeRecordBridgeState
from src.core.life_session_tracker import InactiveStartCandidate
from src.core.local_time import LocalTimeContext


NOW = datetime(2026, 8, 7, 10, 0, tzinfo=timezone.utc)


class _Signal:
    def __init__(self) -> None:
        self.emitted: list[tuple] = []

    def emit(self, *args) -> None:
        self.emitted.append(args)


class _Mood:
    def __init__(self) -> None:
        self.events: list[str] = []

    def get_snapshot(self):
        self.events.append("snapshot")
        return {
            "profile": "synthetic",
            "current_mood": "calm",
            "temporary_state": "steady",
            "valence": 0.1,
            "energy": 0.2,
            "bond": 0.3,
            "stress": 0.4,
            "expression_traits": {"unused": True},
            "updated_at": "2026-08-07T09:00:00+00:00",
        }

    def on_user_message(self, *_args, **_kwargs):
        self.events.append("message")
        return self.get_snapshot()


class _Calendar:
    def __init__(self) -> None:
        self.conversation_count = 0
        self.pending_head_pats = 3

    def increment_conversation_count(self) -> None:
        self.conversation_count += 1

    def get_pending_head_pat_count(self) -> int:
        return self.pending_head_pats

    def drain_pending_head_pat_count(self) -> int:
        count = self.pending_head_pats
        self.pending_head_pats = 0
        return count


class _GateBridge(LifeRecordBridgeMixin):
    def __init__(self, *, enabled: bool = True, minutes: int = 60) -> None:
        context = LocalTimeContext("UTC", ZoneInfo("UTC"), lambda: NOW)
        self.life_record_state = LifeRecordBridgeState(
            candidate=InactiveStartCandidate(
                started_at=NOW - timedelta(minutes=minutes),
                source="graceful_exit",
            ),
            life_records_writable=True,
            time_context=context,
            view_timezone="UTC",
        )
        self.settings = {
            "enable_life_records": enabled,
            "life_record_min_inactive_minutes": 60,
        }
        self.mood_manager = _Mood()
        self.life_record_notice = _Signal()
        self.request_pending_stage_changed = _Signal()
        self.request_pending_changed = _Signal()
        self.world = "# 합성 마을\n\n광장과 공방이 있다."
        self.language_calls = 0
        self.committed: list[PreparedChatRequest] = []
        self.started: list[int] = []

    def _load_life_world_for_gate(self) -> str:
        return self.world

    def _resolve_life_prompt_language(self) -> str:
        self.language_calls += 1
        return "ko"

    def _commit_prepared_chat_request(self, request: PreparedChatRequest) -> None:
        self.committed.append(request)

    def _start_auto_life_record_generation(self, operation_id: int) -> None:
        self.started.append(operation_id)


def test_exact_threshold_stashes_one_private_frozen_request_before_chat_commit() -> None:
    bridge = _GateBridge(minutes=60)

    request = bridge._prepare_chat_request(
        received_at=NOW.replace(microsecond=999999),
        request_type="text",
        message="합성 인사",
        attachments=[{"name": "sample.txt", "nested": {"size": 3}}],
        head_pat_count_before_message=2,
    )
    bridge._dispatch_general_request(request)

    assert request.received_at == NOW
    assert request.language == "ko"
    assert set(vars(request.mood_snapshot)) == {
        "label",
        "valence",
        "energy",
        "bond",
        "stress",
        "short_term_mood",
    }
    assert "합성 인사" not in repr(request)
    assert bridge.language_calls == 1
    assert bridge.life_record_state.auto_decision_completed is True
    assert bridge.life_record_state.pending_request is request
    assert bridge.life_record_state.phase == "auto_generating"
    assert bridge.committed == []
    assert bridge.mood_manager.events == ["snapshot"]
    assert bridge.request_pending_stage_changed.emitted == [("life_record",)]
    assert bridge.request_pending_changed.emitted == [(True,)]
    assert bridge.started == [bridge.life_record_state.operation_id]


def test_skip_decision_commits_once_and_does_not_rearm() -> None:
    bridge = _GateBridge(minutes=59)
    first = bridge._prepare_chat_request(
        received_at=NOW,
        request_type="text",
        message="첫 합성 문장",
    )
    second = bridge._prepare_chat_request(
        received_at=NOW,
        request_type="text",
        message="둘째 합성 문장",
    )

    bridge._dispatch_general_request(first)
    bridge.life_record_state.candidate = InactiveStartCandidate(
        started_at=NOW - timedelta(hours=3),
        source="graceful_exit",
    )
    bridge._dispatch_general_request(second)

    assert bridge.life_record_state.auto_decision_completed is True
    assert bridge.started == []
    assert bridge.committed == [first, second]


def test_empty_world_emits_safe_notice_and_continues_without_lock() -> None:
    bridge = _GateBridge(minutes=90)
    bridge.world = " \n"
    request = bridge._prepare_chat_request(
        received_at=NOW,
        request_type="text",
        message="합성 질문",
    )

    bridge._dispatch_general_request(request)

    assert bridge.life_record_notice.emitted == [("world_empty",)]
    assert bridge.life_record_state.phase == "idle"
    assert bridge.life_record_state.pending_request is None
    assert bridge.started == []
    assert bridge.committed == [request]


def test_busy_arbiter_rejects_without_consuming_pending_or_candidate() -> None:
    bridge = _GateBridge(minutes=90)
    original = bridge._prepare_chat_request(
        received_at=NOW,
        request_type="text",
        message="보류된 합성 요청",
    )
    operation_id = bridge.life_record_state.try_begin_operation(
        "auto_generating",
        pending_request=original,
    )

    before_candidate = bridge.life_record_state.candidate
    assert operation_id is not None
    assert bridge._life_operation_accepts_input() is False
    assert bridge.life_record_state.pending_request is original
    assert bridge.life_record_state.candidate is before_candidate
    assert bridge.life_record_state.auto_decision_completed is False


def test_operation_id_rejects_stale_callbacks_and_pending_is_taken_once() -> None:
    state = LifeRecordBridgeState()
    request = _GateBridge()._prepare_chat_request(
        received_at=NOW,
        request_type="text",
        message="합성 요청",
    )
    operation_id = state.try_begin_operation(
        "auto_generating",
        pending_request=request,
    )

    assert operation_id == 1
    assert state.matches_operation(operation_id, "auto_generating") is True
    assert state.matches_operation(operation_id + 1, "auto_generating") is False
    assert state.take_pending(operation_id + 1) is None
    assert state.take_pending(operation_id) is request
    assert state.take_pending(operation_id) is None


def test_state_rejects_unknown_read_only_reason_and_releases_finished_worker() -> None:
    try:
        LifeRecordBridgeState(read_only_reason="raw-provider-error")
    except ValueError as exc:
        assert str(exc) == "invalid_life_record_read_only_reason"
    else:
        raise AssertionError("알 수 없는 내부 오류 문장을 상태 코드로 보관하면 안 됩니다.")

    state = LifeRecordBridgeState(worker=object())
    operation_id = state.try_begin_operation("manual_regenerating")
    assert operation_id is not None
    assert state.finish_operation(operation_id) is True
    assert state.worker is None


def test_state_repr_hides_pending_life_world_prompt() -> None:
    private_world = "PRIVATE-LIFE-WORLD-SENTINEL"
    private_error = "PRIVATE-WORKER-ERROR-SENTINEL"

    state = LifeRecordBridgeState(
        pending_world_markdown=private_world,
        worker_error=private_error,
    )

    assert private_world not in repr(state)
    assert private_error not in repr(state)
    assert "pending_world_markdown" not in repr(state)
    assert "worker_error" not in repr(state)


def test_busy_text_slot_rejects_before_any_side_effect() -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.calendar_manager = _Calendar()
    bridge.life_record_state.phase = "auto_generating"
    bridge._start_ai_worker = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("worker must not start")
    )
    bridge.send_to_ai("/note 합성 명령")

    assert bridge.calendar_manager.conversation_count == 0
    assert bridge.calendar_manager.pending_head_pats == 3
    assert bridge.conversation_buffer == []
    assert bridge.life_record_state.auto_decision_completed is False


def test_idle_tool_command_captures_clock_but_does_not_consume_opportunity() -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    captured: list[str] = []
    bridge._capture_life_received_at = lambda: captured.append("clock") or NOW
    bridge._handle_note_command = lambda message: message.startswith("/note")

    bridge.send_to_ai("/note 합성 명령")

    assert captured == ["clock"]
    assert bridge.life_record_state.auto_decision_completed is False


def test_first_general_chat_snapshots_mood_before_mood_update() -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.calendar_manager = _Calendar()
    bridge.mood_manager = _Mood()
    bridge.life_record_state.life_records_writable = False
    bridge._start_ai_worker = lambda *_args, **_kwargs: None

    bridge.send_to_ai("합성 인사")

    assert bridge.mood_manager.events[:2] == ["snapshot", "message"]


def test_busy_attachment_slot_rejects_before_json_or_session_side_effects(monkeypatch) -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.life_record_state.phase = "auto_generating"
    original_session = bridge._attachment_session
    monkeypatch.setattr(
        "src.core.bridge_mixins.attachments.json.loads",
        lambda _value: (_ for _ in ()).throw(AssertionError("JSON must not be parsed")),
    )

    bridge.send_to_ai_with_attachments("합성 요청", "[]")

    assert bridge._attachment_session is original_session
    assert bridge._pending_attachment_cache == {}
    assert bridge._message_attachment_records == {}
    assert bridge.conversation_buffer == []
    assert bridge.life_record_state.auto_decision_completed is False


def test_busy_legacy_image_slot_rejects_before_json_side_effects(monkeypatch) -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.life_record_state.phase = "auto_generating"
    parsed = []
    monkeypatch.setattr(
        "src.core.bridge_mixins.attachments.json.loads",
        lambda value: parsed.append(value) or [],
    )

    bridge.send_to_ai_with_images("합성 요청", "[]")

    assert bridge.conversation_buffer == []
    assert bridge.life_record_state.auto_decision_completed is False
    assert parsed == []


def test_attachment_slot_captures_clock_once_and_commits_deep_snapshot(monkeypatch) -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.life_record_state.life_records_writable = False
    bridge._capture_life_received_at = lambda: NOW
    bridge._start_ai_worker = lambda *_args, **_kwargs: None
    captured: list[list[dict]] = []

    def resolve(items):
        captured.append(items)
        items[0]["nested"]["value"] = 99
        return [{
            "id": "synthetic-file",
            "name": "sample.txt",
            "type": "text/plain",
            "category": "document",
            "status": "ready",
            "extractedText": "Synthetic document.",
            "tokenEstimate": 3,
        }]

    bridge._resolve_prepared_attachments = resolve
    bridge.send_to_ai_with_attachments(
        "합성 요청",
        '[{"id":"synthetic-file","nested":{"value":1}}]',
    )

    assert captured[0][0]["nested"]["value"] == 99
    assert "2026-08-07 10:00" in bridge._last_request_payload["message_with_time"]
    assert bridge.conversation_buffer[0][2] == "2026-08-07 10:00"


def test_prepared_text_language_survives_setting_change_in_all_prompt_labels(monkeypatch) -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.settings = {"ui_language": "en"}
    bridge.life_record_state.life_records_writable = False
    bridge.conversation_buffer = [("assistant", "Synthetic earlier reply.", "2026-08-07 09:50")]
    bridge._start_ai_worker = lambda *_args, **_kwargs: None
    request = bridge._prepare_chat_request(
        received_at=NOW,
        request_type="text",
        message="Synthetic current request.",
    )
    bridge.settings["ui_language"] = "ja"
    monkeypatch.setattr(
        chat_flow_module,
        "resolve_prompt_language",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("prepared commit must not resolve language again")
        ),
    )

    bridge._dispatch_general_request(request)

    payload = bridge._last_request_payload
    assert payload["message_with_time"].startswith("[Current Time: 2026-08-07 10:00]")
    assert "[Message Time: 2026-08-07 09:50]" in payload["recent_memory_context"]
    assert "[ENE] Synthetic earlier reply." in payload["recent_memory_context"]
    assert "[Current User Message] Synthetic current request." in payload["memory_search_text"]
    assert "現在" not in payload["memory_search_text"]


def test_prepared_attachment_language_is_forwarded_to_memory_inputs() -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge.settings = {"ui_language": "en"}
    bridge.life_record_state.life_records_writable = False
    bridge._start_ai_worker = lambda *_args, **_kwargs: None
    bridge._resolve_prepared_attachments = lambda _items: []
    languages = []

    def build_inputs(message, timestamp, *, language=None):
        languages.append(language)
        return {
            "memory_search_text": message,
            "latest_user_message": message,
            "recent_context_text": timestamp,
        }

    bridge._build_memory_search_inputs = build_inputs
    request = bridge._prepare_chat_request(
        received_at=NOW,
        request_type="attachments",
        message="Synthetic attachment request.",
        attachments=[],
    )
    bridge.settings["ui_language"] = "ja"

    bridge._dispatch_general_request(request)

    assert languages == ["en"]


@pytest.mark.parametrize(
    "phase",
    [
        "auto_generating",
        "resuming_reply",
        "normal_reply",
        "manual_regenerating",
        "shutting_down",
    ],
)
@pytest.mark.parametrize("entrypoint", ["preview", "delete"])
def test_busy_attachment_management_slots_have_zero_side_effects(
    monkeypatch,
    phase,
    entrypoint,
) -> None:
    bridge = WebBridge()
    bridge.life_record_state.phase = phase
    bridge._message_attachment_records = {
        "synthetic-message": {
            "attachments": [{
                "id": "synthetic-image",
                "category": "image",
                "deleted": False,
                "dataUrl": "data:image/png;base64,synthetic",
            }]
        }
    }
    original_records = bridge._message_attachment_records
    parsed = []
    previews = []
    bridge.attachment_preview_ready.connect(previews.append)
    monkeypatch.setattr(
        "src.core.bridge_mixins.attachments.json.loads",
        lambda value: parsed.append(value) or [],
    )

    if entrypoint == "preview":
        bridge.preview_attachments("[]")
    else:
        bridge.delete_message_attachment("synthetic-message", "synthetic-image")

    item = original_records["synthetic-message"]["attachments"][0]
    assert parsed == []
    assert item["deleted"] is False
    assert item["dataUrl"] == "data:image/png;base64,synthetic"
    assert bridge._pending_attachment_cache == {}
    assert bridge.conversation_buffer == []
    assert previews == []


@pytest.mark.parametrize("method_name,args", [
    ("reroll_last_response", ()),
    ("edit_last_user_message", ("수정된 합성 요청",)),
])
def test_busy_retry_entrypoints_reject_before_rollback(method_name, args) -> None:
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge._last_request_payload = {"type": "text", "message_with_time": "synthetic"}
    bridge.life_record_state.phase = "auto_generating"
    bridge._rollback_last_turn_pair_for_retry = lambda: (_ for _ in ()).throw(
        AssertionError("rollback must not run")
    )

    getattr(bridge, method_name)(*args)

    assert bridge._last_request_payload == {
        "type": "text",
        "message_with_time": "synthetic",
    }


class _WorkerSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in list(self.callbacks):
            callback(*args)


class _Worker:
    def __init__(self, *_args, **_kwargs) -> None:
        self.response_ready = _WorkerSignal()
        self.error_occurred = _WorkerSignal()
        self.finished = _WorkerSignal()
        self.started = False

    def start(self) -> None:
        self.started = True

    def isRunning(self) -> bool:
        return self.started

    def wait(self) -> None:
        raise AssertionError("GUI thread must not wait")


def test_general_worker_keeps_normal_reply_until_visible_response_finalizer(monkeypatch) -> None:
    monkeypatch.setattr(chat_flow_module, "AIWorker", _Worker)
    state = LifeRecordBridgeState()
    dummy = SimpleNamespace(
        life_record_state=state,
        worker=None,
        llm_client=object(),
        _with_ene_thought_context=lambda value: value,
        _with_tts_output_reminder=lambda value: value,
        _emit_request_pending_stage_changed=lambda _value: None,
        _emit_request_pending_changed=lambda _value: None,
        _on_response_ready=lambda *_args, **_kwargs: None,
        _on_error=lambda *_args, **_kwargs: None,
        _drain_queues_after_worker_finished=lambda: None,
    )
    dummy._begin_normal_reply_operation = lambda: (
        ChatFlowBridgeMixin._begin_normal_reply_operation(dummy)
    )
    dummy._on_normal_reply_worker_finished = lambda operation_id, worker: (
        ChatFlowBridgeMixin._on_normal_reply_worker_finished(dummy, operation_id, worker)
    )
    dummy._finish_normal_operation = lambda operation_id: (
        ChatFlowBridgeMixin._finish_normal_operation(dummy, operation_id)
    )
    dummy._connect_worker_finished_drain = lambda operation_id=None: (
        ChatFlowBridgeMixin._connect_worker_finished_drain(dummy, operation_id)
    )

    assert ChatFlowBridgeMixin._start_ai_worker(dummy, "synthetic") is True
    operation_id = state.operation_id
    assert state.matches_operation(operation_id, "normal_reply") is True

    dummy.worker.finished.emit()

    assert state.matches_operation(operation_id, "normal_reply") is True
    dummy._finish_normal_operation(operation_id)
    assert state.phase == "idle"


@pytest.mark.parametrize("method_name,args", [
    ("_start_diary_worker", ("합성 일기", "synthetic")),
    ("_start_note_worker", ("합성 노트", "synthetic")),
])
def test_tool_worker_construction_failure_releases_normal_reply(
    monkeypatch,
    method_name,
    args,
) -> None:
    class FailingWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            raise RuntimeError("synthetic worker construction failure")

    monkeypatch.setattr(chat_flow_module, "AIWorker", FailingWorker)
    state = LifeRecordBridgeState()
    dummy = SimpleNamespace(
        life_record_state=state,
        worker=None,
        llm_client=object(),
        diary_service=object(),
        note_service=object(),
        obsidian_manager=object(),
    )

    with pytest.raises(RuntimeError, match="synthetic worker construction failure"):
        getattr(ChatFlowBridgeMixin, method_name)(dummy, *args)

    assert state.phase == "idle"


@pytest.mark.parametrize("flow", ["chat", "diary", "note"])
@pytest.mark.parametrize("failure_stage", ["constructor", "start"])
def test_worker_start_failure_restores_phase_pending_stage_and_reroll(
    monkeypatch,
    flow,
    failure_stage,
) -> None:
    class FailingWorker:
        def __init__(self, *_args, **_kwargs) -> None:
            if failure_stage == "constructor":
                raise RuntimeError("synthetic constructor failure")
            self.response_ready = _WorkerSignal()
            self.error_occurred = _WorkerSignal()
            self.finished = _WorkerSignal()

        def start(self) -> None:
            raise RuntimeError("synthetic start failure")

        def isRunning(self) -> bool:
            return False

    monkeypatch.setattr(chat_flow_module, "AIWorker", FailingWorker)
    bridge = WebBridge()
    bridge.llm_client = object()
    bridge._with_ene_thought_context = lambda value: value
    bridge._with_tts_output_reminder = lambda value: value
    bridge._is_rerolling = True
    stages = []
    pending = []
    reroll = []
    bridge.request_pending_stage_changed.connect(stages.append)
    bridge.request_pending_changed.connect(pending.append)
    bridge.reroll_state_changed.connect(reroll.append)

    with pytest.raises(RuntimeError, match="synthetic"):
        if flow == "chat":
            bridge._start_ai_worker("synthetic")
        elif flow == "diary":
            bridge._start_diary_worker("synthetic diary", "synthetic")
        else:
            bridge._start_note_worker("synthetic note", "synthetic")

    assert bridge.life_record_state.phase == "idle"
    assert bridge.life_record_state.pending_request is None
    assert bridge._is_rerolling is False
    assert stages[-1] == "thinking"
    assert pending[-1] is False
    assert reroll[-1] is False


class _StatusManager:
    def __init__(self) -> None:
        self.calls = []

    def set_status(self, *args) -> None:
        self.calls.append(args)


def test_busy_auto_entrypoints_have_zero_queue_status_and_capture_side_effects() -> None:
    promise_manager = _StatusManager()
    promise_started = []
    promise = SimpleNamespace(
        life_record_state=LifeRecordBridgeState(phase="auto_generating"),
        worker=None,
        promise_manager=promise_manager,
        promise_run_queue=[],
        _should_suppress_duplicate_promise_fire=lambda _payload: False,
        _start_promise_ai_worker=lambda payload: promise_started.append(payload),
        _life_operation_accepts_input=lambda: False,
    )
    PromiseBridgeMixin._enqueue_due_promise(promise, {"id": "synthetic-promise"})

    proactive_manager = _StatusManager()
    proactive_started = []
    proactive = SimpleNamespace(
        life_record_state=LifeRecordBridgeState(phase="auto_generating"),
        worker=None,
        proactive_manager=proactive_manager,
        proactive_run_queue=[],
        _should_suppress_duplicate_proactive_fire=lambda _payload: False,
        _start_proactive_ai_worker=lambda payload: proactive_started.append(payload),
        _life_operation_accepts_input=lambda: False,
    )
    ProactiveBridgeMixin._enqueue_due_proactive_conversation(
        proactive,
        {"id": "synthetic-proactive"},
    )

    away_started = []
    away = SimpleNamespace(
        enable_away_nudge=True,
        away_check_in_progress=False,
        user_message_count=1,
        last_user_message_at=NOW - timedelta(hours=2),
        worker=None,
        _life_operation_accepts_input=lambda: False,
        _start_away_capture_pipeline=lambda: away_started.append("capture"),
    )
    AwayNudgeBridgeMixin._check_away_nudge_condition(away)

    assert promise.promise_run_queue == []
    assert promise_manager.calls == []
    assert promise_started == []
    assert proactive.proactive_run_queue == []
    assert proactive_manager.calls == []
    assert proactive_started == []
    assert away_started == []
