"""양쪽 저장소의 가상 계약 사례와 엄격한 입력 경계를 확인한다."""

import base64
import json
from pathlib import Path
import secrets

import pytest

from tests.companion_helpers import sample_id


CASES = json.loads(
    (
        Path(__file__).resolve().parents[1] / "contracts/companion/v1/cases.json"
    ).read_text(encoding="utf-8")
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_shared_contract_case(case):
    from src.core.companion.protocol import ProtocolError, decode_message

    raw = json.dumps(case["message"], ensure_ascii=False)
    if "error" in case:
        with pytest.raises(ProtocolError) as caught:
            decode_message(raw)
        assert caught.value.code == case["error"]
    else:
        assert decode_message(raw).to_dict() == case["expected"]


@pytest.mark.parametrize(
    "raw",
    [
        b"\xff",
        "{",
        "[]",
        '{"type":"hello","protocol_version":NaN}',
        '{"type":"hello","protocol_version":1,"capabilities":["\ud800"]}',
    ],
)
def test_invalid_json_is_a_safe_error(raw):
    from src.core.companion.protocol import ProtocolError, decode_message

    with pytest.raises(ProtocolError) as caught:
        decode_message(raw)
    assert str(caught.value) == caught.value.code


def test_wire_limit_and_utf8_input_limit():
    from src.core.companion.protocol import ProtocolError, decode_message

    body = {
        "type": "send_text",
        "protocol_version": 1,
        "server_epoch": sample_id(1),
        "conversation_id": sample_id(2),
        "request_id": sample_id(3),
    }
    assert (
        decode_message(
            json.dumps({**body, "text": "🪐" * 4096}, ensure_ascii=False)
        ).to_dict()["text"]
        == "🪐" * 4096
    )
    with pytest.raises(ProtocolError, match="text_too_large"):
        decode_message(json.dumps({**body, "text": "🪐" * 4097}, ensure_ascii=False))
    with pytest.raises(ProtocolError, match="message_too_large"):
        decode_message(" " * 65537)


def test_unknown_nested_fields_have_depth_limit():
    from src.core.companion.protocol import ProtocolError, decode_message

    extra = {}
    for _ in range(20):
        extra = {"child": extra}
    with pytest.raises(ProtocolError, match="invalid_message"):
        decode_message(
            json.dumps({"type": "hello", "protocol_version": 1, "extra": extra})
        )


def test_message_direction_and_preauth_limit_are_enforced():
    from src.core.companion.protocol import ProtocolError, decode_message

    with pytest.raises(ProtocolError, match="unsupported_command"):
        decode_message(
            '{"type":"hello","protocol_version":1}', allowed_types={"send_text"}
        )
    with pytest.raises(ProtocolError, match="message_too_large"):
        decode_message(" " * 8193, max_bytes=8192)


def test_credentials_are_runtime_generated_and_hidden_from_repr():
    from src.core.companion.protocol import ProtocolError, decode_message

    secret = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    body = {
        "type": "pair_request",
        "protocol_version": 1,
        "pairing_id": sample_id(1),
        "secret": secret,
        "device_name": "가상 단말",
    }
    message = decode_message(json.dumps(body))
    assert message.to_dict() == body
    assert secret not in repr(message)
    with pytest.raises(ProtocolError, match="invalid_message"):
        decode_message(json.dumps({**body, "secret": secret[:-1]}))


def test_normalized_message_is_deeply_immutable():
    from src.core.companion.protocol import decode_message

    message = decode_message(
        '{"type":"hello","protocol_version":1,"capabilities":["text"]}'
    )
    copy = message.to_dict()
    copy["capabilities"].append("unexpected")
    assert message.to_dict()["capabilities"] == ["text"]
    with pytest.raises(TypeError):
        message.fields["capabilities"] = ()


def test_public_serializer_drops_private_metadata():
    from src.core.companion.protocol import decode_message, encode_message

    body = {
        "type": "event",
        "protocol_version": 1,
        "server_epoch": sample_id(1),
        "conversation_id": sample_id(2),
        "event_seq": 1,
        "conversation_revision": 1,
        "op": "append",
        "payload": {
            "id": sample_id(3),
            "role": "assistant",
            "text": "가상 구름이 이동합니다.",
            "displayed_at": "2026-01-01T00:00:00Z",
            "thought": "공개 금지 가상 값",
            "local_path": "가상 경로",
        },
    }
    encoded = encode_message(body)
    assert "공개 금지" not in encoded and "local_path" not in encoded
    assert (
        decode_message(encoded).to_dict()["payload"]["text"] == body["payload"]["text"]
    )
