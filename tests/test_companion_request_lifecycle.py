"""준비·TTS·재접속을 지나도 동일 요청의 수락 결과를 보존한다."""

from datetime import datetime, timedelta, timezone
from dataclasses import replace
from zoneinfo import ZoneInfo
from types import SimpleNamespace

import pytest

from src.core.bridge_workers import LifeRecordWorkerResult
from src.core.local_time import LocalTimeContext
from src.core.life_session_tracker import InactiveStartCandidate
from tests.companion_helpers import sample_id
from tests.test_companion_admission import admission, connect, mobile_message  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401


def enable_preparation(bridge):
    now = datetime(2030, 2, 3, 10, tzinfo=timezone.utc)
    state = bridge.life_record_state
    bridge.settings["enable_life_records"] = True
    state.life_records_writable = True
    state.time_context = LocalTimeContext("UTC", ZoneInfo("UTC"), lambda: now)
    state.candidate = InactiveStartCandidate(
        started_at=now - timedelta(hours=2), source="graceful_exit"
    )
    bridge._load_life_world_for_gate = lambda: (
        "# 가상 공간\n\n도형만 존재하는 합성 공간."
    )
    bridge._start_auto_life_record_generation = lambda operation_id: None


def test_preparation_retries_stay_reserved_until_single_commit(admission):
    bridge, _, context, counts = admission
    enable_preparation(bridge)
    message = mobile_message(bridge)
    first = bridge.submit_mobile_text(context, message)
    assert first.state == "reserved"
    assert bridge.submit_mobile_text(context, message) == first
    assert not any(counts.values())
    assert bridge.chat_state.public_transcript.capture().processing.phase == "preparing"
    state = bridge.life_record_state
    state.worker_error = "generation_failed"
    bridge._finalize_life_record_operation(state.operation_id)
    assert bridge.submit_mobile_text(context, message).state == "accepted"
    assert counts["prompt"] == counts["memory"] == counts["conversation"] == 1
    bridge.worker.reply()
    assert bridge.submit_mobile_text(context, message).state == "completed"


def test_reset_during_preparation_prevents_save_and_resume(admission):
    bridge, _, context, counts = admission
    enable_preparation(bridge)
    bridge.submit_mobile_text(context, mobile_message(bridge))
    operation = bridge.life_record_state.operation_id
    bridge.clear_conversation()
    bridge._finalize_life_record_operation(operation)
    assert bridge.worker is None
    assert not any(counts.values())
    assert bridge.life_record_state.phase == "idle"


def test_shutdown_marks_reserved_request_failed_without_user_publication(admission):
    bridge, _, context, counts = admission
    enable_preparation(bridge)
    result = bridge.submit_mobile_text(context, mobile_message(bridge))
    ref = result.request_ref
    bridge.begin_shutdown()
    record = bridge.chat_state.request_ledger.lookup(ref.key)
    assert record.state == "failed" and record.code == "shutdown"
    assert not any(counts.values())
    assert bridge.chat_state.public_transcript.capture().messages == ()


def test_provider_failure_is_terminal_and_does_not_retry_ai(admission):
    bridge, _, context, counts = admission
    message = mobile_message(bridge)
    accepted = bridge.submit_mobile_text(context, message)
    bridge.worker.error_occurred.emit("합성 공급자 오류")
    result = bridge.submit_mobile_text(context, message)
    assert result.state == "failed" and result.message_id == accepted.message_id
    assert counts["prompt"] == 1


def test_tts_wait_keeps_request_accepted_until_text_display(admission):
    bridge, _, context, _ = admission
    bridge.enable_tts = True
    bridge.tts_client = bridge.audio_player = object()
    bridge._play_tts = lambda text: None
    message = mobile_message(bridge)
    bridge.submit_mobile_text(context, message)
    bridge.worker.reply(spoken="가상 음성")
    assert bridge.submit_mobile_text(context, message).state == "accepted"
    bridge._flush_pending_response_if_any()
    assert bridge.submit_mobile_text(context, message).state == "completed"
    assert bridge.chat_state.public_transcript.capture().processing.phase == "idle"


def test_gateway_restart_preserves_pending_request_and_ledger(admission):
    bridge, adapter, context, counts = admission
    enable_preparation(bridge)
    message = mobile_message(bridge)
    bridge.submit_mobile_text(context, message)
    adapter.disable()
    replacement = replace(
        context, gateway_generation=sample_id(501), connection_generation=sample_id(601)
    )
    adapter.configure(
        replacement.gateway_generation, replacement.registration_generation
    )
    connect(adapter, replacement)
    assert bridge.submit_mobile_text(replacement, message).state == "reserved"
    assert (
        bridge.submit_mobile_text(replacement, mobile_message(bridge, number=31)).code
        == "busy"
    )
    state = bridge.life_record_state
    state.worker_error = "generation_failed"
    bridge._finalize_life_record_operation(state.operation_id)
    bridge.worker.reply()
    assert bridge.submit_mobile_text(replacement, message).state == "completed"
    assert counts["prompt"] == 1


def test_reconnect_capture_recovers_pending_request_status(admission):
    bridge, _, context, _ = admission
    message = mobile_message(bridge)
    accepted = bridge.submit_mobile_text(context, message)
    captured = bridge.capture(
        context.registration_generation, (message.fields["request_id"], sample_id(99))
    )
    assert captured.transcript.messages[0].id == accepted.message_id
    assert [item.fields["state"] for item in captured.statuses] == [
        "accepted",
        "unknown",
    ]


def test_preparation_success_saves_once_then_accepts_and_processes_mood_once(admission):
    bridge, _, context, counts = admission
    enable_preparation(bridge)
    message = mobile_message(bridge)
    bridge.submit_mobile_text(context, message)
    state = bridge.life_record_state
    saves = []
    bridge._save_generated_life_record = lambda result: saves.append(result)
    bridge._emit_saved_life_record = lambda record: True
    state.worker_result = LifeRecordWorkerResult(
        state.operation_id, SimpleNamespace(entries=()), None, None, 1
    )
    operation = state.operation_id
    bridge._finalize_life_record_operation(operation)
    bridge._finalize_life_record_operation(operation)
    assert len(saves) == 1
    bridge.worker.reply()
    assert bridge.submit_mobile_text(context, message).state == "completed"
    assert counts["worker"] == counts["memory"] == counts["mood"] == 1


@pytest.mark.parametrize("stage", ["prompt", "preparation"])
def test_exception_before_worker_clears_owned_processing_and_gate(admission, stage):
    bridge, _, context, _ = admission

    def fail(*args, **kwargs):
        raise RuntimeError("합성 로컬 준비 실패")

    if stage == "preparation":
        enable_preparation(bridge)
        bridge._start_auto_life_record_generation = fail
    else:
        bridge._build_general_chat_prompt = fail
    message = mobile_message(bridge)
    result = bridge.submit_mobile_text(context, message)
    assert result.state == "failed"
    assert bridge.life_record_state.phase == "idle"
    assert bridge.chat_state.public_transcript.capture().processing.phase == "idle"
    assert bridge.chat_state.operation_requests == {}
    assert bridge.submit_mobile_text(context, message).state == "failed"


def test_cancelled_preparation_fails_without_resuming_normal_worker(admission):
    bridge, _, context, counts = admission
    enable_preparation(bridge)
    message = mobile_message(bridge)
    bridge.submit_mobile_text(context, message)
    state = bridge.life_record_state
    state.worker_error = "cancelled"
    bridge._finalize_life_record_operation(state.operation_id)
    assert bridge.submit_mobile_text(context, message).state == "failed"
    assert state.phase == "idle"
    assert not any(counts.values())


def test_acceptance_signal_observes_committed_ledger_and_original_message_id(admission):
    bridge, _, context, _ = admission
    results = []

    def record_result(result):
        record = bridge.chat_state.request_ledger.lookup(result.request_ref.key)
        assert record.state == result.state
        results.append(result)

    bridge.companion_admission_result.connect(record_result)
    first = bridge.submit_mobile_text(context, mobile_message(bridge))
    bridge.worker.reply()
    assert [result.state for result in results] == ["accepted", "completed"]
    assert all(result.message_id == first.message_id for result in results)


def test_completion_callback_cannot_clear_processing_for_new_request(admission):
    bridge, _, context, _ = admission
    bridge.enable_tts = True
    bridge.tts_client = bridge.audio_player = object()
    bridge._play_tts = lambda text: None
    bridge.submit_mobile_text(context, mobile_message(bridge))
    bridge.worker.reply(spoken="가상 음성")
    next_message = mobile_message(bridge, number=31)
    new_results = []
    pending_values = []
    bridge.request_pending_changed.connect(pending_values.append)

    def submit_next(result):
        if result.state == "completed":
            new_results.append(bridge.submit_mobile_text(context, next_message))

    bridge.companion_admission_result.connect(submit_next)
    bridge._flush_pending_response_if_any()
    assert len(new_results) == 1 and new_results[0].state == "accepted"
    processing = bridge.chat_state.public_transcript.capture().processing
    assert processing.phase == "responding"
    assert processing.request_id == next_message.fields["request_id"]
    assert (
        bridge.worker.companion_request_ref.request_id
        == next_message.fields["request_id"]
    )
    assert pending_values[-1] is True


def test_worker_start_failure_keeps_accepted_user_but_no_duplicate_retry(
    admission, monkeypatch
):
    bridge, _, context, counts = admission
    from src.core.bridge_mixins import chat_flow

    original = chat_flow.AIWorker

    class FailedStart(original):
        def start(self):
            raise RuntimeError("합성 worker 시작 실패")

    monkeypatch.setattr(chat_flow, "AIWorker", FailedStart)
    message = mobile_message(bridge)
    result = bridge.submit_mobile_text(context, message)
    assert result.state == "failed" and result.message_id is not None
    assert bridge.submit_mobile_text(context, message) == result
    assert counts["worker"] == counts["memory"] == 1
    assert bridge.life_record_state.phase == "idle"
    assert bridge.chat_state.public_transcript.capture().processing.phase == "idle"


def test_shutdown_discards_pending_tts_display(admission):
    bridge, _, context, _ = admission
    bridge.enable_tts = True
    bridge.tts_client = bridge.audio_player = object()
    bridge._play_tts = lambda text: None
    result = bridge.submit_mobile_text(context, mobile_message(bridge))
    bridge.worker.reply(spoken="가상 대기 음성")
    bridge.begin_shutdown()
    bridge._flush_pending_response_if_any()
    assert len(bridge.chat_state.public_transcript.capture().messages) == 1
    assert (
        bridge.chat_state.request_ledger.lookup(result.request_ref.key).state
        == "failed"
    )


def test_failure_callback_can_start_next_request_without_losing_worker(
    admission, monkeypatch
):
    bridge, _, context, _ = admission
    from src.core.bridge_mixins import chat_flow

    original = chat_flow.AIWorker

    class FailedStart(original):
        def start(self):
            raise RuntimeError("합성 worker 시작 실패")

    monkeypatch.setattr(chat_flow, "AIWorker", FailedStart)
    new_results = []

    def submit_next(result):
        if result.state == "failed":
            monkeypatch.setattr(chat_flow, "AIWorker", original)
            new_results.append(
                bridge.submit_mobile_text(context, mobile_message(bridge, number=31))
            )

    bridge.companion_admission_result.connect(submit_next)
    assert bridge.submit_mobile_text(context, mobile_message(bridge)).state == "failed"
    assert len(new_results) == 1 and new_results[0].state == "accepted"
    assert bridge.worker is not None
    assert bridge.worker.companion_request_ref.request_id == sample_id(31)
    assert bridge.life_record_state.phase == "normal_reply"
