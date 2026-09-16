"""asyncio 연결 수명에 종속된 HTTP 작업·음성 원본·요청 상한."""

import asyncio

from .protocol import uuid_value


class MediaError(ValueError):
    def __init__(self, code, status):
        self.code, self.status = code, status
        super().__init__(code)


class ConnectionResources:
    def __init__(self):
        from .session import TokenBucket

        self.rate = TokenBucket(8, 16)
        self.closed = False
        self._tasks = {}
        self.audio_id = self.audio_source = None
        self.audio_consumed = self.audio_cancelled = False
        self.audio_ready = asyncio.Event()

    @property
    def active_count(self):
        return len(self._tasks)

    def add_audio(self, utterance_id, source):
        uuid_value(utterance_id)
        if self.closed:
            raise MediaError("not_found", 404)
        if "audio" in self._tasks.values():
            raise MediaError("resource_busy", 429)
        if utterance_id == self.audio_id:
            raise MediaError("not_found", 404)
        if self.audio_source is not None:
            self.audio_source.close()
        self.audio_id, self.audio_source = utterance_id, source
        self.audio_consumed = self.audio_cancelled = False
        self.audio_ready.set()

    def acquire(self, kind):
        if self.closed:
            raise MediaError("not_found", 404)
        limit = {"audio": 1, "asset": 2, "manifest": 1}[kind]
        if sum(value == kind for value in self._tasks.values()) >= limit:
            raise MediaError("resource_busy", 429)
        task = asyncio.current_task()
        self._tasks[task] = kind
        return task

    def acquire_audio(self, utterance_id):
        if utterance_id != self.audio_id or self.audio_source is None:
            raise MediaError("not_found", 404)
        if self.audio_cancelled:
            raise MediaError("audio_cancelled", 410)
        if self.audio_consumed:
            raise MediaError("not_found", 404)
        task = self.acquire("audio")
        self.audio_consumed = True
        return task, self.audio_source

    def release(self, task):
        self._tasks.pop(task, None)

    def cancel_audio(self):
        self.audio_cancelled = True
        if self.audio_source is not None:
            self.audio_source.cancel_transfer()
        for task, kind in tuple(self._tasks.items()):
            if kind == "audio":
                task.cancel()
        self.audio_ready.set()

    def cancel(self):
        self.closed = True
        self.cancel_audio()
        for task in tuple(self._tasks):
            task.cancel()

    async def wait_closed(self):
        await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
