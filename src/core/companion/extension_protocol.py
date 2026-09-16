"""기본 대화 순서와 분리된 미디어 봉투의 구문·협상·세대 검사."""

from dataclasses import dataclass
import math
import re

from .protocol import ProtocolError, integer_value, text_value, uuid_value


CAPABILITIES = ("audio_pcm_v1", "character_v1", "character_controls_v1")
AUDIO_REFS = ("conversation_id", "message_id", "operation_id", "utterance_id")
AUDIO_TYPES = frozenset(
    {
        "audio_availability",
        "audio_status",
        "audio_offer",
        "audio_prepared",
        "audio_rejected",
        "audio_start",
        "audio_started",
        "audio_source_end",
        "audio_progress",
        "audio_progress_ack",
        "audio_finished",
        "audio_cancel",
    }
)
CHARACTER_TYPES = frozenset(
    {
        "character_changed",
        "character_snapshot_request",
        "character_action",
        "character_playback",
    }
)
CONTROL_TYPES = frozenset(
    {
        "head_pat",
        "head_pat_state",
        "character_settings_patch",
        "character_settings_result",
    }
)
EXTENSION_TYPES = (
    AUDIO_TYPES
    | CHARACTER_TYPES
    | CONTROL_TYPES
    | {"extensions_ready", "extension_error"}
)
FROM_PHONE = frozenset(
    {
        "audio_availability",
        "audio_prepared",
        "audio_rejected",
        "audio_started",
        "audio_progress",
        "audio_finished",
        "audio_cancel",
        "character_snapshot_request",
        "head_pat",
        "character_settings_patch",
    }
)
FROM_PC = EXTENSION_TYPES - FROM_PHONE | {"audio_cancel"}
SMALL_TYPES = frozenset(
    {
        "audio_progress",
        "audio_progress_ack",
        "character_playback",
        "head_pat",
        "head_pat_state",
    }
)
BOOL_SETTINGS = frozenset(
    {
        "enable_builtin_idle_motion",
        "enable_auto_eye_blink",
        "enable_idle_motion",
        "enable_expressive_motion",
        "enable_expressive_pose_transitions",
        "enable_idle_synthetic_gestures",
        "enable_head_pat",
    }
)
NUMBER_SETTINGS = {
    "idle_motion_strength": (0.2, 2.0),
    "idle_motion_speed": (0.5, 2.0),
    "expressive_motion_strength": (0.2, 2.5),
    "expressive_motion_speed": (0.4, 2.0),
    "expressive_motion_speech_boost": (0.0, 2.5),
    "synthetic_gesture_scale": (0.5, 3.0),
    "head_pat_strength": (0.5, 2.5),
}
INT_SETTINGS = {
    "head_pat_fade_in_ms": (50, 1000),
    "head_pat_fade_out_ms": (50, 1200),
    "head_pat_end_emotion_duration_sec": (1, 30),
}
EXPRESSION_SETTINGS = frozenset(
    {"head_pat_active_emotion_custom", "head_pat_end_emotion_custom"}
)


@dataclass(frozen=True)
class ExtensionContext:
    registration_generation: int
    server_epoch: str
    connection_generation: str
    conversation_id: str


def wire_limit(kind):
    return (
        2048
        if kind in SMALL_TYPES
        else 49152
        if kind == "character_settings_patch"
        else 65536
    )


def negotiate(offered, supported=()):
    common = set(offered) & set(supported) & set(CAPABILITIES)
    if "character_v1" not in common:
        common.discard("character_controls_v1")
    return tuple(item for item in CAPABILITIES if item in common)


def _choice(value, choices):
    if not isinstance(value, str) or value not in choices:
        raise ProtocolError()
    return value


def _bool(value):
    if type(value) is not bool:
        raise ProtocolError()
    return value


def _number(value, minimum=-math.inf, maximum=math.inf):
    if type(value) not in {int, float}:
        raise ProtocolError()
    try:
        valid = math.isfinite(value) and minimum <= value <= maximum
    except OverflowError:
        valid = False
    if not valid:
        raise ProtocolError()
    return value


def _code(value):
    value = text_value(value)
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", value):
        raise ProtocolError()
    return value


def _digest(value, nullable=False):
    if nullable and value is None:
        return None
    value = text_value(value)
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ProtocolError()
    return value


def _object(value):
    if not isinstance(value, dict):
        raise ProtocolError()
    return value


def normalize_settings(changes):
    result = {}
    for key, value in _object(changes).items():
        if key in BOOL_SETTINGS:
            result[key] = _bool(value)
        elif key in NUMBER_SETTINGS:
            result[key] = _number(value, *NUMBER_SETTINGS[key])
        elif key in INT_SETTINGS:
            result[key] = integer_value(value, *INT_SETTINGS[key])
        elif key in EXPRESSION_SETTINGS:
            result[key] = text_value(value, max_bytes=128)
        elif key == "idle_synthetic_gesture_frequency":
            result[key] = _choice(value, {"low", "normal", "high"})
        else:
            raise ProtocolError()
    return result


def normalize_extension(kind, body):
    result = {
        "registration_generation": integer_value(
            body.get("registration_generation"), 1
        ),
        "server_epoch": uuid_value(body.get("server_epoch")),
        "connection_generation": uuid_value(body.get("connection_generation")),
    }
    get = body.get
    if kind in AUDIO_TYPES - {"audio_availability", "audio_status"}:
        result.update({key: uuid_value(get(key)) for key in AUDIO_REFS})
    if kind in {
        "head_pat",
        "head_pat_state",
        "character_action",
        "character_settings_patch",
    }:
        result["model_version"] = _digest(get("model_version"))
    if kind in {
        "audio_rejected",
        "audio_cancel",
        "audio_status",
        "audio_availability",
        "character_changed",
        "head_pat_state",
        "character_settings_result",
    }:
        result["reason"] = _code(get("reason"))
    if kind == "extensions_ready":
        capabilities = get("capabilities")
        if not isinstance(capabilities, list) or not 1 <= len(capabilities) <= 3:
            raise ProtocolError()
        capabilities = [_choice(item, CAPABILITIES) for item in capabilities]
        if len(set(capabilities)) != len(capabilities) or set(
            negotiate(capabilities, CAPABILITIES)
        ) != set(capabilities):
            raise ProtocolError()
        result["capabilities"] = capabilities
    elif kind == "audio_availability":
        result.update(
            available=_bool(get("available")),
            conversation_id=uuid_value(get("conversation_id")),
        )
    elif kind == "audio_status":
        result["mode"] = _choice(get("mode"), {"disabled", "pc_only", "auto"})
    elif kind == "audio_offer":
        result.update(
            sample_rate=integer_value(get("sample_rate"), 8000, 48000),
            channels=integer_value(get("channels"), 1, 2),
            sample_width=integer_value(get("sample_width"), 2, 2),
            prepare_timeout_ms=integer_value(get("prepare_timeout_ms"), 2000, 2000),
        )
    elif kind == "audio_prepared":
        result["buffered_frames"] = integer_value(get("buffered_frames"), 0, 48000 * 4)
    elif kind in {
        "audio_started",
        "audio_progress",
        "audio_progress_ack",
        "audio_finished",
    }:
        result["played_frames"] = integer_value(
            get("played_frames"), 0, 0 if kind == "audio_started" else 48000 * 180
        )
        if kind == "audio_progress":
            result["mouth_open"] = _number(get("mouth_open"), 0, 1)
    elif kind == "audio_source_end":
        result["total_frames"] = integer_value(get("total_frames"), 0, 48000 * 180)
    elif kind == "character_changed":
        if "model_version" not in body:
            raise ProtocolError()
        result.update(
            state_revision=integer_value(get("state_revision"), 1),
            model_version=_digest(get("model_version"), nullable=True),
        )
    elif kind == "character_action":
        result.update(
            action_seq=integer_value(get("action_seq"), 1),
            kind=_choice(get("kind"), {"expression", "gesture"}),
            action_id=text_value(get("action_id"), max_bytes=128, nonblank=True),
            duration_ms=integer_value(get("duration_ms"), 0, 30000),
        )
    elif kind == "character_playback":
        result.update(
            {
                key: uuid_value(get(key))
                for key in ("conversation_id", "message_id", "utterance_id")
            }
        )
        result.update(
            output=_choice(get("output"), {"pc", "phone", "none"}),
            played_ms=integer_value(get("played_ms"), 0, 180000),
            mouth_open=_number(get("mouth_open"), 0, 1),
            active=_bool(get("active")),
        )
    elif kind in {"head_pat", "head_pat_state"}:
        result.update(
            interaction_id=uuid_value(get("interaction_id")),
            interaction_no=integer_value(get("interaction_no"), 1),
            seq=integer_value(get("seq")),
            intensity=_number(get("intensity"), 0, 1),
            phase=_choice(
                get("phase"),
                {"start", "update", "end", "cancel"}
                if kind == "head_pat"
                else {"accepted", "update", "ended", "cancelled", "rejected"},
            ),
        )
        if kind == "head_pat_state":
            result["source"] = _choice(get("source"), {"pc", "phone"})
    elif kind == "character_settings_patch":
        parameters = _object(get("parameters"))
        if len(parameters) > 256:
            raise ProtocolError()
        result.update(
            command_id=uuid_value(get("command_id")),
            expected_revision=integer_value(get("expected_revision")),
            changes=normalize_settings(get("changes")),
            parameters={
                text_value(key, max_bytes=128, nonblank=True): None
                if value is None
                else _number(value)
                for key, value in parameters.items()
            },
        )
    elif kind == "character_settings_result":
        result.update(
            command_id=uuid_value(get("command_id")),
            status=_choice(get("status"), {"accepted", "conflict", "rejected"}),
            settings_revision=integer_value(get("settings_revision")),
        )
    elif kind == "extension_error":
        result.update(
            feature=_choice(get("feature"), CAPABILITIES), code=_code(get("code"))
        )
        if "command_id" in body:
            result["command_id"] = uuid_value(get("command_id"))
    elif kind not in {
        "audio_rejected",
        "audio_cancel",
        "audio_start",
        "character_snapshot_request",
    }:
        raise ProtocolError("unsupported_command")
    return result


def feature_for(kind, fields):
    if kind in AUDIO_TYPES:
        return "audio_pcm_v1"
    if kind in CHARACTER_TYPES:
        return "character_v1"
    if kind in CONTROL_TYPES:
        return "character_controls_v1"
    return fields.get("feature") if kind == "extension_error" else None


def validate_extension(message, context, capabilities, *, direction, sample_rate=None):
    """구문 검사 뒤 현재 연결의 권한도 확인한다. 실제 작업·모델 범위는 각 조정기가 검사한다."""
    fields, kind = message.fields, message.type
    if kind not in EXTENSION_TYPES:
        raise ProtocolError("unsupported_command")
    if (
        fields["registration_generation"],
        fields["server_epoch"],
        fields["connection_generation"],
    ) != (
        context.registration_generation,
        context.server_epoch,
        context.connection_generation,
    ) or (
        "conversation_id" in fields
        and fields["conversation_id"] != context.conversation_id
    ):
        raise ProtocolError("stale_extension")
    negotiated = set(negotiate(capabilities, CAPABILITIES))
    feature = feature_for(kind, fields)
    if (feature is not None and feature not in negotiated) or (
        kind == "extensions_ready"
        and (not negotiated or set(fields["capabilities"]) != negotiated)
    ):
        raise ProtocolError("extension_not_negotiated")
    if direction not in {"from_phone", "from_pc"} or kind not in (
        FROM_PHONE if direction == "from_phone" else FROM_PC
    ):
        raise ProtocolError("unsupported_command")
    if sample_rate is not None:
        integer_value(sample_rate, 8000, 48000)
        for name, seconds in (
            ("buffered_frames", 4),
            ("played_frames", 180),
            ("total_frames", 180),
        ):
            if name in fields and fields[name] > sample_rate * seconds:
                raise ProtocolError()
