"""
Gemini 외 공급자용 HTTP 기반 LLM 클라이언트.
OpenAI 호환, Anthropic, Ollama 경로를 제공한다.
"""
from __future__ import annotations

import base64
import binascii
import copy
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
from typing import Callable, Dict, List, Tuple
from urllib.parse import urlsplit

import requests

from ..conversation_format import prepend_message_time
from .memory_context_builder import build_memory_context as build_common_memory_context
from .openai_model_policy import normalize_reasoning_effort
from .persona_names import resolve_prompt_persona_names
from .prompt import build_runtime_system_prompt, get_parseable_emotions
from .prompt_language import resolve_prompt_language
from .response_contract import build_response_repair_prompt
from .response_envelope import (
    RESPONSE_ENVELOPE_SCHEMA_NAME,
    RESPONSE_REPAIR_SCHEMA_NAME,
    build_response_requirements,
    get_response_envelope_v1_schema,
    get_response_repair_schema,
)
from .response_pipeline import ResponseAttempt, execute_final_response
from .response_protocol import (
    InvalidFinalResponseError,
    RESPONSE_ENVELOPE_SCHEMA_ID,
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    LLMRequestKind,
    ProviderResponse,
    ProviderProfile,
    ResponseCapabilityKey,
    ResponseDeliveryMetadata,
    ResponseMode,
    ResponseStatus,
    StructuredOutputUnsupported,
)
from .response_cleanup import extract_goal_update_metadata, extract_thought_metadata
from .response_parser import (
    extract_analysis_block,
    extract_legacy_japanese_tts_lines,
    extract_tts_text,
    is_japanese,
    parse_analysis_lines,
    parse_llm_response,
)
from .summary_parser import (
    is_complete_summary_response,
    missing_summary_response_sections,
    parse_summary_memory_meta,
    parse_summary_response,
    parse_summary_response_with_topic_memory,
)
from .markdown_document_prompt import build_markdown_document_prompt
from .runtime_prompt_settings import (
    _settings_to_dict,
    build_runtime_prompt_settings_source,
)
from .summary_prompt import build_summary_prompt, build_summary_prompt_from_text
from .tool_calling import (
    build_web_search_context_from_settings,
    compose_contextual_message,
    create_web_search_decision_provider,
)
DEFAULT_GENERATION_PARAMS = {
    "temperature": 0.9,
    "top_p": 1.0,
    "max_tokens": 2048,
}
SUMMARY_MIN_OUTPUT_TOKENS = 4096

LLM_RESPONSE_TUPLE = Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict], str, Dict[str, str], List[Dict], str]
_CONTEXT_FINGERPRINT_KEY = secrets.token_bytes(32)


def _fingerprint_payload(value) -> str:
    """원문을 남기지 않고 컨텍스트 동일성만 비교하기 위한 process-local HMAC을 만든다."""
    try:
        serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except TypeError:
        serialized = str(value)
    return hmac.new(_CONTEXT_FINGERPRINT_KEY, serialized.encode("utf-8"), hashlib.sha256).hexdigest()


def _payload_length(value) -> int:
    if isinstance(value, str):
        return len(value)
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
    except TypeError:
        return len(str(value))


_CAPABILITY_ENDPOINT_FINGERPRINT_KEY = secrets.token_bytes(32)

_NAMED_PROVIDER_DEFAULT_MODES = {
    ("gemini", "gemini"): ResponseMode.JSON_SCHEMA,
    ("openai", "openai_responses"): ResponseMode.JSON_SCHEMA,
    ("openrouter", "openai_chat"): ResponseMode.JSON_SCHEMA,
    ("deepseek", "openai_chat"): ResponseMode.JSON_OBJECT,
    ("anthropic", "anthropic"): ResponseMode.JSON_SCHEMA,
}

_OFFICIAL_RESPONSE_ENDPOINTS = {
    (
        "openai_responses",
        "https",
        "api.openai.com",
        None,
        "/v1/responses",
    ): ("openai", ResponseMode.JSON_SCHEMA),
    (
        "openai_chat",
        "https",
        "api.openai.com",
        None,
        "/v1/chat/completions",
    ): ("openai", ResponseMode.JSON_SCHEMA),
    (
        "openai_chat",
        "https",
        "openrouter.ai",
        None,
        "/api/v1/chat/completions",
    ): ("openrouter", ResponseMode.JSON_SCHEMA),
    (
        "openai_chat",
        "https",
        "api.deepseek.com",
        None,
        "/chat/completions",
    ): ("deepseek", ResponseMode.JSON_OBJECT),
    (
        "openai_chat",
        "https",
        "api.deepseek.com",
        None,
        "/v1/chat/completions",
    ): ("deepseek", ResponseMode.JSON_OBJECT),
    (
        "openai_chat",
        "https",
        "api.deepseek.com",
        None,
        "/beta/chat/completions",
    ): ("deepseek", ResponseMode.STRICT_TOOL),
    (
        "anthropic",
        "https",
        "api.anthropic.com",
        None,
        "/v1/messages",
    ): ("anthropic", ResponseMode.JSON_SCHEMA),
}

_UNAMBIGUOUS_STRUCTURED_OUTPUT_PARAMETER_NAME = (
    r"(?:response_format(?:\.type|\.json_schema"
    r"(?:\.(?:strict|schema|name))?)?|"
    r"text\.format(?:\.(?:type|strict|schema|name))?|"
    r"output_config(?:\.format(?:\.(?:schema|type))?)?|"
    r"json_schema|response_mime_type|response_schema|"
    r"response_json_schema)"
)
_OLLAMA_FORMAT_PARAMETER_NAME = r"(?:format)"
_STRICT_TOOL_PARAMETER_NAME = r"(?:tool_choice|tools|strict)"
_PARAMETER_SEPARATOR = r"\W{0,24}"
_EXPLICIT_MODEL_IDENTIFIER = (
    r"(?:\"[^\"\r\n]{1,128}\"|'[^'\r\n]{1,128}'|"
    r"`[^`\r\n]{1,128}`|"
    r"(?=[\w./:@+\-]*[0-9./:_@+\-])[\w./:@+\-]+)"
)
_NATURAL_ASSERTION_START = r"\A\s*"
_SCHEMA_TOKEN = (
    r"(?<![A-Za-z0-9_-])"
    r"(?:schema|response_schema|json_schema|output_schema)"
    r"(?![A-Za-z0-9_-])"
)
_SCHEMA_VALIDATION_MARKER = (
    r"(?<![A-Za-z0-9_-])"
    r"(?:invalid|malformed|validate|validating|validation|"
    r"failed|mismatch|rejected)"
    r"(?![A-Za-z0-9_-])"
)
_SCHEMA_VALIDATION_IDENTIFIER = (
    r"(?<![A-Za-z0-9_-])(?:invalid|malformed)_schema"
    r"(?![A-Za-z0-9_-])"
)
_SCHEMA_PARSE_FAILURE_MARKER = (
    r"(?<![A-Za-z0-9_-])"
    r"(?:unable|cannot|could\s+not|failed)"
    r"(?:\s+(?:to|be))?\s+(?:parse|parsed|parsing)"
    r"(?![A-Za-z0-9_-])"
)
_SCHEMA_EXPLICIT_ERROR_PATTERN = re.compile(
    rf"(?:{_SCHEMA_TOKEN}\s+is\s+not\s+valid\b|"
    rf"(?:\bthe\s+)?{_SCHEMA_TOKEN}\s+has\s+an\s+error\b|"
    rf"{_SCHEMA_TOKEN}\s+error\b|"
    rf"\berror\s+in\s+(?:the\s+)?{_SCHEMA_TOKEN}|"
    rf"{_SCHEMA_VALIDATION_IDENTIFIER})",
    re.IGNORECASE,
)
_SCHEMA_TOKEN_PATTERN = re.compile(_SCHEMA_TOKEN, re.IGNORECASE)
_SCHEMA_VALIDATION_MARKER_PATTERN = re.compile(
    _SCHEMA_VALIDATION_MARKER,
    re.IGNORECASE,
)
_SCHEMA_PARSE_FAILURE_MARKER_PATTERN = re.compile(
    _SCHEMA_PARSE_FAILURE_MARKER,
    re.IGNORECASE,
)
_UNSUPPORTED_MARKER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])unsupported(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_SCHEMA_FEATURE_MARKER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])(?:keyword|property|feature)"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_SCHEMA_VIOLATION_MARKER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])violat(?:e|es|ed|ing)"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_SCHEMA_CONSTRAINT_MARKER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])constraint(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_ERROR_PREFIX_PATTERN = re.compile(
    r"\A\s*(?:(?:api|request)\s+error|error|bad\s+request)\s*:\s*",
    re.IGNORECASE,
)
_GUIDANCE_PREFIX_PATTERN = re.compile(
    r"\A\s*(?:"
    r"if\b|"
    r"check\s+(?:whether|if|for)\b|"
    r"(?:it|this|there)\s+(?:may|might|could)\b|"
    r"it\s+is\s+possible\b|"
    r"this\s+(?:is\s+not|isn't)\b|"
    r"(?:not|no|possibly|probably|perhaps|maybe)\b|"
    r"(?:for\s+)?example\b|"
    r"(?:the\s+)?(?:api\s+)?documentation\b|"
    r"docs?\s+example\b"
    r")",
    re.IGNORECASE,
)

_OPENROUTER_STRUCTURED_ROUTE_ABSENCE_PATTERN = re.compile(
    r"\Ano endpoints found that support the requested parameters\.?\Z",
    re.IGNORECASE,
)

def _compile_explicit_unsupported_pattern(
    parameter_name_pattern: str,
) -> re.Pattern[str]:
    parameter = (
        rf"(?<![\w./\[\]\-]){parameter_name_pattern}"
        rf"(?![\w/\[\]\-]|\.(?!\s|$))"
    )
    quoted_parameter = rf"(?:[\"'`]{parameter}[\"'`]|{parameter})"
    asserted_parameter = (
        rf"(?:\(\s*{quoted_parameter}\s*\)|{quoted_parameter})"
    )
    assertion_separator = r"(?:\s+(?:parameter\s+)?(?:is\s+)?|\s*:\s*)"
    bounded_response_type = r"(?:json_schema|json_object)"
    bounded_response_type_value = (
        rf"(?:{bounded_response_type}|'{bounded_response_type}'|"
        rf'"{bounded_response_type}"|`{bounded_response_type}`)'
    )
    response_type_modifier = rf"(?:\s+of\s+type\s+{bounded_response_type_value})?"
    return re.compile(
        rf"(?:"
        rf"\b(?:unknown|unsupported)\s+(?:parameter|field)\b"
        rf"{_PARAMETER_SEPARATOR}{quoted_parameter}"
        rf"|{_NATURAL_ASSERTION_START}(?:the\s+)?(?:"
        rf"{asserted_parameter}{assertion_separator}"
        rf"(?:unsupported|not\s+supported)\b"
        rf"|\binvalid\s+(?:parameter|field)\b"
        rf"{_PARAMETER_SEPARATOR}{asserted_parameter}{response_type_modifier}"
        rf"{_PARAMETER_SEPARATOR}(?:is\s+)?"
        rf"(?:unsupported|not\s+supported)\b"
        rf"|\binvalid\s+(?:parameter|field)\b"
        rf"{_PARAMETER_SEPARATOR}{asserted_parameter}"
        rf"\s*\.\s*this\s+(?:parameter|field)\s+is\s+"
        rf"(?:unsupported|not\s+supported)\b"
        rf"|\b(?:parameter|field)\b{_PARAMETER_SEPARATOR}"
        rf"{asserted_parameter}{_PARAMETER_SEPARATOR}"
        rf"(?:is\s+)?(?:unsupported|not\s+supported)\b"
        rf"|\b(?:this\s+|the\s+)?(?:model|provider|endpoint|api)"
        rf"(?:\s+{_EXPLICIT_MODEL_IDENTIFIER})?\s+"
        rf"does\s+not\s+support\b{_PARAMETER_SEPARATOR}"
        rf"(?:the\s+)?{asserted_parameter}"
        rf"(?:\s+(?:parameter|field))?\b"
        rf")"
        rf")",
        re.IGNORECASE,
    )


_EXPLICIT_UNAMBIGUOUS_UNSUPPORTED_PATTERN = _compile_explicit_unsupported_pattern(
    _UNAMBIGUOUS_STRUCTURED_OUTPUT_PARAMETER_NAME
)
_EXPLICIT_OLLAMA_FORMAT_UNSUPPORTED_PATTERN = _compile_explicit_unsupported_pattern(
    _OLLAMA_FORMAT_PARAMETER_NAME
)
_EXPLICIT_STRICT_TOOL_UNSUPPORTED_PATTERN = _compile_explicit_unsupported_pattern(
    _STRICT_TOOL_PARAMETER_NAME
)


def _marker_patterns_are_nearby(
    message: str,
    patterns: tuple[re.Pattern[str], ...],
    *,
    max_distance: int,
) -> bool:
    events = sorted(
        (match.start(), match.end(), pattern_index)
        for pattern_index, pattern in enumerate(patterns)
        for match in pattern.finditer(message)
    )
    counts = [0] * len(patterns)
    covered = 0
    left = 0
    for position, _, pattern_index in events:
        if counts[pattern_index] == 0:
            covered += 1
        counts[pattern_index] += 1
        while position - events[left][1] > max_distance:
            expired_index = events[left][2]
            counts[expired_index] -= 1
            if counts[expired_index] == 0:
                covered -= 1
            left += 1
        if covered == len(patterns):
            return True
    return False


def _has_schema_validation_context(message: str) -> bool:
    if _SCHEMA_EXPLICIT_ERROR_PATTERN.search(message):
        return True
    return (
        _marker_patterns_are_nearby(
            message,
            (
                _SCHEMA_TOKEN_PATTERN,
                _SCHEMA_VALIDATION_MARKER_PATTERN,
            ),
            max_distance=32,
        )
        or _marker_patterns_are_nearby(
            message,
            (
                _SCHEMA_TOKEN_PATTERN,
                _SCHEMA_PARSE_FAILURE_MARKER_PATTERN,
            ),
            max_distance=32,
        )
        or _marker_patterns_are_nearby(
            message,
            (
                _SCHEMA_TOKEN_PATTERN,
                _UNSUPPORTED_MARKER_PATTERN,
                _SCHEMA_FEATURE_MARKER_PATTERN,
            ),
            max_distance=64,
        )
        or _marker_patterns_are_nearby(
            message,
            (
                _SCHEMA_TOKEN_PATTERN,
                _SCHEMA_VIOLATION_MARKER_PATTERN,
                _SCHEMA_CONSTRAINT_MARKER_PATTERN,
            ),
            max_distance=64,
        )
    )


def _normalize_unsupported_candidate(message: str) -> str | None:
    candidate = message.strip()
    if not candidate or _GUIDANCE_PREFIX_PATTERN.search(candidate):
        return None
    candidate = _ERROR_PREFIX_PATTERN.sub("", candidate, count=1).strip()
    if not candidate or _GUIDANCE_PREFIX_PATTERN.search(candidate):
        return None
    return candidate


def _unsupported_match_messages(detail: str) -> tuple[str, ...]:
    json_detail = detail.lstrip()
    if json_detail.startswith("\ufeff"):
        json_detail = json_detail[1:].lstrip()
    json_like = json_detail.startswith(("{", "["))
    try:
        payload = json.loads(json_detail)
    except (json.JSONDecodeError, TypeError):
        return () if json_like else (json_detail,)
    if not isinstance(payload, dict):
        return ()

    messages: list[str] = []
    for key in ("message", "detail"):
        value = payload.get(key)
        if isinstance(value, str):
            messages.append(value)

    error = payload.get("error")
    if isinstance(error, str):
        messages.append(error)
    elif isinstance(error, dict):
        for key in ("message", "detail"):
            value = error.get(key)
            if isinstance(value, str):
                messages.append(value)
    return tuple(messages)


def _normalize_profile_value(value) -> str:
    return str(value or "").strip().lower()


def _parse_endpoint_identity(
    endpoint: str,
) -> tuple[str, str, int | None, str] | None:
    raw_value = str(endpoint or "")
    if any(ord(character) < 32 or ord(character) == 127 for character in raw_value):
        return None
    if raw_value != raw_value.strip():
        return None
    value = raw_value
    if not value:
        return None
    if "?" in value or "#" in value:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if not parsed.scheme or not host:
        return None
    if parsed.netloc.endswith(":"):
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.query or parsed.fragment:
        return None
    return (
        parsed.scheme.lower(),
        host.lower(),
        port,
        parsed.path,
    )


def _is_loopback_host(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _official_profile_for_endpoint(
    wire_format: str,
    endpoint: str,
) -> tuple[str, ResponseMode] | None:
    identity = _parse_endpoint_identity(endpoint)
    if identity is None:
        return None
    scheme, host, port, path = identity
    canonical_wire_format = _normalize_profile_value(wire_format)
    known = _OFFICIAL_RESPONSE_ENDPOINTS.get(
        (canonical_wire_format, scheme, host, port, path)
    )
    if known is not None:
        return known
    if (
        canonical_wire_format == "ollama"
        and scheme == "http"
        and path == "/api/chat"
        and _is_loopback_host(host)
    ):
        return "ollama", ResponseMode.JSON_SCHEMA
    return None


def default_response_mode(
    profile: ProviderProfile,
    configured_mode: str = "auto",
) -> ResponseMode:
    mode = _normalize_profile_value(configured_mode)
    if mode == "legacy":
        return ResponseMode.LEGACY_TAGS
    if mode != "auto":
        raise ValueError(f"invalid structured response mode: {configured_mode!r}")

    provider = _normalize_profile_value(profile.provider)
    wire_format = _normalize_profile_value(profile.wire_format)
    endpoint = str(profile.endpoint or "")
    if not endpoint:
        return _NAMED_PROVIDER_DEFAULT_MODES.get(
            (provider, wire_format),
            ResponseMode.LEGACY_TAGS,
        )

    official = _official_profile_for_endpoint(wire_format, endpoint)
    if official is None:
        return ResponseMode.LEGACY_TAGS
    official_provider, response_mode = official
    if provider not in {"custom_api", official_provider}:
        return ResponseMode.LEGACY_TAGS
    return response_mode


def resolve_response_mode(
    profile: ProviderProfile,
    configured_mode: str = "auto",
) -> ResponseMode:
    return default_response_mode(profile, configured_mode)


def _endpoint_fingerprint(endpoint: str) -> str:
    value = str(endpoint or "").encode("utf-8")
    return hmac.new(
        _CAPABILITY_ENDPOINT_FINGERPRINT_KEY,
        value,
        hashlib.sha256,
    ).hexdigest()


def build_capability_key(
    profile: ProviderProfile,
    *,
    request_kind: LLMRequestKind = LLMRequestKind.FINAL_REPLY,
    schema_id: str = RESPONSE_ENVELOPE_SCHEMA_ID,
    schema_version: str = RESPONSE_ENVELOPE_SCHEMA_VERSION,
) -> ResponseCapabilityKey:
    return ResponseCapabilityKey(
        provider=_normalize_profile_value(profile.provider),
        wire_format=_normalize_profile_value(profile.wire_format),
        endpoint_fingerprint=_endpoint_fingerprint(profile.endpoint),
        model=str(profile.model or "").strip(),
        request_kind=request_kind,
        schema_id=str(schema_id),
        schema_version=str(schema_version),
    )


class ResponseCapabilityRegistry:
    def __init__(self) -> None:
        self._overrides: dict[ResponseCapabilityKey, ResponseMode] = {}

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"legacy_overrides={len(self._overrides)})"
        )

    def resolve(
        self,
        profile: ProviderProfile,
        configured_mode: str = "auto",
        *,
        schema_version: str = RESPONSE_ENVELOPE_SCHEMA_VERSION,
        capability_key: ResponseCapabilityKey | None = None,
    ) -> ResponseMode:
        default_mode = default_response_mode(profile, configured_mode)
        if default_mode is ResponseMode.LEGACY_TAGS:
            return default_mode
        key = capability_key or build_capability_key(
            profile,
            schema_version=schema_version,
        )
        return self._overrides.get(key, default_mode)

    def mark_legacy(self, key: ResponseCapabilityKey) -> None:
        self._overrides[key] = ResponseMode.LEGACY_TAGS

    def clear(self) -> None:
        self._overrides.clear()


_HTTP_RESPONSE_CAPABILITY_REGISTRY = ResponseCapabilityRegistry()


def clear_http_response_capability_cache() -> None:
    """테스트와 런타임 재설정을 위해 HTTP 구조화 출력 capability 캐시를 비운다."""
    _HTTP_RESPONSE_CAPABILITY_REGISTRY.clear()


def is_explicit_structured_output_unsupported(
    failure: BaseException,
    *,
    profile: ProviderProfile | None = None,
    response_mode: ResponseMode | None = None,
) -> bool:
    if not isinstance(failure, requests.HTTPError):
        return False
    response = getattr(failure, "response", None)
    if response is None:
        return False
    try:
        status_code = int(getattr(response, "status_code", 0))
    except (TypeError, ValueError):
        return False
    if status_code not in {400, 404, 422}:
        return False
    detail = getattr(response, "text", "")
    if not isinstance(detail, str) or not detail.strip():
        return False
    raw_match_messages = _unsupported_match_messages(detail)
    match_messages = tuple(
        candidate
        for message in raw_match_messages
        if (candidate := _normalize_unsupported_candidate(message)) is not None
    )
    if (
        status_code == 404
        and response_mode is ResponseMode.JSON_SCHEMA
        and profile is not None
        and _normalize_profile_value(profile.provider)
        in {"openrouter", "custom_api"}
        and _official_profile_for_endpoint(profile.wire_format, profile.endpoint)
        == ("openrouter", ResponseMode.JSON_SCHEMA)
        and any(
            _OPENROUTER_STRUCTURED_ROUTE_ABSENCE_PATTERN.fullmatch(message.strip())
            for message in raw_match_messages
        )
    ):
        return True
    if any(
        _EXPLICIT_UNAMBIGUOUS_UNSUPPORTED_PATTERN.search(message)
        for message in match_messages
    ):
        return True
    if response_mode is ResponseMode.STRICT_TOOL:
        return any(
            _EXPLICIT_STRICT_TOOL_UNSUPPORTED_PATTERN.search(message)
            and not _has_schema_validation_context(message)
            for message in match_messages
        )
    if (
        response_mode is ResponseMode.JSON_SCHEMA
        and profile is not None
        and _normalize_profile_value(profile.provider)
        in {"ollama", "custom_api"}
        and _normalize_profile_value(profile.wire_format) == "ollama"
    ):
        return any(
            _EXPLICIT_OLLAMA_FORMAT_UNSUPPORTED_PATTERN.search(message)
            and not _has_schema_validation_context(message)
            for message in match_messages
        )
    return False

@dataclass(frozen=True)
class LLMRequestContext:
    """공급자별 payload로 변환되기 전의 공통 요청 컨텍스트."""

    provider_format: str
    request_kind: LLMRequestKind
    response_mode: ResponseMode
    schema_version: str
    system_prompt: str
    user_content: object
    history: list[dict] = field(default_factory=list)
    attachments_metadata: list[dict] = field(default_factory=list)
    include_sub_prompt: bool = True
    generation_params: dict = field(default_factory=dict)

    def fingerprint(self) -> dict:
        return {
            "provider_format": self.provider_format,
            "request_kind": self.request_kind.value,
            "response_mode": self.response_mode.value,
            "schema_version": self.schema_version,
            "include_sub_prompt": self.include_sub_prompt,
            "system_prompt_sha256": _fingerprint_payload(self.system_prompt),
            "system_prompt_chars": len(self.system_prompt),
            "user_content_sha256": _fingerprint_payload(self.user_content),
            "user_content_chars": _payload_length(self.user_content),
            "history_sha256": _fingerprint_payload(self.history),
            "history_turns": len(self.history),
            "attachments_sha256": _fingerprint_payload(self.attachments_metadata),
            "attachment_count": len(self.attachments_metadata),
            "generation_params": dict(self.generation_params),
        }


def _parse_summary_memory_meta_lines(meta_lines: list[str]) -> dict:
    """요약 응답의 MEMORY_META 줄을 정규화된 딕셔너리로 변환한다."""
    return parse_summary_memory_meta(meta_lines)

@dataclass(frozen=True)
class HTTPFinalRequestDescriptor:
    """한 번의 최종 응답 시도에 고정된 HTTP 요청 정보."""

    context: LLMRequestContext
    attempt: ResponseAttempt
    schema_name: str = ""
    schema: dict | None = None
    timeout_seconds: float = 60.0


def _build_summary_prompt(conversation_text: str) -> str:
    """HTTP 공급자 공통 요약 프롬프트를 생성한다."""
    return build_summary_prompt_from_text(conversation_text).prompt


def _extract_error_detail(response) -> str:
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = data.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    text = getattr(response, "text", "")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ""


def _safe_error_provider(provider_name: object) -> str:
    if type(provider_name) is not str:
        return "unknown"
    provider = re.sub(
        r"[^a-z0-9_.-]+",
        "_",
        provider_name.strip().lower(),
    )[:64]
    return provider or "unknown"


def _safe_error_status(response) -> str:
    try:
        status_code = getattr(response, "status_code", None)
    except Exception:
        return "unknown"
    if type(status_code) is int:
        return str(status_code) if 100 <= status_code <= 599 else "unknown"
    if type(status_code) is str:
        candidate = status_code.strip()
        if candidate.isascii() and candidate.isdigit():
            parsed = int(candidate)
            if 100 <= parsed <= 599:
                return str(parsed)
    return "unknown"


def _raise_for_status_with_detail(response, provider_name: str) -> None:
    try:
        response.raise_for_status()
        return
    except requests.HTTPError:
        pass
    provider = _safe_error_provider(provider_name)
    status = _safe_error_status(response)
    raise requests.HTTPError(
        f"provider={provider} status={status} category=http_error",
        response=response,
    ) from None


def _post_with_safe_errors(
    provider_name: str,
    url: str,
    post_request: Callable[..., object],
    **kwargs,
):
    try:
        return post_request(url, **kwargs)
    except requests.RequestException as failure:
        if isinstance(failure, requests.Timeout):
            error_type = requests.Timeout
        elif isinstance(failure, requests.ConnectionError):
            error_type = requests.ConnectionError
        else:
            error_type = requests.RequestException

    provider = _safe_error_provider(provider_name)
    raise error_type(
        f"provider={provider} status=unknown category=network_error"
    ) from None


def _normalize_generation_params(params: dict | None) -> dict:
    normalized = dict(DEFAULT_GENERATION_PARAMS)
    if not isinstance(params, dict):
        return normalized

    try:
        normalized["temperature"] = max(0.0, min(2.0, float(params.get("temperature", normalized["temperature"]))))
    except (TypeError, ValueError):
        pass

    try:
        normalized["top_p"] = max(0.0, min(1.0, float(params.get("top_p", normalized["top_p"]))))
    except (TypeError, ValueError):
        pass

    try:
        normalized["max_tokens"] = max(0, int(params.get("max_tokens", normalized["max_tokens"])))
    except (TypeError, ValueError):
        pass

    if "reasoning_effort" in params:
        normalized["reasoning_effort"] = normalize_reasoning_effort(params.get("reasoning_effort"))

    return normalized


class _CommonMixin:
    def _summary_output_token_budget(self) -> int:
        """요약은 메타 섹션까지 필요하므로 일반 답변보다 큰 최소 출력 예산을 쓴다."""
        current = 0
        try:
            current = int((getattr(self, "generation_params", {}) or {}).get("max_tokens") or 0)
        except (TypeError, ValueError):
            current = 0
        return max(SUMMARY_MIN_OUTPUT_TOKENS, current)

    @contextmanager
    def _temporary_summary_generation_budget(self):
        original = dict(getattr(self, "generation_params", {}) or {})
        updated = dict(original)
        updated["max_tokens"] = self._summary_output_token_budget()
        self.generation_params = updated
        try:
            yield
        finally:
            self.generation_params = original

    def _summary_retry_prompt(self, prompt: str, missing_sections: list[str]) -> str:
        missing = ", ".join(missing_sections) if missing_sections else "필수 섹션"
        return (
            f"{prompt}\n\n"
            "이전 요약 응답이 중간에 끊겼거나 형식이 불완전했습니다. "
            f"빠진 부분: {missing}. "
            "[SUMMARY], [MASTER_INFO], [ENE_INFO], [MEMORY_META] 네 섹션을 모두 포함해서 처음부터 다시 작성하세요."
        )

    def _request_summary_text(self, prompt: str) -> str:
        with self._temporary_summary_generation_budget():
            response_text = self._request_one_shot_raw(
                prompt,
                request_kind=LLMRequestKind.SUMMARY,
                include_sub_prompt=False,
            )
            if is_complete_summary_response(response_text):
                return response_text

            missing_sections = missing_summary_response_sections(response_text)
            print(f"[LLM] 요약 응답이 불완전해 재시도합니다. missing={missing_sections}")
            return self._request_one_shot_raw(
                self._summary_retry_prompt(prompt, missing_sections),
                request_kind=LLMRequestKind.SUMMARY,
                include_sub_prompt=False,
            )

    def _setting_enabled(self, key: str, default: bool = False) -> bool:
        settings = getattr(self, "settings", None)
        if settings is None:
            return default
        getter = getattr(settings, "get", None)
        if callable(getter):
            try:
                return bool(getter(key, default))
            except Exception:
                return default
        if isinstance(settings, dict):
            return bool(settings.get(key, default))
        return bool(getattr(settings, key, default))

    def _runtime_prompt_settings_source(self):
        """현재 선제 대화 쿨다운 상태를 반영한 프롬프트 설정을 반환한다."""
        return build_runtime_prompt_settings_source(
            getattr(self, "settings", None),
            proactive_manager=getattr(self, "proactive_manager", None),
        )

    def _build_request_context(
        self,
        user_content,
        *,
        provider_format: str,
        request_kind: LLMRequestKind,
        response_mode: ResponseMode = ResponseMode.LEGACY_TAGS,
        schema_version: str = RESPONSE_ENVELOPE_SCHEMA_VERSION,
        include_sub_prompt: bool = True,
        include_history: bool = True,
        attachments_metadata: list[dict] | None = None,
        settings_source: object | None = None,
        history_snapshot: list[dict] | None = None,
        generation_params_snapshot: dict | None = None,
    ) -> LLMRequestContext:
        normalized_request_kind = LLMRequestKind(request_kind)
        normalized_response_mode = ResponseMode(response_mode)
        prompt_settings = (
            settings_source
            if settings_source is not None
            else self._runtime_prompt_settings_source()
        )
        history_source = (
            history_snapshot
            if history_snapshot is not None
            else list(getattr(self, "_history", []) or [])
        )
        generation_source = (
            generation_params_snapshot
            if generation_params_snapshot is not None
            else dict(getattr(self, "generation_params", {}) or {})
        )
        attachments = (
            copy.deepcopy(list(attachments_metadata))
            if attachments_metadata is not None
            else self._attachment_metadata_from_content(user_content)
        )
        context = LLMRequestContext(
            provider_format=provider_format,
            request_kind=normalized_request_kind,
            response_mode=normalized_response_mode,
            schema_version=str(schema_version),
            system_prompt=build_runtime_system_prompt(
                include_sub_prompt=include_sub_prompt,
                include_analysis_appendix=True,
                settings_source=prompt_settings,
                request_kind=normalized_request_kind,
                response_mode=normalized_response_mode,
            ),
            user_content=user_content,
            history=copy.deepcopy(history_source) if include_history else [],
            attachments_metadata=attachments,
            include_sub_prompt=include_sub_prompt,
            generation_params=dict(generation_source),
        )
        fingerprint = context.fingerprint()
        self._last_request_context_fingerprint = fingerprint
        debug_enabled = (
            bool(prompt_settings.get("debug_llm_context_parity", False))
            if isinstance(prompt_settings, dict)
            else self._setting_enabled("debug_llm_context_parity", False)
        )
        if debug_enabled:
            print(f"[LLM] request context fingerprint: {fingerprint}")
        return context

    def get_last_request_context_fingerprint(self) -> dict:
        """최근 요청 컨텍스트의 privacy-safe fingerprint를 반환한다."""
        return dict(getattr(self, "_last_request_context_fingerprint", {}) or {})

    def _image_context_metadata(self, images_data: list | None) -> list[dict]:
        """이미지 원문 없이 parity 확인에 필요한 최소 메타데이터를 만든다."""
        metadata = []
        for index, image in enumerate(images_data or []):
            if not isinstance(image, dict):
                continue
            data_url = str(image.get("dataUrl", "") or "")
            mime_type = ""
            payload = data_url
            if data_url and "," in data_url:
                header, payload = data_url.split(",", 1)
                if ":" in header and ";" in header:
                    mime_type = header.split(":", 1)[1].split(";", 1)[0]
            byte_count = 0
            digest_source = payload
            if payload:
                try:
                    raw_bytes = base64.b64decode(payload, validate=True)
                    byte_count = len(raw_bytes)
                    digest_source = raw_bytes.hex()
                except (binascii.Error, ValueError):
                    byte_count = len(payload)
            metadata.append(
                {
                    "index": index,
                    "mime_type": mime_type,
                    "byte_count": byte_count,
                    "digest": _fingerprint_payload(digest_source),
                }
            )
        return metadata

    def _image_payload_metadata(self, *, index: int, payload: str, mime_type: str = "") -> dict:
        byte_count = 0
        digest_source = payload
        if payload:
            try:
                raw_bytes = base64.b64decode(payload, validate=True)
                byte_count = len(raw_bytes)
                digest_source = raw_bytes.hex()
            except (binascii.Error, ValueError):
                byte_count = len(payload)
        return {
            "index": index,
            "mime_type": mime_type,
            "byte_count": byte_count,
            "digest": _fingerprint_payload(digest_source),
        }

    def _attachment_metadata_from_content(self, content) -> list[dict]:
        """provider user content 안에 포함된 이미지 첨부를 원문 없이 요약한다."""
        metadata = []

        def add_payload(payload: str, mime_type: str = "") -> None:
            metadata.append(
                self._image_payload_metadata(
                    index=len(metadata),
                    payload=payload,
                    mime_type=mime_type,
                )
            )

        def add_data_url(data_url: str) -> None:
            payload = data_url
            mime_type = ""
            if data_url and "," in data_url:
                header, payload = data_url.split(",", 1)
                if ":" in header and ";" in header:
                    mime_type = header.split(":", 1)[1].split(";", 1)[0]
            add_payload(payload, mime_type)

        def visit(value) -> None:
            if isinstance(value, list):
                for item in value:
                    visit(item)
                return
            if not isinstance(value, dict):
                return

            image_url = value.get("image_url")
            if isinstance(image_url, dict):
                url = image_url.get("url")
                if isinstance(url, str) and url:
                    add_data_url(url)
                return
            if isinstance(image_url, str) and image_url:
                add_data_url(image_url)
                return

            inline_data = value.get("inlineData")
            if isinstance(inline_data, dict) and inline_data.get("data"):
                add_payload(
                    str(inline_data.get("data", "")),
                    mime_type=str(inline_data.get("mimeType", "")),
                )
                return

            source = value.get("source")
            if isinstance(source, dict) and source.get("data"):
                add_payload(
                    str(source.get("data", "")),
                    mime_type=str(source.get("media_type", "")),
                )
                return

            images = value.get("images")
            if isinstance(images, list):
                for image in images:
                    if image:
                        add_payload(str(image))
                return

            for nested in value.values():
                visit(nested)

        visit(content)
        return metadata

    def _empty_text_fallback_response(self) -> LLM_RESPONSE_TUPLE:
        return "음... 무슨 일이 있었나봐요.", "confused", None, [], {}, [], "", {}, [], ""

    def _parse_response_with_empty_fallback(self, response_text: str) -> LLM_RESPONSE_TUPLE:
        if not str(response_text or "").strip():
            return self._empty_text_fallback_response()
        return self._parse_response(response_text)

    def _execute_final_response(
        self,
        requester: Callable[[HTTPFinalRequestDescriptor], str | ProviderResponse],
        *,
        user_content,
        history_user_content,
        provider_format: str,
        attachments_metadata: list[dict] | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        """최종 응답을 검증한 뒤 사용자에게 보이는 텍스트만 대화 기록에 저장한다."""
        self._last_response_delivery_metadata = ResponseDeliveryMetadata.empty()
        settings_snapshot = copy.deepcopy(
            _settings_to_dict(self._runtime_prompt_settings_source())
        )
        history_snapshot = copy.deepcopy(list(getattr(self, "_history", []) or []))
        generation_params_snapshot = dict(
            getattr(self, "generation_params", {}) or {}
        )
        attachment_snapshot = (
            copy.deepcopy(list(attachments_metadata))
            if attachments_metadata is not None
            else self._attachment_metadata_from_content(user_content)
        )
        requirements = build_response_requirements(
            settings_snapshot,
            get_parseable_emotions(settings_snapshot),
        )
        profile = ProviderProfile(
            provider=str(
                getattr(self, "provider_name", "custom_api") or "custom_api"
            ),
            wire_format=str(
                getattr(self, "wire_format", provider_format) or provider_format
            ),
            endpoint=str(getattr(self, "endpoint", "") or ""),
            model=str(getattr(self, "model_name", "") or ""),
        )
        capability_key = build_capability_key(profile)
        initial_mode = _HTTP_RESPONSE_CAPABILITY_REGISTRY.resolve(
            profile,
            str(settings_snapshot.get("structured_response_mode", "auto") or "auto"),
            capability_key=capability_key,
        )

        def request_attempt(attempt: ResponseAttempt) -> ProviderResponse:
            is_repair = attempt.phase == "repair"
            if is_repair:
                request_user_content = build_response_repair_prompt(
                    attempt.preserved_reply,
                    requirements.response_language,
                    requirements.tts_language,
                    attempt.repair_fields,
                    attempt.mode,
                )
                context = LLMRequestContext(
                    provider_format=provider_format,
                    request_kind=LLMRequestKind.FINAL_REPLY,
                    response_mode=attempt.mode,
                    schema_version=RESPONSE_ENVELOPE_SCHEMA_VERSION,
                    system_prompt="",
                    user_content=request_user_content,
                    history=[],
                    attachments_metadata=[],
                    include_sub_prompt=False,
                    generation_params=dict(generation_params_snapshot),
                )
            else:
                context = self._build_request_context(
                    user_content,
                    provider_format=provider_format,
                    request_kind=LLMRequestKind.FINAL_REPLY,
                    response_mode=attempt.mode,
                    attachments_metadata=attachment_snapshot,
                    settings_source=settings_snapshot,
                    history_snapshot=history_snapshot,
                    generation_params_snapshot=generation_params_snapshot,
                )

            schema_name = ""
            schema = None
            if attempt.mode is not ResponseMode.LEGACY_TAGS:
                if is_repair:
                    schema_name = RESPONSE_REPAIR_SCHEMA_NAME
                    schema = get_response_repair_schema(attempt.repair_fields)
                else:
                    schema_name = RESPONSE_ENVELOPE_SCHEMA_NAME
                    schema = get_response_envelope_v1_schema()
            descriptor = HTTPFinalRequestDescriptor(
                context=context,
                attempt=attempt,
                schema_name=schema_name,
                schema=schema,
                timeout_seconds=20.0 if is_repair else 60.0,
            )
            try:
                raw_response = requester(descriptor)
            except Exception as failure:
                if (
                    attempt.mode is not ResponseMode.LEGACY_TAGS
                    and is_explicit_structured_output_unsupported(
                        failure,
                        profile=profile,
                        response_mode=attempt.mode,
                    )
                ):
                    raise StructuredOutputUnsupported(
                        attempt.mode,
                        provider=profile.provider,
                    ) from failure
                raise

            if isinstance(raw_response, str):
                status = (
                    ResponseStatus.COMPLETE
                    if raw_response.strip()
                    else ResponseStatus.EMPTY
                )
                return ProviderResponse(
                    carrier=raw_response,
                    status=status,
                    mode=attempt.mode,
                )
            return raw_response

        def commit_payload(payload: LLM_RESPONSE_TUPLE) -> None:
            self._history = copy.deepcopy(history_snapshot)
            self._remember_turn(
                copy.deepcopy(history_user_content),
                self._assistant_history_content_for_response("", payload),
            )

        try:
            result = execute_final_response(
                request_attempt,
                requirements=requirements,
                initial_mode=initial_mode,
                mark_unsupported=(
                    lambda _mode: _HTTP_RESPONSE_CAPABILITY_REGISTRY.mark_legacy(
                        capability_key
                    )
                ),
            )
        except InvalidFinalResponseError:
            fallback = self._empty_text_fallback_response()
            commit_payload(fallback)
            return fallback

        commit_payload(result.payload)
        self._last_response_delivery_metadata = result.metadata
        return result.payload

    def _assistant_history_content_for_response(self, response_text: str, parsed_payload: LLM_RESPONSE_TUPLE) -> str:
        return str(parsed_payload[0] or "")

    def get_last_response_delivery_metadata(self) -> ResponseDeliveryMetadata:
        """마지막으로 검증 완료된 최종 응답의 전달 메타데이터를 반환한다."""
        return getattr(
            self,
            "_last_response_delivery_metadata",
            ResponseDeliveryMetadata.empty(),
        )

    def get_last_token_usage(self) -> dict[str, None]:
        """HTTP 제공자는 아직 공통 토큰 사용량을 수집하지 않으므로 빈 값을 반환한다."""
        return {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }

    def _prompt_language(self) -> str:
        return resolve_prompt_language(settings_source=getattr(self, "settings", None))

    def _build_summary_prompt_for_messages(
        self,
        messages: list,
        loaded_topic_memory_context: str = "",
    ) -> str:
        language = self._prompt_language()
        names = resolve_prompt_persona_names(settings_source=getattr(self, "settings", None), language=language)
        return build_summary_prompt(
            messages,
            user_profile=getattr(self, "user_profile", None),
            language=language,
            assistant_name=names.assistant,
            user_name=names.user,
            loaded_topic_memory_context=loaded_topic_memory_context,
        ).prompt

    def _empty_summary_fallback_response(self) -> tuple[str, list[str], list[str], dict, list]:
        """LLM이 빈 요약을 돌려준 경우 topic 힌트 없이 안전한 fallback을 반환한다."""
        return (
            "대화 내용을 요약하지 못했어요.",
            [],
            [],
            {
                "memory_type": "general",
                "importance_reason": "empty_llm_response",
                "confidence": 0.0,
                "entity_names": [],
            },
            [],
        )

    def _summarize_conversation_from_messages(
        self,
        messages: list,
        loaded_topic_memory_context: str = "",
    ) -> tuple[str, list[str], list[str], dict, list]:
        prompt = self._build_summary_prompt_for_messages(
            messages,
            loaded_topic_memory_context=loaded_topic_memory_context,
        )
        response_text = self._request_summary_text(prompt)
        if not str(response_text or "").strip():
            return self._empty_summary_fallback_response()
        return self._parse_summary_response_with_topic_memory(response_text)

    def _remember_turn(self, user_content, assistant_content) -> None:
        self._history.append({"role": "user", "content": user_content})
        self._history.append({"role": "assistant", "content": assistant_content})

    def _create_web_search_decision_provider(self):
        return create_web_search_decision_provider(
            lambda prompt: self._request_one_shot_raw(
                prompt,
                request_kind=LLMRequestKind.DECISION,
                include_sub_prompt=False,
            )
        )

    def _to_openai_input_content(self, content) -> list[dict]:
        items = []
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    items.append({"type": "input_text", "text": str(part.get("text", ""))})
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url", {}) or {}
                    url = image_url.get("url")
                    if url:
                        items.append({"type": "input_image", "detail": "auto", "image_url": str(url)})
        if items:
            return items
        return [{"type": "input_text", "text": str(content)}]

    def _to_google_parts_from_history(self, content) -> list[dict]:
        if isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if text is not None:
                    parts.append({"text": str(text)})
                    continue
                inline_data = part.get("inlineData")
                if isinstance(inline_data, dict) and inline_data.get("data"):
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": str(inline_data.get("mimeType", "image/png")),
                                "data": str(inline_data.get("data", "")),
                            }
                        }
                    )
            if parts:
                return parts
        return [{"text": str(content)}]

    def _to_anthropic_blocks_from_history(self, content) -> list[dict]:
        if isinstance(content, list):
            blocks = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    blocks.append({"type": "text", "text": str(block.get("text", ""))})
                    continue
                if block.get("type") == "image":
                    source = block.get("source", {}) or {}
                    if source.get("data"):
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": str(source.get("type", "base64")),
                                    "media_type": str(source.get("media_type", "image/png")),
                                    "data": str(source.get("data", "")),
                                },
                            }
                        )
            if blocks:
                return blocks
        return [{"type": "text", "text": str(content)}]

    def _to_ollama_message_from_history(self, item: dict) -> dict:
        role = str(item.get("role", "user"))
        content = item.get("content", "")
        if role == "user" and isinstance(content, dict):
            message = {"role": role, "content": str(content.get("content", ""))}
            images = [str(image) for image in (content.get("images") or []) if image]
            if images:
                message["images"] = images
            return message
        return {"role": role, "content": str(content)}

    def _parse_analysis_lines(self, raw_block: str) -> Dict[str, str]:
        """analysis 메타 블록의 key=value 줄을 파싱한다."""
        return parse_analysis_lines(raw_block)

    def _extract_analysis_block(self, response_text: str) -> Tuple[str, Dict[str, str]]:
        """응답의 analysis 블록 또는 상단 메타 줄을 분리한다."""
        return extract_analysis_block(response_text)

    def _extract_thought_block(self, response_text: str) -> Tuple[str, str]:
        """응답 본문에서 에네의 짧은 속마음 블록을 분리한다."""
        return extract_thought_metadata(response_text)

    def _extract_goal_update_block(self, response_text: str) -> Tuple[str, Dict[str, str]]:
        """응답 본문에서 목표 업데이트 메타데이터 블록을 분리한다."""
        return extract_goal_update_metadata(response_text)

    def _extract_legacy_japanese_tts_lines(self, text: str) -> Tuple[str, str | None]:
        """구형 일본어 TTS 줄을 표시 텍스트와 분리한다."""
        return extract_legacy_japanese_tts_lines(text)

    def _extract_tts_text(self, text: str) -> Tuple[str, str | None]:
        """명시적 TTS 블록 또는 설정 언어에 따라 TTS용 텍스트를 분리한다."""
        return extract_tts_text(text, settings_source=getattr(self, "settings", None))

    def _build_diary_markdown_prompt(self, message: str, memory_context: str) -> str:
        return build_markdown_document_prompt(
            message,
            memory_context=memory_context,
            language=self._prompt_language(),
        )

    async def generate_markdown_document(self, message: str) -> str:
        memory_context = await self._build_memory_context(message)
        diary_prompt = self._build_diary_markdown_prompt(message, memory_context)
        response_text = self._request_one_shot_raw(
            diary_prompt,
            request_kind=LLMRequestKind.MARKDOWN,
            include_sub_prompt=False,
        )
        return (response_text or "").strip()

    async def generate_diary_completion_reply(
        self,
        context_message: str,
    ) -> LLM_RESPONSE_TUPLE:
        response_text = self._request_one_shot_raw(
            context_message,
            request_kind=LLMRequestKind.PLAIN_TEXT,
            include_sub_prompt=True,
        )
        return self._parse_response(response_text)

    async def generate_note_command_plan(self, context_message: str) -> str:
        memory_context = await self._build_memory_context(context_message)
        enhanced = f"{memory_context}\n\n{context_message}" if memory_context else context_message
        response_text = self._request_one_shot_raw(
            enhanced,
            request_kind=LLMRequestKind.DECISION,
            include_sub_prompt=False,
        )
        return (response_text or "").strip()

    async def generate_note_execution_report(
        self,
        context_message: str,
    ) -> LLM_RESPONSE_TUPLE:
        response_text = self._request_one_shot_raw(
            context_message,
            request_kind=LLMRequestKind.PLAIN_TEXT,
            include_sub_prompt=True,
        )
        return self._parse_response(response_text)

    def _parse_response(self, response_text: str) -> LLM_RESPONSE_TUPLE:
        return parse_llm_response(
            response_text,
            settings_source=getattr(self, "settings", None),
            available_emotions=get_parseable_emotions(settings_source=getattr(self, "settings", None)),
        )

    def _parse_summary_response(self, response_text: str) -> tuple[str, list[str], list[str], dict]:
        return parse_summary_response(response_text)

    def _parse_summary_response_with_topic_memory(self, response_text: str) -> tuple[str, list[str], list[str], dict, list]:
        return parse_summary_response_with_topic_memory(response_text)

    def _is_japanese(self, text: str) -> bool:
        return is_japanese(text)

    async def _build_memory_context(
        self,
        query: str,
        recent_context: str = "",
        head_pat_count_before_message: int | None = None,
    ) -> str:
        return await build_common_memory_context(
            self,
            query,
            recent_context=recent_context,
            head_pat_count_before_message=head_pat_count_before_message,
        )

    async def _build_contextual_message(
        self,
        message: str,
        *,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
    ) -> str:
        search_query = str(memory_search_text or "").strip() or message
        primary_query = str(latest_user_message or "").strip() or search_query
        support_context = str(recent_memory_context or "").strip()
        memory_context = await self._build_memory_context(
            primary_query,
            recent_context=support_context,
            head_pat_count_before_message=head_pat_count_before_message,
        )
        web_search_context = build_web_search_context_from_settings(
            getattr(self, "settings", None),
            message=message,
            latest_user_message=str(latest_user_message or ""),
            recent_context=support_context,
            progress_callback=progress_callback,
            decision_provider=self._create_web_search_decision_provider(),
            search_cache=self._get_web_search_cache(),
            turn_index=self._next_web_search_turn_index(),
        )
        return compose_contextual_message(
            message,
            memory_context=memory_context,
            web_search_context=web_search_context,
        )

    def _get_web_search_cache(self) -> dict:
        cache = getattr(self, "_web_search_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._web_search_cache = cache
        return cache

    def _next_web_search_turn_index(self) -> int:
        current = getattr(self, "_web_search_turn_index", 0)
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = 0
        current += 1
        self._web_search_turn_index = current
        return current

    def _messages_for_openai(
        self,
        user_content,
        include_sub_prompt: bool = True,
        provider_format: str = "openai_chat",
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ):
        context = (
            request_descriptor.context
            if request_descriptor is not None
            else self._build_request_context(
                user_content,
                provider_format=provider_format,
                request_kind=LLMRequestKind.FINAL_REPLY,
                include_sub_prompt=include_sub_prompt,
            )
        )
        messages = [{
            "role": "system",
            "content": context.system_prompt,
        }]
        messages.extend(context.history)
        messages.append({"role": "user", "content": context.user_content})
        return messages

    def clear_context(self):
        self._history = []
        self._web_search_cache = {}
        self._web_search_turn_index = 0
        self._last_response_delivery_metadata = ResponseDeliveryMetadata.empty()

    def _get_item_role(self, item) -> str:
        if isinstance(item, dict):
            return str(item.get("role", "")).lower()
        return str(getattr(item, "role", "")).lower()

    def rollback_last_assistant_turn(self) -> bool:
        if len(self._history) < 2:
            return False
        if self._get_item_role(self._history[-1]) != "assistant":
            return False
        if self._get_item_role(self._history[-2]) != "user":
            return False
        self._history = self._history[:-2]
        return True

    def rebuild_context_from_conversation(self, conversation_buffer: list) -> bool:
        try:
            rebuilt = []
            for item in conversation_buffer or []:
                if not item or len(item) < 2:
                    continue
                role = str(item[0]).strip().lower()
                raw_content = str(item[1]) if item[1] is not None else ""
                timestamp = str(item[2]).strip() if len(item) >= 3 and item[2] else ""
                content = prepend_message_time(raw_content, timestamp)
                if role == "assistant":
                    rebuilt.append({"role": "assistant", "content": content})
                elif role == "user":
                    rebuilt.append({"role": "user", "content": content})
            self._history = rebuilt
            return True
        except Exception:
            return False

    def get_conversation_history(self):
        return list(self._history)
