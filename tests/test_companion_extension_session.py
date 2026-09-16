"""확장 협상·세대·진행 ACK가 기본 대화 순서와 독립임을 확인한다."""

import asyncio
import pytest

from src.core.companion.protocol import decode_message, encode_message
from tests.companion_helpers import sample_id
from tests.test_companion_gateway import harness, connect, synchronize
from tests.test_companion_media_http import media_connection


@pytest.fixture
def qt_app(monkeypatch):
    from PyQt6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def test_extension_dispatch_rechecks_qt_owner_and_direction(qt_app):
    from src.core.companion.adapter import AdapterError, QtGatewayAdapter
    from tests.test_companion_adapter import SyntheticOwner, context, run_adapter

    owner = SyntheticOwner()
    owner.submit_extension = owner.submit
    adapter = QtGatewayAdapter(owner)
    adapter.configure(sample_id(500), 1)

    async def scenario():
        await adapter.call("connect", context())
        fields = {
            "protocol_version": 1,
            "type": "audio_availability",
            "registration_generation": 1,
            "server_epoch": owner.transcript.server_epoch,
            "connection_generation": context().connection_generation,
            "conversation_id": owner.transcript.conversation_id,
            "available": True,
            "reason": "ready",
        }

        def message(value):
            return decode_message(encode_message(value))

        await adapter.call("extension", context(), message=message(fields))
        with pytest.raises(AdapterError, match="stale_extension"):
            await adapter.call(
                "extension",
                context(),
                message=message(fields | {"conversation_id": sample_id(99)}),
            )
        with pytest.raises(AdapterError, match="unsupported_command"):
            await adapter.call(
                "extension",
                context(),
                message=message(fields | {"type": "audio_status", "mode": "auto"}),
            )

    run_adapter(qt_app, adapter, scenario)
    assert len(owner.submitted) == 1
    assert all(thread == qt_app.thread() for thread in owner.thread_ids)


def test_legacy_hello_never_receives_extension_frames(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            _,
            client,
            base,
            token,
            _,
            _,
        ):
            ws, ready = await connect(client, base, token)
            assert ready["capabilities"] == []
            assert (await synchronize(ws))[0]["type"] == "snapshot_begin"
            await ws.close()

    asyncio.run(scenario())


def test_conversation_reset_discards_an_unsent_audio_start(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            gateway,
            client,
            base,
            token,
            port,
            _,
        ):
            ws, ready, extension, _ = await media_connection(client, base, token)
            start = {
                **extension,
                "type": "audio_start",
                "conversation_id": ready["conversation_id"],
                "message_id": sample_id(901),
                "operation_id": sample_id(902),
                "utterance_id": sample_id(903),
            }
            start.pop("capabilities")
            gateway.publish(decode_message(encode_message(start)))
            port.transcript.reset()
            gateway.publish(
                decode_message(
                    encode_message(
                        {
                            "type": "resync_required",
                            "protocol_version": 1,
                            "server_epoch": port.transcript.server_epoch,
                            "conversation_id": port.transcript.conversation_id,
                            "reason": "gap",
                        }
                    )
                )
            )
            assert (await ws.receive_json(timeout=2))["type"] == "resync_required"
            await ws.close()

    asyncio.run(scenario())


def test_connection_child_task_limits_and_cancellation_are_bounded():
    from src.core.companion.connection_resources import ConnectionResources, MediaError

    async def scenario():
        resources = ConnectionResources()
        entered = asyncio.Queue()

        async def child(kind):
            task = resources.acquire(kind)
            entered.put_nowait(kind)
            try:
                await asyncio.Event().wait()
            finally:
                resources.release(task)

        jobs = [
            asyncio.create_task(child(kind))
            for kind in ("audio", "asset", "asset", "manifest")
        ]
        for _ in jobs:
            await entered.get()
        assert resources.active_count == 4
        for kind in ("audio", "asset", "manifest"):
            with pytest.raises(MediaError, match="resource_busy"):
                resources.acquire(kind)
        resources.cancel()
        await resources.wait_closed()
        assert resources.active_count == 0 and all(job.cancelled() for job in jobs)

    asyncio.run(scenario())


def test_progress_ack_requires_current_generation_and_owner_acceptance(tmp_path):
    async def scenario():
        async with harness(tmp_path, capabilities=("audio_pcm_v1",)) as (
            gateway,
            client,
            base,
            token,
            port,
            _,
        ):
            accepted = []
            original = port.call

            async def call(operation, context, *, message=None, pending=()):
                if operation != "extension":
                    return await original(
                        operation, context, message=message, pending=pending
                    )
                accepted.append(message)
                if message.fields["played_frames"] == 999:
                    return None
                result = message.to_dict()
                result["type"] = "audio_progress_ack"
                result.pop("mouth_open")
                return decode_message(encode_message(result))

            port.call = call
            ws, ready, extension, _ = await media_connection(client, base, token)
            before = port.transcript.capture()
            message = {
                **extension,
                "type": "audio_progress",
                "conversation_id": ready["conversation_id"],
                "message_id": sample_id(901),
                "operation_id": sample_id(902),
                "utterance_id": sample_id(903),
                "played_frames": 100,
                "mouth_open": 0.25,
            }
            message.pop("capabilities")
            await ws.send_json(message | {"connection_generation": sample_id(99)})
            await ws.send_json(message)
            ack = await ws.receive_json(timeout=2)
            assert ack["type"] == "audio_progress_ack" and ack["played_frames"] == 100
            await ws.send_json(message | {"played_frames": 999})
            await ws.send_json(
                {"type": "ping", "protocol_version": 1, "nonce": sample_id(800)}
            )
            assert (await ws.receive_json(timeout=1))["type"] == "pong"
            assert len(accepted) >= 1
            after = port.transcript.capture()
            assert (before.conversation_revision, before.event_seq) == (
                after.conversation_revision,
                after.event_seq,
            )
            await ws.close()

    asyncio.run(scenario())
