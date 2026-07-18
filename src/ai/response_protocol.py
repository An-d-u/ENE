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
