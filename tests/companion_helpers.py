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

    def __init__(self):
        import aiohttp

        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3))
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
