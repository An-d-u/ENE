"""개인 LAN 전용 HTTP/WS 진입점. PC 로컬 승인 API는 네트워크에 노출하지 않는다."""

import asyncio
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
        on_state=None,
        hello_timeout=5,
        heartbeat_interval=15,
        heartbeat_timeout=10,
    ):
        self.pairing, self.adapter = pairing, adapter
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
                self._failure,
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

        @web.middleware
        async def guard(request, handler):
            if "Origin" in request.headers or request.query_string:
                return self._response("forbidden", 403)
            if not self._running or self._failure:
                return self._response("gateway_unavailable", 503)
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
        # 자격증명이 URL/헤더/예외에 포함될 수 있으므로 액세스 로그를 만들지 않는다.
        self._runner = web.AppRunner(app, access_log=None, shutdown_timeout=2)
        try:
            await self._runner.setup()
            self._site = web.TCPSite(self._runner, host, port)
            await self._site.start()
            self.port = self._runner.addresses[0][1]
            self._running = True
            self._expiry_task = asyncio.create_task(
                self._expiry_loop(), name="companion-pair-expiry"
            )
            self._notify()
        except BaseException:
            await self._runner.cleanup()
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
            await self._first_message(ws, "hello")
            # hello를 기다리는 동안 바뀐 등록이나 이미 진행 중인 교체를 다시 검사한다.
            current = self.pairing.authorize(token)
            token = None
            if current != registration or self._changing or self._transition.locked():
                raise SessionError("admission_blocked")
            async with self._transition:
                context = self._context(connection=str(uuid4()))
                old = self._active
                if old is not None:
                    self.adapter.cancel_connection(old.context)
                head = await self.adapter.call("connect", context)
                if old is not None:
                    old.stop("connection_replaced")
                    await old.finished.wait()
                ready = {
                    "type": "ready",
                    "protocol_version": 1,
                    "server_id": registration.server_id,
                    "server_epoch": head.server_epoch,
                    "conversation_id": head.conversation_id,
                    "registration_generation": registration.registration_generation,
                    "capabilities": [],
                }
                session = CompanionSession(
                    ws,
                    self.adapter,
                    context,
                    ready,
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
        if self._active is not None:
            self._active.stop(code)
            await self._active.finished.wait()
        for ws in tuple(self._preauth_sockets):
            await self._close_ws(ws, code)
        if self._site is not None:
            await self._site.stop()
        self._notify()

    async def stop(self):
        """호출 전에 controller가 Qt의 신규 접수를 무효화해야 한다."""
        self._running = False
        self.pairing.invalidate()
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
            await self._runner.cleanup()
            self._runner = self._site = None
        self.port = None
        self._notify()
