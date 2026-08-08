from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from src.core.bridge_mixins.life_records import (
    LifeRecordBridgeMixin,
    PreparedChatRequest,
)
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
