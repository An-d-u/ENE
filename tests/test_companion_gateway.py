"""외부 접속 없는 실제 루프백 HTTPS/WSS 시험. 데이터는 모두 합성한다."""

import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import json

import aiohttp
import pytest

from src.core.companion.adapter import ConversationHead
from src.core.companion.network import Endpoint
from src.core.companion.pairing import PairingService
from src.core.companion.protocol import decode_message, encode_message
from src.core.companion.session import SyncCapture
from src.core.companion.storage import RegistrationStore
from src.core.companion.tls_identity import TrustAnchor, utc_now
from src.core.companion.tls_storage import TlsIdentityStore
from src.core.companion.transcript import CurrentConversationTranscript
from tests.companion_helpers import FakeClock, LoopbackClient, sample_id


class SyntheticPort:
    def __init__(self):
        self.transcript = CurrentConversationTranscript()
        self.calls = []
        self.cancelled = []

    async def call(self, operation, context, *, message=None, pending=()):
        self.calls.append((operation, context))
        if operation == "connect":
            return ConversationHead(
                self.transcript.server_epoch, self.transcript.conversation_id
            )
        if operation == "capture":
            return SyncCapture(self.transcript.capture())
        if operation == "send":
            return decode_message(
                encode_message(
                    {
                        "type": "request_status",
                        "protocol_version": 1,
                        "server_epoch": self.transcript.server_epoch,
                        "conversation_id": self.transcript.conversation_id,
                        "request_id": message.fields["request_id"],
                        "state": "reserved",
                    }
                )
            )

    def cancel_connection(self, context):
        self.cancelled.append(context)


@asynccontextmanager
async def harness(tmp_path, *, registered=True, tls_clock=utc_now, **options):
    from src.core.companion.gateway import CompanionGateway

    clock = FakeClock()
    registration = RegistrationStore(tmp_path / "registration.json")
    with TlsIdentityStore(registration, clock=tls_clock) as tls_store:
        identity = tls_store.load_or_create()
        anchor = TrustAnchor.parse(
            identity.ca_certificate, identity.server_id, tls_clock()
        )
        pairing = PairingService(
            registration,
            trust_anchor=anchor,
            tls_now=tls_clock,
            monotonic=clock.monotonic,
            utcnow=clock.utcnow,
        )
        token = None
        if registered:
            ticket = pairing.issue_qr((Endpoint("192.0.2.10", 8765),))
            pairing.request(
                ticket.pairing_id, ticket.secret, sample_id(50), "가상 단말"
            )
            token = pairing.approve(ticket.pairing_id, sample_id(50)).token
        port = SyntheticPort()
        gateway = CompanionGateway(
            pairing,
            port,
            sample_id(500),
            tls_store=tls_store,
            tls_clock=tls_clock,
            **options,
        )
        await gateway.start("127.0.0.1", 0)
        client = LoopbackClient(anchor)
        try:
            yield (
                gateway,
                client,
                f"https://{identity.hostname}:{gateway.port}/companion/v1",
                token,
                port,
                clock,
            )
        finally:
            await client.close()
            await gateway.stop()


async def connect(client, base, token):
    ws = await client.ws_connect(
        base + "/ws", headers={"Authorization": f"Bearer {token}"}
    )
    await ws.send_json({"type": "hello", "protocol_version": 1})
    # 구소켓이 close에 응답하지 않아도 계약의 2초 유예 뒤 새 연결은 진행해야 한다.
    ready = await ws.receive_json(timeout=3)
    assert ready["type"] == "ready"
    return ws, ready


async def synchronize(ws):
    await ws.send_json({"type": "sync_request", "protocol_version": 1})
    frames = []
    while True:
        frame = await ws.receive_json(timeout=2)
        frames.append(frame)
        if frame["type"] == "snapshot_end":
            return frames


def test_info_is_minimal_no_cache_and_browser_or_query_is_rejected(tmp_path):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            async with client.get(base + "/info") as response:
                assert await response.json() == {
                    "server_id": gateway.pairing.registration.server_id,
                    "protocol_versions": [1],
                }
                assert response.headers["Cache-Control"] == "no-store"
                assert "Access-Control-Allow-Origin" not in response.headers
            for suffix, headers in [
                ("/info", {"Origin": "null"}),
                ("/info?token=synthetic", {}),
            ]:
                async with client.get(base + suffix, headers=headers) as response:
                    assert response.status == 403
            assert not port.calls

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "headers", [{}, {"Authorization": "Bearer invalid"}, {"Origin": "null"}]
)
def test_unauthorized_ws_never_accesses_conversation(tmp_path, headers):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            with pytest.raises(aiohttp.WSServerHandshakeError) as error:
                await client.ws_connect(base + "/ws", headers=headers)
            assert error.value.status in {401, 403}
            assert not port.calls

    asyncio.run(scenario())


def test_header_and_hello_then_snapshot_and_text_command(tmp_path):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            port.transcript.append_user("가상의 원")
            ws, ready = await connect(client, base, token)
            send = {
                "type": "send_text",
                "protocol_version": 1,
                "server_epoch": ready["server_epoch"],
                "conversation_id": ready["conversation_id"],
                "request_id": sample_id(20),
                "text": "가상의 타원",
            }
            await ws.send_json(send)
            assert (await ws.receive_json(timeout=1))["code"] == "sync_required"
            assert not any(op == "send" for op, _ in port.calls)
            frames = await synchronize(ws)
            assert frames[0]["message_count"] == 1
            assert frames[0]["sha256"] == frames[-1]["sha256"]
            await ws.send_json(send)
            result = await ws.receive_json(timeout=1)
            assert result["type"] == "request_status" and result["state"] == "reserved"
            assert sum(op == "send" for op, _ in port.calls) == 1
            await ws.close()

    asyncio.run(scenario())


def test_pairing_requires_local_approval_and_durable_barrier_before_token(tmp_path):
    async def scenario():
        async with harness(tmp_path, registered=False) as (
            gateway,
            client,
            base,
            token,
            port,
            clock,
        ):
            ticket = await gateway.issue_qr((Endpoint("192.0.2.10", gateway.port),))
            ws = await client.ws_connect(base + "/pair")
            await ws.send_json(
                {
                    "type": "pair_request",
                    "protocol_version": 1,
                    "pairing_id": ticket.pairing_id,
                    "secret": ticket.secret,
                    "device_name": "가상 시험 단말",
                }
            )
            assert (await ws.receive_json(timeout=1))["type"] == "pair_pending"
            assert not port.calls and gateway.pairing.registration.token_hash is None
            pending = gateway.pairing.pending
            await gateway.approve(pending.pairing_id, pending.connection_id)
            approved = await ws.receive_json(timeout=1)
            assert approved["type"] == "pair_approved"
            assert [op for op, _ in port.calls] == ["block", "register"]
            assert (
                gateway.pairing.authorize(approved["token"]).device_id
                == approved["device_id"]
            )
            normal, _ = await connect(client, base, approved["token"])
            await normal.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("state_refresh", [False, True])
def test_pairing_expiration_closes_pending_even_after_state_refresh(
    tmp_path, state_refresh
):
    async def scenario():
        async with harness(tmp_path, registered=False) as (
            gateway,
            client,
            base,
            token,
            port,
            clock,
        ):
            ticket = await gateway.issue_qr((Endpoint("192.0.2.10", gateway.port),))
            ws = await client.ws_connect(base + "/pair")
            await ws.send_json(
                {
                    "type": "pair_request",
                    "protocol_version": 1,
                    "pairing_id": ticket.pairing_id,
                    "secret": ticket.secret,
                    "device_name": "가상 단말",
                }
            )
            await ws.receive_json(timeout=1)
            clock.advance(120)
            if state_refresh:
                gateway._notify()
            failure = await ws.receive_json(timeout=1)
            assert (
                failure["type"] == "pair_failed"
                and failure["code"] == "pairing_expired"
            )
            assert not port.calls and gateway.pairing.pending is None

    asyncio.run(scenario())


def test_pairing_socket_rejects_conversation_commands_before_approval(tmp_path):
    async def scenario():
        async with harness(tmp_path, registered=False) as (
            gateway,
            client,
            base,
            token,
            port,
            clock,
        ):
            ticket = await gateway.issue_qr((Endpoint("192.0.2.10", gateway.port),))
            ws = await client.ws_connect(base + "/pair")
            await ws.send_json(
                {
                    "type": "pair_request",
                    "protocol_version": 1,
                    "pairing_id": ticket.pairing_id,
                    "secret": ticket.secret,
                    "device_name": "가상 단말",
                }
            )
            await ws.receive_json(timeout=1)
            await ws.send_json({"type": "sync_request", "protocol_version": 1})
            failure = await ws.receive_json(timeout=1)
            assert (
                failure["type"] == "pair_failed"
                and failure["code"] == "unsupported_command"
            )
            assert not port.calls and gateway.pairing.registration.token_hash is None

    asyncio.run(scenario())


def test_new_connection_replaces_old_only_after_hello_and_old_cleanup_is_harmless(
    tmp_path,
):
    async def scenario():
        async with harness(tmp_path, hello_timeout=0.08) as (
            gateway,
            client,
            base,
            token,
            port,
            clock,
        ):
            first, _ = await connect(client, base, token)
            incomplete = await client.ws_connect(
                base + "/ws", headers={"Authorization": f"Bearer {token}"}
            )
            await asyncio.sleep(0.12)
            await incomplete.receive(timeout=1)
            await first.send_json(
                {"type": "ping", "protocol_version": 1, "nonce": sample_id(60)}
            )
            assert (await first.receive_json(timeout=1))["type"] == "pong"
            second, _ = await connect(client, base, token)
            await first.receive(timeout=1)
            await second.send_json(
                {"type": "ping", "protocol_version": 1, "nonce": sample_id(61)}
            )
            assert (await second.receive_json(timeout=1))["nonce"] == sample_id(61)
            assert port.cancelled
            await second.close()

    asyncio.run(scenario())


def test_missing_pong_closes_connection_without_extending_for_other_data(tmp_path):
    async def scenario():
        async with harness(
            tmp_path, heartbeat_interval=0.05, heartbeat_timeout=0.05
        ) as (gateway, client, base, token, port, clock):
            ws, _ = await connect(client, base, token)
            assert (await ws.receive_json(timeout=1))["type"] == "ping"
            await ws.send_json(
                {"type": "pong", "protocol_version": 1, "nonce": sample_id(99)}
            )
            messages = []
            while True:
                item = await ws.receive(timeout=1)
                messages.append(item)
                if item.type in {
                    aiohttp.WSMsgType.CLOSE,
                    aiohttp.WSMsgType.CLOSED,
                    aiohttp.WSMsgType.ERROR,
                }:
                    break
            assert ws.closed

    asyncio.run(scenario())


def test_only_two_preauth_connections_per_address(tmp_path):
    async def scenario():
        async with harness(tmp_path, hello_timeout=1) as (
            gateway,
            client,
            base,
            token,
            port,
            clock,
        ):
            headers = {"Authorization": f"Bearer {token}"}
            first = await client.ws_connect(base + "/ws", headers=headers)
            second = await client.ws_connect(base + "/ws", headers=headers)
            with pytest.raises(aiohttp.WSServerHandshakeError) as error:
                await client.ws_connect(base + "/ws", headers=headers)
            assert error.value.status == 429
            assert not port.calls
            await first.close()
            await second.close()

    asyncio.run(scenario())


def test_server_start_failure_releases_runner_and_stop_is_idempotent(tmp_path):
    from src.core.companion.gateway import CompanionGateway

    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            other = CompanionGateway(
                gateway.pairing,
                SyntheticPort(),
                sample_id(501),
                tls_store=gateway._tls_store,
            )
            with pytest.raises(OSError):
                await other.start("127.0.0.1", gateway.port)
            await other.stop()
            await other.stop()
            async with client.get(base + "/info") as response:
                assert response.status == 200

    asyncio.run(scenario())


@pytest.mark.parametrize("uncertain", [False, True])
def test_registration_write_failure_notifies_pair_and_only_restores_known_old_state(
    tmp_path, uncertain
):
    from src.core.companion.storage import StorageError

    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            old, _ = await connect(client, base, token)
            ticket = await gateway.issue_qr((Endpoint("192.0.2.10", gateway.port),))
            ws = await client.ws_connect(base + "/pair")
            await ws.send_json(
                {
                    "type": "pair_request",
                    "protocol_version": 1,
                    "pairing_id": ticket.pairing_id,
                    "secret": ticket.secret,
                    "device_name": "교체용 가상 단말",
                }
            )
            await ws.receive_json(timeout=1)
            pending = gateway.pairing.pending
            original_writer = gateway.pairing.store._writer

            def failed_writer(path, value):
                if uncertain:
                    original_writer(path, value)
                raise OSError("synthetic_write_failure")

            gateway.pairing.store._writer = failed_writer

            async def read_old_close():
                if uncertain:
                    await old.receive(timeout=3)

            old_reader = asyncio.create_task(read_old_close())
            with pytest.raises(StorageError) as error:
                await gateway.approve(pending.pairing_id, pending.connection_id)
            if uncertain:
                assert error.value.code == "storage_uncertain"
                assert not any(op == "restore" for op, _ in port.calls)
                await ws.receive(timeout=3)
                assert old.closed
            else:
                assert error.value.code == "storage_write_failed"
                assert (await ws.receive_json(timeout=1))[
                    "code"
                ] == "storage_write_failed"
                assert any(op == "restore" for op, _ in port.calls)
                await old.send_json(
                    {"type": "ping", "protocol_version": 1, "nonce": sample_id(62)}
                )
                assert (await old.receive_json(timeout=1))["type"] == "pong"
            await old_reader

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "raw", ["not-json", "x" * 65537], ids=["invalid_json", "oversized"]
)
def test_invalid_or_oversized_messages_close_without_submission(tmp_path, raw):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            ws, _ = await connect(client, base, token)
            await ws.send_str(raw)
            await ws.receive(timeout=1)
            assert ws.closed
            assert not any(op == "send" for op, _ in port.calls)

    asyncio.run(scenario())


def test_restored_old_connection_resynchronizes_changes_made_during_barrier(tmp_path):
    from src.core.companion.storage import StorageError

    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            old, _ = await connect(client, base, token)
            await synchronize(old)
            original_call = port.call

            async def barrier_with_change(operation, context, **kwargs):
                result = await original_call(operation, context, **kwargs)
                if operation == "block":
                    event = port.transcript.append_user("장벽 사이에 추가된 가상 도형")
                    gateway.publish(decode_message(encode_message(event.to_wire())))
                return result

            port.call = barrier_with_change

            def failed_writer(path, value):
                raise OSError("synthetic_write_failure")

            gateway.pairing.store._writer = failed_writer
            with pytest.raises(StorageError):
                await gateway.revoke()
            message = await old.receive_json(timeout=1)
            assert message["type"] == "resync_required"
            begin = await old.receive_json(timeout=1)
            assert begin["type"] == "snapshot_begin" and begin["message_count"] == 1

    asyncio.run(scenario())


def test_large_snapshot_on_real_socket_has_all_messages_and_public_fields_only(
    tmp_path,
):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            for index in range(5000):
                port.transcript.append_user(f"가상 도형 {index}")
            ws, _ = await connect(client, base, token)
            frames = await synchronize(ws)
            data = b"".join(
                base64.b64decode(frame["data_base64"])
                for frame in frames
                if frame["type"] == "snapshot_part"
            )
            assert hashlib.sha256(data).hexdigest() == frames[0]["sha256"]
            payload = json.loads(data)
            assert len(payload["messages"]) == 5000
            assert payload["messages"][0]["text"] == "가상 도형 0"
            assert payload["messages"][-1]["text"] == "가상 도형 4999"
            assert set(payload["messages"][0]) == {"id", "role", "text", "displayed_at"}
            assert len(frames) > 3

    asyncio.run(scenario())


def test_control_message_flood_closes_real_socket(tmp_path):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, clock):
            ws, _ = await connect(client, base, token)
            for _ in range(100):
                await ws.send_json(
                    {"type": "pong", "protocol_version": 1, "nonce": sample_id(98)}
                )
            await ws.receive(timeout=1)
            assert ws.closed
            assert not any(op == "send" for op, _ in port.calls)

    asyncio.run(scenario())
