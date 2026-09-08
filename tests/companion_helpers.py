"""동반 앱 시험은 가상 시각·식별자·문장만 사용한다."""

from datetime import datetime, timedelta, timezone
from itertools import count


def sample_id(number):
    return f"00000000-0000-4000-8000-{number:012d}"


def id_factory(start=100):
    numbers = count(start)
    return lambda: sample_id(next(numbers))


class FakeClock:
    def __init__(self):
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def utcnow(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
            seconds=self.seconds
        )

    def advance(self, seconds):
        self.seconds += seconds


class LoopbackClient:
    """실제 클라이언트의 업그레이드 응답까지 명시적으로 닫는 시험용 수명 래퍼."""

    def __init__(self, trust_anchor=None):
        import aiohttp

        connector = tls_connector(trust_anchor) if trust_anchor is not None else None
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=3), connector=connector
        )
        self._sockets = []

    def get(self, *args, **kwargs):
        return self.session.get(*args, **kwargs)

    async def ws_connect(self, *args, **kwargs):
        socket = await self.session.ws_connect(*args, **kwargs)
        self._sockets.append(socket)
        return socket

    async def close(self):
        import asyncio

        try:
            for socket in self._sockets:
                await asyncio.wait_for(socket.close(), 2)
        finally:
            await self.session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def tls_connector(anchor):
    """QR의 CA만 신뢰하고 고정 인증서 이름을 루프백으로 라우팅한다."""
    import aiohttp
    import socket
    import ssl
    from cryptography.hazmat.primitives import serialization

    class Resolver(aiohttp.abc.AbstractResolver):
        async def resolve(self, host, port=0, family=socket.AF_INET):
            return [
                {
                    "hostname": host,
                    "host": "127.0.0.1",
                    "port": port,
                    "family": socket.AF_INET,
                    "proto": 0,
                    "flags": 0,
                }
            ]

        async def close(self):
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(
        cadata=anchor.certificate.public_bytes(serialization.Encoding.PEM).decode(
            "ascii"
        )
    )
    return aiohttp.TCPConnector(ssl=context, resolver=Resolver())
