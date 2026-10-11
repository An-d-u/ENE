"""실제 Qt와 TLS를 거쳐 합성 사진의 수락·썸네일·삭제까지 검사한다."""

import asyncio
from hashlib import sha256
import threading

from src.core.companion.controller import CompanionController
from src.core.companion.network import Endpoint
from src.core.companion.storage import RegistrationStore
from src.core.companion.tls_identity import TrustAnchor, utc_now
from tests.companion_helpers import LoopbackClient, NoDiscovery, sample_id
from tests.test_companion_bridge_transcript import bridge as synthetic_bridge  # noqa: F401
from tests.test_companion_dialog import qt_app as synthetic_qt_app, spin  # noqa: F401
from tests.test_companion_media_http import media_connection
from tests.test_companion_media_integration import matching
from tests.test_companion_input_uploads import picture


def test_photo_upload_and_thumbnail_over_actual_qt_tls(request, tmp_path):
    owner = request.getfixturevalue("synthetic_bridge")
    app = request.getfixturevalue("synthetic_qt_app")
    outcome = []
    controller = CompanionController(owner, store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
        endpoint_provider=lambda port: (Endpoint("192.0.2.10", port),), discovery_factory=NoDiscovery)
    owner.companion_event.connect(controller.adapter.publish)
    controller.start(port=0, host="127.0.0.1", test_port=True)
    thread = None
    try:
        spin(app, lambda: controller.state.running)
        controller.request_qr()
        spin(app, lambda: controller.state.qr is not None)
        ticket, port = controller.state.qr, controller.state.port

        async def phone():
            anchor = TrustAnchor.parse(ticket.ca_certificate, ticket.server_id, utc_now())
            base = f"https://{anchor.hostname}:{port}/companion/v1"
            async with LoopbackClient(anchor) as client:
                pair = await client.ws_connect(base + "/pair")
                await pair.send_json(dict(type="pair_request", protocol_version=1, pairing_id=ticket.pairing_id,
                                         secret=ticket.secret, device_name="합성 입력 단말"))
                assert (await pair.receive_json(timeout=2))["type"] == "pair_pending"
                approved = await pair.receive_json(timeout=3)
                ws, ready, ext, headers = await media_connection(client, base, approved["token"], ("chat_images_v1",))
                envelope = {key: ext[key] for key in ("protocol_version", "registration_generation", "server_epoch", "connection_generation")}
                envelope["conversation_id"] = ready["conversation_id"]
                data = picture((600, 300))
                digest = sha256(data).hexdigest()
                await ws.send_json(dict(**envelope, type="input_reserve", command_id=sample_id(90), purpose="image", byte_length=len(data), sha256=digest))
                slot = await matching(ws, "input_reserved")
                async with client.put(base + "/input/" + slot["upload_id"], headers=headers, data=data) as response:
                    assert response.status == 200
                await ws.send_json(dict(**envelope, type="chat_images_send", request_id=sample_id(91), text="가상 색상표입니다.",
                    images=[dict(upload_id=slot["upload_id"], byte_length=len(data), sha256=digest, mime="image/png")]))
                # 수락 제어와 공개 이벤트는 별도 큐이므로 도착 순서를 가정하지 않는다.
                accepted = event = None
                for _ in range(30):
                    frame = await ws.receive_json(timeout=3)
                    if frame["type"] == "request_status" and frame["state"] == "accepted":
                        accepted = frame
                    if frame["type"] == "event" and frame["op"] == "append":
                        event = frame
                    if accepted is not None and event is not None:
                        break
                assert accepted is not None and event is not None
                assert event["payload"]["id"] == accepted["message_id"]
                await ws.send_json(dict(**envelope, type="chat_images_request", query_id=sample_id(92),
                    message_id=accepted["message_id"], conversation_revision=event["conversation_revision"]))
                metadata = await matching(ws, "chat_images_state")
                image, = metadata["images"]
                path = base + "/chat-images/" + accepted["message_id"] + "/" + image["id"]
                async with client.get(path, headers=headers) as response:
                    assert response.status == 200
                    assert response.headers["Cache-Control"] == "no-store"
                    assert response.headers["X-ENE-Attachment-Revision"] == str(metadata["attachment_revision"])
                    assert len(await response.read()) <= 128 * 1024
                async with client.get(path) as response:
                    assert response.status == 401
                async with client.get(base + "/chat-images/" + sample_id(95) + "/" + image["id"], headers=headers) as response:
                    assert response.status == 404
                await ws.close()

        def run():
            try:
                asyncio.run(phone())
                outcome.append(None)
            except BaseException as error:
                outcome.append(error)
        thread = threading.Thread(target=run, name="synthetic-input-peer")
        thread.start()
        spin(app, lambda: controller.state.pending is not None or bool(outcome))
        assert not outcome
        pending = controller.state.pending
        controller.approve(pending.pairing_id, pending.connection_id)
        spin(app, lambda: bool(outcome), timeout=15)
        if outcome[0] is not None:
            raise outcome[0]
        assert len(owner.chat_state.public_transcript.capture().messages) == 1
        owner.worker.reply()
    finally:
        controller.stop()
        spin(app, lambda: not controller.has_thread, timeout=7)
        if thread is not None:
            thread.join(1)
