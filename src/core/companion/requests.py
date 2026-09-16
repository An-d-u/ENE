"""Qt 소유의 현재 대화 요청 원장. 네트워크 객체나 만료 타이머가 없다."""

from dataclasses import dataclass, replace
from typing import Literal


RequestKey = tuple[int, str, str, str]


class RequestStateError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RequestRef:
    registration_generation: int
    server_epoch: str
    conversation_id: str
    request_id: str
    source: Literal["pc", "mobile", "automatic"]
    operation_id: str | None = None

    @property
    def key(self) -> RequestKey:
        return (
            self.registration_generation,
            self.server_epoch,
            self.conversation_id,
            self.request_id,
        )


@dataclass(frozen=True)
class RequestRecord:
    body_hash: str
    state: str = "reserved"
    message_id: str | None = None
    code: str | None = None
    is_new: bool = False


@dataclass(frozen=True)
class AdmissionResult:
    """본문 없이 PC 표시와 네트워크에 전달할 수락 결과."""

    request_ref: RequestRef
    state: str
    message_id: str | None = None
    code: str | None = None

    def to_wire(self):
        from .protocol import decode_message, encode_message

        payload = {
            "protocol_version": 1, "type": "request_status",
            "server_epoch": self.request_ref.server_epoch,
            "conversation_id": self.request_ref.conversation_id,
            "request_id": self.request_ref.request_id, "state": self.state,
        }
        if self.message_id is not None:
            payload["message_id"] = self.message_id
        if self.code is not None:
            payload["code"] = self.code
        return decode_message(encode_message(payload))


class RequestLedger:
    def __init__(self):
        self._records: dict[RequestKey, RequestRecord] = {}

    def lookup(self, key: RequestKey) -> RequestRecord | None:
        return self._records.get(key)

    def reserve(self, key: RequestKey, body_hash: str) -> RequestRecord:
        existing = self.lookup(key)
        if existing is not None:
            if existing.body_hash != body_hash:
                raise RequestStateError("request_conflict")
            return existing
        record = RequestRecord(body_hash=body_hash)
        self._records[key] = record
        return replace(record, is_new=True)

    def _require(self, key):
        record = self.lookup(key)
        if record is None:
            raise RequestStateError("unknown_request")
        return record

    def mark_accepted(self, key: RequestKey, message_id: str) -> RequestRecord:
        record = self._require(key)
        if (
            record.state in {"accepted", "completed", "failed"}
            and record.message_id == message_id
        ):
            return record
        if record.state != "reserved" or not message_id:
            raise RequestStateError("invalid_transition")
        result = replace(record, state="accepted", message_id=message_id)
        self._records[key] = result
        return result

    def finish(
        self, key: RequestKey, *, succeeded: bool, code: str | None = None
    ) -> RequestRecord:
        record = self._require(key)
        state = "completed" if succeeded else "failed"
        code = None if succeeded else (code or "request_failed")
        if record.state == state and record.code == code:
            return record
        if record.state not in {"reserved", "accepted"} or (
            succeeded and record.state != "accepted"
        ):
            raise RequestStateError("invalid_transition")
        result = replace(record, state=state, code=code)
        self._records[key] = result
        return result

    def discard_reservation(self, key: RequestKey):
        if self._require(key).state != "reserved":
            raise RequestStateError("invalid_transition")
        del self._records[key]

    def reset(self):
        """명시적 대화 초기화에서만 호출한다. 게이트웨이 종료에서는 호출하지 않는다."""
        self._records.clear()
