"""설정 조회·저장이 이미지 전송과 독립적으로 협상되고 실제 저장 결과를 반환하는지 확인한다."""
from unittest.mock import Mock

import pytest

from src.core.companion.adapter import AdapterCommand, QtGatewayAdapter
from src.core.companion.extension_protocol import ExtensionContext, negotiate, validate_extension
from src.core.companion.protocol import ProtocolError, decode_message, encode_message
from tests.companion_helpers import sample_id
from tests.test_companion_adapter import SyntheticOwner, context, qt_app  # noqa: F401


def wire(kind, scope, **fields):
    return decode_message(encode_message(dict(type="observation_intervals_" + kind, protocol_version=1,
                                               **vars(scope), **fields)))


def test_setting_exchange_and_revision_are_scoped_to_authenticated_connection(qt_app):
    owner = SyntheticOwner()
    pair = (30, 300)
    owner.observation_intervals_state = lambda: pair
    owner.set_observation_intervals = Mock(return_value=False)
    adapter = QtGatewayAdapter(owner)
    route = context()
    adapter.configure(route.gateway_generation, route.registration_generation)

    def execute(operation, message=None):
        return adapter._execute(AdapterCommand(sample_id(18), operation, route, float("inf"), message=message))

    execute("connect")
    scope = ExtensionContext(route.registration_generation, owner.head().server_epoch, route.connection_generation, owner.head().conversation_id)
    assert negotiate(["observation_intervals_v1"], ["observation_intervals_v1"]) == ("observation_intervals_v1",)
    get = wire("get", scope, query_id=sample_id(71))
    validate_extension(get, scope, {"observation_intervals_v1"}, direction="from_phone")
    with pytest.raises(ProtocolError):
        validate_extension(get, scope, {"camera_v1"}, direction="from_phone")
    initial = execute("extension", get).fields
    assert (initial["query_id"], initial["sample_seconds"], initial["request_seconds"], initial["saved"]) == (sample_id(71), 30, 300, True)

    update = wire("set", scope, query_id=sample_id(72), sample_seconds=2, request_seconds=26)
    failed = execute("extension", update).fields
    owner.set_observation_intervals.assert_called_once_with(2, 26)
    assert (failed["query_id"], failed["sample_seconds"], failed["request_seconds"], failed["saved"]) == (sample_id(72), 30, 300, False)
    assert failed["revision"] == initial["revision"]
    pair = (2, 26)
    owner.set_observation_intervals.return_value = True
    success = execute("extension", update).fields
    assert (success["sample_seconds"], success["request_seconds"], success["saved"]) == (2, 26, True)
    assert success["revision"] > initial["revision"]


@pytest.mark.parametrize("value", [True, 1.5, "2", 0, 86401])
def test_settings_reject_invalid_seconds(value):
    scope = ExtensionContext(1, sample_id(1), sample_id(2), sample_id(3))
    with pytest.raises(ProtocolError):
        wire("set", scope, query_id=sample_id(4), sample_seconds=value, request_seconds=300)
