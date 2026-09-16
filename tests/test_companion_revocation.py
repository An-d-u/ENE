"""종료·등록 교체 이후 Qt 큐에 남은 명령이 새 요청을 만들지 못한다."""

import asyncio
from dataclasses import replace
import threading

import pytest

from src.core.companion.adapter import AdapterError, QtGatewayAdapter
from tests.companion_helpers import sample_id
from tests.test_companion_adapter import (
    SyntheticOwner,
    context,
    qt_app,
    run_adapter,
    send_message,
)  # noqa: F401
from tests.test_companion_admission import admission, connect, mobile_message  # noqa: F401
from tests.test_companion_bridge_transcript import bridge  # noqa: F401


def test_disable_completes_network_wait_without_processing_qt_queue(qt_app):
    owner = SyntheticOwner()
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)
    queued = threading.Event()
    finished = threading.Event()

    async def scenario():
        request = asyncio.create_task(adapter.call("connect", context()))
        await asyncio.sleep(0)
        queued.set()
        with pytest.raises(AdapterError, match="stale_gateway"):
            await request
        finished.set()

    def before_events(loop):
        assert queued.wait(2)
        adapter.disable()
        assert finished.wait(0.5), "종료는 Qt queued ACK에 의존하면 안 된다"

    run_adapter(qt_app, adapter, scenario, before_events=before_events)
    assert owner.thread_ids == []


def test_new_gateway_deduplicates_same_registration_but_revocation_blocks_old(
    admission,
):
    bridge, adapter, old_context, counts = admission
    message = mobile_message(bridge)
    accepted = bridge.submit_mobile_text(old_context, message)
    adapter.disable()
    new_context = replace(
        old_context,
        gateway_generation=sample_id(501),
        connection_generation=sample_id(601),
    )
    adapter.configure(
        new_context.gateway_generation, new_context.registration_generation
    )
    connect(adapter, new_context)
    assert (
        bridge.submit_mobile_text(new_context, message).message_id
        == accepted.message_id
    )
    assert counts["worker"] == 1
    bridge.worker.reply()
    adapter.configure(new_context.gateway_generation, 2)
    assert bridge.submit_mobile_text(new_context, message).state == "rejected"
    assert counts["worker"] == 1


def test_call_created_after_disable_fails_without_qt_dispatch(qt_app):
    adapter = QtGatewayAdapter(SyntheticOwner())
    adapter.configure(sample_id(500), 1)
    loop = asyncio.new_event_loop()
    adapter.attach(loop, lambda *_: None)
    adapter.disable()
    try:
        with pytest.raises(AdapterError, match="stale_gateway"):
            loop.run_until_complete(
                asyncio.wait_for(adapter.call("connect", context()), 0.1)
            )
        assert adapter.pending_count == 0
    finally:
        loop.close()
        adapter.detach()
