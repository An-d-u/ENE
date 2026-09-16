"""기본 텍스트 계약의 엄격한 해석과 공개 허용 목록 직렬화."""

import base64
from dataclasses import dataclass, field
from datetime import datetime
import json
import re
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID


PROTOCOL_VERSION = 1
MAX_WIRE_BYTES = 65536
MAX_PREAUTH_BYTES = 8192
MAX_TEXT_BYTES = 16384
MAX_PUBLIC_TEXT_BYTES = 1048576
MAX_SNAPSHOT_BYTES = 33554432
MAX_MESSAGES = 50000
SNAPSHOT_PART_BYTES = 32768
MAX_PARTS = MAX_SNAPSHOT_BYTES // SNAPSHOT_PART_BYTES
MAX_SAFE_INTEGER = 2**53 - 1
_UUID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_CAPABILITY = re.compile(r"[a-z][a-z0-9_.:-]{0,63}\Z")
_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z\Z")


class ProtocolError(ValueError):
    """공개 가능한 고정 코드만 보관하고 원본 입력은 보관하지 않는다."""

    def __init__(self, code="invalid_message"):
        self.code = code
        super().__init__(code)


def _freeze(value):
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


@dataclass(frozen=True)
class WireMessage:
    type: str
    fields: Mapping[str, Any] = field(repr=False)

    def to_dict(self):
        return {
            "type": self.type,
            "protocol_version": PROTOCOL_VERSION,
            **_thaw(self.fields),
        }


def text_value(value, *, max_bytes=None, nonblank=False, limit_code="invalid_message"):
    if not isinstance(value, str):
        raise ProtocolError()
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise ProtocolError() from None
    if max_bytes is not None and size > max_bytes:
        raise ProtocolError(limit_code)
    if nonblank and not value.strip():
        raise ProtocolError()
    return value


def uuid_value(value):
    if not isinstance(value, str) or not _UUID.fullmatch(value):
        raise ProtocolError()
    return str(UUID(value))


def integer_value(value, minimum=0, maximum=MAX_SAFE_INTEGER):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ProtocolError()
    return value


def _object(value):
    if not isinstance(value, dict):
        raise ProtocolError()
    return value


def _symbol(value, pattern=_CODE):
    value = text_value(value)
    if not pattern.fullmatch(value):
        raise ProtocolError()
    return value


def _enum(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ProtocolError()
    return value


def _uuid_list(value, maximum):
    if not isinstance(value, list) or len(value) > maximum:
        raise ProtocolError()
    result = [uuid_value(item) for item in value]
    if len(set(result)) != len(result):
        raise ProtocolError()
    return result


def _capabilities(value):
    if not isinstance(value, list) or len(value) > 32:
        raise ProtocolError()
    result = [_symbol(item, _CAPABILITY) for item in value]
    if len(set(result)) != len(result):
        raise ProtocolError()
    return result


def _credential(value):
    value = text_value(value)
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise ProtocolError()
    decoded = base64.b64decode(value + "=", altchars=b"-_", validate=True)
    if (
        len(decoded) != 32
        or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value
    ):
        raise ProtocolError()
    return value


def _utc(value):
    value = text_value(value)
    if not _UTC.fullmatch(value):
        raise ProtocolError()
    try:
        datetime.fromisoformat(value)
    except ValueError:
        raise ProtocolError() from None
    return value


def normalize_public_message(value):
    value = _object(value)
    result = {
        "id": uuid_value(value.get("id")),
        "role": _enum(value.get("role"), {"user", "assistant"}),
        "text": text_value(value.get("text"), max_bytes=MAX_PUBLIC_TEXT_BYTES),
        "displayed_at": _utc(value.get("displayed_at")),
    }
    if "request_id" in value:
        result["request_id"] = uuid_value(value["request_id"])
    if "attachment_unsupported" in value:
        if value["attachment_unsupported"] is not True:
            raise ProtocolError()
        result["attachment_unsupported"] = True
    return result


def normalize_processing(value):
    value = _object(value)
    result = {"phase": _enum(value.get("phase"), {"idle", "preparing", "responding"})}
    if "request_id" in value:
        if result["phase"] == "idle":
            raise ProtocolError()
        result["request_id"] = uuid_value(value["request_id"])
    return result


def _session(value):
    return {
        name: uuid_value(value.get(name))
        for name in ("server_epoch", "conversation_id")
    }


def _snapshot_sizes(value):
    size = integer_value(value.get("byte_count"), 1, MAX_SNAPSHOT_BYTES)
    parts = integer_value(value.get("part_count"), 1, MAX_PARTS)
    if parts != (size + SNAPSHOT_PART_BYTES - 1) // SNAPSHOT_PART_BYTES:
        raise ProtocolError()
    digest = text_value(value.get("sha256"))
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ProtocolError()
    return {"part_count": parts, "byte_count": size, "sha256": digest}


def decode_part(value):
    value = text_value(value)
    try:
        data = base64.b64decode(value, validate=True)
    except ValueError:
        raise ProtocolError() from None
    if (
        not 1 <= len(data) <= SNAPSHOT_PART_BYTES
        or base64.b64encode(data).decode() != value
    ):
        raise ProtocolError()
    return data


def _normalize(body):
    body = _object(body)
    version = integer_value(body.get("protocol_version"))
    if version != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_version")
    kind = text_value(body.get("type"))
    from .extension_protocol import EXTENSION_TYPES, normalize_extension
    if kind in EXTENSION_TYPES:
        return WireMessage(kind, _freeze(normalize_extension(kind, body)))
    result = {}
    if kind == "hello":
        result["capabilities"] = _capabilities(body.get("capabilities", []))
    elif kind == "ready":
        result = _session(body)
        result.update(
            server_id=uuid_value(body.get("server_id")),
            registration_generation=integer_value(
                body.get("registration_generation"), 1
            ),
            capabilities=_capabilities(body.get("capabilities", [])),
        )
    elif kind == "sync_request":
        result["pending_request_ids"] = _uuid_list(
            body.get("pending_request_ids", []), 1
        )
    elif kind in {"pair_request", "pair_pending", "pair_failed", "pair_approved"}:
        result["pairing_id"] = uuid_value(body.get("pairing_id"))
        if kind == "pair_request":
            name = text_value(body.get("device_name"), nonblank=True)
            if len(name) > 80:
                raise ProtocolError()
            result.update(secret=_credential(body.get("secret")), device_name=name)
        elif kind == "pair_failed":
            result["code"] = _symbol(body.get("code"))
        elif kind == "pair_approved":
            result.update(
                server_id=uuid_value(body.get("server_id")),
                device_id=uuid_value(body.get("device_id")),
                registration_generation=integer_value(
                    body.get("registration_generation"), 1
                ),
                token=_credential(body.get("token")),
            )
    elif kind in {"snapshot_begin", "snapshot_part", "snapshot_end"}:
        result = {**_session(body), "snapshot_id": uuid_value(body.get("snapshot_id"))}
        if kind == "snapshot_part":
            decode_part(body.get("data_base64"))
            result.update(
                index=integer_value(body.get("index"), 0, MAX_PARTS - 1),
                data_base64=body["data_base64"],
            )
        else:
            result.update(_snapshot_sizes(body))
            if kind == "snapshot_begin":
                result.update(
                    event_seq=integer_value(body.get("event_seq")),
                    conversation_revision=integer_value(
                        body.get("conversation_revision")
                    ),
                    message_count=integer_value(
                        body.get("message_count"), 0, MAX_MESSAGES
                    ),
                )
    elif kind == "event":
        result = _session(body)
        op = _enum(body.get("op"), {"append", "processing"})
        payload = (
            normalize_public_message(body.get("payload"))
            if op == "append"
            else normalize_processing(body.get("payload"))
        )
        result.update(
            event_seq=integer_value(body.get("event_seq")),
            conversation_revision=integer_value(body.get("conversation_revision")),
            op=op,
            payload=payload,
        )
    elif kind == "resync_required":
        result = {
            **_session(body),
            "reason": _enum(
                body.get("reason"), {"reset", "replace", "large_event", "gap"}
            ),
        }
    elif kind == "send_text":
        result = {
            **_session(body),
            "request_id": uuid_value(body.get("request_id")),
            "text": text_value(
                body.get("text"),
                max_bytes=MAX_TEXT_BYTES,
                nonblank=True,
                limit_code="text_too_large",
            ),
        }
    elif kind == "request_status":
        result = {
            **_session(body),
            "request_id": uuid_value(body.get("request_id")),
            "state": _enum(
                body.get("state"),
                {"unknown", "reserved", "accepted", "completed", "failed", "rejected"},
            ),
        }
        if "message_id" in body:
            result["message_id"] = uuid_value(body["message_id"])
        if "code" in body:
            result["code"] = _symbol(body["code"])
    elif kind in {"ping", "pong"}:
        result["nonce"] = uuid_value(body.get("nonce"))
    elif kind == "error":
        result["code"] = _symbol(body.get("code"))
        if "request_id" in body:
            result["request_id"] = uuid_value(body["request_id"])
    else:
        raise ProtocolError("unsupported_command")
    return WireMessage(kind, _freeze(result))


def _check_depth(raw):
    depth = 0
    quoted = escaped = False
    for char in raw:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            if depth > 16:
                raise ProtocolError()
        elif char in "]}":
            depth -= 1


def _invalid_constant(_value):
    raise ProtocolError()


def decode_message(raw, *, allowed_types=None, max_bytes=MAX_WIRE_BYTES):
    try:
        if isinstance(raw, bytes):
            if len(raw) > max_bytes:
                raise ProtocolError("message_too_large")
            raw = raw.decode("utf-8")
        raw = text_value(raw, max_bytes=max_bytes, limit_code="message_too_large")
        _check_depth(raw)
        message = _normalize(json.loads(raw, parse_constant=_invalid_constant))
        from .extension_protocol import wire_limit
        text_value(raw, max_bytes=wire_limit(message.type), limit_code="message_too_large")
        if allowed_types is not None and message.type not in allowed_types:
            raise ProtocolError("unsupported_command")
        return message
    except ProtocolError:
        raise
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise ProtocolError() from None


def encode_message(message):
    body = message.to_dict() if isinstance(message, WireMessage) else message
    normalized = _normalize(body)
    raw = json.dumps(
        normalized.to_dict(), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    from .extension_protocol import wire_limit
    return text_value(raw, max_bytes=wire_limit(normalized.type), limit_code="message_too_large")
