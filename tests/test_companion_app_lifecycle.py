"""개인 설정 대신 임시 저장소로 실제 앱의 연결·종료 수명을 검증한다."""

import asyncio
import json
import socket
import threading
import time
from types import SimpleNamespace

from PyQt6.QtCore import QObject, QTimer, pyqtSignal
import pytest

from src.core.app import ENEApplication
from src.core.companion.controller import CompanionController
from src.core.companion.gateway import GatewayState
from src.core.companion.storage import RegistrationStore
from src.core.companion.network import Endpoint
from src.core.companion.tls_identity import TrustAnchor, utc_now
from src.core.settings import Settings
from tests.test_companion_bridge_transcript import bridge  # noqa: F401
from tests.test_companion_dialog import qt_app, spin  # noqa: F401
from tests.test_life_record_app_lifecycle import _shutdown_app
from tests.companion_helpers import LoopbackClient, sample_id


class ControllerDouble(QObject):
    state_changed = pyqtSignal(object)
    operation_failed = pyqtSignal(str)
    stopped = pyqtSignal()

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.calls = []
        self.state = GatewayState(False, None, False, None, None)
        self.has_thread = False
        self.adapter = SimpleNamespace(
            publish=lambda event: self.calls.append(("event", event))
        )

    def start(self, port):
        self.calls.append(("start", port))
        self.has_thread = True

    def stop(self):
        self.calls.append(("stop",))

    request_stop = stop

    def isRunning(self):
        return self.has_thread

    @property
    def finished(self):
        return self.stopped

    def emergency_stop(self):
        self.calls.append(("emergency",))
        self.stop()

    def request_qr(self):
        self.calls.append(("qr",))

    def approve(self, *args):
        self.calls.append(("approve", *args))

    def reject(self, *args):
        self.calls.append(("reject", *args))

    def revoke(self):
        self.calls.append(("revoke",))

    def reset_tls(self):
        self.calls.append(("reset_tls",))


def app_with_settings(bridge, tmp_path, enabled=False):
    app = ENEApplication.__new__(ENEApplication)
    QObject.__init__(app)
    settings = Settings.__new__(Settings)
    settings.config = {"companion_enabled": enabled, "companion_port": 9876}
    settings.secret_config = {}
    settings.config_path = tmp_path / "synthetic-settings.json"
    app.settings = settings
    app.overlay_window = SimpleNamespace(bridge=bridge)
    app._companion_controller_factory = ControllerDouble
    return app


def test_default_off_and_real_bridge_owned_by_app(bridge, tmp_path):
    assert Settings.DEFAULT_CONFIG["companion_enabled"] is False
    assert Settings.DEFAULT_CONFIG["companion_port"] == 8765
    app = app_with_settings(bridge, tmp_path)
    app._init_companion_runtime()
    assert app.companion_controller.owner is bridge
    assert app.companion_controller.calls == []
    bridge.companion_event.emit({"synthetic": True})
    assert app.companion_controller.calls == [("event", {"synthetic": True})]


def test_app_dialog_reuses_one_instance_and_keeps_actions_distinct(bridge, tmp_path):
    app = app_with_settings(bridge, tmp_path)
    app._init_companion_runtime()
    app._show_companion_dialog()
    dialog = app._companion_dialog
    try:
        app._show_companion_dialog()
        assert app._companion_dialog is dialog
        assert dialog.port_spin.value() == 9876
        app.companion_controller.state = GatewayState(True, 9876, True, None, None)
        app._on_companion_state(app.companion_controller.state)
        dialog.qr_button.click()
        dialog.revoke_button.click()
        dialog.enable_check.setChecked(False)
        assert app.companion_controller.calls == [("qr",), ("revoke",), ("stop",)]
    finally:
        dialog.close()


def test_enabled_startup_and_durable_toggle(bridge, tmp_path):
    app = app_with_settings(bridge, tmp_path, enabled=True)
    app._init_companion_runtime()
    assert app.companion_controller.calls == [("start", 9876)]
    app._set_companion_enabled(False, 9876)
    assert app.companion_controller.calls[-1] == ("stop",)
    assert (
        json.loads(app.settings.config_path.read_text(encoding="utf-8"))[
            "companion_enabled"
        ]
        is False
    )


def test_failed_settings_save_cannot_start_listener(bridge, tmp_path, monkeypatch):
    app = app_with_settings(bridge, tmp_path)
    app._init_companion_runtime()
    monkeypatch.setattr(
        "src.core.settings.save_json_data_atomic",
        lambda *_: (_ for _ in ()).throw(OSError("synthetic")),
    )
    app._set_companion_enabled(True, 9876)
    assert app.companion_controller.calls == []
    assert app.settings.get("companion_enabled") is False
    assert app._companion_error_code == "settings_write_failed"


def test_shutdown_blocks_phone_before_bridge_and_drains_without_join(
    qt_app, monkeypatch
):
    app, _, scheduler, order = _shutdown_app(monkeypatch)
    controller = ControllerDouble(None)
    controller.has_thread = True
    controller.stop = lambda: order.append("companion_block")
    app.companion_controller = controller
    app._finish_quit_application()
    assert order.index("companion_block") < order.index("begin_shutdown")
    assert "qapplication_quit" not in order
    assert controller in app._shutdown_worker_refs
    controller.has_thread = False
    controller.stopped.emit()
    while scheduler.pending:
        scheduler.run_next()
    assert "qapplication_quit" in order
    assert app.life_session_tracker.stop_calls == 1


def test_emergency_quit_does_not_need_another_qt_ack(qt_app, monkeypatch):
    app, _, _, _ = _shutdown_app(monkeypatch)
    controller = ControllerDouble(None)
    app.companion_controller = controller
    app._finish_quit_application(_about_to_quit=True)
    assert ("emergency",) in controller.calls


def test_shutdown_timeout_is_not_reported_as_clean(qt_app, monkeypatch, capsys):
    app, _, scheduler, _ = _shutdown_app(monkeypatch, poll_limit=1)
    controller = ControllerDouble(None)
    controller.has_thread = True
    app.companion_controller = controller
    app._finish_quit_application()
    scheduler.run_next()
    assert app.life_session_tracker.stop_calls == 0
    assert "companion_shutdown_failed" in capsys.readouterr().out


def test_twenty_real_tls_start_stop_cycles_keep_same_conversation(
    bridge, qt_app, tmp_path
):
    controller = CompanionController(
        bridge, store_factory=lambda: RegistrationStore(tmp_path / "registration.json")
    )
    bridge.companion_event.connect(controller.adapter.publish)
    original = bridge.head()
    try:
        for _ in range(20):
            controller.start(port=0, host="127.0.0.1", test_port=True)
            assert controller.state.qr is None
            spin(qt_app, lambda: controller.state.running)
            port = controller.state.port
            controller.stop()
            spin(qt_app, lambda: not controller.has_thread)
            assert controller.adapter.pending_count == 0
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        assert bridge.head() == original
        assert not any(
            thread.name == "ene-companion-server" for thread in threading.enumerate()
        )
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread)


def test_port_conflict_never_exposes_qr(bridge, qt_app, tmp_path):
    controller = CompanionController(
        bridge, store_factory=lambda: RegistrationStore(tmp_path / "registration.json")
    )
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        controller.start(port=blocker.getsockname()[1], host="127.0.0.1")
        spin(qt_app, lambda: not controller.has_thread)
    assert controller.state.code == "listen_failed"
    assert controller.state.qr is None


def test_real_controller_emergency_stop_releases_queued_start_without_qt(
    bridge, qt_app, tmp_path
):
    controller = CompanionController(
        bridge, store_factory=lambda: RegistrationStore(tmp_path / "registration.json")
    )
    controller.start(port=0, host="127.0.0.1", test_port=True)
    try:
        deadline = time.monotonic() + 3
        while not controller.adapter.pending_count and time.monotonic() < deadline:
            time.sleep(0.001)
        assert controller.adapter.pending_count
        started = time.monotonic()
        controller.emergency_stop()
        assert time.monotonic() - started < 0.5
        assert not controller.has_thread
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread)


@pytest.mark.parametrize("value", [True, 0, -1, 65536, "8765"])
def test_invalid_saved_port_does_not_start(bridge, tmp_path, value):
    app = app_with_settings(bridge, tmp_path, enabled=True)
    app.settings.config["companion_port"] = value
    app._init_companion_runtime()
    assert app.companion_controller.calls == []
    assert app._companion_error_code == "invalid_port"


def test_real_app_bridge_tls_pairing_chat_and_duplicate_roundtrip(
    bridge, qt_app, tmp_path
):
    from tests.test_companion_gateway import connect, synchronize

    controller = CompanionController(
        bridge,
        store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
        endpoint_provider=lambda port: (Endpoint("192.0.2.10", port),),
    )
    bridge.companion_event.connect(controller.adapter.publish)
    replies = []

    def respond(raw):
        event = json.loads(raw)
        if event.get("op") == "append" and event["message"]["role"] == "user":
            replies.append(event["message"]["id"])
            QTimer.singleShot(
                0, lambda: bridge.worker.reply("가상 도형 전송을 확인했습니다.")
            )

    bridge.chat_display_event.connect(respond)
    outcome = []
    controller.start(port=0, host="127.0.0.1", test_port=True)
    try:
        spin(qt_app, lambda: controller.state.running)
        controller.request_qr()
        spin(qt_app, lambda: controller.state.qr is not None)
        ticket, port = controller.state.qr, controller.state.port

        async def phone():
            anchor = TrustAnchor.parse(
                ticket.ca_certificate, ticket.server_id, utc_now()
            )
            base = f"https://{anchor.hostname}:{port}/companion/v1"
            async with LoopbackClient(anchor) as client:
                pair = await client.ws_connect(base + "/pair")
                await pair.send_json(
                    {
                        "type": "pair_request",
                        "protocol_version": 1,
                        "pairing_id": ticket.pairing_id,
                        "secret": ticket.secret,
                        "device_name": "합성 통신 단말",
                    }
                )
                assert (await pair.receive_json(timeout=2))["type"] == "pair_pending"
                approved = await pair.receive_json(timeout=3)
                ws, ready = await connect(client, base, approved["token"])
                await synchronize(ws)
                request = {
                    "type": "send_text",
                    "protocol_version": 1,
                    "server_epoch": ready["server_epoch"],
                    "conversation_id": ready["conversation_id"],
                    "request_id": sample_id(93),
                    "text": "가상 도형을 전송합니다.",
                }
                for _ in range(2):
                    await ws.send_json(request)
                    while True:
                        response = await ws.receive_json(timeout=3)
                        if (
                            response["type"] == "request_status"
                            and response["state"] == "completed"
                        ):
                            break
                frames = await synchronize(ws)
                assert (
                    next(
                        frame for frame in frames if frame["type"] == "snapshot_begin"
                    )["message_count"]
                    == 2
                )

        def run_phone():
            try:
                asyncio.run(phone())
                outcome.append(None)
            except BaseException as error:
                outcome.append(error)

        phone_thread = threading.Thread(
            target=run_phone, name="synthetic-companion-phone"
        )
        phone_thread.start()
        spin(qt_app, lambda: controller.state.pending is not None or bool(outcome))
        assert not outcome
        pending = controller.state.pending
        controller.approve(pending.pairing_id, pending.connection_id)
        spin(qt_app, lambda: bool(outcome), timeout=10)
        phone_thread.join(0.1)
        if outcome[0] is not None:
            raise outcome[0]
        assert len(replies) == 1
        assert len(bridge.chat_state.public_transcript.capture().messages) == 2
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread, timeout=7)
