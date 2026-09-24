"""외부 제공자 호출 없이 실패한 대화의 표시·재시도·문맥 보존을 검증한다."""

import json
from copy import deepcopy

import pytest

from src.ai.http_llm_common import _CommonMixin
from tests.test_companion_admission import admission  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_edit_reroll import command, state


def fail_worker(bridge):
    worker = bridge.worker
    worker.running = False
    worker.error_occurred.emit("synthetic provider failure")
    worker.finished.emit()
    return worker


def prepare_failure(admission, prior_success=True):
    bridge, _, _, counts = admission
    client = _CommonMixin()
    client._history = []
    bridge.llm_client = client
    if prior_success:
        bridge.submit_chat_request("가상 육각형을 배치합니다.")
        bridge.worker.reply("가상 육각형 배치를 완료했습니다.")
    previous = state(bridge).messages
    bridge.submit_chat_request("가상 삼각형을 옮깁니다.")
    failed = fail_worker(bridge)
    return bridge, previous, failed, counts


@pytest.mark.parametrize("prior_success", [False, True])
def test_failure_has_public_retry_target_but_never_becomes_success(admission, prior_success):
    bridge, previous, worker, _ = prepare_failure(admission, prior_success)
    messages = state(bridge).messages
    assert len(messages) == len(previous) + 2
    user, notice = messages[-2:]
    assert (user.role, notice.role) == ("user", "assistant")
    assert notice.request_id == user.request_id == worker.companion_request_ref.request_id
    assert worker.companion_request_ref.key not in bridge.chat_state.public_assistant_ids
    assert bridge.chat_state.request_ledger.lookup(worker.companion_request_ref.key).state == "failed"
    assert notice.text not in [entry[1] for entry in bridge.conversation_buffer]
    assert all(notice.text not in entry["content"] for entry in bridge.llm_client.get_conversation_history())
    assert json.loads(bridge.get_companion_chat_state())["messages"][-1]["id"] == notice.id
    assert bridge.life_record_state.phase == "idle"


def test_unanswered_request_rebuild_does_not_rollback_previous_provider_success(admission):
    bridge, _, _, _ = prepare_failure(admission)
    previous_history = bridge.llm_client.get_conversation_history()
    assert [entry["role"] for entry in previous_history] == ["user", "assistant"]
    assert bridge._rollback_last_turn_pair_for_retry()
    assert bridge.llm_client.get_conversation_history() == previous_history


@pytest.mark.parametrize("kind", ["reroll", "edit"])
@pytest.mark.parametrize("prior_success", [False, True])
@pytest.mark.parametrize("deferred_tts", [False, True])
def test_failed_request_can_be_retried_without_losing_previous_turns(
    admission, kind, prior_success, deferred_tts
):
    bridge, previous, _, counts = prepare_failure(admission, prior_success)
    before = state(bridge).messages
    prior_history = bridge.llm_client.get_conversation_history()
    before_counts = dict(counts)
    if deferred_tts:
        bridge.enable_tts = True
        bridge.tts_client = object()
        bridge.audio_player = object()
        bridge._play_tts = lambda _: None
    if kind == "edit":
        result = json.loads(bridge.edit_companion_message(command(bridge, "user", text="가상 오각형을 옮깁니다.")))
    else:
        result = json.loads(bridge.reroll_companion_message(command(bridge, "assistant")))
    assert result["state"] == "accepted"
    assert bridge.llm_client.get_conversation_history() == prior_history
    assert counts["worker"] == before_counts["worker"] + 1
    assert counts["conversation"] == before_counts["conversation"]
    worker = bridge.worker
    worker.reply("가상 이동을 완료했습니다.", spoken="가상 음성 안내")
    if deferred_tts:
        assert state(bridge).messages[-1] == before[-1]
        bridge._flush_pending_response_if_any()
    after = state(bridge).messages
    assert [message.id for message in after] == [message.id for message in before]
    assert after[:len(previous)] == previous
    assert after[-1].text == "가상 이동을 완료했습니다."
    assert after[-2].text == ("가상 오각형을 옮깁니다." if kind == "edit" else before[-2].text)
    assert bridge.chat_state.request_ledger.lookup(worker.companion_request_ref.key).state == "completed"
    assert [item[1] for item in bridge.conversation_buffer] == [message.text for message in after]
    assert bridge.life_record_state.phase == "idle"
    assert bridge.chat_state.failed_assistant_ids == {}


@pytest.mark.parametrize("kind", ["reroll", "edit"])
def test_repeated_failure_keeps_same_retry_target_and_original_input(admission, kind):
    bridge, _, original_worker, _ = prepare_failure(admission)
    original_messages = state(bridge).messages
    original_buffer = list(bridge.conversation_buffer)
    legacy = []
    bridge.message_received.connect(lambda *args: legacy.append(args))
    for _ in range(2):
        if kind == "edit":
            result = json.loads(bridge.edit_companion_message(command(bridge, "user", text="가상 편집 요청")))
        else:
            result = json.loads(bridge.reroll_companion_message(command(bridge, "assistant")))
        assert result["state"] == "accepted"
        failed_worker = fail_worker(bridge)
        assert state(bridge).messages == original_messages
        assert bridge.conversation_buffer == original_buffer
        assert bridge.chat_state.last_request_ref == original_worker.companion_request_ref
        assert bridge.chat_state.request_ledger.lookup(failed_worker.companion_request_ref.key).state == "failed"
        assert legacy == []
    assert json.loads(bridge.reroll_companion_message(command(bridge, "assistant")))["state"] == "accepted"
    bridge.worker.reply("가상 복구를 완료했습니다.")
    assert state(bridge).messages[-1].text == "가상 복구를 완료했습니다."


@pytest.mark.parametrize("prior_success", [False, True])
def test_failure_display_events_move_reroll_to_failed_turn(admission, prior_success):
    from tests.test_chat_dom_runtime import run_dom_case

    bridge, _, _, _ = admission
    if prior_success:
        bridge.submit_chat_request("가상 점을 표시합니다.")
        bridge.worker.reply("가상 점 표시를 완료했습니다.")
    snapshot = json.loads(bridge.get_companion_chat_state())
    events = []
    bridge.chat_display_event.connect(lambda raw: events.append(["display", json.loads(raw)]))
    bridge.request_pending_changed.connect(lambda active: events.append(["pending", active]))
    bridge.submit_chat_request("가상 선을 표시합니다.")
    failed_worker = fail_worker(bridge)
    result = run_dom_case(f"""
window.eneCompanionChat.applySnapshot({json.dumps(snapshot)});
for (const [kind, value] of {json.dumps(events)}) {{
    if (kind === 'display') window.eneCompanionChat.applyEvent(value);
    if (kind === 'pending') window.eneCompanionChat.setBackendPending(value);
}}
await new Promise(resolve => setTimeout(resolve, 0));
const buttons = chatMessages.querySelectorAll('.message-reroll-btn');
const pendingBeforeClick = isRequestPending;
buttons[0]?.click();
result = {{count: buttons.length, pending: pendingBeforeClick,
    target: calls[0]?.payload.target_message_id || null,
    request: lastAssistantMessageEl?.dataset.messageId || null}};
""")
    latest = state(bridge).messages[-1]
    assert latest.request_id == failed_worker.companion_request_ref.request_id
    assert result == {"count": 1, "pending": False, "target": latest.id, "request": latest.id}


def test_reset_invalidates_failed_target_and_delayed_worker(admission):
    bridge, _, worker, _ = prepare_failure(admission)
    captured = command(bridge, "assistant")
    bridge.clear_conversation()
    worker.error_occurred.emit("synthetic late failure")
    worker.reply("가상 지연 응답")
    assert state(bridge).messages == ()
    assert bridge.chat_state.failed_assistant_ids == {}
    assert json.loads(bridge.reroll_companion_message(captured))["code"] == "stale_session"


def test_recovered_reply_supports_another_successful_reroll(admission):
    bridge, previous, _, _ = prepare_failure(admission)
    ids = [message.id for message in state(bridge).messages]
    for reply in ("가상 첫 복구 응답", "가상 두 번째 재생성 응답"):
        assert json.loads(bridge.reroll_companion_message(command(bridge, "assistant")))["state"] == "accepted"
        bridge.worker.reply(reply)
        assert [message.id for message in state(bridge).messages] == ids
        assert state(bridge).messages[:len(previous)] == previous
        assert state(bridge).messages[-1].text == reply
        assert [item[1] for item in bridge.conversation_buffer] == [message.text for message in state(bridge).messages]


def test_new_request_invalidates_old_failure_target_without_starting_worker(admission):
    bridge, _, _, counts = prepare_failure(admission)
    old_command = json.loads(command(bridge, "assistant"))
    bridge.submit_chat_request("가상 구를 놓습니다.")
    bridge.worker.reply("가상 구를 놓았습니다.")
    before = dict(counts)
    old_command["expected_revision"] = state(bridge).conversation_revision
    assert json.loads(bridge.reroll_companion_message(json.dumps(old_command)))["code"] == "stale_target"
    assert counts == before


def test_failed_request_retry_rejects_busy_and_old_worker_signals(admission):
    bridge, _, old_worker, counts = prepare_failure(admission)
    assert json.loads(bridge.reroll_companion_message(command(bridge, "assistant")))["state"] == "accepted"
    before = dict(counts)
    snapshot = state(bridge).messages
    current_worker = bridge.worker
    assert json.loads(bridge.reroll_companion_message(command(bridge, "assistant")))["state"] == "rejected"
    old_worker.error_occurred.emit("synthetic outdated failure")
    old_worker.reply("가상 폐기 대상 응답")
    assert counts == before
    assert state(bridge).messages == snapshot
    assert bridge.worker is current_worker
    current_worker.reply("가상 현재 응답")
    assert state(bridge).messages[-1].text == "가상 현재 응답"


@pytest.mark.parametrize("kind", ["reroll", "edit"])
def test_retry_worker_start_failure_restores_recoverable_turn(admission, monkeypatch, kind):
    from src.core.bridge_mixins import chat_flow

    bridge, _, original_worker, _ = prepare_failure(admission)
    snapshot = state(bridge).messages
    payload = deepcopy(bridge._last_request_payload)

    def fail_start(worker):
        raise RuntimeError("synthetic startup failure")

    monkeypatch.setattr(chat_flow.AIWorker, "start", fail_start)
    if kind == "edit":
        result = json.loads(bridge.edit_companion_message(command(bridge, "user", text="가상 수정 요청")))
    else:
        result = json.loads(bridge.reroll_companion_message(command(bridge, "assistant")))
    assert result["state"] == "failed"
    assert state(bridge).messages == snapshot
    assert bridge._last_request_payload == payload
    assert bridge.chat_state.last_request_ref == original_worker.companion_request_ref
    assert bridge.life_record_state.phase == "idle"
    assert not bridge._is_rerolling


def test_failed_attachment_request_preserves_local_attachment_on_retry(admission):
    from tests.test_companion_edit_reroll import pc_payload

    bridge, _, _, _ = admission
    client = _CommonMixin()
    client._history = []
    bridge.llm_client = client
    bridge._resolve_prepared_attachments = lambda values: values
    submitted = json.loads(bridge.submit_pc_chat(pc_payload(bridge, "가상 첨부를 확인합니다.", [{
        "id": "synthetic-document", "name": "synthetic.txt", "category": "document",
        "status": "ready", "text": "가상 문서 내용",
    }])))
    fail_worker(bridge)
    record = deepcopy(bridge._message_attachment_records[submitted["message_id"]])
    assert json.loads(bridge.reroll_companion_message(command(bridge, "assistant")))["state"] == "accepted"
    bridge.worker.reply("가상 첨부를 확인했습니다.")
    assert bridge._message_attachment_records[submitted["message_id"]] == record
    assert state(bridge).messages[0].attachment_unsupported
    assert len(state(bridge).messages) == 2


def test_reset_during_failed_turn_retry_cannot_restore_old_failure(admission):
    bridge, _, _, _ = prepare_failure(admission)
    assert json.loads(bridge.edit_companion_message(command(bridge, "user", text="가상 수정 지시")))["state"] == "accepted"
    worker = bridge.worker
    bridge.clear_conversation()
    worker.running = False
    worker.error_occurred.emit("synthetic reset failure")
    worker.finished.emit()
    assert state(bridge).messages == ()
    assert bridge.conversation_buffer == []
    assert bridge.chat_state.failed_assistant_ids == {}
