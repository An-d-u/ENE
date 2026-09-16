"""개인 LAN 전용 HTTPS/WSS 진입점. 로컬 승인 API는 네트워크에 노출하지 않는다."""

import asyncio
import time
from dataclasses import dataclass
from uuid import uuid4

from aiohttp import WSMsgType, web

from .adapter import AdapterError, AdmissionContext
from .pairing import PairingError, PairingTicket, PendingPairing
from .protocol import (
    MAX_PREAUTH_BYTES,
    MAX_WIRE_BYTES,
    ProtocolError,
    decode_message,
    encode_message,
)
from .session import CompanionSession, PreauthLimiter, SessionError
from .storage import StorageError
from .private_files import PrivateFileError
from .tls_identity import TlsError, utc_now
from .tls_listener import TlsListener
from .connection_resources import MediaError
from .extension_protocol import CAPABILITIES, negotiate
from .media_http import MediaHttp


# 기존 최소 의존성과 새 aiohttp의 타입 지정 요청 키를 모두 지원한다.
_PREAUTH_SLOT = (
    web.RequestKey("companion_slot", str)
    if hasattr(web, "RequestKey")
    else "companion_slot"
)


@dataclass(frozen=True)
class GatewayState:
    running: bool
    port: int | None
    registered: bool
    qr: PairingTicket | None
    pending: PendingPairing | None
    code: str | None = None


class CompanionGateway:
    def __init__(
        self,
        pairing,
        adapter,
        gateway_generation,
        *,
        tls_store,
        tls_clock=utc_now,
        renewal_clock=time.monotonic,
        on_state=None,
        hello_timeout=5,
        heartbeat_interval=15,
        heartbeat_timeout=10,
        capabilities=(),
    ):
        self.pairing, self.adapter = pairing, adapter
        self.capabilities = negotiate(capabilities, CAPABILITIES)
        self._media = MediaHttp(self._authorize_media, self._validate_session_tls)
        self._tls_store = tls_store
        self._tls_identity = None
        self._tls_clock, self._renewal_clock = tls_clock, renewal_clock
        self._tls_task = self._renew_task = None
        self._renew_attempts = 0
        self._renew_after = 0
        self._tls_warning = None
        self._host = None
        self.generation = gateway_generation
        self._on_state = on_state or (lambda state: None)
        self._hello_timeout = hello_timeout
        self._heartbeat_interval, self._heartbeat_timeout = (
            heartbeat_interval,
            heartbeat_timeout,
        )
        self._limiter = PreauthLimiter()
        self._runner = self._site = self._expiry_task = None
        self._pair_sockets = {}
        self._pairing_ids = {}
        self._preauth_sockets = set()
        self._active = None
        self._transition = asyncio.Lock()
        self._changing = False
        self._deferred_resync = None
        self._running = False
        self._failure = None
        self._last_qr = None
        self.port = None

    def _context(self, registration=None, connection=None):
        return AdmissionContext(
            self.generation,
            self.pairing.registration.registration_generation
            if registration is None
            else registration,
            connection,
        )

    def _notify(self):
        self._last_qr = self.pairing.qr
        self._on_state(
            GatewayState(
                self._running,
                self.port,
                self.pairing.registration.token_hash is not None,
                self._last_qr,
                self.pairing.pending,
                self._failure or self._tls_warning,
            )
        )

    def _response(self, code, status):
        return web.json_response(
            {"code": code, "server_id": self.pairing.registration.server_id},
            status=status,
            headers={"Cache-Control": "no-store"},
        )

    async def start(self, host="0.0.0.0", port=8765):
        if self._runner is not None:
            raise RuntimeError("gateway_already_started")
        identity = self._tls_store.load_or_create()
        if (
            identity.ca_sha256 != self.pairing.registration.ca_sha256
            or identity.server_id != self.pairing.registration.server_id
        ):
            raise TlsError("tls_repair_required")
        if identity.renewal_due(self._tls_clock()):
            identity = identity.renew(self._tls_clock())
            context = self._tls_store.server_context(identity)
            self._tls_store.save(identity)
        else:
            context = self._tls_store.server_context(identity)
        self._tls_identity = identity
        self._host = host

        @web.middleware
        async def guard(request, handler):
            media = request.path.startswith(
                ("/companion/v1/audio/", "/companion/v1/character/")
            )
            if not media and ("Origin" in request.headers or request.query_string):
                return self._response("forbidden", 403)
            if not self._running or self._failure:
                return self._response("gateway_unavailable", 503)
            try:
                self._tls_identity.validate_connection(self._tls_clock())
            except TlsError:
                return self._response("gateway_unavailable", 503)
            if media:
                return await handler(request)
            try:
                slot = self._limiter.acquire(request.remote or "unknown")
            except SessionError:
                return self._response("rate_limited", 429)
            request[_PREAUTH_SLOT] = slot
            try:
                return await handler(request)
            finally:
                self._limiter.release(slot)

        app = web.Application(middlewares=[guard], client_max_size=MAX_PREAUTH_BYTES)
        app.router.add_get("/companion/v1/info", self._info)
        app.router.add_get("/companion/v1/pair", self._pair)
        app.router.add_get("/companion/v1/ws", self._normal)
        app.router.add_get(
            "/companion/v1/audio/{utterance_id}", self._media.audio, allow_head=False
        )
        # 자격증명이 URL/헤더/예외에 포함될 수 있으므로 액세스 로그를 만들지 않는다.
        self._runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        try:
            await self._runner.setup()
            self._site = await TlsListener.start(self._runner, host, port, context)
            self.port = self._site.port
            self._running = True
            self._expiry_task = asyncio.create_task(
                self._expiry_loop(), name="companion-pair-expiry"
            )
            self._tls_task = asyncio.create_task(
                self._tls_loop(), name="companion-tls-watch"
            )
            self._notify()
        except BaseException:
            if self._site is not None:
                await self._site.stop()
            await self._runner.cleanup()
            if self._site is not None:
                await self._site.wait_closed()
            self._runner = self._site = None
            raise

    async def _info(self, request):
        return web.json_response(
            {
                "server_id": self.pairing.registration.server_id,
                "protocol_versions": [1],
            },
            headers={"Cache-Control": "no-store"},
        )

    async def _first_message(self, ws, kind):
        item = await asyncio.wait_for(ws.receive(), self._hello_timeout)
        if item.type != WSMsgType.TEXT:
            raise ProtocolError()
        return decode_message(
            item.data, allowed_types={kind}, max_bytes=MAX_PREAUTH_BYTES
        )

    async def _close_ws(self, ws, code="connection_closed"):
        try:
            await asyncio.wait_for(
                ws.close(
                    code=1000 if code == "connection_closed" else 1008,
                    message=code.encode("ascii"),
                ),
                2,
            )
        except (TimeoutError, ConnectionError):
            pass

    async def _pair(self, request):
        ws = web.WebSocketResponse(
            max_msg_size=MAX_PREAUTH_BYTES, compress=False, autoping=False
        )
        await ws.prepare(request)
        connection = str(uuid4())
        self._preauth_sockets.add(ws)
        try:
            message = await self._first_message(ws, "pair_request")
            pending = self.pairing.request(
                message.fields["pairing_id"],
                message.fields["secret"],
                connection,
                message.fields["device_name"],
            )
            self._pair_sockets[connection] = ws
            self._pairing_ids[connection] = pending.pairing_id
            await asyncio.wait_for(
                ws.send_str(
                    encode_message(
                        {
                            "type": "pair_pending",
                            "protocol_version": 1,
                            "pairing_id": pending.pairing_id,
                        }
                    )
                ),
                2,
            )
            self._notify()
            # 이 소켓에서는 첫 요청 이후 원격 명령을 받지 않는다.
            async for _ in ws:
                await self._fail_pair(
                    connection, pending.pairing_id, "unsupported_command"
                )
                break
        except (PairingError, ProtocolError) as error:
            await self._close_ws(ws, error.code)
        except TimeoutError:
            await self._close_ws(ws, "hello_timeout")
        except ConnectionError:
            pass
        finally:
            self._pair_sockets.pop(connection, None)
            self._pairing_ids.pop(connection, None)
            self._preauth_sockets.discard(ws)
            self.pairing.connection_closed(connection)
            self._notify()
            await self._close_ws(ws)
        return ws

    async def _normal(self, request):
        if self._changing:
            return self._response("admission_blocked", 503)
        header = request.headers.getall("Authorization", [])
        token = (
            header[0][7:]
            if len(header) == 1 and header[0].startswith("Bearer ")
            else None
        )
        try:
            registration = self.pairing.authorize(token)
        except PairingError:
            return self._response("unauthorized", 401)
        ws = web.WebSocketResponse(
            max_msg_size=MAX_WIRE_BYTES, compress=False, autoping=False
        )
        await ws.prepare(request)
        self._preauth_sockets.add(ws)
        session = None
        try:
            hello = await self._first_message(ws, "hello")
            # hello를 기다리는 동안 바뀐 등록이나 이미 진행 중인 교체를 다시 검사한다.
            current = self.pairing.authorize(token)
            token = None
            if current != registration or self._changing or self._transition.locked():
                raise SessionError("admission_blocked")
            async with self._transition:
                context = self._context(connection=str(uuid4()))
                old = self._active
                if old is not None:
                    old.stop("connection_replaced")
                    await old.finished.wait()
                head = await self.adapter.call("connect", context)
                ready = {
                    "type": "ready",
                    "protocol_version": 1,
                    "server_id": registration.server_id,
                    "server_epoch": head.server_epoch,
                    "conversation_id": head.conversation_id,
                    "registration_generation": registration.registration_generation,
                    "capabilities": list(
                        negotiate(hello.fields["capabilities"], self.capabilities)
                    ),
                }
                session = CompanionSession(
                    ws,
                    self.adapter,
                    context,
                    ready,
                    validate_connection=self._validate_session_tls,
                    heartbeat_interval=self._heartbeat_interval,
                    heartbeat_timeout=self._heartbeat_timeout,
                )
                self._active = session
            self._limiter.release(request[_PREAUTH_SLOT])
            self._preauth_sockets.discard(ws)
            await session.run()
        except (PairingError, ProtocolError, SessionError, AdapterError) as error:
            await self._close_ws(ws, error.code)
        except TimeoutError:
            await self._close_ws(ws, "hello_timeout")
        except ConnectionError:
            pass
        finally:
            token = None
            self._preauth_sockets.discard(ws)
            if session is not None and self._active is session:
                self._active = None
                try:
                    await self.adapter.call("disconnect", session.context)
                except AdapterError:
                    pass
            await self._close_ws(ws)
        return ws

    def _authorize_media(self, request):
        header = request.headers.getall("Authorization", [])
        token = (
            header[0][7:]
            if len(header) == 1 and header[0].startswith("Bearer ")
            else None
        )
        try:
            registration = self.pairing.authorize(token)
        except PairingError:
            try:
                self._limiter.release(
                    self._limiter.acquire(request.remote or "unknown")
                )
            except SessionError:
                raise MediaError("rate_limited", 429) from None
            raise MediaError("unauthorized", 401) from None
        finally:
            token = None
        session = self._active
        connection = request.headers.getall("X-ENE-Connection", [])
        if (
            self._changing
            or self._transition.locked()
            or session is None
            or session.resources.closed
            or registration.registration_generation
            != session.context.registration_generation
            or connection != [session.context.connection_generation]
        ):
            raise MediaError("not_found", 404)
        return session

    def publish(self, message):
        if self._changing and message.type in {"event", "resync_required"}:
            self._deferred_resync = decode_message(
                encode_message(
                    {
                        "type": "resync_required",
                        "protocol_version": 1,
                        "server_epoch": message.fields["server_epoch"],
                        "conversation_id": message.fields["conversation_id"],
                        "reason": "gap",
                    }
                )
            )
        elif self._active is not None and self._running:
            self._active.publish(message)

    async def _fail_pair(self, connection, pairing_id, code):
        ws = self._pair_sockets.pop(connection, None)
        if ws is None:
            return
        try:
            await asyncio.wait_for(
                ws.send_str(
                    encode_message(
                        {
                            "type": "pair_failed",
                            "protocol_version": 1,
                            "pairing_id": pairing_id,
                            "code": code,
                        }
                    )
                ),
                2,
            )
        except (TimeoutError, ConnectionError):
            pass
        await self._close_ws(ws, code)

    async def _expiry_loop(self):
        while True:
            await asyncio.sleep(0.05)
            current = self.pairing.qr
            if current is None and not self._changing:
                for connection in tuple(self._pair_sockets):
                    await self._fail_pair(
                        connection, self._pairing_ids[connection], "pairing_expired"
                    )
                if self._last_qr is not None:
                    self._notify()

    async def issue_qr(self, addresses):
        if not self._running or self._failure:
            raise PairingError("gateway_unavailable")
        try:
            self._tls_identity.validate_connection(self._tls_clock())
        except TlsError as error:
            raise PairingError(error.code) from None
        pending = self.pairing.pending
        ticket = self.pairing.issue_qr(addresses)
        if pending:
            await self._fail_pair(
                pending.connection_id, pending.pairing_id, "pairing_replaced"
            )
        self._notify()
        return ticket

    async def reject(self, pairing_id):
        pending = self.pairing.reject(pairing_id)
        if pending:
            await self._fail_pair(
                pending.connection_id, pending.pairing_id, "pairing_rejected"
            )
        self._notify()

    async def approve(self, pairing_id, connection_id):
        await self._change_registration((pairing_id, connection_id))

    async def revoke(self):
        await self._change_registration(None)

    async def _change_registration(self, approval):
        if not self._running or self._failure or self._transition.locked():
            raise PairingError("admission_blocked")
        if approval is not None:
            pending = self.pairing.pending
            if (
                pending is None
                or (pending.pairing_id, pending.connection_id) != approval
            ):
                raise PairingError("invalid_pairing")
        async with self._transition:
            old_context = self._context()
            old_pending = self.pairing.pending
            self._changing = True
            if self._active is not None:
                self.adapter.cancel_connection(self._active.context)
            try:
                await self.adapter.call("block", old_context)
                try:
                    grant = self.pairing.approve(*approval) if approval else None
                    if approval is None:
                        self.pairing.revoke()
                except (StorageError, PairingError) as error:
                    if error.code == "storage_uncertain":
                        await self._fail_closed(error.code)
                    else:
                        await self.adapter.call("restore", old_context)
                        if approval is not None:
                            await self._fail_pair(approval[1], approval[0], error.code)
                    raise
                await self.adapter.call("register", self._context())
                if self._active is not None:
                    self._active.stop("registration_changed")
                    await self._active.finished.wait()
                if grant is not None:
                    ws = self._pair_sockets.get(grant.connection_id)
                    if ws is not None:
                        await asyncio.wait_for(
                            ws.send_str(encode_message(grant.to_wire())), 2
                        )
                        await self._close_ws(ws)
                elif old_pending is not None:
                    await self._fail_pair(
                        old_pending.connection_id,
                        old_pending.pairing_id,
                        "registration_changed",
                    )
            except AdapterError:
                await self._fail_closed("adapter_unavailable")
                raise
            finally:
                self._changing = False
                deferred, self._deferred_resync = self._deferred_resync, None
                if deferred is not None and self._failure is None:
                    self.publish(deferred)
                self._notify()

    async def _fail_closed(self, code):
        self._failure = code
        self._running = False
        self.pairing.invalidate()
        try:
            await self.adapter.call("block", self._context())
        except AdapterError:
            pass
        if self._active is not None:
            self._active.stop(code)
            await self._active.finished.wait()
        for ws in tuple(self._preauth_sockets):
            await self._close_ws(ws, code)
        if self._site is not None:
            await self._site.stop()
        self._notify()

    def _validate_session_tls(self):
        try:
            self._tls_identity.validate_connection(self._tls_clock())
        except TlsError as error:
            raise SessionError(error.code) from None

    async def _tls_loop(self):
        while self._running:
            await self.check_tls()
            if not self._running:
                return
            remaining = (
                min(self._tls_identity.ca_not_after, self._tls_identity.leaf_not_after)
                - self._tls_clock()
            ).total_seconds()
            await asyncio.sleep(max(0.01, min(60, remaining)))

    async def check_tls(self):
        """갱신 준비와 별도로 만료를 감시해 느린 디스크가 차단을 늦추지 않게 한다."""
        if not self._running:
            return
        now = self._tls_clock()
        try:
            self._tls_identity.validate_connection(now)
        except TlsError:
            async with self._transition:
                # 대기 중 갱신된 인증서에 이전 인증서의 만료 판단을 적용하지 않는다.
                if self._running:
                    try:
                        self._tls_identity.validate_connection(self._tls_clock())
                    except TlsError as current_error:
                        await self._fail_closed(current_error.code)
            return
        if self._tls_identity.ca_repair_due(now):
            if self._tls_warning != "tls_repair_required":
                self._tls_warning = "tls_repair_required"
                self._notify()
            return
        if (
            self._tls_identity.renewal_due(now)
            and self._renew_attempts < 4
            and self._renewal_clock() >= self._renew_after
            and (self._renew_task is None or self._renew_task.done())
        ):
            self._renew_task = asyncio.create_task(
                self._renew_tls(now), name="companion-tls-renew"
            )

    def _prepare_renewal(self, identity, now):
        renewed = identity.renew(now)
        context = self._tls_store.server_context(renewed)
        self._tls_store.save(renewed)
        return renewed, context

    async def _renew_tls(self, now):
        worker = asyncio.create_task(
            asyncio.to_thread(self._prepare_renewal, self._tls_identity, now)
        )
        try:
            try:
                renewed, context = await asyncio.shield(worker)
            except asyncio.CancelledError:
                # 취소로 실제 파일 작업이 끝났다고 간주하지 않는다. 보관 잠금 해제 전 회수한다.
                await asyncio.gather(worker, return_exceptions=True)
                raise
            if not self._running:
                return
            async with self._transition:
                if not self._running:
                    return
                self._changing = True
                try:
                    await self.adapter.call("block", self._context())
                    self.pairing.invalidate()
                    await self._site.stop()
                    if self._active is not None:
                        self._active.stop("tls_renewed")
                        await self._active.finished.wait()
                    for ws in tuple(self._preauth_sockets):
                        await self._close_ws(ws, "tls_renewed")
                    self._runner.server.pre_shutdown()
                    await self._runner.server.shutdown(2)
                    await self._site.wait_closed()
                    if not self._running:
                        return
                    self._site = await TlsListener.start(
                        self._runner, self._host, self.port, context
                    )
                    self._tls_identity = renewed
                    await self.adapter.call("restore", self._context())
                    self._renew_attempts = 0
                    self._tls_warning = None
                finally:
                    self._changing = False
                    deferred, self._deferred_resync = self._deferred_resync, None
                    if deferred is not None and self._failure is None:
                        self.publish(deferred)
                    self._notify()
        except PrivateFileError as error:
            if error.code == "tls_write_failed":
                self._renew_attempts += 1
                if self._renew_attempts < 4:
                    self._renew_after = (
                        self._renewal_clock() + (60, 120, 300)[self._renew_attempts - 1]
                    )
                self._tls_warning = "tls_renewal_failed"
                self._notify()
            else:
                async with self._transition:
                    await self._fail_closed(error.code)
        except (TlsError, AdapterError, OSError):
            async with self._transition:
                await self._fail_closed("tls_renewal_failed")
        except Exception:
            async with self._transition:
                await self._fail_closed("tls_renewal_failed")

    async def stop(self):
        """호출 전에 controller가 Qt의 신규 접수를 무효화해야 한다."""
        self._running = False
        self.pairing.invalidate()
        for task in (self._tls_task, self._renew_task):
            if task is not None:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._tls_task = self._renew_task = None
        if self._expiry_task is not None:
            self._expiry_task.cancel()
            await asyncio.gather(self._expiry_task, return_exceptions=True)
            self._expiry_task = None
        if self._active is not None:
            self._active.stop("gateway_stopped")
            await self._active.finished.wait()
        for ws in tuple(self._preauth_sockets):
            await self._close_ws(ws, "gateway_stopped")
        if self._runner is not None:
            if self._site is not None:
                await self._site.stop()
            await self._runner.cleanup()
            if self._site is not None:
                await self._site.wait_closed()
            self._runner = self._site = None
        self.port = None
        self._notify()
