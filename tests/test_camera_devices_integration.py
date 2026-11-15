"""실제 페어링·TLS·Qt 요청 경로에 서로 구별되는 합성 창과 카메라를 연결한다."""
import asyncio
from concurrent.futures import Future
from hashlib import sha256
import threading
from types import SimpleNamespace

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QColor, QImage

from src.core.bridge_mixins import chat_flow
from src.core.companion.controller import CompanionController
from src.core.companion.network import Endpoint
from src.core.companion.storage import RegistrationStore
from src.core.companion.tls_identity import TrustAnchor, utc_now
from src.core.screen_frame import ScreenFrame, jpeg_bytes
from tests.companion_helpers import LoopbackClient, NoDiscovery, sample_id
from tests.test_companion_bridge_transcript import FakeWorker, bridge  # noqa: F401
from tests.test_companion_dialog import qt_app, spin  # noqa: F401
from tests.test_companion_input_uploads import picture
from tests.test_companion_media_http import media_connection
from tests.test_companion_media_integration import matching
from tests.test_screen_input_handoff import pc


class DesktopAction(QObject):
    requested = pyqtSignal(object, object)

    def __init__(self):
        super().__init__()
        self.requested.connect(self.perform)

    @pyqtSlot(object, object)
    def perform(self, action, result):
        try:
            result.set_result(action())
        except Exception as exc:
            result.set_exception(exc)

    async def run(self, action):
        result = Future()
        self.requested.emit(action, result)
        return await asyncio.wait_for(asyncio.wrap_future(result), timeout=5)


class CameraWorker(FakeWorker):
    screen_unavailable = pyqtSignal(str, str)


def run_paired_exchange(owner, qt_app, tmp_path, capability, exercise):
    controller = CompanionController(owner, store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
        endpoint_provider=lambda port: (Endpoint("192.0.2.12", port),), discovery_factory=NoDiscovery)
    owner.companion_event.connect(controller.adapter.publish)
    controller.start(port=0, host="127.0.0.1", test_port=True)
    outcome = Future()
    thread = None
    try:
        spin(qt_app, lambda: controller.state.running)
        controller.request_qr()
        spin(qt_app, lambda: controller.state.qr is not None)
        ticket = controller.state.qr

        async def exchange():
            anchor = TrustAnchor.parse(ticket.ca_certificate, ticket.server_id, utc_now())
            base = f"https://{anchor.hostname}:{controller.state.port}/companion/v1"
            async with LoopbackClient(anchor) as client:
                pair = await client.ws_connect(base + "/pair")
                await pair.send_json(dict(type="pair_request", protocol_version=1, pairing_id=ticket.pairing_id,
                    secret=ticket.secret, device_name="합성 카메라 단말"))
                await matching(pair, "pair_pending")
                approved = await pair.receive_json(timeout=5)
                ws, ready, ext, headers = await media_connection(client, base, approved["token"], (capability,))
                scope = {key: ext[key] for key in ("protocol_version", "registration_generation", "server_epoch", "connection_generation")}
                scope["conversation_id"] = ready["conversation_id"]

                await exercise(client, base, ws, ready, headers, scope)
                await ws.close()

        def phone():
            try:
                asyncio.run(exchange())
                outcome.set_result(None)
            except BaseException as exc:
                outcome.set_exception(exc)

        thread = threading.Thread(target=phone, name="synthetic-camera-peer")
        thread.start()
        spin(qt_app, lambda: controller.state.pending is not None or outcome.done())
        if outcome.done():
            outcome.result()
        pending = controller.state.pending
        controller.approve(pending.pairing_id, pending.connection_id)
        spin(qt_app, outcome.done, timeout=18)
        outcome.result()
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread, timeout=7)
        if thread is not None:
            thread.join(timeout=1)


def test_camera_then_desktop_then_phone_without_camera(bridge, qt_app, tmp_path, monkeypatch):
    monkeypatch.setattr(chat_flow, "AIWorker", CameraWorker)
    owner = bridge
    phone_jpeg = picture((96, 64), "JPEG")
    desktop_image = QImage(96, 64, QImage.Format.Format_RGB32)
    desktop_image.fill(QColor("gold"))
    pc_jpeg = jpeg_bytes(desktop_image)
    assert pc_jpeg and pc_jpeg != phone_jpeg
    captures, submitted, observed = [], [], []
    observation_done = threading.Event()

    def observe(_prompt, frame):
        observed.append(frame.read())
        observation_done.set()
        return '{"reply":"","tts":""}'

    owner.llm_client = SimpleNamespace(model_name="synthetic-vision", endpoint="http://127.0.0.1",
        supports_image_input=True, send_screen_question=lambda *args: "", observe_screen_once=observe)
    owner._screen_share = SimpleNamespace(question=True, observe=True, title="합성 창", generation=1,
        question_epoch=1, observe_epoch=1, validate=lambda: True, can_send=lambda value: value == 1)
    owner.away_timer.stop()

    def desktop_frame():
        captures.append(True)
        return ScreenFrame(pc_jpeg, lambda: True)

    owner._capture_question_frame = desktop_frame
    start = owner._start_ai_worker

    def record(*args, **kwargs):
        frame = kwargs.get("screen_frame")
        submitted.append((kwargs["request_ref"].source, frame.read() if frame else None))
        return start(*args, **kwargs)

    owner._start_ai_worker = record
    desktop = DesktopAction()

    async def exercise(client, base, ws, ready, headers, scope):
        async def share(generation, enabled):
            await ws.send_json(dict(**scope, type="camera_share", generation=generation, lens="back",
                                    question=enabled, observe=enabled))
            return await matching(ws, "camera_state", generation=generation)

        async def upload(generation, number):
            digest = sha256(phone_jpeg).hexdigest()
            await ws.send_json(dict(**scope, type="input_reserve", purpose="camera", generation=generation,
                                    command_id=sample_id(number), byte_length=len(phone_jpeg), sha256=digest))
            slot = await matching(ws, "input_reserved")
            async with client.put(base + "/input/" + slot["upload_id"], headers=headers, data=phone_jpeg) as response:
                assert response.status == 200
            return dict(upload_id=slot["upload_id"], sha256=digest, byte_length=len(phone_jpeg), mime="image/jpeg")

        await share(1, False)
        state = await share(2, True)
        assert state["available"] and state["model"] == "synthetic-vision"
        assert not state["observe_allowed"]
        await ws.send_json(dict(**scope, type="camera_question", generation=2, request_id=sample_id(32),
            text="첫 타일의 모양을 알려 주세요.", frame=await upload(2, 31)))
        receipt = await matching(ws, "request_status", request_id=sample_id(32))
        assert receipt["state"] == "accepted", receipt
        await desktop.run(lambda: owner.worker.reply())
        # 양쪽 관찰을 켜도 휴대폰에서 보낸 질문에는 해당 카메라 한 장만 전달한다.
        assert submitted == [("mobile", phone_jpeg)] and not captures
        assert (await share(3, True))["observe_allowed"]
        await ws.send_json(dict(**scope, type="camera_observation", generation=3, frame=await upload(3, 35)))
        assert await asyncio.to_thread(observation_done.wait, 3)
        assert observed == [phone_jpeg] and not captures
        assert await desktop.run(lambda: pc(owner, 33, text="두 번째 타일은 어느 색인가요?")["state"]) == "accepted"
        await desktop.run(lambda: owner.worker.reply())
        assert submitted[-1] == ("pc", pc_jpeg) and len(captures) == 1
        await matching(ws, "camera_state", generation=3, observe_allowed=False)
        state = await share(4, False)
        assert not state["observe_allowed"]
        await ws.send_json(dict(type="send_text", protocol_version=1, server_epoch=ready["server_epoch"],
            conversation_id=ready["conversation_id"], request_id=sample_id(34), text="다음 도형으로 넘어갑니다."))
        await matching(ws, "request_status", request_id=sample_id(34), state="accepted")
        await desktop.run(lambda: owner.worker.reply())
        assert submitted[-1] == ("mobile", None) and len(captures) == 1
        assert not await desktop.run(lambda: bool(owner._ambient_context()))

    run_paired_exchange(owner, qt_app, tmp_path, "camera_v1", exercise)
    assert not owner._message_attachment_records
    assert len(owner.chat_state.public_transcript.capture().messages) == 6

def test_paired_phone_and_pc_share_persisted_intervals_without_camera(bridge, qt_app, tmp_path):
    from src.core.settings import Settings

    config, secret = str(tmp_path / "settings.json"), str(tmp_path / "keys.json")
    bridge.settings = Settings(config, secret)
    desktop = DesktopAction()

    async def exercise(client, base, ws, ready, headers, scope):
        query = sample_id(82)
        await ws.send_json(dict(**scope, type="observation_intervals_get", query_id=query))
        initial = await matching(ws, "observation_intervals_state", query_id=query)
        assert (initial["sample_seconds"], initial["request_seconds"]) == (30, 300)
        query = sample_id(83)
        await ws.send_json(dict(**scope, type="observation_intervals_set", query_id=query,
                                sample_seconds=8, request_seconds=121))
        reply = await matching(ws, "observation_intervals_state", query_id=query)
        assert reply["saved"] and (reply["sample_seconds"], reply["request_seconds"]) == (8, 121)
        assert await desktop.run(bridge.observation_intervals_state) == (8, 121)
        assert await desktop.run(lambda: bridge.set_observation_intervals(12, 90))
        broadcast = await matching(ws, "observation_intervals_state", sample_seconds=12, request_seconds=90)
        assert broadcast["revision"] > reply["revision"] and "query_id" not in broadcast

    run_paired_exchange(bridge, qt_app, tmp_path, "observation_intervals_v1", exercise)
    saved = Settings(config, secret)
    assert (saved.get("observation_sample_seconds"), saved.get("observation_request_seconds")) == (12, 90)
    assert not getattr(bridge, "_mobile_camera", None) and not getattr(bridge, "_screen_share", None)
