"""사진·STT 확장의 합성 공통 사례와 목적별 협상 경계를 검사한다."""

from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.core.companion.extension_protocol import ExtensionContext, validate_extension
from src.core.companion.protocol import ProtocolError, decode_message, encode_message


ROOT = Path(__file__).parents[1] / "contracts/companion/v1"
CASES = [(feature, case) for feature in ("chat_images", "stt_input")
         for case in json.loads((ROOT / (feature + "_cases.json")).read_text(encoding="utf-8"))]
PHONE = {"input_reserve", "input_cancel", "chat_images_send", "chat_images_request", "chat_images_limits_request",
         "stt_limits_request", "stt_begin", "stt_transcribe", "stt_cancel"}


@pytest.mark.parametrize("feature,case", CASES, ids=[feature + "/" + case["name"] for feature, case in CASES])
def test_input_shared_cases(feature, case):
    body = case["body"]
    if not case["valid"]:
        with pytest.raises(ProtocolError):
            decode_message(json.dumps(body))
        return
    message = decode_message(json.dumps(body))
    assert json.loads(encode_message(message)) == body
    context = ExtensionContext(*(body[key] for key in ("registration_generation", "server_epoch", "connection_generation", "conversation_id")))
    direction = "from_phone" if body["type"] in PHONE else "from_pc"
    validate_extension(message, context, {feature + "_v1"}, direction=direction)
    for caps, current, source in ((set(), context, direction), ({feature + "_v1"}, replace(context, registration_generation=2), direction),
                                  ({feature + "_v1"}, context, "from_pc" if direction == "from_phone" else "from_phone")):
        with pytest.raises(ProtocolError):
            validate_extension(message, current, caps, direction=source)
    for key in body.keys() - {"type", "protocol_version"}:
        with pytest.raises(ProtocolError):
            decode_message(json.dumps({k: v for k, v in body.items() if k != key}))
