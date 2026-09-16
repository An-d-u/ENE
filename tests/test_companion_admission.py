"""실제 브리지의 공통 수락과 부수효과 횟수를 합성 요청으로 검증한다."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.core.companion.adapter import (
    AdmissionContext,
    AdapterCommand,
    QtGatewayAdapter,
)
from src.core.companion.protocol import decode_message, encode_message
from tests.companion_helpers import sample_id
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_bridge_transcript import FakeWorker
from src.core.bridge_mixins import chat_flow


def mobile_message(bridge, number=30, text="가상 원뿔을 두 칸 옮깁니다.", **changes):
    transcript = bridge.chat_state.public_transcript
    payload = {
        "type": "send_text",
        "protocol_version": 1,
        "server_epoch": transcript.server_epoch,
        "conversation_id": transcript.conversation_id,
        "request_id": sample_id(number),
        "text": text,
        **changes,
    }
    return decode_message(encode_message(payload))


def connect(adapter, context):
    adapter._execute(AdapterCommand(sample_id(800), "connect", context, float("inf")))


@pytest.fixture
def admission(bridge, monkeypatch):
    adapter = QtGatewayAdapter(bridge)
    context = AdmissionContext(sample_id(500), 1, sample_id(600))
    adapter.configure(context.gateway_generation, context.registration_generation)
    connect(adapter, context)
    counts = {"prompt": 0, "memory": 0, "mood": 0, "conversation": 0, "worker": 0}

    class CountedWorker(FakeWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            counts["worker"] += 1

    monkeypatch.setattr(chat_flow, "AIWorker", CountedWorker)
    bridge.settings["enable_response_analysis"] = False
    bridge.mood_manager = SimpleNamespace(
        advance_time_and_save=lambda *_: counts.__setitem__("mood", counts["mood"] + 1)
    )
    for name, key in (
        ("_build_general_chat_prompt", "prompt"),
        ("_build_memory_search_inputs", "memory"),
    ):
        original = getattr(bridge, name)

        def counted(*args, _original=original, _key=key, **kwargs):
            counts[_key] += 1
            return _original(*args, **kwargs)

        setattr(bridge, name, counted)
    bridge.calendar_manager = SimpleNamespace(
        increment_conversation_count=lambda: counts.__setitem__(
            "conversation", counts["conversation"] + 1
        ),
        drain_pending_head_pat_count=lambda: 0,
        get_pending_head_pat_count=lambda: 0,
    )
    return bridge, adapter, context, counts


def test_same_request_is_accepted_once_and_completed_retry_returns_original(admission):
    bridge, _, context, counts = admission
    message = mobile_message(bridge)
    first = bridge.submit_mobile_text(context, message)
    worker = bridge.worker
    assert first.state == "accepted"
    assert bridge.submit_mobile_text(context, message) == first
    assert bridge.worker is worker
    assert counts["prompt"] == counts["memory"] == counts["conversation"] == 1
    worker.reply()
    result = bridge.submit_mobile_text(context, message)
    assert result.state == "completed"
    assert result.message_id == first.message_id
    assert counts["prompt"] == 1
    assert counts["worker"] == counts["mood"] == 1
    assert len(bridge.chat_state.public_transcript.capture().messages) == 2


@pytest.mark.parametrize("pc_first", [True, False])
def test_pc_and_mobile_share_one_gate(admission, pc_first):
    bridge, _, context, counts = admission
    if pc_first:
        first = bridge.submit_chat_request("가상 정육면체를 분류합니다.")
        second = bridge.submit_mobile_text(context, mobile_message(bridge))
    else:
        first = bridge.submit_mobile_text(context, mobile_message(bridge))
        second = bridge.submit_chat_request("가상 정육면체를 분류합니다.")
    assert first.state == "accepted"
    assert second.state == "rejected" and second.code == "busy"
    assert counts["prompt"] == counts["memory"] == counts["conversation"] == 1


def test_same_id_different_body_conflicts_before_busy(admission):
    bridge, _, context, counts = admission
    bridge.submit_mobile_text(context, mobile_message(bridge))
    result = bridge.submit_mobile_text(
        context, mobile_message(bridge, text="가상 원뿔을 세 칸 옮깁니다.")
    )
    assert result.code == "request_conflict"
    assert counts["prompt"] == 1


@pytest.mark.parametrize(
    "command", ["/note 가상 문서", "/DIARY 가상 기록", " /obs read synthetic.md "]
)
def test_mobile_file_commands_have_no_side_effects(admission, command):
    bridge, _, context, counts = admission
    result = bridge.submit_mobile_text(context, mobile_message(bridge, text=command))
    assert result.state == "rejected" and result.code == "unsupported_command"
    assert not any(counts.values())
    assert bridge.worker is None
    assert bridge.chat_state.public_transcript.capture().messages == ()


@pytest.mark.parametrize(
    "field", ["gateway_generation", "registration_generation", "connection_generation"]
)
def test_stale_authority_has_no_side_effects(admission, field):
    bridge, _, context, counts = admission
    stale = replace(
        context, **{field: 2 if field == "registration_generation" else sample_id(700)}
    )
    result = bridge.submit_mobile_text(stale, mobile_message(bridge))
    assert result.state == "rejected"
    assert (
        result.code
        == {
            "gateway_generation": "stale_gateway",
            "registration_generation": "stale_registration",
            "connection_generation": "stale_connection",
        }[field]
    )
    assert not any(counts.values())


def test_old_conversation_and_disabled_admission_have_no_side_effects(admission):
    bridge, adapter, context, counts = admission
    message = mobile_message(bridge)
    bridge.clear_conversation()
    assert bridge.submit_mobile_text(context, message).code == "stale_session"
    adapter.disable()
    assert (
        bridge.submit_mobile_text(context, mobile_message(bridge)).state == "rejected"
    )
    assert not any(counts.values())


def test_legacy_pc_entry_uses_same_ledger(admission):
    bridge, _, _, counts = admission
    bridge.send_to_ai("가상 타원은 두 개입니다.")
    message = bridge.chat_state.public_transcript.capture().messages[0]
    ref = bridge.worker.companion_request_ref
    assert ref.source == "pc" and ref.request_id == message.request_id
    assert bridge.chat_state.request_ledger.lookup(ref.key).state == "accepted"
    bridge.worker.reply()
    assert bridge.chat_state.request_ledger.lookup(ref.key).state == "completed"
    assert counts["prompt"] == 1


def test_pc_attachment_entry_uses_same_ledger(admission):
    bridge, _, _, counts = admission
    result = bridge.send_to_ai_with_attachments("가상 첨부 요청입니다.", "[]")
    assert result.state == "accepted"
    assert (
        bridge.chat_state.request_ledger.lookup(
            bridge.worker.companion_request_ref.key
        ).state
        == "accepted"
    )
    assert counts["worker"] == 1


@pytest.mark.parametrize(
    "message",
    ["", "  ", "\ud800", "x" * 1048577],
    ids=["empty", "blank", "surrogate", "oversize"],
)
def test_invalid_pc_input_has_no_side_effects(admission, message):
    bridge, _, _, counts = admission
    assert bridge.submit_chat_request(message).state == "rejected"
    assert not any(counts.values())
