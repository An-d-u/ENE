"""사진과 PCM 입력의 목적별 계약. 바이너리는 이 봉투에 포함하지 않는다."""

from .protocol import MAX_TEXT_BYTES, ProtocolError, integer_value, text_value, uuid_value


UPLOAD_TYPES = frozenset({"input_reserve", "input_reserved", "input_cancel"})
IMAGE_TYPES = frozenset({"chat_images_send", "chat_images_request", "chat_images_state",
                         "chat_images_invalidated", "chat_images_limits_request", "chat_images_limits"})
STT_TYPES = frozenset({"stt_limits_request", "stt_limits", "stt_begin", "stt_ready",
                      "stt_transcribe", "stt_result", "stt_cancel"})
INPUT_TYPES = UPLOAD_TYPES | IMAGE_TYPES | STT_TYPES
INPUT_FROM_PHONE = frozenset({"input_reserve", "input_cancel", "chat_images_send", "chat_images_request",
                             "chat_images_limits_request", "stt_limits_request", "stt_begin", "stt_transcribe", "stt_cancel"})


def input_feature(kind, body):
    if kind in IMAGE_TYPES:
        return "chat_images_v1"
    if kind in STT_TYPES:
        return "stt_input_v1"
    return "chat_images_v1" if body.get("purpose") == "image" else "stt_input_v1"


def normalize_input(kind, body):
    from .extension_protocol import _bool, _choice, _code, _digest, _object

    get = body.get
    result = {"conversation_id": uuid_value(get("conversation_id"))}
    if kind in UPLOAD_TYPES | {"stt_begin", "stt_ready", "stt_transcribe", "stt_result", "stt_cancel"}:
        result["command_id"] = uuid_value(get("command_id"))
    if kind in {"chat_images_request", "chat_images_state", "chat_images_limits_request", "chat_images_limits",
                "stt_limits_request", "stt_limits"}:
        result["query_id"] = uuid_value(get("query_id"))
    if kind in UPLOAD_TYPES:
        purpose = result["purpose"] = _choice(get("purpose"), {"image", "pcm"})
        if kind == "input_reserve":
            length = result["byte_length"] = integer_value(get("byte_length"), 1, 4194304 if purpose == "image" else 960000)
            if purpose == "pcm" and length % 2:
                raise ProtocolError()
            result["sha256"] = _digest(get("sha256"))
        else:
            result["upload_id"] = uuid_value(get("upload_id"))
    elif kind == "chat_images_send":
        result.update(request_id=uuid_value(get("request_id")), text=text_value(get("text"), max_bytes=MAX_TEXT_BYTES))
        images = get("images")
        if not isinstance(images, list) or not 1 <= len(images) <= 4:
            raise ProtocolError()
        result["images"] = []
        for item in images:
            item = _object(item)
            result["images"].append({
                "upload_id": uuid_value(item.get("upload_id")), "sha256": _digest(item.get("sha256")),
                "byte_length": integer_value(item.get("byte_length"), 1, 4194304),
                "mime": _choice(item.get("mime"), {"image/png", "image/jpeg"}),
            })
        if len({item["upload_id"] for item in result["images"]}) != len(images):
            raise ProtocolError()
    elif kind in {"chat_images_request", "chat_images_state", "chat_images_invalidated"}:
        result["message_id"] = uuid_value(get("message_id"))
        if kind != "chat_images_invalidated":
            result["conversation_revision"] = integer_value(get("conversation_revision"))
        if kind != "chat_images_request":
            result["attachment_revision"] = integer_value(get("attachment_revision"))
        if kind == "chat_images_state":
            images = get("images")
            if not isinstance(images, list) or len(images) > 4:
                raise ProtocolError()
            result["images"] = []
            for item in images:
                item = _object(item)
                result["images"].append({
                    "id": uuid_value(item.get("id")), "width": integer_value(item.get("width"), 1, 2048),
                    "height": integer_value(item.get("height"), 1, 2048),
                    "mime": _choice(item.get("mime"), {"image/png", "image/jpeg"}),
                })
            if len({item["id"] for item in result["images"]}) != len(images):
                raise ProtocolError()
    elif kind in {"stt_limits", "stt_ready"}:
        minimum = result["min_ms"] = integer_value(get("min_ms"), 0, 30000)
        result["max_ms"] = integer_value(get("max_ms"), max(1, minimum), 30000)
        if kind == "stt_limits":
            for name, value in (("sample_rate", 16000), ("channels", 1), ("sample_width", 2)):
                result[name] = integer_value(get(name), value, value)
    elif kind == "stt_transcribe":
        result.update(upload_id=uuid_value(get("upload_id")), sha256=_digest(get("sha256")),
                      byte_length=integer_value(get("byte_length"), 2, 960000))
        if result["byte_length"] % 2:
            raise ProtocolError()
    elif kind == "stt_result":
        status = result["status"] = _choice(get("status"), {"complete", "failed", "cancelled"})
        value = result["text"] = text_value(get("text"), max_bytes=MAX_TEXT_BYTES)
        result["reason"] = _code(get("reason"))
        if (status == "complete" and not value.strip()) or (status != "complete" and value):
            raise ProtocolError()
    if kind in {"chat_images_limits", "stt_limits"}:
        result.update(allowed=_bool(get("allowed")), reason=_code(get("reason")))
        if result["allowed"] != (result["reason"] == "ready"):
            raise ProtocolError()
        if kind == "chat_images_limits":
            result["max_count"] = integer_value(get("max_count"), 4, 4)
    return result
