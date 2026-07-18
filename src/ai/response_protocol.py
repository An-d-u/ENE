"""공급자 중립 구조화 응답의 공통 프로토콜 타입."""

from dataclasses import dataclass, field
from enum import Enum


RESPONSE_ENVELOPE_SCHEMA_VERSION = "1"


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
    schema_version: str


class LLMRequestKind(str, Enum):
    FINAL_REPLY = "final_reply"
    SUMMARY = "summary"
    DECISION = "decision"
    MARKDOWN = "markdown"
    PLAIN_TEXT = "plain_text"


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
