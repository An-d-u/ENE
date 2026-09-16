"""TTS 워커의 PCM을 한정된 메모리와 단일 깨우기로 Qt에 전달한다."""

from collections import deque
import threading
import time

from PyQt6.QtCore import QObject, Qt, pyqtSignal, pyqtSlot


class BoundedTtsMailbox(QObject):
    wake = pyqtSignal()

    def __init__(self, chunk, finished, failed, parent=None):
        super().__init__(parent)
        self._chunk, self._finished, self._failed = chunk, finished, failed
        self._condition = threading.Condition()
        self._queue = deque()
        self._bytes = 0
        self.capacity = 0
        self._scheduled = self._closed = self._ended = False
        self._error = False
        self.wake.connect(self._drain, Qt.ConnectionType.QueuedConnection)

    def configure(self, sample_rate, channels, sample_width):
        # 확장 전송 큐의 2초와 합쳐 4초를 넘지 않도록 나눈다.
        with self._condition:
            self.capacity = min(sample_rate * channels * sample_width * 2, 524288)

    @property
    def buffered_bytes(self):
        with self._condition:
            return self._bytes

    def _schedule(self):
        if not self._scheduled:
            self._scheduled = True
            self.wake.emit()

    def push(self, data, mouth):
        with self._condition:
            if len(data) > min(32768, self.capacity) or self.capacity <= 0:
                raise ValueError("tts_chunk_limit")
            deadline = time.monotonic() + 5
            while (
                not self._closed
                and not self._ended
                and (self._bytes + len(data) > self.capacity or len(self._queue) >= 128)
            ):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("tts_delivery_timeout")
                self._condition.wait(remaining)
            if self._closed or self._ended:
                return False
            self._queue.append((data, mouth))
            self._bytes += len(data)
            self._schedule()
            return True

    def finish(self):
        with self._condition:
            if not self._closed:
                self._ended = True
                self._schedule()

    def cancel(self):
        with self._condition:
            self._closed = True
            self._queue.clear()
            self._bytes = 0
            self._condition.notify_all()

    def fail(self):
        with self._condition:
            if self._closed:
                return
            self.cancel()
            self._error = True
            self._schedule()

    @pyqtSlot()
    def _drain(self):
        # 한 번에 전부 비우지 않아 UI 및 취소 신호도 처리할 수 있게 한다.
        for _ in range(8):
            with self._condition:
                if self._error:
                    self._error = False
                    self._scheduled = False
                    action = self._failed
                elif self._closed:
                    self._scheduled = False
                    return
                elif not self._queue:
                    self._scheduled = False
                    if not self._ended:
                        return
                    self._closed = True
                    action = self._finished
                else:
                    action = None
                    data, mouth = self._queue.popleft()
            if action is not None:
                if action == self._failed:
                    action("tts_stream_error")
                else:
                    action()
                return
            try:
                self._chunk(data, mouth)
            except Exception:
                self.fail()
            finally:
                with self._condition:
                    if not self._closed:
                        self._bytes -= len(data)
                    self._condition.notify_all()
        with self._condition:
            self._scheduled = False
            self._schedule()
