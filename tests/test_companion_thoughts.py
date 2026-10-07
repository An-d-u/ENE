"""표시된 합성 생각만 협상된 연결에서 조회하는 경계를 검증한다."""

import json
from types import SimpleNamespace

import pytest

from src.core.companion.extension_protocol import ExtensionContext, validate_extension
from src.core.companion.protocol import ProtocolError, decode_message, encode_message
from src.core.companion.transcript import CurrentConversationTranscript


def uid(number):
    return f"00000000-0000-4000-8000-{number:012d}"


def wire(kind="thought_request", **extra):
    return {"type": kind, "protocol_version": 1, "registration_generation": 1,
            "server_epoch": uid(1), "connection_generation": uid(2), "conversation_id": uid(3),
            **({} if kind == "thought_invalidated" else {
                "query_id": uid(4), "message_id": uid(5), "conversation_revision": 2}), **extra}


@pytest.mark.parametrize("kind,extra,direction", [
    ("thought_request", {}, "from_phone"),
    ("thought_response", {"status": "available", "text": "가상 타일의 색을 비교한다."}, "from_pc"),
    ("thought_invalidated", {}, "from_pc"),
])
def test_contract_requires_negotiation_and_current_connection(kind, extra, direction):
    payload = wire(kind, **extra)
    message = decode_message(json.dumps(payload, ensure_ascii=False))
    assert json.loads(encode_message(message)) == payload
    context = ExtensionContext(1, uid(1), uid(2), uid(3))
    validate_extension(message, context, {"message_thoughts_v1"}, direction=direction)
    with pytest.raises(ProtocolError, match="extension_not_negotiated"):
        validate_extension(message, context, set(), direction=direction)
    with pytest.raises(ProtocolError, match="stale_extension"):
        validate_extension(message, ExtensionContext(2, uid(1), uid(2), uid(3)), {"message_thoughts_v1"}, direction=direction)
    with pytest.raises(ProtocolError, match="unsupported_command"):
        validate_extension(message, context, {"message_thoughts_v1"}, direction="from_pc" if direction == "from_phone" else "from_phone")
    assert "가상 타일" not in repr(message)


def test_response_limit_and_status_cannot_smuggle_text():
    decode_message(json.dumps(wire("thought_response", status="available", text="\x01" * 8192)))
    for status, text in [("available", "x" * 8193), ("empty", "비어 있지 않은 합성 문장"), ("available", " "), ("unknown", "")]:
        with pytest.raises(ProtocolError):
            decode_message(json.dumps(wire("thought_response", status=status, text=text)))


@pytest.fixture
def display():
    from src.core.companion.thoughts_bridge import CompanionThoughtsBridge

    transcript = CurrentConversationTranscript(server_epoch=uid(1), conversation_id=uid(3))
    user = transcript.append_user("가상 타일을 놓아 줘.").message
    answer = transcript.publish_assistant("가상 타일을 놓았습니다.").message
    owner = SimpleNamespace(chat_state=SimpleNamespace(public_transcript=transcript, pc_messages={
        answer.id: {**answer.to_dict(), "thought": "가상 타일의 색을 비교한다.", "emotion": "비공개 분석"},
        user.id: {**user.to_dict(), "thought": "전송하면 안 되는 합성 자료"},
        uid(99): {"role": "assistant", "thought": "미공개 합성 자료"},
    }), _are_ene_thoughts_enabled=lambda: True)
    return owner, CompanionThoughtsBridge(owner), answer, user


def test_only_public_displayed_assistant_is_exposed(display):
    owner, bridge, answer, user = display
    result = bridge.response(wire(message_id=answer.id))
    assert result["text"] == owner.chat_state.pc_messages[answer.id]["thought"]
    assert result["status"] == "available"
    assert "emotion" not in result
    for message_id in [user.id, uid(99)]:
        assert bridge.response(wire(message_id=message_id))["text"] == ""
    owner.chat_state.pc_messages[answer.id]["local_only"] = True
    assert bridge.response(wire(message_id=answer.id))["status"] == "empty"


def test_settings_revision_replacement_and_size(display):
    owner, bridge, answer, _ = display
    owner._are_ene_thoughts_enabled = lambda: False
    assert bridge.response(wire(message_id=answer.id))["status"] == "empty"
    owner._are_ene_thoughts_enabled = lambda: True
    assert bridge.response(wire(message_id=answer.id, conversation_revision=0))["status"] == "stale"
    owner.chat_state.public_transcript.replace(answer.id, "새 합성 답변", expected_revision=2)
    owner.chat_state.pc_messages[answer.id]["thought"] = "새 합성 생각"
    assert bridge.response(wire(message_id=answer.id))["text"] == ""
    assert bridge.response(wire(message_id=answer.id, conversation_revision=3))["text"] == "새 합성 생각"
    owner.chat_state.pc_messages[answer.id]["thought"] = "나" * 2731
    assert bridge.response(wire(message_id=answer.id, conversation_revision=3))["status"] == "too_large"


def test_settings_invalidation_contains_no_content(display):
    owner, bridge, answer, _ = display
    sent = []
    owner._companion_adapter = SimpleNamespace(publish_extension=lambda kind, fields: sent.append((kind, fields)))
    bridge.settings_changed(False)
    assert bridge.response(wire(message_id=answer.id))["text"] == ""
    assert sent == [("thought_invalidated", {"conversation_id": uid(3)})]
    bridge.settings_changed(False)
    assert len(sent) == 1
    bridge.settings_changed(True)
    assert bridge.response(wire(message_id=answer.id))["status"] == "available"
