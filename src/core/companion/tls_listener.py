"""공개 asyncio API로만 여는 TLS 전용 리스너."""

import asyncio
import ssl

from .tls_identity import TlsError


class _ClosingProtocol(asyncio.Protocol):
    """TLS 협상 뒤의 공개 protocol 콜백에서 종료된 리스너의 늦은 연결을 거절한다."""

    def __init__(self, handler, listener):
        self._handler, self._listener = handler, listener
        self._connected = False

    def connection_made(self, transport):
        if self._listener._closed:
            transport.close()
            return
        self._connected = True
        self._handler.connection_made(transport)

    def connection_lost(self, exc):
        if self._connected:
            self._handler.connection_lost(exc)

    def data_received(self, data):
        if self._connected:
            self._handler.data_received(data)

    def eof_received(self):
        if self._connected:
            return self._handler.eof_received()

    def pause_writing(self):
        if self._connected:
            self._handler.pause_writing()

    def resume_writing(self):
        if self._connected:
            self._handler.resume_writing()


class TlsListener:
    def __init__(self):
        self._closed = False
        self._server = None
        self._close_waiter = None
        self.port = None

    @classmethod
    async def start(cls, runner, host, port, context):
        if (
            not isinstance(context, ssl.SSLContext)
            or context.protocol != ssl.PROTOCOL_TLS_SERVER
            or context.minimum_version < ssl.TLSVersion.TLSv1_2
        ):
            raise TlsError("tls_identity_invalid")
        if runner.server is None:
            raise TlsError("tls_storage_unavailable")
        listener = cls()
        factory = runner.server
        server = await asyncio.get_running_loop().create_server(
            lambda: _ClosingProtocol(factory(), listener),
            host,
            port,
            ssl=context,
            ssl_handshake_timeout=5,
            ssl_shutdown_timeout=2,
        )
        listener._server = server
        listener.port = server.sockets[0].getsockname()[1]
        return listener

    async def stop(self):
        # 접수부터 닫고, HTTP/WS를 종료한 다음 wait_closed를 호출한다.
        if self._closed:
            return
        self._closed = True
        # Python 3.11은 close 뒤의 wait_closed가 진행 중인 TLS 협상을 기다리지 않는다.
        # 먼저 대기를 등록한다. 0초 양보는 고정 시간 대기가 아니라 등록 순서 보장이다.
        self._close_waiter = asyncio.create_task(self._server.wait_closed())
        try:
            await asyncio.sleep(0)
        finally:
            self._server.close()

    async def wait_closed(self):
        if self._close_waiter is not None:
            # 한 호출자의 취소가 다른 종료 대기까지 취소하지 않게 한다.
            await asyncio.shield(self._close_waiter)
        await self._server.wait_closed()
