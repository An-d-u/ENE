"""실제 Qt 위젯과 개발 서버 수명만 검사하며 개인 설정을 열지 않는다."""

import asyncio
from dataclasses import replace
import time
import threading

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
import pytest

from src.core.companion.gateway import GatewayState
from src.core.companion.network import Endpoint
from src.core.companion.pairing import PendingPairing
from src.core.companion.tls_identity import TrustAnchor, utc_now
from src.core.companion.storage import RegistrationStore
from tests.companion_helpers import LoopbackClient, sample_id
from tests.test_companion_adapter import SyntheticOwner


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def spin(qt_app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qt_app.processEvents()
        time.sleep(0.001)
    assert predicate(), "Qt 상태 전이가 제한 시간 내 완료되지 않음"


def test_dialog_starts_disabled_explains_tls_and_never_interprets_device_html(
    qt_app,
):
    from src.ui.companion_dialog import CompanionDialog

    dialog = CompanionDialog()
    assert not dialog.enable_check.isChecked()
    assert dialog.port_spin.minimum() == 1 and dialog.port_spin.maximum() == 65535
    assert not dialog.approve_button.isEnabled()
    assert not dialog.qr_button.isEnabled()
    assert "암호화" in dialog.warning_label.text()
    assert "HTTPS/WSS" in dialog.warning_label.text()
    assert "암호화하지 않고" not in dialog.warning_label.text()
    assert dialog.pending_label.textFormat() == Qt.TextFormat.PlainText
    pending = PendingPairing(sample_id(1), sample_id(2), "<b>가상 단말</b>")
    dialog.set_state(GatewayState(True, 8765, False, None, pending))
    assert "<b>가상 단말</b>" in dialog.pending_label.text()
    assert dialog.approve_button.isEnabled()
    assert not dialog.port_spin.isEnabled()
    dialog.close()


def test_dialog_approval_is_explicit_and_qr_is_cleared_on_expiration(qt_app, tmp_path):
    from src.ui.companion_dialog import CompanionDialog

    from tests.test_companion_pairing import service as make_service

    service, _clock = make_service(tmp_path)
    ticket = service.issue_qr((Endpoint("192.0.2.10", 8765),))
    pending = service.request(
        ticket.pairing_id, ticket.secret, sample_id(2), "가상 단말"
    )
    dialog = CompanionDialog()
    approvals = []
    dialog.approve_requested.connect(
        lambda pairing, connection: approvals.append((pairing, connection))
    )
    state = GatewayState(True, 8765, False, ticket, pending)
    dialog.set_state(state)
    assert not approvals
    assert not dialog.qr_label.pixmap().isNull()
    dialog.approve_button.click()
    assert approvals == [(ticket.pairing_id, sample_id(2))]
    dialog.set_state(replace(state, qr=None, pending=None))
    assert dialog.qr_label.pixmap().isNull()
    assert not dialog.approve_button.isEnabled()
    dialog.close()


def test_controller_start_stop_is_nonblocking_and_releases_server_thread(
    qt_app, tmp_path
):
    from src.core.companion.controller import CompanionController

    owner = SyntheticOwner()
    controller = CompanionController(
        owner,
        store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
        endpoint_provider=lambda port: (Endpoint("192.0.2.10", port),),
    )
    started = time.monotonic()
    controller.start(port=0, host="127.0.0.1", test_port=True)
    assert time.monotonic() - started < 0.5
    spin(qt_app, lambda: controller.state.running)
    bound_port = controller.state.port
    controller.request_qr()
    spin(qt_app, lambda: controller.state.qr is not None)
    qr = controller.state.qr
    anchor = TrustAnchor.parse(qr.ca_certificate, qr.server_id, utc_now())

    async def inspect_info():
        async with LoopbackClient(anchor) as client:
            async with client.get(
                f"https://{anchor.hostname}:{bound_port}/companion/v1/info"
            ) as response:
                return response.status

    assert asyncio.run(inspect_info()) == 200
    controller.stop()
    spin(qt_app, lambda: not controller.has_thread)
    assert not controller.state.running
    assert controller.adapter.pending_count == 0
    controller.stop()


def test_controller_early_stop_cannot_start_late_listener(qt_app, tmp_path):
    from src.core.companion.controller import CompanionController

    controller = CompanionController(
        SyntheticOwner(),
        store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
    )
    states = []
    controller.state_changed.connect(states.append)
    controller.start(port=0, host="127.0.0.1", test_port=True)
    controller.stop()
    spin(qt_app, lambda: not controller.has_thread)
    assert not any(state.running for state in states)
    assert controller.state.code is None


def test_controller_refuses_user_port_zero_and_qr_without_listener(qt_app, tmp_path):
    from src.core.companion.controller import CompanionController

    controller = CompanionController(
        SyntheticOwner(),
        store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
    )
    with pytest.raises(ValueError):
        controller.start(port=0)
    errors = []
    controller.operation_failed.connect(errors.append)
    controller.request_qr()
    assert errors == ["gateway_unavailable"]
    assert not controller.has_thread


def test_smoke_owner_echoes_once_and_keeps_request_status_for_sync(qt_app):
    from tools.companion_smoke import SyntheticConversation
    from src.core.companion.adapter import AdmissionContext
    from src.core.companion.protocol import decode_message, encode_message

    owner = SyntheticConversation()
    events = []
    owner.publish = events.append
    head = owner.head()
    message = decode_message(
        encode_message(
            {
                "type": "send_text",
                "protocol_version": 1,
                "server_epoch": head.server_epoch,
                "conversation_id": head.conversation_id,
                "request_id": sample_id(20),
                "text": "가상의 오각형",
            }
        )
    )
    context = AdmissionContext(sample_id(500), 1, sample_id(1))
    first = owner.submit(context, message)
    again = owner.submit(context, message)
    snapshot = owner.capture(1, (sample_id(20),))
    assert first == again and first.fields["state"] == "completed"
    assert owner.response_count == 1
    assert len(snapshot.transcript.messages) == 2
    assert snapshot.statuses[0] == first


def test_full_controller_qt_approval_socket_echo_and_duplicate_recovery(
    qt_app, tmp_path
):
    from src.core.companion.controller import CompanionController
    from tools.companion_smoke import SyntheticConversation

    owner = SyntheticConversation()
    controller = CompanionController(
        owner,
        store_factory=lambda: RegistrationStore(tmp_path / "registration.json"),
        endpoint_provider=lambda port: (Endpoint("192.0.2.10", port),),
    )
    owner.publish = controller.adapter.publish
    controller.start(port=0, host="127.0.0.1", test_port=True)
    try:
        spin(qt_app, lambda: controller.state.running)
        controller.request_qr()
        spin(qt_app, lambda: controller.state.qr is not None)
        ticket, port = controller.state.qr, controller.state.port
        outcome = []

        async def phone():
            from tests.test_companion_gateway import connect, synchronize

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
                        "device_name": "루프백 가상 단말",
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
                    "request_id": sample_id(45),
                    "text": "합성 육각형",
                }
                for _ in range(2):
                    await ws.send_json(request)
                    while True:
                        response = await ws.receive_json(timeout=2)
                        if response["type"] == "request_status":
                            assert response["state"] == "completed"
                            break
                frames = await synchronize(ws)
                begin = next(
                    frame for frame in frames if frame["type"] == "snapshot_begin"
                )
                assert begin["message_count"] == 2

        def worker():
            try:
                asyncio.run(phone())
                outcome.append(None)
            except BaseException as error:
                outcome.append(error)

        thread = threading.Thread(target=worker, name="companion-test-phone")
        thread.start()
        spin(qt_app, lambda: controller.state.pending is not None or bool(outcome))
        assert not outcome
        pending = controller.state.pending
        controller.approve(pending.pairing_id, pending.connection_id)
        spin(qt_app, lambda: bool(outcome), timeout=10)
        thread.join(0.1)
        if outcome[0] is not None:
            raise outcome[0]
        assert owner.response_count == 1
        assert len(owner.transcript.capture().messages) == 2
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread, timeout=7)


def test_tls_reset_requires_explicit_local_confirmation(qt_app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox
    from src.ui.companion_dialog import CompanionDialog

    dialog = CompanionDialog()
    calls = []
    dialog.tls_reset_requested.connect(lambda: calls.append(True))
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.StandardButton.No
    )
    dialog.tls_reset_button.click()
    assert calls == []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    dialog.tls_reset_button.click()
    assert calls == [True]
    dialog.set_state(GatewayState(True, 8765, False, None, None))
    assert not dialog.tls_reset_button.isEnabled()
    dialog.close()


def test_local_tls_reset_repairs_missing_key_without_touching_conversation(
    qt_app, tmp_path
):
    from src.core.companion.controller import CompanionController
    from src.core.companion.tls_storage import TlsIdentityStore

    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration) as store:
        first = store.load_or_create()
        (store.directory.path / "identity.json").unlink()
    owner = SyntheticOwner()
    before = owner.transcript.capture()
    controller = CompanionController(owner, store_factory=lambda: registration)
    controller.start(port=0, host="127.0.0.1", test_port=True)
    spin(qt_app, lambda: not controller.has_thread)
    assert controller.state.code == "tls_repair_required"
    started = time.monotonic()
    controller.reset_tls()
    assert time.monotonic() - started < 0.5
    spin(qt_app, lambda: not controller.has_thread)
    assert controller.state.code == "tls_reset_complete"
    assert registration.load_or_create().ca_sha256 != first.ca_sha256
    # 캡처마다 새로 발급되는 전송 식별자는 제외하고 대화·처리 상태 전체를 비교한다.
    assert replace(owner.transcript.capture(), snapshot_id=before.snapshot_id) == before
    controller.start(port=0, host="127.0.0.1", test_port=True)
    try:
        spin(qt_app, lambda: controller.state.running)
        errors = []
        controller.operation_failed.connect(errors.append)
        controller.reset_tls()
        assert errors == ["tls_stop_first"]
    finally:
        controller.stop()
        spin(qt_app, lambda: not controller.has_thread)
