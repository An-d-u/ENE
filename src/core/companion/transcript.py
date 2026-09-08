"""PC 표시 경계에서 갱신하고 불변 스냅샷을 전달하는 현재 대화 기록."""

import base64
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
from uuid import uuid4

from .protocol import (
    MAX_MESSAGES,
    MAX_PUBLIC_TEXT_BYTES,
    MAX_SAFE_INTEGER,
    MAX_SNAPSHOT_BYTES,
    SNAPSHOT_PART_BYTES,
    normalize_processing,
    text_value,
)


class TranscriptError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PublicMessage:
    id: str
    role: str
    text: str = field(repr=False)
    displayed_at: str
    request_id: str | None = None
    attachment_unsupported: bool = False

    def to_dict(self):
        result = {
            "id": self.id,
            "role": self.role,
            "text": self.text,
            "displayed_at": self.displayed_at,
        }
        if self.request_id is not None:
            result["request_id"] = self.request_id
        if self.attachment_unsupported:
            result["attachment_unsupported"] = True
        return result


@dataclass(frozen=True)
class ProcessingState:
    phase: str = "idle"
    request_id: str | None = None

    def to_dict(self):
        result = {"phase": self.phase}
        if self.request_id is not None:
            result["request_id"] = self.request_id
        return result


@dataclass(frozen=True)
class TranscriptEvent:
    server_epoch: str
    conversation_id: str
    event_seq: int
    conversation_revision: int
    op: str
    message: PublicMessage | None = None
    processing: ProcessingState | None = None

    def to_wire(self):
        if self.op == "replace":
            return {
                "type": "resync_required",
                "protocol_version": 1,
                "server_epoch": self.server_epoch,
                "conversation_id": self.conversation_id,
                "reason": "replace",
            }
        payload = self.message.to_dict() if self.message else self.processing.to_dict()
        return {
            "type": "event",
            "protocol_version": 1,
            "server_epoch": self.server_epoch,
            "conversation_id": self.conversation_id,
            "event_seq": self.event_seq,
            "conversation_revision": self.conversation_revision,
            "op": self.op,
            "payload": payload,
        }


@dataclass(frozen=True)
class CapturedTranscript:
    server_epoch: str
    conversation_id: str
    snapshot_id: str
    event_seq: int
    conversation_revision: int
    messages: tuple[PublicMessage, ...] = field(repr=False)
    processing: ProcessingState

    def to_bytes(self):
        if len(self.messages) > MAX_MESSAGES:
            raise TranscriptError("snapshot_too_large")
        for message in self.messages:
            if len(message.text.encode("utf-8")) > MAX_PUBLIC_TEXT_BYTES:
                raise TranscriptError("snapshot_too_large")
        payload = {
            "messages": [message.to_dict() for message in self.messages],
            "processing": self.processing.to_dict(),
        }
        data = bytearray()
        encoder = json.JSONEncoder(
            ensure_ascii=False, separators=(",", ":"), allow_nan=False
        )
        for piece in encoder.iterencode(payload):
            encoded = piece.encode("utf-8")
            if len(data) + len(encoded) > MAX_SNAPSHOT_BYTES:
                raise TranscriptError("snapshot_too_large")
            data.extend(encoded)
        return bytes(data)

    def wire_messages(self):
        """전체 base64 부분 목록을 만들지 않고 한 부분씩 생성한다."""
        data = self.to_bytes()
        part_count = (len(data) + SNAPSHOT_PART_BYTES - 1) // SNAPSHOT_PART_BYTES
        common = {
            "protocol_version": 1,
            "server_epoch": self.server_epoch,
            "conversation_id": self.conversation_id,
            "snapshot_id": self.snapshot_id,
        }
        sizes = {
            "part_count": part_count,
            "byte_count": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        yield {
            **common,
            **sizes,
            "type": "snapshot_begin",
            "event_seq": self.event_seq,
            "conversation_revision": self.conversation_revision,
            "message_count": len(self.messages),
        }
        for index in range(part_count):
            chunk = data[
                index * SNAPSHOT_PART_BYTES : (index + 1) * SNAPSHOT_PART_BYTES
            ]
            yield {
                **common,
                "type": "snapshot_part",
                "index": index,
                "data_base64": base64.b64encode(chunk).decode("ascii"),
            }
        yield {**common, **sizes, "type": "snapshot_end"}


class CurrentConversationTranscript:
    """소유자는 Qt 메인 스레드다. 내부 AI 컨텍스트나 영구 저장소와 연결하지 않는다."""

    def __init__(
        self, *, server_epoch=None, conversation_id=None, clock=None, id_factory=None
    ):
        self._id_factory = id_factory or (lambda: str(uuid4()))
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.server_epoch = server_epoch or self._id_factory()
        self.conversation_id = conversation_id or self._id_factory()
        self._messages: list[PublicMessage] = []
        self._published_requests: set[str] = set()
        self._event_seq = 0
        self._revision = 0
        self._processing = ProcessingState()

    def _next_event(self, op, *, message=None, processing=None):
        if self._event_seq >= MAX_SAFE_INTEGER or (
            op != "processing" and self._revision >= MAX_SAFE_INTEGER
        ):
            raise TranscriptError("sequence_exhausted")
        self._event_seq += 1
        if op != "processing":
            self._revision += 1
        return TranscriptEvent(
            self.server_epoch,
            self.conversation_id,
            self._event_seq,
            self._revision,
            op,
            message,
            processing,
        )

    def _append(self, role, text, request_id, attachment_unsupported=False):
        text_value(text)
        displayed_at = (
            self._clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )
        message = PublicMessage(
            self._id_factory(),
            role,
            text,
            displayed_at,
            request_id,
            attachment_unsupported,
        )
        event = self._next_event("append", message=message)
        self._messages.append(message)
        return event

    def append_user(self, text, *, request_id=None, attachment_unsupported=False):
        return self._append("user", text, request_id, attachment_unsupported)

    def publish_assistant(self, text, *, request_id=None):
        if request_id is not None and request_id in self._published_requests:
            return None
        event = self._append("assistant", text, request_id)
        if request_id is not None:
            self._published_requests.add(request_id)
        return event

    def set_processing(self, phase, request_id=None):
        candidate = ProcessingState(phase, request_id)
        normalize_processing(candidate.to_dict())
        if candidate == self._processing:
            return None
        event = self._next_event("processing", processing=candidate)
        self._processing = candidate
        return event

    def replace(self, target_message_id, text, *, expected_revision):
        if type(expected_revision) is not int or expected_revision != self._revision:
            raise TranscriptError("stale_target")
        index = next(
            (
                index
                for index, message in enumerate(self._messages)
                if message.id == target_message_id
            ),
            None,
        )
        if index is None:
            raise TranscriptError("stale_target")
        message = replace(self._messages[index], text=text_value(text))
        event = self._next_event("replace", message=message)
        self._messages[index] = message
        return event

    def reset(self):
        self.conversation_id = self._id_factory()
        self._messages.clear()
        self._published_requests.clear()
        self._event_seq = self._revision = 0
        self._processing = ProcessingState()

    def capture(self):
        return CapturedTranscript(
            self.server_epoch,
            self.conversation_id,
            self._id_factory(),
            self._event_seq,
            self._revision,
            tuple(self._messages),
            self._processing,
        )
