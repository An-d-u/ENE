"""기기 출처를 일반 응답에만 고정하고 재시도 본문은 보존한다."""

import pytest

from src.core.bridge_mixins import chat_flow
from src.core.bridge_workers import AIWorker
from src.core.companion.requests import RequestRef
from tests.test_bridge_request_pending import _DummyBridge, _DummyWorker
from tests.test_companion_admission import admission, mobile_message  # noqa: F401
from tests.test_companion_bridge_transcript import bridge, FakeWorker  # noqa: F401
from tests.test_companion_edit_reroll import command
from tests.companion_helpers import sample_id


def ref(source):
    return RequestRef(1, sample_id(1), sample_id(2), sample_id(3), source)


@pytest.mark.parametrize("enabled", [True, False, None, 1, "true"])
@pytest.mark.parametrize("source", ["pc", "mobile", "automatic", "unknown", None])
def test_worker_captures_only_enabled_real_source(monkeypatch, enabled, source):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()
    bridge.settings = {"include_input_device_context": enabled}
    bridge._start_ai_worker(
        "가상 블록을 정렬합니다.", request_ref=ref(source) if source else None
    )
    expected = source if enabled is True and source in ("pc", "mobile") else None
    assert bridge.worker.kwargs.get("request_device") == expected
    bridge.settings["include_input_device_context"] = not enabled
    assert bridge.worker.kwargs.get("request_device") == expected


def test_file_command_and_synthetic_binding_do_not_share_device(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()
    bridge.settings = {"include_input_device_context": True}
    bridge._bind_companion_worker = lambda worker, *_args, **_kwargs: setattr(
        worker, "companion_request_ref", ref("pc")
    )
    bridge._start_ai_worker(
        "가상 문서 결과", companion_file_result=True, request_ref=ref("pc")
    )
    assert bridge.worker.kwargs.get("request_device") is None


@pytest.mark.parametrize(
    "images,use_memory", [([], True), ([{"dataUrl": "synthetic"}], True), ([], False)]
)
@pytest.mark.parametrize("device", [None, "pc", "mobile"])
def test_worker_forwards_device_without_decorating_input(images, use_memory, device):
    received = []

    class Client:
        async def send_message_with_memory(self, message, *args, **kwargs):
            return self.send_message(message, **kwargs)

        async def send_message_with_images(self, message, *args, **kwargs):
            return self.send_message(message, **kwargs)

        def send_message(self, message, **kwargs):
            received.append((message, kwargs))
            return (
                "가상 배열을 정렬했습니다.",
                "normal",
                None,
                [],
                {},
                [],
                "",
                {},
                [],
                "",
            )

    worker = AIWorker(
        Client(),
        "가상 배열",
        images=images,
        use_memory=use_memory,
        request_device=device,
    )
    worker.run()
    assert len(received) == 1
    assert received[0][0] == "가상 배열"
    assert received[0][1].get("request_device") == device


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_mobile_then_pc_retry_captures_action_device(admission, monkeypatch, kind):
    bridge, _, context, _ = admission
    bridge.settings["include_input_device_context"] = True
    captured = []

    class Worker(FakeWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(kwargs.get("request_device"))

    monkeypatch.setattr(chat_flow, "AIWorker", Worker)
    bridge.llm_client.rollback_last_assistant_turn = lambda: True
    bridge.llm_client.rebuild_context_from_conversation = lambda *_: True
    bridge.submit_mobile_text(
        context, mobile_message(bridge, text="가상 상자를 분류합니다.")
    )
    bridge.worker.reply("가상 분류가 완료되었습니다.")
    if kind == "edit":
        bridge.edit_companion_message(
            command(bridge, "user", text="가상 상자를 색으로 분류합니다.")
        )
    else:
        bridge.reroll_companion_message(command(bridge, "assistant"))
    assert captured == ["mobile", "pc"]
    assert "request_device" not in bridge._last_request_payload
    assert "입력 기기" not in str(bridge.conversation_buffer)
    bridge.worker.reply()


@pytest.mark.parametrize("kind", ["edit", "reroll"])
def test_pc_then_mobile_retry_uses_new_setting(admission, monkeypatch, kind):
    from tests.test_companion_chat_actions import action

    bridge, _, context, _ = admission
    captured = []

    class Worker(FakeWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(kwargs.get("request_device"))

    monkeypatch.setattr(chat_flow, "AIWorker", Worker)
    bridge.settings["include_input_device_context"] = False
    bridge.llm_client.rollback_last_assistant_turn = lambda: True
    bridge.llm_client.rebuild_context_from_conversation = lambda *_: True
    assert bridge.submit_chat_request("가상 선분을 배치합니다.").state == "accepted"
    bridge.worker.reply()
    bridge.settings["include_input_device_context"] = True
    assert (
        bridge.submit_extension(context, action(bridge, context, kind)).fields["state"]
        == "accepted"
    )
    bridge.worker.reply()
    assert captured == [None, "mobile"]
    bridge.settings["include_input_device_context"] = False
    assert (
        bridge.submit_mobile_text(context, mobile_message(bridge, number=997)).state
        == "accepted"
    )
    bridge.worker.reply()
    assert captured == [None, "mobile", None]


def test_prepared_request_captures_setting_when_worker_starts(bridge, monkeypatch):
    from tests.test_companion_bridge_transcript import prepare

    captured = []

    class Worker(FakeWorker):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            captured.append(kwargs.get("request_device"))

    monkeypatch.setattr(chat_flow, "AIWorker", Worker)
    bridge.settings["include_input_device_context"] = False
    request = prepare(bridge, "가상 타일을 배치합니다.")
    bridge.settings["include_input_device_context"] = True
    bridge._commit_prepared_chat_request(request)
    assert captured == ["pc"]
    bridge.settings["include_input_device_context"] = False
    assert captured == ["pc"]
    bridge.worker.reply()


def test_synthetic_default_ref_does_not_count_as_user_input(monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", _DummyWorker)
    bridge = _DummyBridge()
    bridge.settings = {"include_input_device_context": True}
    bridge._bind_companion_worker = lambda worker, *_args, **_kwargs: setattr(
        worker, "companion_request_ref", ref("pc")
    )
    bridge._start_ai_worker("가상 자동 발화")
    assert bridge.worker.kwargs.get("request_device") is None


def test_cancelled_worker_never_sends_device():
    class Client:
        def send_message(self, *_args, **_kwargs):
            pytest.fail("취소된 요청은 전송되면 안 된다")

    worker = AIWorker(Client(), "가상 요청", use_memory=False, request_device="mobile")
    worker.requestInterruption()
    worker.run()
