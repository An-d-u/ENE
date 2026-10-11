"""현재 연결이 예약한 입력만 보관한다. 검증된 입력은 Qt에서 한 번 원자 이전한다."""

from dataclasses import dataclass, field
from hashlib import sha256
from io import BytesIO
import re
import threading
import time
from uuid import uuid4

from PIL import Image

from .protocol import ProtocolError, uuid_value


IMAGE_BYTES = 4 * 1024 * 1024
PCM_BYTES = 960000
TOTAL_BYTES = 4 * IMAGE_BYTES + PCM_BYTES
UPLOAD_TTL = 120


class InputError(ValueError):
    def __init__(self, code, status=400):
        self.code, self.status = code, status
        super().__init__(code)


@dataclass(frozen=True, repr=False)
class VerifiedInput:
    body: bytes
    sha256: str
    mime: str
    width: int = 0
    height: int = 0

    @property
    def byte_length(self):
        return len(self.body)


def verify_input(body, purpose, expected_hash):
    if sha256(body).hexdigest() != expected_hash:
        raise InputError("upload_mismatch")
    if purpose == "pcm":
        if not 0 < len(body) <= PCM_BYTES or len(body) % 2:
            raise InputError("invalid_audio")
        return VerifiedInput(body, expected_hash, "audio/pcm")
    if purpose != "image" or not 0 < len(body) <= IMAGE_BYTES:
        raise InputError("invalid_image")
    try:
        with Image.open(BytesIO(body)) as image:
            if (image.format not in {"PNG", "JPEG"} or getattr(image, "n_frames", 1) != 1
                    or not 0 < image.width <= 2048 or not 0 < image.height <= 2048):
                raise InputError("invalid_image")
            mime = "image/png" if image.format == "PNG" else "image/jpeg"
            width, height = image.size
            image.verify()
        # verify는 픽셀 디코드와 다르므로 손상된 압축 데이터도 검사한다.
        with Image.open(BytesIO(body)) as image:
            image.load()
        return VerifiedInput(body, expected_hash, mime, width, height)
    except InputError:
        raise
    except Exception:
        raise InputError("invalid_image") from None


class InputBudget:
    """이전 연결의 검증 worker가 끝나기 전에도 전체 예약량 상한을 유지한다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._bytes = 0

    def acquire(self, size):
        with self._lock:
            if self._bytes + size > TOTAL_BYTES:
                raise InputError("input_limit", 429)
            self._bytes += size

    def release(self, size):
        with self._lock:
            self._bytes -= size


@dataclass(repr=False)
class _Slot:
    command_id: str
    purpose: str
    length: int
    digest: str
    expires: float
    buffer: BytesIO | None = field(default=None)
    received: int = 0
    verified: VerifiedInput | None = None
    validating: bool = False
    removed: bool = False


class UploadStore:
    def __init__(self, context, *, clock=time.monotonic, budget=None):
        self.context = context
        self._clock = clock
        self._budget = budget or InputBudget()
        self._lock = threading.RLock()
        self._slots = {}
        self._active = None
        self._closed = False

    @property
    def reserved_bytes(self):
        with self._lock:
            self._expire()
            return sum(slot.length for slot in self._slots.values())

    def _check(self, context):
        if self._closed or context != self.context:
            raise InputError("stale_extension", 409)
        self._expire()

    def _expire(self):
        for key, slot in tuple(self._slots.items()):
            if self._clock() >= slot.expires:
                self._discard(key)

    def _discard(self, key):
        slot = self._slots.pop(key, None)
        if slot is None:
            return
        slot.removed = True
        if self._active == key:
            self._active = None
        if slot.buffer is not None:
            slot.buffer.close()
            slot.buffer = None
        slot.verified = None
        # 검증 중인 바이트는 worker가 실제로 끝날 때 예산을 반환한다.
        if not slot.validating:
            self._budget.release(slot.length)

    def _slot(self, context, key):
        self._check(context)
        slot = self._slots.get(key)
        if slot is None:
            raise InputError("upload_not_found", 404)
        return slot

    def reserve(self, context, command_id, purpose, byte_length, digest):
        with self._lock:
            self._check(context)
            try:
                uuid_value(command_id)
            except ProtocolError:
                raise InputError("invalid_request") from None
            limit = IMAGE_BYTES if purpose == "image" else PCM_BYTES if purpose == "pcm" else 0
            if (type(byte_length) is not int or not 0 < byte_length <= limit
                    or (purpose == "pcm" and byte_length % 2)
                    or not isinstance(digest, str) or re.fullmatch("[a-f0-9]{64}", digest) is None):
                raise InputError("invalid_request")
            for key, slot in self._slots.items():
                if slot.command_id == command_id:
                    if (slot.purpose, slot.length, slot.digest) != (purpose, byte_length, digest):
                        raise InputError("request_conflict", 409)
                    return key
            if sum(slot.purpose == purpose for slot in self._slots.values()) >= (4 if purpose == "image" else 1):
                raise InputError("input_limit", 429)
            self._budget.acquire(byte_length)
            key = str(uuid4())
            self._slots[key] = _Slot(command_id, purpose, byte_length, digest, self._clock() + UPLOAD_TTL)
            return key

    def purpose(self, context, key):
        with self._lock:
            return self._slot(context, key).purpose

    def begin(self, context, key, length):
        with self._lock:
            slot = self._slot(context, key)
            if type(length) is not int or length != slot.length:
                raise InputError("upload_mismatch")
            if self._active is not None:
                raise InputError("upload_busy", 409)
            if slot.buffer is not None or slot.verified is not None or slot.validating:
                raise InputError("upload_already_received", 409)
            self._active = key
            slot.buffer = BytesIO()

    def append(self, context, key, chunk):
        with self._lock:
            slot = self._slot(context, key)
            if self._active != key or slot.buffer is None:
                raise InputError("upload_not_ready", 409)
            if slot.received + len(chunk) > slot.length:
                self._discard(key)
                raise InputError("upload_mismatch")
            slot.buffer.write(chunk)
            slot.received += len(chunk)

    def finish(self, context, key):
        with self._lock:
            slot = self._slot(context, key)
            if self._active != key or slot.buffer is None:
                raise InputError("upload_not_ready", 409)
            if slot.received != slot.length:
                self._discard(key)
                raise InputError("upload_mismatch")
            body = slot.buffer.getvalue()
            slot.buffer.close()
            slot.buffer = None
            slot.validating = True
        try:
            verified = verify_input(body, slot.purpose, slot.digest)
            with self._lock:
                self._slot(context, key)
                if slot.removed:
                    raise InputError("upload_not_found", 404)
                slot.verified = verified
                self._active = None
        except BaseException:
            with self._lock:
                self._discard(key)
            raise
        finally:
            with self._lock:
                slot.validating = False
                if slot.removed:
                    self._budget.release(slot.length)

    def claim(self, context, descriptors, purpose):
        with self._lock:
            self._check(context)
            limit = 4 if purpose == "image" else 1
            if not 1 <= len(descriptors) <= limit:
                raise InputError("invalid_request")
            keys = [item["upload_id"] for item in descriptors]
            if len(set(keys)) != len(keys):
                raise InputError("upload_mismatch")
            result = []
            for key, declared in zip(keys, descriptors):
                slot = self._slot(context, key)
                item = slot.verified
                if item is None:
                    raise InputError("upload_not_ready", 409)
                if slot.purpose != purpose or (item.sha256, item.byte_length, item.mime) != (
                        declared["sha256"], declared["byte_length"], declared["mime"]):
                    raise InputError("upload_mismatch")
                result.append(item)
            for key in keys:
                self._discard(key)
            return tuple(result)

    def cancel(self, context, key):
        with self._lock:
            self._check(context)
            self._discard(key)

    def reset(self, context):
        with self._lock:
            for key in tuple(self._slots):
                self._discard(key)
            self.context = context

    def close(self):
        with self._lock:
            self._closed = True
            self.reset(self.context)

    def expire(self):
        with self._lock:
            self._expire()
