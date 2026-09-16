"""실제 Qt/TLS와 합성 휴대폰 피어로 음성·대화 완료 수명을 함께 검증한다."""

import asyncio
import json
import threading
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from src.core.companion.controller import CompanionController
from src.core.companion.network import Endpoint
from src.core.companion.storage import RegistrationStore
from src.core.companion.tls_identity import TrustAnchor, utc_now
from tests.companion_helpers import LoopbackClient, sample_id
from tests.test_companion_audio_buffer import wav
from tests.test_companion_bridge_transcript import bridge as synthetic_bridge  # noqa: F401
from tests.test_companion_dialog import qt_app as synthetic_qt_app, spin  # noqa: F401
from tests.test_companion_media_http import media_connection
from tests.test_companion_character_assets import synthetic_model
from tests.test_companion_character_state import CATALOG
from tests.test_companion_character_settings_storage import settings as synthetic_settings  # noqa: F401


async def matching(ws, kind, **fields):
    for _ in range(100):
        frame = await ws.receive_json(timeout=3)
        if frame["type"] == kind and all(frame.get(key) == value for key, value in fields.items()):
            return frame
    raise AssertionError("합성 미디어 응답 상한 초과")


@pytest.mark.parametrize("disconnect", [False, True])
def test_qt_tts_to_authenticated_pcm_keeps_one_output_and_one_completion(
    request, tmp_path, monkeypatch, disconnect
):
    from src.core.bridge_mixins import tts

    bridge = request.getfixturevalue("synthetic_bridge")
    app = request.getfixturevalue("synthetic_qt_app")
    store = request.getfixturevalue("synthetic_settings")
    bridge.settings = store
    path = synthetic_model(tmp_path / "model")
    store.set("model_json_path", str(path))
    character = bridge._ensure_companion_character()
    bridge._companion_prepare_character(path, (), store.config, {})
    bridge.character_catalog_requested.connect(lambda raw: bridge.report_companion_character_catalog(json.dumps({
        **json.loads(raw), "parameters": CATALOG, "expressions": ["normal", "bright"], "gestures": ["nod"],
    })))
    counted = []
    bridge._record_confirmed_head_pat = lambda: counted.append(1)
    pcm = b"\x00\x10" * 4800
    generated, played, outcome = [], [], []

    class Worker(QObject):
        tts_ready = pyqtSignal(bytes, list)
        error_occurred = pyqtSignal(str)

        def __init__(self, *_):
            super().__init__()
            self.running = False

        def start(self):
            self.running = True
            generated.append(1)
            QTimer.singleShot(0, self.complete)

        def complete(self):
            self.running = False
            self.tts_ready.emit(wav(pcm), [])

        def isRunning(self):
            return self.running

        def request_stop(self):
            self.running = False

    monkeypatch.setattr(tts, "TTSWorker", Worker)
    bridge.enable_tts = True
    bridge.tts_client = SimpleNamespace(uses_browser_playback=False, supports_streaming=False)
    bridge.audio_player = SimpleNamespace(play=played.append, stop=lambda: None)
    controller = CompanionController(
        bridge, store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
        endpoint_provider=lambda port: (Endpoint("192.0.2.10", port),),
    )
    bridge.companion_event.connect(controller.adapter.publish)

    def answer(raw):
        event = json.loads(raw)
        if event.get("op") == "append" and event["message"]["role"] == "user":
            QTimer.singleShot(0, lambda: bridge.worker.reply("합성 도형의 배치를 확인했습니다.", spoken="가상의 음성 안내입니다."))

    bridge.chat_display_event.connect(answer)
    controller.start(port=0, host="127.0.0.1", test_port=True)
    thread = None
    try:
        spin(app, lambda: controller.state.running)
        spin(app, lambda: character.state.status == "ready")
        controller.request_qr()
        spin(app, lambda: controller.state.qr is not None)
        ticket, port = controller.state.qr, controller.state.port

        async def phone():
            anchor = TrustAnchor.parse(ticket.ca_certificate, ticket.server_id, utc_now())
            base = f"https://{anchor.hostname}:{port}/companion/v1"
            async with LoopbackClient(anchor) as client:
                pair = await client.ws_connect(base + "/pair")
                await pair.send_json({"type": "pair_request", "protocol_version": 1,
                    "pairing_id": ticket.pairing_id, "secret": ticket.secret, "device_name": "합성 음성 단말"})
                assert (await pair.receive_json(timeout=2))["type"] == "pair_pending"
                approved = await pair.receive_json(timeout=3)
                ws, ready, ext, headers = await media_connection(client, base, approved["token"],
                    ("audio_pcm_v1", "character_v1", "character_controls_v1"))
                envelope = {key: ext[key] for key in ("protocol_version", "registration_generation", "server_epoch", "connection_generation")}
                async with client.get(base + "/character/manifest", headers=headers) as response:
                    assert response.status == 200
                    manifest = await response.json()
                assert manifest["status"] == "ready"
                command = {**envelope, "type": "character_settings_patch", "command_id": sample_id(902),
                    "model_version": manifest["model_version"], "expected_revision": manifest["settings_revision"],
                    "changes": {"head_pat_strength": 1.7}, "parameters": {}}
                await ws.send_json(command)
                result = await matching(ws, "character_settings_result", command_id=sample_id(902))
                assert result["status"] == "accepted"
                async with client.get(base + "/character/manifest", headers=headers) as response:
                    fresh = await response.json()
                assert fresh["settings"]["head_pat_strength"] == 1.7
                assert fresh["settings_revision"] >= result["settings_revision"]
                pat = {**envelope, "type": "head_pat", "model_version": manifest["model_version"],
                    "interaction_id": sample_id(903), "interaction_no": 1, "phase": "start", "seq": 0, "intensity": .4}
                await ws.send_json(pat)
                await matching(ws, "head_pat_state", phase="accepted")
                for _ in range(2):
                    await ws.send_json({**pat, "phase": "end", "seq": 1})
                    await matching(ws, "head_pat_state", phase="ended")
                await ws.send_json({**envelope, "type": "audio_availability", "conversation_id": ready["conversation_id"], "available": True, "reason": "ready"})
                await matching(ws, "audio_status")
                await ws.send_json({"type": "send_text", "protocol_version": 1,
                    "server_epoch": ready["server_epoch"], "conversation_id": ready["conversation_id"],
                    "request_id": sample_id(901), "text": "합성 도형의 위치를 안내합니다."})
                assistant_ids = []
                while True:
                    frame = await ws.receive_json(timeout=3)
                    assert not (frame["type"] == "request_status" and frame["state"] == "completed")
                    if frame["type"] == "event" and frame["op"] == "append" and frame["payload"]["role"] == "assistant":
                        assistant_ids.append(frame["payload"]["id"])
                    if frame["type"] == "audio_offer":
                        offer = frame
                        break
                assert offer["message_id"] in assistant_ids
                async with client.get(base + "/audio/" + offer["utterance_id"], headers=headers) as response:
                    assert response.status == 200
                    assert response.headers["Cache-Control"] == "no-store"
                    assert await response.read() == pcm
                reference = {**envelope, **{key: offer[key] for key in ("conversation_id", "message_id", "operation_id", "utterance_id")}}
                await ws.send_json({**reference, "type": "audio_prepared", "buffered_frames": 4800})
                while True:
                    frame = await ws.receive_json(timeout=3)
                    assert not (frame["type"] == "request_status" and frame["state"] == "completed")
                    if frame["type"] == "audio_start":
                        break
                if disconnect:
                    await ws.close()
                    return
                await ws.send_json({**reference, "type": "audio_progress", "played_frames": 2400, "mouth_open": 0.25})
                while (frame := await ws.receive_json(timeout=3))["type"] != "audio_progress_ack":
                    assert not (frame["type"] == "request_status" and frame["state"] == "completed")
                assert frame["played_frames"] == 2400
                await ws.send_json({**reference, "type": "audio_finished", "played_frames": 4800})
                while (frame := await ws.receive_json(timeout=3))["type"] != "request_status":
                    pass
                assert frame["state"] == "completed"
                await ws.close()

        def run():
            try:
                asyncio.run(phone())
                outcome.append(None)
            except BaseException as error:
                outcome.append(error)

        thread = threading.Thread(target=run, name="synthetic-audio-peer")
        thread.start()
        spin(app, lambda: controller.state.pending is not None or bool(outcome))
        assert not outcome
        pending = controller.state.pending
        controller.approve(pending.pairing_id, pending.connection_id)
        spin(app, lambda: bool(outcome), timeout=12)
        if outcome[0] is not None:
            raise outcome[0]
        spin(app, lambda: bridge.life_record_state.phase == "idle")
        assert generated == [1] and played == []
        assert counted == [1] and store.get("head_pat_strength") == 1.7
        assert bridge._companion_audio.coordinator.active_ref is None
    finally:
        controller.stop()
        spin(app, lambda: not controller.has_thread, timeout=7)
        if thread is not None:
            thread.join(1)
