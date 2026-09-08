"""실제 Qt 대기 신호와 별도 asyncio 스레드 사이의 수락 장벽을 검증한다."""

import asyncio
from dataclasses import FrozenInstanceError
import threading
import time

from PyQt6.QtCore import QThread
from PyQt6.QtWidgets import QApplication
import pytest

from src.core.companion.protocol import decode_message, encode_message
from src.core.companion.transcript import CurrentConversationTranscript
from tests.companion_helpers import sample_id


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


class SyntheticOwner:
    def __init__(self):
        self.transcript = CurrentConversationTranscript()
        self.thread_ids = []
        self.submitted = []

    def head(self):
        from src.core.companion.adapter import ConversationHead

        self.thread_ids.append(QThread.currentThread())
        return ConversationHead(
            self.transcript.server_epoch, self.transcript.conversation_id
        )

    def capture(self, generation, pending):
        from src.core.companion.session import SyncCapture

        self.thread_ids.append(QThread.currentThread())
        return SyncCapture(self.transcript.capture())

    def submit(self, context, message):
        self.thread_ids.append(QThread.currentThread())
        self.submitted.append(message)
        return message


def run_adapter(qt_app, adapter, scenario, *, before_events=None, on_event=None):
    loop = asyncio.new_event_loop()
    adapter.attach(loop, on_event or (lambda message: None))
    outcome = []

    def worker():
        asyncio.set_event_loop(loop)
        try:
            outcome.append(loop.run_until_complete(scenario()))
        except BaseException as error:
            outcome.append(error)
        finally:
            loop.close()

    thread = threading.Thread(target=worker, name="companion-test-network")
    thread.start()
    try:
        if before_events:
            before_events(loop)
        deadline = time.monotonic() + 8
        while thread.is_alive() and time.monotonic() < deadline:
            qt_app.processEvents()
            thread.join(0.001)
        assert not thread.is_alive(), "네트워크 시험 스레드가 종료되지 않음"
        if isinstance(outcome[0], BaseException):
            raise outcome[0]
        return outcome[0]
    finally:
        if not thread.is_alive():
            adapter.detach()


def context(connection=1, registration=1):
    from src.core.companion.adapter import AdmissionContext

    return AdmissionContext(sample_id(500), registration, sample_id(connection))


def send_message(owner):
    return decode_message(
        encode_message(
            {
                "type": "send_text",
                "protocol_version": 1,
                "server_epoch": owner.transcript.server_epoch,
                "conversation_id": owner.transcript.conversation_id,
                "request_id": sample_id(30),
                "text": "가상의 삼각형",
            }
        )
    )


def test_adapter_dispatches_only_on_qt_thread_and_returns_correlated_results(qt_app):
    from src.core.companion.adapter import QtGatewayAdapter

    owner = SyntheticOwner()
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)

    async def scenario():
        head = await adapter.call("connect", context())
        snapshot = await adapter.call("capture", context(), pending=(sample_id(30),))
        message = send_message(owner)
        result = await adapter.call("send", context(), message=message)
        assert head.conversation_id == snapshot.transcript.conversation_id
        assert result == message

    run_adapter(qt_app, adapter, scenario)
    assert owner.thread_ids and all(
        item == qt_app.thread() for item in owner.thread_ids
    )
    assert len(owner.submitted) == 1
    with pytest.raises(FrozenInstanceError):
        context().registration_generation = 2


def test_block_restore_and_registration_change_reject_old_context(qt_app):
    from src.core.companion.adapter import AdapterError, QtGatewayAdapter

    owner = SyntheticOwner()
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)

    async def scenario():
        await adapter.call("connect", context())
        await adapter.call("block", context())
        with pytest.raises(AdapterError, match="admission_blocked"):
            await adapter.call("send", context(), message=send_message(owner))
        await adapter.call("restore", context())
        await adapter.call("send", context(), message=send_message(owner))
        await adapter.call("block", context())
        await adapter.call("register", context(2, 2))
        with pytest.raises(AdapterError, match="stale_registration"):
            await adapter.call("capture", context())
        await adapter.call("connect", context(2, 2))
        await adapter.call("capture", context(2, 2))

    run_adapter(qt_app, adapter, scenario)
    assert len(owner.submitted) == 1


def test_new_connection_and_old_disconnect_cannot_reactivate_old_requests(qt_app):
    from src.core.companion.adapter import AdapterError, QtGatewayAdapter

    owner = SyntheticOwner()
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)

    async def scenario():
        await adapter.call("connect", context())
        await adapter.call("connect", context(2))
        await adapter.call("disconnect", context())
        with pytest.raises(AdapterError, match="stale_connection"):
            await adapter.call("send", context(), message=send_message(owner))
        await adapter.call("send", context(2), message=send_message(owner))

    run_adapter(qt_app, adapter, scenario)
    assert len(owner.submitted) == 1


def test_cancelled_queued_send_has_no_owner_side_effect(qt_app):
    from src.core.companion.adapter import AdapterError, QtGatewayAdapter

    owner = SyntheticOwner()
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)
    ready = threading.Event()

    async def scenario():
        task = asyncio.create_task(
            adapter.call("send", context(), message=send_message(owner))
        )
        await asyncio.sleep(0)
        adapter.cancel_connection(context())
        ready.set()
        with pytest.raises(AdapterError, match="stale_connection"):
            await task

    run_adapter(qt_app, adapter, scenario, before_events=lambda loop: ready.wait(2))
    assert owner.submitted == []


def test_timeout_never_executes_late_send_and_capture_queue_is_bounded(qt_app):
    from src.core.companion.adapter import AdapterError, QtGatewayAdapter

    owner = SyntheticOwner()
    adapter = QtGatewayAdapter(owner, timeout=0.02)
    adapter.configure(sample_id(500), 1)
    ready = threading.Event()

    async def scenario():
        with pytest.raises(AdapterError, match="adapter_timeout"):
            await adapter.call("capture", context())
        with pytest.raises(AdapterError, match="adapter_busy"):
            await adapter.call("capture", context())
        with pytest.raises(AdapterError, match="adapter_timeout"):
            await adapter.call("send", context(), message=send_message(owner))
        ready.set()
        while adapter.pending_count:
            await asyncio.sleep(0.001)

    run_adapter(qt_app, adapter, scenario, before_events=lambda loop: ready.wait(2))
    assert not owner.thread_ids
    assert not owner.submitted


def test_local_disable_invalidates_already_queued_gateway_requests(qt_app):
    from src.core.companion.adapter import AdapterError, QtGatewayAdapter

    owner = SyntheticOwner()
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)
    ready = threading.Event()

    async def scenario():
        task = asyncio.create_task(adapter.call("connect", context()))
        await asyncio.sleep(0)
        ready.set()
        with pytest.raises(AdapterError, match="stale_gateway"):
            await task

    def disable_before_events(loop):
        assert ready.wait(2)
        adapter.disable()

    run_adapter(qt_app, adapter, scenario, before_events=disable_before_events)
    assert not owner.thread_ids


def test_event_delivery_is_immutable_and_uses_server_loop(qt_app):
    from src.core.companion.adapter import QtGatewayAdapter

    owner = SyntheticOwner()
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)
    ready = threading.Event()
    received = []

    async def scenario():
        ready.set()
        while not received:
            await asyncio.sleep(0.001)
        assert received[0][0].type == "event"
        assert received[0][1] == threading.get_ident()

    def publish(loop):
        assert ready.wait(2)
        adapter.publish(owner.transcript.append_user("가상의 정사각형"))

    run_adapter(
        qt_app,
        adapter,
        scenario,
        before_events=publish,
        on_event=lambda event: received.append((event, threading.get_ident())),
    )
