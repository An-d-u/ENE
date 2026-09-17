"""실제 TLS 통신에서 신뢰 실패가 HTTP·토큰 처리보다 먼저 발생함을 확인한다."""

import asyncio
import json
import ssl
import threading
from datetime import timedelta

import aiohttp
import pytest

from src.core.companion.network import Endpoint
from src.core.companion.tls_identity import TlsIdentity, TrustAnchor, utc_now
from tests.companion_helpers import LoopbackClient, sample_id
from tests.test_companion_gateway import harness, connect, synchronize


def test_tls_info_qr_and_authenticated_websocket(tmp_path):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, _clock):
            async with client.get(base + "/info") as response:
                assert response.status == 200
            qr = await gateway.issue_qr((Endpoint("192.0.2.10", gateway.port),))
            payload = json.loads(qr.to_json())
            assert payload["transport"] == "tls_v1"
            assert len(qr.to_json().encode()) <= 2048
            anchor = TrustAnchor.parse(
                payload["ca_certificate"], payload["server_id"], utc_now()
            )
            assert anchor.sha256 == gateway.pairing.registration.ca_sha256
            ws, _ready = await connect(client, base, token)
            assert (await synchronize(ws))[-1]["type"] == "snapshot_end"

    asyncio.run(scenario())


class RenewalClock:
    def __init__(self):
        self.current = utc_now() - timedelta(days=61)
        self.seconds = 0

    def utcnow(self):
        return self.current

    def monotonic(self):
        return self.seconds

    def advance(self, seconds):
        self.seconds += seconds
        self.current += timedelta(seconds=seconds)


def test_same_ca_renewal_replaces_listener_closes_qr_and_preserves_registration(
    tmp_path,
):
    async def scenario():
        clock = RenewalClock()
        async with harness(
            tmp_path, tls_clock=clock.utcnow, renewal_clock=clock.monotonic
        ) as (gateway, client, base, token, port, _clock):
            before = gateway._tls_identity
            record = gateway.pairing.registration
            await gateway.issue_qr((Endpoint("192.0.2.10", gateway.port),))
            ws, _ = await connect(client, base, token)
            await synchronize(ws)
            clock.advance(61 * 86400)
            await gateway.check_tls()
            assert gateway._renew_task is not None
            await gateway._renew_task
            assert gateway._tls_identity.ca_sha256 == before.ca_sha256
            assert gateway._tls_identity.leaf_certificate != before.leaf_certificate
            assert gateway.pairing.registration == record
            assert gateway.pairing.qr is None
            assert gateway._running
            assert any(operation == "block" for operation, _context in port.calls)
            assert any(operation == "restore" for operation, _context in port.calls)
            async with client.get(base + "/info") as response:
                assert response.status == 200
            again, _ = await connect(client, base, token)
            assert (await synchronize(again))[-1]["type"] == "snapshot_end"

    asyncio.run(scenario())


def test_failed_renewal_has_bounded_retries_but_expiry_still_blocks_access(
    tmp_path, monkeypatch
):
    from src.core.companion.private_files import PrivateFileError

    async def scenario():
        clock = RenewalClock()
        async with harness(
            tmp_path, tls_clock=clock.utcnow, renewal_clock=clock.monotonic
        ) as (gateway, client, base, token, port, _clock):
            attempts = []

            def fail(_identity):
                attempts.append(clock.monotonic())
                raise PrivateFileError("tls_write_failed")

            monkeypatch.setattr(gateway._tls_store, "save", fail)
            clock.advance(61 * 86400)
            for wait in (0, 60, 120, 300):
                clock.advance(wait)
                await gateway.check_tls()
                await gateway._renew_task
                assert gateway._running
            assert len(attempts) == 4
            clock.advance(300)
            await gateway.check_tls()
            assert len(attempts) == 4
            clock.advance(30 * 86400)
            await gateway.check_tls()
            assert not gateway._running and gateway._failure == "tls_expired"
            assert any(operation == "block" for operation, _context in port.calls)

    asyncio.run(scenario())


def test_uncertain_renewal_write_closes_admission_immediately(tmp_path, monkeypatch):
    from src.core.companion.private_files import PrivateFileError

    async def scenario():
        clock = RenewalClock()
        async with harness(
            tmp_path, tls_clock=clock.utcnow, renewal_clock=clock.monotonic
        ) as (gateway, client, base, token, port, _clock):

            def fail(_identity):
                raise PrivateFileError("tls_storage_uncertain")

            monkeypatch.setattr(gateway._tls_store, "save", fail)
            clock.advance(61 * 86400)
            await gateway.check_tls()
            await gateway._renew_task
            assert not gateway._running
            assert gateway._failure == "tls_storage_uncertain"

    asyncio.run(scenario())


def test_expired_active_socket_cannot_submit_a_command(tmp_path):
    async def scenario():
        clock = RenewalClock()
        async with harness(
            tmp_path, tls_clock=clock.utcnow, renewal_clock=clock.monotonic
        ) as (gateway, client, base, token, port, _clock):
            ws, ready = await connect(client, base, token)
            await synchronize(ws)
            clock.advance(91 * 86400)
            await ws.send_json(
                {
                    "type": "send_text",
                    "protocol_version": 1,
                    "server_epoch": ready["server_epoch"],
                    "conversation_id": ready["conversation_id"],
                    "request_id": sample_id(73),
                    "text": "합성 도형",
                }
            )
            item = await ws.receive(timeout=3)
            assert item.type in {aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED}
            assert not any(operation == "send" for operation, _context in port.calls)

    asyncio.run(scenario())


def test_stop_waits_for_stalled_handshakes_without_leaving_a_listener(tmp_path):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, _token, _port, _clock):
            reader, writer = await asyncio.open_connection("127.0.0.1", gateway.port)
            try:
                await asyncio.wait_for(gateway.stop(), 7)
                try:
                    assert await asyncio.wait_for(reader.read(1), 1) == b""
                except ConnectionResetError:
                    pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionResetError:
                    pass

    asyncio.run(scenario())


def test_repeated_listener_stop_and_cancelled_waiter_still_drain_handshake(tmp_path):
    async def scenario():
        async with harness(tmp_path) as (gateway, _client, _base, _token, _port, _clock):
            site = gateway._site
            reader, writer = await asyncio.open_connection("127.0.0.1", gateway.port)
            try:
                await site.stop()
                await site.stop()
                waiting = asyncio.create_task(site.wait_closed())
                await asyncio.sleep(0)
                assert not waiting.done()
                waiting.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await waiting
                await asyncio.wait_for(site.wait_closed(), 7)
                try:
                    assert await asyncio.wait_for(reader.read(1), 1) == b""
                except ConnectionResetError:
                    pass
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except ConnectionResetError:
                    pass

    asyncio.run(scenario())


def test_handshake_completed_during_renewal_cannot_keep_old_listener_alive(tmp_path):
    from cryptography.hazmat.primitives import serialization

    async def scenario():
        clock = RenewalClock()
        async with harness(
            tmp_path, tls_clock=clock.utcnow, renewal_clock=clock.monotonic
        ) as (gateway, client, base, _token, _port, _clock):
            old_site = gateway._site
            identity = gateway._tls_identity
            reader, writer = await asyncio.open_connection("127.0.0.1", gateway.port)
            try:
                clock.advance(61 * 86400)
                await gateway.check_tls()
                async with asyncio.timeout(2):
                    while old_site._server.is_serving():
                        await asyncio.sleep(0.001)
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.load_verify_locations(
                    cadata=identity.ca.public_bytes(serialization.Encoding.PEM).decode(
                        "ascii"
                    )
                )
                try:
                    await writer.start_tls(context, server_hostname=identity.hostname)
                    writer.write(
                        f"GET /companion/v1/info HTTP/1.1\r\nHost: {identity.hostname}\r\n\r\n".encode(
                            "ascii"
                        )
                    )
                    await writer.drain()
                except (ConnectionError, ssl.SSLError):
                    pass
                await asyncio.wait_for(asyncio.shield(gateway._renew_task), 2)
                assert gateway._running
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except (ConnectionError, ssl.SSLError):
                    pass

    asyncio.run(scenario())


def test_stop_during_key_write_waits_for_worker_and_never_reopens_listener(
    tmp_path, monkeypatch
):
    async def scenario():
        clock = RenewalClock()
        async with harness(
            tmp_path, tls_clock=clock.utcnow, renewal_clock=clock.monotonic
        ) as (gateway, client, base, _token, _port, _clock):
            entered, release = threading.Event(), threading.Event()
            save = gateway._tls_store.save

            def slow(identity):
                entered.set()
                assert release.wait(3), "가상 파일 작업 해제가 누락됨"
                save(identity)

            monkeypatch.setattr(gateway._tls_store, "save", slow)
            clock.advance(61 * 86400)
            await gateway.check_tls()
            async with asyncio.timeout(2):
                while not entered.is_set():
                    await asyncio.sleep(0.001)
            stopping = asyncio.create_task(gateway.stop())
            try:
                await asyncio.sleep(0)
                assert not stopping.done()
                assert not gateway._running
            finally:
                release.set()
                await asyncio.wait_for(stopping, 4)
            assert gateway._site is None and gateway._renew_task is None

    asyncio.run(scenario())


def test_near_expiry_ca_does_not_enter_repeated_leaf_renewal(tmp_path):
    from src.core.companion.storage import RegistrationStore
    from src.core.companion.tls_storage import TlsIdentityStore

    async def scenario():
        clock = RenewalClock()
        clock.current = utc_now()
        registration = RegistrationStore(tmp_path / "registration.json")
        record = registration.load_or_create()
        identity = TlsIdentity.create(
            record.server_id, clock.utcnow() - timedelta(days=3640)
        )
        identity = identity.renew(clock.utcnow() - timedelta(days=21))
        with TlsIdentityStore(registration, clock=clock.utcnow) as store:
            store._write(identity)
            store.load_or_create()
        async with harness(
            tmp_path, tls_clock=clock.utcnow, renewal_clock=clock.monotonic
        ) as (gateway, client, base, _token, _port, _clock):
            for _ in range(3):
                await gateway.check_tls()
            assert gateway._renew_task is None
            assert gateway._tls_warning == "tls_repair_required"
            async with client.get(base + "/info") as response:
                assert response.status == 200
            clock.advance(11 * 86400)
            await gateway.check_tls()
            assert gateway._failure == "tls_expired"

    asyncio.run(scenario())


def test_listener_refuses_absent_or_weak_tls_context():
    from src.core.companion.tls_listener import TlsListener
    from src.core.companion.tls_identity import TlsError

    async def scenario():
        with pytest.raises(TlsError):
            await TlsListener.start(None, "127.0.0.1", 0, None)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        with pytest.warns(DeprecationWarning):
            context.minimum_version = ssl.TLSVersion.TLSv1_1
        with pytest.raises(TlsError):
            await TlsListener.start(None, "127.0.0.1", 0, context)

    asyncio.run(scenario())


def test_expiry_waiting_for_renewal_rechecks_current_identity(tmp_path, monkeypatch):
    async def scenario():
        clock = RenewalClock()
        async with harness(
            tmp_path, tls_clock=clock.utcnow, renewal_clock=clock.monotonic
        ) as (gateway, client, base, _token, port, _clock):
            reached, release = asyncio.Event(), asyncio.Event()
            call = port.call

            async def delayed_block(operation, context, **kwargs):
                if operation == "block" and not reached.is_set():
                    reached.set()
                    await release.wait()
                return await call(operation, context, **kwargs)

            monkeypatch.setattr(port, "call", delayed_block)
            clock.advance(61 * 86400)
            await gateway.check_tls()
            try:
                await asyncio.wait_for(reached.wait(), 2)
                clock.advance(30 * 86400)
                checking = asyncio.create_task(gateway.check_tls())
                await asyncio.sleep(0)
                assert not checking.done()
            finally:
                release.set()
            await asyncio.wait_for(asyncio.gather(gateway._renew_task, checking), 3)
            gateway._tls_identity.validate_connection(clock.utcnow())
            assert gateway._running and gateway._failure is None

    asyncio.run(scenario())


@pytest.mark.parametrize("version", [ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1])
def test_actual_listener_rejects_legacy_tls_versions(tmp_path, version):
    from cryptography.hazmat.primitives import serialization

    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, _token, _port, _clock):
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            context.load_verify_locations(
                cadata=gateway._tls_identity.ca.public_bytes(
                    serialization.Encoding.PEM
                ).decode("ascii")
            )
            # 시험 클라이언트만 구형 ClientHello를 보낸다. 서버의 TLS 하한은 바꾸지 않는다.
            with pytest.warns(DeprecationWarning):
                context.minimum_version = version
                context.maximum_version = version
            context.set_ciphers("ALL:@SECLEVEL=0")
            with pytest.raises((ssl.SSLError, ConnectionError)) as failure:
                await asyncio.open_connection(
                    "127.0.0.1",
                    gateway.port,
                    ssl=context,
                    server_hostname=gateway._tls_identity.hostname,
                    ssl_handshake_timeout=2,
                )
            assert getattr(failure.value, "reason", None) not in {
                "NO_PROTOCOLS_AVAILABLE",
                "NO_CIPHERS_AVAILABLE",
            }
            assert gateway._limiter.attempt_count == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("period", ["expired", "future"])
def test_real_tls_client_rejects_invalid_leaf_dates_before_http(tmp_path, period):
    from aiohttp import web
    from cryptography.hazmat.primitives import serialization
    from src.core.companion.private_files import PrivateDirectory
    from src.core.companion.tls_listener import TlsListener

    async def scenario():
        now = utc_now()
        identity = TlsIdentity.create(sample_id(400), now - timedelta(days=91))
        if period == "future":
            identity = identity.renew(now + timedelta(days=1))
        anchor = TrustAnchor.parse(identity.ca_certificate, identity.server_id, now)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        # 잘못된 서버를 재현하는 시험에만 날짜 검사를 거치지 않은 인증서를 로드한다.
        folder = PrivateDirectory(tmp_path / "invalid-test-server")
        pem = (
            identity.leaf_key_pem
            + identity.leaf.public_bytes(serialization.Encoding.PEM)
            + identity.ca.public_bytes(serialization.Encoding.PEM)
        )
        with folder.temporary_file(pem) as path:
            context.load_cert_chain(path)
        received = []

        async def handler(request):
            received.append(True)
            return web.Response(text="가상 응답")

        app = web.Application()
        app.router.add_get("/", handler)
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        await runner.setup()
        site = await TlsListener.start(runner, "127.0.0.1", 0, context)
        try:
            async with LoopbackClient(anchor) as client:
                with pytest.raises(aiohttp.ClientConnectorCertificateError):
                    await client.get(f"https://{identity.hostname}:{site.port}/")
            assert received == []
        finally:
            await site.stop()
            await runner.cleanup()
            await site.wait_closed()

    asyncio.run(scenario())


@pytest.mark.parametrize("wrong", ["ca", "hostname", "plaintext"])
def test_untrusted_or_plaintext_request_never_reaches_application(tmp_path, wrong):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, token, port, _clock):
            identity = gateway._tls_store.load_or_create()
            if wrong == "ca":
                identity = TlsIdentity.create(identity.server_id, utc_now())
            anchor = TrustAnchor.parse(
                identity.ca_certificate, identity.server_id, utc_now()
            )
            target = base
            if wrong == "hostname":
                target = base.replace(identity.hostname, "wrong.invalid")
            if wrong == "plaintext":
                target = f"http://127.0.0.1:{gateway.port}/companion/v1"
            async with LoopbackClient(anchor) as outsider:
                with pytest.raises(aiohttp.ClientError):
                    await outsider.ws_connect(
                        target + "/ws", headers={"Authorization": f"Bearer {token}"}
                    )
            assert gateway._limiter.attempt_count == 0
            assert port.calls == []

    asyncio.run(scenario())


def test_several_stalled_handshakes_are_closed_within_timeout(tmp_path):
    async def scenario():
        async with harness(tmp_path) as (gateway, client, base, _token, _port, _clock):
            peers = [
                await asyncio.open_connection("127.0.0.1", gateway.port)
                for _ in range(4)
            ]
            try:
                async with client.get(base + "/info") as response:
                    assert response.status == 200

                async def ended(reader):
                    try:
                        return await reader.read(1)
                    except ConnectionResetError:
                        return b""

                assert (
                    await asyncio.wait_for(
                        asyncio.gather(*(ended(reader) for reader, _writer in peers)), 6
                    )
                    == [b""] * 4
                )
            finally:
                for _reader, writer in peers:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except ConnectionResetError:
                        pass

    asyncio.run(scenario())
