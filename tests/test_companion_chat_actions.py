"""실제 공통 브리지에서 마지막 쌍 조작의 권한과 복원을 검증한다."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from src.core.companion.protocol import decode_message, encode_message
from tests.companion_helpers import sample_id
from tests.test_companion_admission import admission, mobile_message  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_edit_reroll import completed_pair, state, command
from tests.test_companion_error_recovery import fail_worker, prepare_failure


def action(bridge, context, kind="reroll", number=910, **changes):
    captured = state(bridge)
    role = "user" if kind == "edit" else "assistant"
    target = next(item for item in reversed(captured.messages) if item.role == role)
    body = {
        "type": "chat_action", "protocol_version": 1,
        "registration_generation": context.registration_generation,
        "server_epoch": captured.server_epoch,
        "connection_generation": context.connection_generation,
        "conversation_id": captured.conversation_id,
        "request_id": sample_id(number), "kind": kind,
        "target_message_id": target.id,
        "expected_revision": captured.conversation_revision,
        **({"text": "가상의 청록색 구를 배치해 줘."} if kind == "edit" else {}),
        **changes,
    }
    return decode_message(encode_message(body))


def query(bridge, context):
    return decode_message(encode_message({
        "type": "chat_actions_request", "protocol_version": 1,
        "registration_generation": context.registration_generation,
        "server_epoch": state(bridge).server_epoch,
        "connection_generation": context.connection_generation,
        "conversation_id": state(bridge).conversation_id,
        "query_id": sample_id(920), "refresh": False,
    }))


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_mobile_action_is_idempotent_after_revision_changed(admission, kind):
    bridge, context, counts = completed_pair(admission)
    original_ids = [item.id for item in state(bridge).messages]
    request = action(bridge, context, kind)
    before = dict(counts)
    first = bridge.submit_extension(context, request)
    assert first.fields["state"] == "accepted"
    worker = bridge.worker
    assert worker.companion_request_ref.source == "mobile"
    assert worker.companion_request_ref.registration_generation == context.registration_generation
    assert bridge.submit_extension(context, request).fields["state"] == "accepted"
    assert bridge.worker is worker
    worker.reply("가상의 자주색 원기둥을 정렬했습니다.")
    finished_counts = dict(counts)
    assert finished_counts["worker"] == before["worker"] + 1
    assert finished_counts["conversation"] == before["conversation"]
    assert bridge.submit_extension(context, request).fields["state"] == "completed"
    assert counts == finished_counts
    assert [item.id for item in state(bridge).messages] == original_ids
    assert bridge.capture(context.registration_generation, [request.fields["request_id"]]).statuses[0].fields["state"] == "completed"
    assert bridge.submit_extension(context, query(bridge, context)).fields["reroll_allowed"]


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_failed_action_restores_original_pair_and_can_retry(admission, kind):
    bridge, context, _ = completed_pair(admission)
    before = state(bridge).messages
    payload = deepcopy(bridge._last_request_payload)
    conversation = deepcopy(bridge.conversation_buffer)
    request = action(bridge, context, kind)
    assert bridge.submit_extension(context, request).fields["state"] == "accepted"
    assert not bridge.submit_extension(context, query(bridge, context)).fields["reroll_allowed"]
    fail_worker(bridge)
    assert state(bridge).messages == before
    assert bridge._last_request_payload == payload
    assert bridge.conversation_buffer == conversation
    assert bridge.submit_extension(context, request).fields["state"] == "failed"
    assert bridge.submit_extension(context, action(bridge, context, kind, number=911)).fields["state"] == "accepted"
    bridge.worker.reply()
    assert len(state(bridge).messages) == 2


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_mobile_retry_of_provider_error(admission, kind):
    bridge, _, _, _ = prepare_failure(admission)
    context = admission[2]
    before = state(bridge).messages
    assert bridge.submit_extension(context, action(bridge, context, kind)).fields["state"] == "accepted"
    bridge.worker.reply("가상 배치를 복구했습니다.")
    assert [item.id for item in state(bridge).messages] == [item.id for item in before]


def test_older_pair_and_duplicate_conflict_have_no_side_effects(admission):
    bridge, context, counts = completed_pair(admission)
    old = action(bridge, context)
    bridge.submit_mobile_text(context, mobile_message(bridge, number=931))
    bridge.worker.reply()
    before = dict(counts)
    assert bridge.submit_extension(context, old).fields["code"] == "stale_target"
    assert counts == before
    current = action(bridge, context, "edit")
    assert bridge.submit_extension(context, current).fields["state"] == "accepted"
    conflicting = decode_message(encode_message({**current.to_dict(), "text": "가상 구를 두 개 추가해 줘."}))
    assert bridge.submit_extension(context, conflicting).fields["code"] == "request_conflict"


@pytest.mark.parametrize("phone_first", [True, False])
def test_pc_and_phone_retry_share_gate(admission, phone_first):
    bridge, context, counts = completed_pair(admission)
    phone = action(bridge, context)
    pc = command(bridge, "assistant", request_id=sample_id(933))
    before = counts["worker"]
    if phone_first:
        assert bridge.submit_extension(context, phone).fields["state"] == "accepted"
        assert json.loads(bridge.reroll_companion_message(pc))["code"] == "busy"
    else:
        assert json.loads(bridge.reroll_companion_message(pc))["state"] == "accepted"
        assert bridge.submit_extension(context, phone).fields["code"] == "busy"
    assert counts["worker"] == before + 1


def test_state_and_mobile_edit_do_not_expose_private_payload(admission):
    bridge, context, counts = completed_pair(admission)
    bridge._last_request_payload["synthetic_private"] = "검사용 비공개 메타데이터"
    raw = bridge.submit_extension(context, query(bridge, context)).to_dict()
    assert "검사용 비공개 메타데이터" not in json.dumps(raw, ensure_ascii=False)
    assert raw["query_id"] == sample_id(920)
    before = dict(counts)
    forbidden = action(bridge, context, "edit", text="/note synthetic-only")
    assert bridge.submit_extension(context, forbidden).fields["code"] == "unsupported_command"
    assert counts == before
    bridge._last_request_payload = None
    disabled = bridge.submit_extension(context, query(bridge, context)).fields
    assert not disabled["edit_allowed"] and not disabled["reroll_allowed"]


def test_reset_and_stale_connection_cannot_apply_late_action(admission):
    bridge, context, _ = completed_pair(admission)
    request = action(bridge, context)
    with pytest.raises(ValueError):
        bridge.submit_extension(replace(context, connection_generation=sample_id(944)), request)
    bridge.clear_conversation()
    with pytest.raises(ValueError):
        bridge.submit_extension(context, request)
    assert state(bridge).messages == ()


def test_large_pc_original_disables_only_mobile_edit(admission):
    bridge, context, _ = completed_pair(admission)
    captured = state(bridge)
    bridge.chat_state.public_transcript.replace(captured.messages[0].id, "x" * 16385, expected_revision=captured.conversation_revision)
    availability = bridge.submit_extension(context, query(bridge, context)).fields
    assert not availability["edit_allowed"] and availability["edit_reason"] == "text_too_large"
    assert availability["reroll_allowed"]
