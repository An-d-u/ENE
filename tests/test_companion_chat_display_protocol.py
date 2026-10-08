"""표시 설정 계약의 구문·방향·현재 연결 경계를 검증한다."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.core.companion.extension_protocol import ExtensionContext, negotiate, validate_extension
from src.core.companion.protocol import ProtocolError, decode_message, encode_message

CASES = json.loads((Path(__file__).parents[1] / "contracts/companion/v1/chat_display_cases.json").read_text(encoding="utf-8"))
CONTEXT = ExtensionContext(1, CASES[0]["body"]["server_epoch"], CASES[0]["body"]["connection_generation"],
                           "00000000-0000-4000-8000-000000000003")
CAPS = {"chat_display_v1"}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_cases(case):
    wire = json.dumps(case["body"])
    if not case["valid"]:
        with pytest.raises(ProtocolError):
            decode_message(wire)
        return
    message = decode_message(wire)
    assert json.loads(encode_message(message)) == case["body"]
    direction = "from_phone" if message.type == "chat_display_request" else "from_pc"
    validate_extension(message, CONTEXT, CAPS, direction=direction)
    with pytest.raises(ProtocolError, match="extension_not_negotiated"):
        validate_extension(message, CONTEXT, set(), direction=direction)
    with pytest.raises(ProtocolError, match="unsupported_command"):
        validate_extension(message, CONTEXT, CAPS, direction="from_pc" if direction == "from_phone" else "from_phone")
    for context in (replace(CONTEXT, registration_generation=2),
                    replace(CONTEXT, server_epoch=CONTEXT.conversation_id),
                    replace(CONTEXT, connection_generation=CONTEXT.conversation_id)):
        with pytest.raises(ProtocolError, match="stale_extension"):
            validate_extension(message, context, CAPS, direction=direction)
    # 표시 설정은 대화 교체와 독립적이다.
    validate_extension(message, replace(CONTEXT, conversation_id=CONTEXT.server_epoch), CAPS, direction=direction)


@pytest.mark.parametrize("case", CASES[:2])
def test_small_wire_limit_and_missing_fields(case):
    with pytest.raises(ProtocolError):
        decode_message(json.dumps({**case["body"], "ignored": "x" * 2048}))
    for key in case["body"]:
        if key in {"type", "protocol_version"}:
            continue
        with pytest.raises(ProtocolError):
            decode_message(json.dumps({k: v for k, v in case["body"].items() if k != key}))


def test_display_negotiates_without_media():
    assert negotiate(CAPS, CAPS) == ("chat_display_v1",)
    assert negotiate(CAPS, ()) == ()
