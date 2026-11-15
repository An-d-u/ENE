"""두 입력 기기의 수락·공유 세대를 합성 자료로 검증한다."""
from types import SimpleNamespace
from unittest.mock import Mock

from PyQt6.QtTest import QSignalSpy
import pytest
from src.core.companion.extension_protocol import ExtensionContext
from tests.companion_helpers import sample_id
from tests.test_companion_admission import admission, mobile_message  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_screen_input_handoff import handoff, pc  # noqa: F401
from tests.test_screen_share import capture  # noqa: F401


def message(bridge, context, kind, **values):
    head = bridge.head()
    return SimpleNamespace(type=kind, fields={
        "registration_generation": context.registration_generation,
        "connection_generation": context.connection_generation, "server_epoch": head.server_epoch,
        "conversation_id": head.conversation_id, **values,
    })


def enable_camera(bridge, context, generation=1, **changes):
    values = {"generation": generation, "lens": "back", "question": True, "observe": True, **changes}
    return bridge.mobile_camera_share(context, message(bridge, context, "camera_share", **values)).fields


def setup_cameras(bridge):
    bridge.llm_client.model_name = "synthetic-camera-model"
    bridge.llm_client.supports_image_input = True
    bridge.llm_client.send_screen_question = Mock()
    bridge.llm_client.observe_screen_once = Mock(return_value='{"reply":"","tts":""}')
    bridge._screen_share = SimpleNamespace(question=False, observe=True, observe_epoch=1, generation=8,
                                           snapshot=Mock(), validate=lambda: True)


def test_last_accepted_device_controls_observation_even_after_its_share_stops(admission):
    bridge, _, context, _ = admission
    setup_cameras(bridge)
    assert not enable_camera(bridge, context)["observe_allowed"]
    assert not bridge._start_screen_observation(0)
    assert bridge.submit_mobile_text(context, mobile_message(bridge)).state == "accepted"
    assert bridge._mobile_camera_state()["observe_allowed"]
    assert pc(bridge, 71)["code"] == "busy"
    assert bridge._mobile_camera_state()["observe_allowed"]
    assert not bridge._start_screen_observation(15)
    bridge._companion_connection_closed()
    assert not bridge._start_screen_observation(30)
    bridge._screen_share.snapshot.assert_not_called()
    bridge.worker.reply()
    assert pc(bridge, 72)["state"] == "accepted"
    assert bridge._observation_device() == "pc"
    assert not enable_camera(bridge, context)["observe_allowed"]
    bridge._screen_share.observe = False
    assert bridge._observation_device() is None


def test_phone_frame_only_once_and_lens_change_revokes_before_read(handoff, admission):
    bridge, desktop_captures, calls = handoff
    _, _, context, _ = admission
    setup_cameras(bridge)
    enable_camera(bridge, context)
    fields = mobile_message(bridge).fields
    camera_question = message(bridge, context, "camera_question", generation=1,
        request_id=fields["request_id"], text=fields["text"], frame={"upload_id": sample_id(102)})
    store = Mock(context=ExtensionContext(context.registration_generation, bridge.head().server_epoch,
                                          context.connection_generation, bridge.head().conversation_id))
    store.camera_current.return_value = True
    store.claim.return_value = [SimpleNamespace(body=b"synthetic-jpeg")]
    result = bridge.submit_mobile_camera_question(context, camera_question, store)
    assert result.state == "accepted" and calls[-1][1].read() == b"synthetic-jpeg"
    assert not desktop_captures
    enable_camera(bridge, context, 2, lens="front")
    assert calls[-1][1].read() is None
    assert bridge.submit_mobile_text(context, mobile_message(bridge)) == result
    store.claim.assert_called_once()
    assert not bridge._last_request_payload.get("images")


def test_phone_observation_is_dropped_before_claim_if_pc_owns_dialog(admission):
    bridge, _, context, _ = admission
    setup_cameras(bridge)
    enable_camera(bridge, context)
    incoming = message(bridge, context, "camera_observation", generation=1,
                       frame={"upload_id": sample_id(103)})
    store = Mock()
    bridge.submit_mobile_camera_observation(context, incoming, store)
    store.claim.assert_not_called()
    bridge._screen_share.snapshot.assert_not_called()


def test_phone_observation_uses_only_camera_and_shares_the_global_cooldown(admission):
    bridge, _, context, _ = admission
    setup_cameras(bridge)
    bridge._screen_share.observe = False
    assert enable_camera(bridge, context)["observe_allowed"]
    sent = []

    def observe(prompt, frame):
        sent.append(frame.read())
        assert "카메라" in prompt
        return '{"reply":"합성 원이 나타났습니다.","tts":""}'

    bridge.llm_client.observe_screen_once = observe
    incoming = message(bridge, context, "camera_observation", generation=1,
                       frame={"upload_id": sample_id(109)})
    store = Mock()
    store.camera_current.return_value = True
    store.claim.return_value = [SimpleNamespace(body=b"synthetic-amber")]
    changes = QSignalSpy(bridge.chat_display_event)
    bridge.submit_mobile_camera_observation(context, incoming, store)
    assert len(changes) or changes.wait(2000)
    assert sent == [b"synthetic-amber"]
    bridge.submit_mobile_camera_observation(context, incoming, store)
    store.claim.assert_called_once()
    assert bridge._ambient_quiet_until > 0
    bridge._screen_share.snapshot.assert_not_called()


@pytest.mark.parametrize("revoke", ["transport", "lens", "model", "reset"])
def test_camera_consent_is_checked_again_at_display_and_speech(admission, revoke):
    bridge, _, context, _ = admission
    setup_cameras(bridge)
    bridge._screen_share.observe = False
    enable_camera(bridge, context)
    observed = bridge._ambient_context()
    bridge._observation_pending = observed
    bridge._mobile_observation_current = lambda: revoke != "transport"
    if revoke == "lens":
        enable_camera(bridge, context, 2, lens="front")
    elif revoke == "model":
        bridge._revoke_mobile_camera()
    elif revoke == "reset":
        bridge._reset_companion_conversation()
    bridge._display_companion_response = Mock()
    bridge._play_tts = Mock()
    bridge._finish_screen_observation(observed, '{"reply":"합성 원이 나타났습니다.","tts":"가상 원"}')
    bridge._display_companion_response.assert_not_called()
    bridge._play_tts.assert_not_called()


def test_non_owner_pc_observer_releases_capture_until_pc_asks(admission, capture):
    bridge, _, context, _ = admission
    share, hardware, _ = capture
    setup_cameras(bridge)
    bridge._screen_share = share
    assert share.choose(None)
    share.set_modes(False, True)
    assert hardware.starts == 1
    enable_camera(bridge, context)
    assert hardware.stops == 1 and not share.validate()
    assert bridge.submit_mobile_text(context, mobile_message(bridge)).state == "accepted"
    bridge._companion_connection_closed()
    assert not share.validate() and hardware.starts == 1
    bridge.worker.reply()
    assert pc(bridge, 111)["state"] == "accepted"
    assert share.validate() and hardware.starts == 2


def test_provider_change_revokes_even_when_phone_display_name_is_identical(admission):
    bridge, adapter, context, _ = admission
    setup_cameras(bridge)
    bridge._screen_share = None
    enable_camera(bridge, context, observe=False)
    adapter.publish_extension = Mock()
    previous = bridge.llm_client
    bridge.set_llm_client(SimpleNamespace(
        model_name=previous.model_name, supports_image_input=True, send_screen_question=Mock(),
        observe_screen_once=Mock(), endpoint="https://example.invalid"))
    states = [call.args[1] for call in adapter.publish_extension.call_args_list if call.args[0] == "camera_state"]
    assert [state["available"] for state in states] == [False, True]
    assert not bridge._mobile_camera.question
