"""합성 계약으로 채팅 조작의 구문·크기·협상 경계를 검증한다."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.core.companion.extension_protocol import ExtensionContext, negotiate, validate_extension
from src.core.companion.protocol import ProtocolError, decode_message, encode_message

CASES = json.loads((Path(__file__).resolve().parents[1] / "contracts/companion/v1/chat_actions_cases.json").read_text(encoding="utf-8"))["cases"]
EDIT = CASES[0]["message"]
CONTEXT = ExtensionContext(1, EDIT["server_epoch"], EDIT["connection_generation"], EDIT["conversation_id"])


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_chat_action_contract(case):
    if "error" in case:
        with pytest.raises(ProtocolError) as failure:
            decode_message(json.dumps(case["message"], ensure_ascii=False))
        assert failure.value.code == case["error"]
    else:
        assert json.loads(encode_message(decode_message(json.dumps(case["message"])))) == case["expected"]


def test_chat_actions_need_no_media_capability():
    assert negotiate(["chat_actions_v1"], ["chat_actions_v1"]) == ("chat_actions_v1",)
    assert negotiate(["chat_actions_v1"], ["audio_pcm_v1"]) == ()


def test_chat_action_guards_and_body_privacy():
    message = decode_message(json.dumps(EDIT))
    validate_extension(message, CONTEXT, {"chat_actions_v1"}, direction="from_phone")
    for context in (replace(CONTEXT, registration_generation=2), replace(CONTEXT, conversation_id=EDIT["request_id"])):
        with pytest.raises(ProtocolError, match="stale_extension"):
            validate_extension(message, context, {"chat_actions_v1"}, direction="from_phone")
    with pytest.raises(ProtocolError, match="extension_not_negotiated"):
        validate_extension(message, CONTEXT, set(), direction="from_phone")
    with pytest.raises(ProtocolError, match="unsupported_command"):
        validate_extension(message, CONTEXT, {"chat_actions_v1"}, direction="from_pc")
    assert EDIT["text"] not in repr(message)


def test_chat_action_utf8_limits_and_raw_query_limit():
    decode_message(json.dumps({**EDIT, "text": "가" * 5461 + "a"}, ensure_ascii=False))
    with pytest.raises(ProtocolError, match="text_too_large"):
        decode_message(json.dumps({**EDIT, "text": "가" * 5461 + "ab"}, ensure_ascii=False))
    with pytest.raises(ProtocolError, match="message_too_large"):
        decode_message(json.dumps({**CASES[2]["message"], "ignored": "x" * 2048}))
    with pytest.raises(ProtocolError):
        decode_message(json.dumps({**EDIT, "text": "\ud800"}))
