"""안드로이드와 PC가 같은 합성 카메라 메시지를 수락하는지 확인한다."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from src.core.companion.extension_protocol import ExtensionContext, validate_extension
from src.core.companion.protocol import ProtocolError, decode_message, encode_message


ROOT = Path(__file__).parents[1] / "contracts/companion/v1"
CASES = [(feature, case) for feature in ("camera", "observation_intervals")
         for case in json.loads((ROOT / f"{feature}_cases.json").read_text(encoding="utf-8"))]


@pytest.mark.parametrize("feature,case", CASES, ids=[f"{feature}/{case['name']}" for feature, case in CASES])
def test_camera_contract(feature, case):
    body = case["body"]
    if not case["valid"]:
        with pytest.raises(ProtocolError):
            decode_message(json.dumps(body))
        return
    message = decode_message(json.dumps(body))
    assert json.loads(encode_message(message)) == body
    context = ExtensionContext(*(body[key] for key in (
        "registration_generation", "server_epoch", "connection_generation", "conversation_id")))
    source, other = ("from_pc", "from_phone") if body["type"].endswith("_state") else ("from_phone", "from_pc")
    negotiated = {feature + "_v1"}
    validate_extension(message, context, negotiated, direction=source)
    for current, capabilities, direction in (
        (context, {"chat_images_v1"}, source),
        (replace(context, conversation_id=body["server_epoch"]), negotiated, source),
        (context, negotiated, other),
    ):
        with pytest.raises(ProtocolError):
            validate_extension(message, current, capabilities, direction=direction)
