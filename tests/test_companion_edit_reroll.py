"""공개 ID를 고정한 PC 표시·편집·리롤의 수락 경계를 검증한다."""

import json
from types import SimpleNamespace

import pytest

from tests.companion_helpers import sample_id
from tests.test_companion_admission import admission, mobile_message  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401


def state(bridge):
    return bridge.chat_state.public_transcript.capture()


def command(bridge, role, **changes):
    captured = state(bridge)
    target = next(
        message for message in reversed(captured.messages) if message.role == role
    )
    return json.dumps(
        {
            "server_epoch": captured.server_epoch,
            "conversation_id": captured.conversation_id,
            "target_message_id": target.id,
            "expected_revision": captured.conversation_revision,
            **changes,
        }
    )


def completed_pair(admission):
    bridge, _, context, counts = admission
    bridge.llm_client.rollback_last_assistant_turn = lambda: True
    bridge.llm_client.rebuild_context_from_conversation = lambda *_: True
    bridge.submit_mobile_text(context, mobile_message(bridge))
    bridge.worker.reply("가상 원뿔을 배치했습니다.")
    return bridge, context, counts


def test_pc_submission_uses_public_ids_and_one_display_signal(admission):
    bridge, _, _, _ = admission
    displayed, local = [], []
    bridge.chat_display_event.connect(lambda raw: displayed.append(json.loads(raw)))
    bridge.message_received.connect(lambda *args: local.append(args))
    head = state(bridge)
    result = json.loads(
        bridge.submit_pc_chat(
            json.dumps(
                {
                    "server_epoch": head.server_epoch,
                    "conversation_id": head.conversation_id,
                    "request_id": sample_id(40),
                    "text": "가상 삼각형은 노란색입니다.",
                    "attachments": [],
                }
            )
        )
    )
    assert result["state"] == "accepted"
    bridge.worker.reply()
    appends = [event for event in displayed if event["op"] == "append"]
    assert [event["message"]["id"] for event in appends] == [
        message.id for message in state(bridge).messages
    ]
    assert local == []


def test_phone_user_is_also_displayed_on_pc(admission):
    bridge, _, context, _ = admission
    displayed = []
    bridge.chat_display_event.connect(lambda raw: displayed.append(json.loads(raw)))
    accepted = bridge.submit_mobile_text(context, mobile_message(bridge))
    users = [
        event["message"]
        for event in displayed
        if event.get("message", {}).get("role") == "user"
    ]
    assert len(users) == 1 and users[0]["id"] == accepted.message_id


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_retry_replaces_same_public_ids_without_appending_turn(admission, kind):
    bridge, _, _ = completed_pair(admission)
    before = state(bridge).messages
    if kind == "edit":
        result = json.loads(
            bridge.edit_companion_message(
                command(bridge, "user", text="가상 원뿔을 네 칸 옮깁니다.")
            )
        )
    else:
        result = json.loads(
            bridge.reroll_companion_message(command(bridge, "assistant"))
        )
    assert result["state"] == "accepted"
    bridge.worker.reply("가상 원뿔의 배치를 갱신했습니다.")
    after = state(bridge).messages
    assert [message.id for message in after] == [message.id for message in before]
    assert after[-1].text == "가상 원뿔의 배치를 갱신했습니다."
    assert after[0].text == (
        "가상 원뿔을 네 칸 옮깁니다." if kind == "edit" else before[0].text
    )


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_stale_target_cannot_touch_memory_mood_or_worker(admission, kind):
    bridge, context, counts = completed_pair(admission)
    original = command(
        bridge, "user" if kind == "edit" else "assistant", text="가상 편집 문장"
    )
    bridge.submit_mobile_text(context, mobile_message(bridge, number=31))
    bridge.worker.reply()
    before = dict(counts)
    before_messages = state(bridge).messages
    method = (
        bridge.edit_companion_message
        if kind == "edit"
        else bridge.reroll_companion_message
    )
    result = json.loads(method(original))
    assert result["state"] == "rejected" and result["code"] == "stale_target"
    assert counts == before
    assert state(bridge).messages == before_messages


def test_reset_rejects_previously_captured_edit_target(admission):
    bridge, _, counts = completed_pair(admission)
    original = command(bridge, "user", text="가상 수정 문장")
    bridge.clear_conversation()
    before = dict(counts)
    result = json.loads(bridge.edit_companion_message(original))
    assert result["state"] == "rejected" and result["code"] == "stale_session"
    assert counts == before


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_retry_failure_restores_original_visible_pair_by_id(admission, kind):
    bridge, _, _ = completed_pair(admission)
    before = state(bridge).messages
    if kind == "edit":
        bridge.edit_companion_message(
            command(bridge, "user", text="가상 임시 수정 내용")
        )
    else:
        bridge.reroll_companion_message(command(bridge, "assistant"))
    bridge.worker.error_occurred.emit("합성 재생성 오류")
    after = state(bridge).messages
    assert [(message.id, message.text) for message in after] == [
        (message.id, message.text) for message in before
    ]
    assert bridge.life_record_state.phase == "idle"


def test_busy_retry_preserves_current_public_pair(admission):
    bridge, context, counts = completed_pair(admission)
    captured = command(bridge, "assistant")
    bridge.submit_mobile_text(context, mobile_message(bridge, number=31))
    before = dict(counts)
    result = json.loads(bridge.reroll_companion_message(captured))
    assert result["state"] == "rejected"
    assert counts == before


def pc_payload(bridge, text, attachments=None):
    captured = state(bridge)
    return json.dumps(
        {
            "server_epoch": captured.server_epoch,
            "conversation_id": captured.conversation_id,
            "request_id": sample_id(40),
            "text": text,
            "attachments": attachments or [],
        }
    )


@pytest.mark.parametrize("kind", ["note", "diary"])
def test_pc_file_command_preserves_private_route_and_duplicate_protection(
    admission, kind
):
    bridge, _, _, counts = admission
    bridge._activate_obsidian_integration = lambda: None
    raw = pc_payload(bridge, f"/{kind} 가상 파일 지시")
    first = json.loads(bridge.submit_pc_chat(raw))
    second = json.loads(bridge.submit_pc_chat(raw))
    assert first["state"] == second["state"] == "accepted"
    assert bridge.worker.companion_file_result is True
    assert counts["worker"] == 1
    bridge.worker.reply("가상 비공개 파일 결과")
    assert [message.role for message in state(bridge).messages] == ["assistant"]
    assert (
        state(bridge).messages[0].text
        == "PC 전용 파일 작업 결과입니다. PC에서 확인해 주세요."
    )
    pc = json.loads(bridge.get_companion_chat_state())["messages"]
    assert [message["role"] for message in pc] == ["user", "assistant"]
    assert pc[-1]["text"] == "가상 비공개 파일 결과"


def test_pc_direct_file_preview_is_private_and_reports_completed(admission):
    bridge, _, _, _ = admission
    bridge._activate_obsidian_integration = lambda: None
    bridge.obsidian_manager = SimpleNamespace(
        read_file=lambda _: "가상 파일의 비공개 원문"
    )
    raw = pc_payload(bridge, "/obs read synthetic-private.md")
    result = json.loads(bridge.submit_pc_chat(raw))
    assert result["state"] == "completed"
    assert bridge.worker is None
    assert len(state(bridge).messages) == 1
    assert "비공개 원문" not in state(bridge).messages[0].text
    assert (
        json.loads(bridge.get_companion_chat_state())["messages"][-1]["text"]
        == "가상 파일의 비공개 원문"
    )


def test_attachment_only_pc_input_uses_public_id_for_attachment_record(admission):
    bridge, _, _, _ = admission
    bridge._resolve_prepared_attachments = lambda values: values
    result = json.loads(
        bridge.submit_pc_chat(
            pc_payload(
                bridge,
                "",
                [
                    {
                        "id": "synthetic-file",
                        "name": "synthetic.txt",
                        "category": "document",
                        "status": "ready",
                        "text": "합성 첨부 텍스트",
                        "messageId": "client-only-id",
                    }
                ],
            )
        )
    )
    assert result["state"] == "accepted"
    assert result["message_id"] in bridge._message_attachment_records
    assert state(bridge).messages[0].attachment_unsupported is True


def test_retry_status_keeps_client_correlation_id(admission):
    bridge, _, _ = completed_pair(admission)
    result = json.loads(
        bridge.reroll_companion_message(
            command(bridge, "assistant", request_id=sample_id(70))
        )
    )
    assert result["request_id"] == sample_id(70)


def test_deleted_attachment_stays_deleted_in_pc_reconnection_snapshot(admission):
    bridge, _, _, _ = admission
    bridge._resolve_prepared_attachments = lambda values: values
    result = json.loads(
        bridge.submit_pc_chat(
            pc_payload(
                bridge,
                "가상 그림 설명",
                [
                    {
                        "id": "synthetic-image",
                        "name": "synthetic.png",
                        "category": "image",
                        "status": "ready",
                        "dataUrl": "data:image/png;base64,c3ludGhldGlj",
                    }
                ],
            )
        )
    )
    bridge.worker.reply()
    bridge.delete_message_attachment(result["message_id"], "synthetic-image")
    message = json.loads(bridge.get_companion_chat_state())["messages"][0]
    assert message["attachments"][0]["deleted"] is True
    assert message["attachments"][0]["dataUrl"] == ""


def test_edit_handles_worker_reply_before_start_returns(admission, monkeypatch):
    bridge, _, _ = completed_pair(admission)
    from src.core.bridge_mixins import chat_flow

    monkeypatch.setattr(
        chat_flow.AIWorker, "start", lambda worker: worker.reply("가상 즉시 응답")
    )
    result = json.loads(
        bridge.edit_companion_message(command(bridge, "user", text="가상 즉시 편집"))
    )
    assert result["state"] == "completed"
    assert [message.text for message in state(bridge).messages] == [
        "가상 즉시 편집",
        "가상 즉시 응답",
    ]


def test_failed_edit_preserves_pc_only_original_metadata(admission):
    bridge, _, _ = completed_pair(admission)
    original = state(bridge).messages[0]
    bridge.chat_state.pc_messages[original.id]["thought"] = "가상 PC 표시 메타데이터"
    bridge.edit_companion_message(command(bridge, "user", text="가상 실패할 편집"))
    bridge.worker.error_occurred.emit("합성 오류")
    message = json.loads(bridge.get_companion_chat_state())["messages"][0]
    assert message["thought"] == "가상 PC 표시 메타데이터"


def test_failed_retry_keeps_original_scheduled_items(admission):
    bridge, _, _ = completed_pair(admission)
    deleted = []
    bridge._delete_tracked_promises_for_retry = lambda **kwargs: deleted.append(
        "promise"
    )
    bridge._delete_tracked_proactive_for_retry = lambda **kwargs: deleted.append(
        "proactive"
    )
    original = list(bridge.conversation_buffer)
    bridge.reroll_companion_message(command(bridge, "assistant"))
    bridge.worker.error_occurred.emit("합성 생성 실패")
    assert deleted == []
    assert bridge.conversation_buffer == original


def test_edit_cannot_turn_public_chat_into_private_file_command(admission):
    bridge, _, counts = completed_pair(admission)
    original = state(bridge).messages
    before = dict(counts)
    result = json.loads(
        bridge.edit_companion_message(
            command(bridge, "user", text="/note 가상 파일 지시")
        )
    )
    assert result["code"] == "unsupported_command"
    assert state(bridge).messages == original
    assert counts == before


def test_reset_during_retry_never_restores_previous_pair(admission):
    bridge, _, _ = completed_pair(admission)
    bridge.edit_companion_message(command(bridge, "user", text="가상 폐기될 수정"))
    old_worker = bridge.worker
    bridge.clear_conversation()
    old_worker.reply("가상 늦은 결과")
    assert state(bridge).messages == ()
    assert json.loads(bridge.get_companion_chat_state())["messages"] == []
