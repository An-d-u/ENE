"""PCM 경계 검사와 한도 있는 전송 저장소. 확장용 파일은 만들지 않는다."""

from collections import deque
from dataclasses import dataclass
import struct
import threading
import wave

MAX_CHUNK = 32768
MAX_BYTES = 36 * 1024 * 1024


class AudioBufferError(ValueError):
    def __init__(self, code="invalid_pcm"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PcmFormat:
    sample_rate: int
    channels: int
    sample_width: int = 2

    def __post_init__(self):
        if (
            type(self.sample_rate) is not int
            or not 8000 <= self.sample_rate <= 48000
            or type(self.channels) is not int
            or self.channels not in (1, 2)
            or type(self.sample_width) is not int
            or self.sample_width != 2
        ):
            raise AudioBufferError("unsupported_format")

    @property
    def frame_bytes(self):
        return self.channels * 2

    @property
    def buffer_limit(self):
        return min(self.sample_rate * self.frame_bytes * 4, 1024 * 1024)

    @property
    def source_limit(self):
        return min(self.sample_rate * self.frame_bytes * 180, MAX_BYTES)


class _BytesCursor:
    """wave의 작은 헤더 읽기만 복사하며 전체 BytesIO 복제를 피한다."""

    def __init__(self, raw):
        self.raw, self.position = raw, 0

    def read(self, size):
        end = min(len(self.raw), self.position + size)
        result = self.raw[self.position : end]
        self.position = end
        return result

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset
        if not 0 <= position <= len(self.raw):
            raise AudioBufferError("invalid_wav")
        self.position = position


def _data_bounds(raw):
    if (
        type(raw) is not bytes
        or not 12 <= len(raw) <= MAX_BYTES
        or raw[:4] != b"RIFF"
        or raw[8:12] != b"WAVE"
        or struct.unpack_from("<I", raw, 4)[0] + 8 != len(raw)
    ):
        raise AudioBufferError("invalid_wav")
    position, chunks = 12, {}
    while position < len(raw):
        if position + 8 > len(raw):
            raise AudioBufferError("invalid_wav")
        kind, size = struct.unpack_from("<4sI", raw, position)
        start = position + 8
        end = start + size
        position = end + (size & 1)
        if position > len(raw):
            raise AudioBufferError("invalid_wav")
        if kind in {b"fmt ", b"data"}:
            if kind in chunks:
                raise AudioBufferError("invalid_wav")
            chunks[kind] = (start, end)
    if b"fmt " not in chunks or b"data" not in chunks:
        raise AudioBufferError("invalid_wav")
    return chunks


def _count(count, available, frame_bytes):
    if type(count) is not int or not 0 <= count <= available or count % frame_bytes:
        raise AudioBufferError()


class WavSource:
    """완성 음성은 원본 한 개와 전송 cursor만 보관한다. 소비자는 하나다."""

    def __init__(self, raw):
        chunks = _data_bounds(raw)
        start, end = chunks[b"data"]
        try:
            with wave.open(_BytesCursor(raw), "rb") as reader:
                self.format = PcmFormat(
                    reader.getframerate(), reader.getnchannels(), reader.getsampwidth()
                )
                if reader.getcomptype() != "NONE":
                    raise AudioBufferError("unsupported_format")
        except (wave.Error, EOFError, struct.error, RuntimeError) as exc:
            raise AudioBufferError("invalid_wav") from exc
        fmt_start, fmt_end = chunks[b"fmt "]
        if fmt_end - fmt_start < 16:
            raise AudioBufferError("invalid_wav")
        tag, _, _, byte_rate, alignment, bits = struct.unpack_from(
            "<HHIIHH", raw, fmt_start
        )
        if (
            bits != 16
            or alignment != self.format.frame_bytes
            or byte_rate != self.format.sample_rate * self.format.frame_bytes
            or (
                tag == 0xFFFE and struct.unpack_from("<H", raw, fmt_start + 18)[0] != 16
            )
        ):
            raise AudioBufferError("unsupported_format")
        size = end - start
        if size % self.format.frame_bytes or size > self.format.source_limit:
            raise AudioBufferError()
        self.raw = raw
        self.total_frames = size // self.format.frame_bytes
        self._position, self._end = start, end
        self.closed = False
        self.source_ended = True

    def peek(self, max_bytes=MAX_CHUNK):
        if self.closed or self._position == self._end:
            return None
        size = min(MAX_CHUNK, max_bytes, self._end - self._position)
        _count(size, MAX_CHUNK, self.format.frame_bytes)
        return memoryview(self.raw)[self._position : self._position + size]

    def consume(self, count):
        _count(
            count, min(MAX_CHUNK, self._end - self._position), self.format.frame_bytes
        )
        if self.closed:
            raise AudioBufferError("closed")
        self._position += count

    def close(self):
        self.closed = True


class PcmStream:
    """Qt 생산자/HTTP 소비자가 공유한다. write가 끝난 뒤 consume해야 한다."""

    def __init__(self, format):
        self.format = format
        self._lock = threading.RLock()
        self._chunks = deque()
        self._accepted = self._read = self._retained = 0
        self._prefix = True
        self.closed = self.source_ended = False

    @property
    def buffered_bytes(self):
        with self._lock:
            return self._retained

    @property
    def total_frames(self):
        with self._lock:
            return self._accepted // self.format.frame_bytes

    def offer(self, data):
        with self._lock:
            if self.closed or self.source_ended:
                return "closed"
            if (
                type(data) is not bytes
                or not 0 < len(data) <= MAX_CHUNK
                or len(data) % self.format.frame_bytes
                or self._accepted + len(data) > self.format.source_limit
            ):
                return "invalid"
            if (
                self._retained + len(data) > self.format.buffer_limit
                or len(self._chunks) >= 256
            ):
                return "full"
            self._chunks.append((self._accepted, data))
            self._accepted += len(data)
            self._retained += len(data)
            return "accepted"

    def peek(self, max_bytes=MAX_CHUNK):
        with self._lock:
            if self.closed:
                return None
            for start, data in self._chunks:
                if start <= self._read < start + len(data):
                    offset = self._read - start
                    size = min(max_bytes, MAX_CHUNK, len(data) - offset)
                    _count(size, MAX_CHUNK, self.format.frame_bytes)
                    return memoryview(data)[offset : offset + size]
            return None

    def consume(self, count):
        with self._lock:
            chunk = self.peek()
            _count(
                count, len(chunk) if chunk is not None else 0, self.format.frame_bytes
            )
            self._read += count
            self._discard_consumed()

    def _discard_consumed(self):
        if not self._prefix:
            while (
                self._chunks
                and self._chunks[0][0] + len(self._chunks[0][1]) <= self._read
            ):
                self._retained -= len(self._chunks.popleft()[1])

    def commit(self):
        with self._lock:
            self._prefix = False
            self._discard_consumed()

    def take_for_pc(self):
        with self._lock:
            if not self._prefix or self.closed:
                return ()
            result = tuple(data for _, data in self._chunks)
            self.close()
            return result

    def finish(self):
        with self._lock:
            self.source_ended = True

    def close(self):
        with self._lock:
            self.closed = True
            self._chunks.clear()
            self._retained = 0
