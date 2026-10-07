"""실제 Qt 표시와 TLS 세션을 합성 대화로 연결한다."""

import json

from PyQt6.QtWidgets import QApplication

from tests.test_companion_admission import admission  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_edit_reroll import completed_pair
from tests.test_companion_adapter import run_adapter
from tests.test_companion_gateway import harness


def test_real_display_thought_is_available_only_in_negotiated_tls_extension(admission, tmp_path):
    owner, adapter, _, _ = admission
    completed_pair(admission)
    captured = owner.chat_state.public_transcript.capture()
    answer = captured.messages[-1]
    owner._emit_pc_message(
        owner.chat_state.public_transcript.replace(answer.id, answer.text, expected_revision=captured.conversation_revision),
        thought="가상 종이배의 균형을 살펴본다.",
    )
    current = owner.chat_state.public_transcript.capture()
    assert "thought" not in json.loads(current.to_bytes())["messages"][-1]
    gateways = []

    async def until(ws, kind):
        while True:
            frame = await ws.receive_json(timeout=3)
            if frame["type"] == kind:
                return frame

    async def scenario():
        async with harness(tmp_path, capabilities=("message_thoughts_v1",)) as (gateway, client, base, token, _, _):
            gateway.adapter = adapter
            gateways.append(gateway)
            ws = await client.ws_connect(base + "/ws", headers={"Authorization": "Bearer " + token})
            await ws.send_json({"type": "hello", "protocol_version": 1, "capabilities": ["message_thoughts_v1"]})
            ready = await until(ws, "ready")
            ext = await until(ws, "extensions_ready")
            await ws.send_json({"type": "sync_request", "protocol_version": 1})
            await until(ws, "snapshot_end")
            await ws.send_json({"type": "thought_request", "protocol_version": 1,
                **{key: ready[key] for key in ("registration_generation", "server_epoch", "conversation_id")},
                "connection_generation": ext["connection_generation"], "query_id": answer.id,
                "message_id": answer.id, "conversation_revision": current.conversation_revision})
            response = await until(ws, "thought_response")
            assert response["status"] == "available"
            assert response["text"] == "가상 종이배의 균형을 살펴본다."
            await ws.close()

    run_adapter(QApplication.instance(), adapter, scenario,
                on_event=lambda message: gateways[-1].publish(message) if gateways else None)
