"""공급자 중립 구조화 응답의 공통 프로토콜 타입."""

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType


RESPONSE_ENVELOPE_SCHEMA_VERSION = "1"
RESPONSE_ENVELOPE_SCHEMA_ID = "response_envelope"
LIFE_RECORD_SCHEMA_ID = "life_record_output"
LIFE_RECORD_SCHEMA_VERSION = "1"


def _strict_object(properties: dict[str, dict]) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


_LIFE_RECORD_OUTPUT_SCHEMA_TEMPLATE = _strict_object(
    {
        "entries": {
            "type": "array",
            "minItems": 1,
            "maxItems": 24,
            "items": _strict_object(
                {
                    "started_at": {"type": "string"},
                    "ended_at": {"type": "string"},
                    "place": {"type": "string"},
                    "activity": {"type": "string"},
                }
            ),
        },
        "ending_state": _strict_object(
            {
                "place": {"type": "string"},
                "summary": {"type": "string"},
            }
        ),
    }
)


def _freeze_schema(value):
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_schema(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_schema(item) for item in value)
    return value


LIFE_RECORD_OUTPUT_SCHEMA = _freeze_schema(_LIFE_RECORD_OUTPUT_SCHEMA_TEMPLATE)


def get_life_record_output_schema() -> dict:
    """transport별 변경이 전역 스키마를 오염시키지 않도록 새 복사본을 반환한다."""
    return deepcopy(_LIFE_RECORD_OUTPUT_SCHEMA_TEMPLATE)


class LLMRequestKind(str, Enum):
    FINAL_REPLY = "final_reply"
    SUMMARY = "summary"
    DECISION = "decision"
    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"
    LIFE_RECORD = "life_record"


@dataclass(frozen=True)
class ProviderProfile:
    provider: str
    wire_format: str
    endpoint: str = field(repr=False)
    model: str


@dataclass(frozen=True)
class ResponseCapabilityKey:
    provider: str
    wire_format: str
    endpoint_fingerprint: str
    model: str
    request_kind: LLMRequestKind
    schema_id: str
    schema_version: str


class ResponseMode(str, Enum):
    JSON_SCHEMA = "json_schema"
    STRICT_TOOL = "strict_tool"
    JSON_OBJECT = "json_object"
    LEGACY_TAGS = "legacy_tags"


_TOKEN_USAGE_KEYS = ("input_tokens", "output_tokens", "total_tokens")
MAX_SAFE_TOKEN_COUNT = (1 << 53) - 1


def is_valid_token_count(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_SAFE_TOKEN_COUNT
    )


class TurnTokenUsageAccumulator:
    """한 final 응답 턴에서 실제 공급자 호출의 토큰 사용량을 누산한다."""

    def __init__(self):
        self.attempt_count = 0
        self._totals: dict[str, int | None] = {
            key: 0 for key in _TOKEN_USAGE_KEYS
        }

    def record(self, usage: dict[str, int | None] | None) -> None:
        self.attempt_count += 1
        for key in _TOKEN_USAGE_KEYS:
            if self._totals[key] is None:
                continue
            value = usage.get(key) if isinstance(usage, dict) else None
            if not is_valid_token_count(value):
                self._totals[key] = None
                continue
            total = self._totals[key] + value
            self._totals[key] = total if is_valid_token_count(total) else None

    def snapshot(self) -> dict[str, int | None]:
        if self.attempt_count == 0:
            return {key: None for key in _TOKEN_USAGE_KEYS}
        return {key: self._totals[key] for key in _TOKEN_USAGE_KEYS}


class ResponseStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"
    REFUSAL = "refusal"
    EMPTY = "empty"


@dataclass(frozen=True)
class OneShotTokenUsage:
    """공급자가 실제로 제공한 one-shot 토큰 사용량."""

    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None

    def __post_init__(self) -> None:
        values = (self.input_tokens, self.output_tokens, self.total_tokens)
        if any(
            value is not None and not is_valid_token_count(value)
            for value in values
        ):
            raise ValueError("invalid_token_usage")


@dataclass(frozen=True)
class OneShotGenerationResult:
    """파싱·검증 전 공급자 one-shot 생성 결과."""

    text: str = field(repr=False)
    status: ResponseStatus
    finish_reason: str = field(repr=False)
    token_usage: OneShotTokenUsage


@dataclass(frozen=True)
class ProviderResponse:
    carrier: str
    status: ResponseStatus
    mode: ResponseMode
    finish_reason: str = ""
    usage: dict[str, int | None] | None = None


class StructuredOutputUnsupported(RuntimeError):
    def __init__(self, mode: ResponseMode, *, provider: str):
        super().__init__("structured_output_unsupported")
        self.mode = mode
        self.provider = provider


class ProviderRefusalError(RuntimeError):
    def __init__(self):
        super().__init__("provider_refusal")


class InvalidFinalResponseError(RuntimeError):
    def __init__(self):
        super().__init__("invalid_final_response")


@dataclass(frozen=True)
class ResponseDeliveryMetadata:
    response_mode: str = ""
    schema_version: str = ""
    promises_authoritative: bool = False
    repair_performed: bool = False

    @classmethod
    def empty(cls) -> "ResponseDeliveryMetadata":
        return cls()
