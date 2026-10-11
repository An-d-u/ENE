"""생성 진행 계약의 구문·범위·권한을 양쪽 공통 사례로 검증한다."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.core.companion.extension_protocol import ExtensionContext, negotiate, validate_extension
from src.core.companion.protocol import ProtocolError, decode_message, encode_message

CASES = json.loads((Path(__file__).parents[1] / "contracts/companion/v1/chat_progress_cases.json").read_text(encoding="utf-8"))
CONTEXT = ExtensionContext(1, CASES[0]["body"]["server_epoch"], CASES[0]["body"]["connection_generation"], CASES[0]["body"]["conversation_id"])
CAPS = {"chat_progress_v1"}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_progress_cases(case):
    raw = json.dumps(case["body"], ensure_ascii=False)
    if not case["valid"]:
        with pytest.raises(ProtocolError):
            decode_message(raw)
        return
    message = decode_message(raw)
    assert json.loads(encode_message(message)) == case["body"]
    direction = "from_phone" if message.type == "chat_progress_request" else "from_pc"
    validate_extension(message, CONTEXT, CAPS, direction=direction)
    with pytest.raises(ProtocolError):
        validate_extension(message, CONTEXT, set(), direction=direction)
    with pytest.raises(ProtocolError):
        validate_extension(message, CONTEXT, CAPS, direction="from_pc" if direction == "from_phone" else "from_phone")
    for context in (replace(CONTEXT, registration_generation=2), replace(CONTEXT, server_epoch=CONTEXT.conversation_id),
                    replace(CONTEXT, connection_generation=CONTEXT.conversation_id)):
        with pytest.raises(ProtocolError):
            validate_extension(message, context, CAPS, direction=direction)
    if "conversation_id" in message.fields:
        with pytest.raises(ProtocolError):
            validate_extension(message, replace(CONTEXT, conversation_id=CONTEXT.server_epoch), CAPS, direction=direction)


@pytest.mark.parametrize("case", CASES[:6], ids=lambda case: case["name"])
def test_progress_size_and_required_fields(case):
    body = case["body"]
    raw = json.dumps(body, separators=(",", ":"))
    assert decode_message(raw + " " * (2048 - len(raw.encode("utf-8"))))
    with pytest.raises(ProtocolError):
        decode_message(raw + " " * (2049 - len(raw.encode("utf-8"))))
    with pytest.raises(ProtocolError):
        decode_message(json.dumps({**body, "ignored": "x" * 2048}))
    for key in body.keys() - {"type", "protocol_version"}:
        with pytest.raises(ProtocolError):
            decode_message(json.dumps({k: v for k, v in body.items() if k != key}))


def test_progress_negotiates_without_media():
    assert negotiate(CAPS, CAPS) == ("chat_progress_v1",)
    assert negotiate(CAPS, ()) == ()
