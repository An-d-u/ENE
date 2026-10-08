"""실제 Qt 어댑터와 TLS를 통해 표시 설정을 조회한다."""

import pytest
from dataclasses import replace
from threading import Event
from PyQt6.QtWidgets import QApplication

from tests.test_companion_admission import admission  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_adapter import run_adapter
from tests.test_companion_gateway import harness


@pytest.mark.parametrize("offered", [[], ["chat_display_v1"]])
def test_tls_query_and_effective_change_without_media(admission, tmp_path, offered):
    owner, adapter, _, counts = admission
    before = owner.chat_state.public_transcript.capture()
    gateways = []
    display = owner._ensure_companion_chat_display()
    change_requested = Event()

    async def until(ws, kind):
        while True:
            frame = await ws.receive_json(timeout=3)
            if frame["type"] == kind:
                return frame

    async def scenario():
        async with harness(tmp_path, capabilities=("chat_display_v1",)) as (gateway, client, base, token, _, _):
            gateway.adapter = adapter
            gateways.append(gateway)
            ws = await client.ws_connect(base + "/ws", headers={"Authorization": "Bearer " + token})
            await ws.send_json({"type": "hello", "protocol_version": 1, "capabilities": offered})
            ready = await until(ws, "ready")
            assert ready.get("capabilities", []) == offered
            if offered:
                ext = await until(ws, "extensions_ready")
                await ws.send_json({"type": "chat_display_request", "protocol_version": 1,
                    **{key: ext[key] for key in ("registration_generation", "server_epoch", "connection_generation")}})
                state = await until(ws, "chat_display_state")
                assert state["display_revision"] == 0
                assert state["message_split_enabled"] is False
                # Qt 쪽 유효 설정 변경은 어댑터의 기존 GUI 호출 경계를 통한다.
                change_requested.set()
                state = await until(ws, "chat_display_state")
                assert state["display_revision"] == 1
                assert state["message_split_enabled"] is True
            await ws.close()

    def on_tick():
        if change_requested.is_set():
            change_requested.clear()
            display.settings_changed(True)

    from PyQt6.QtCore import QTimer
    timer = QTimer()
    timer.timeout.connect(on_tick)
    timer.start(5)
    try:
        run_adapter(QApplication.instance(), adapter, scenario,
                    on_event=lambda message: gateways[-1].publish(message) if gateways else None)
    finally:
        timer.stop()
    after = owner.chat_state.public_transcript.capture()
    # capture마다 새로 발급되는 전송 식별자 외의 모든 대화 상태는 보존한다.
    assert replace(after, snapshot_id=before.snapshot_id) == before
    assert counts == {"prompt": 0, "memory": 0, "mood": 0, "conversation": 0, "worker": 0}
