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
        self._closed = True
        self._server.close()

    async def wait_closed(self):
        await self._server.wait_closed()
