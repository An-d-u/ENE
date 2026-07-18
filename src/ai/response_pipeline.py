"""검증된 최종 응답을 위한 공급자 중립 오케스트레이터."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .response_envelope import (
    LLM_RESPONSE_TUPLE,
    ResponseRequirements,
    decode_response_envelope,
    decode_response_repair,
    get_missing_response_repair_fields,
    has_valid_response_payload,
)
from .response_parser import parse_llm_response
from .response_protocol import (
    InvalidFinalResponseError,
    ProviderRefusalError,
    ProviderResponse,
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    ResponseDeliveryMetadata,
    ResponseMode,
    ResponseStatus,
    StructuredOutputUnsupported,
)


_OUTPUT_LIMIT_REASONS = frozenset({"length", "max_tokens", "max_output_tokens"})


@dataclass(frozen=True)
class ResponseAttempt:
    phase: str
    mode: ResponseMode
    repair_fields: tuple[str, ...] = ()
    preserved_reply: str = field(default="", repr=False)
    expand_output_budget: bool = False


@dataclass(frozen=True)
class FinalResponseResult:
    payload: LLM_RESPONSE_TUPLE
    metadata: ResponseDeliveryMetadata
    attempts: tuple[ResponseAttempt, ...]


def _decode_provider_response(
    response: ProviderResponse,
    *,
    requirements: ResponseRequirements,
) -> LLM_RESPONSE_TUPLE | None:
    if response.status is not ResponseStatus.COMPLETE:
        return None
    if response.mode is ResponseMode.LEGACY_TAGS:
        return parse_llm_response(
            response.carrier,
            available_emotions=requirements.allowed_emotions,
            requirements=requirements,
        )
    return decode_response_envelope(
        response.carrier,
        requirements=requirements,
    ).payload


def _needs_expanded_output_budget(response: ProviderResponse) -> bool:
    return (
        response.status is ResponseStatus.INCOMPLETE
        and str(response.finish_reason or "").strip().lower() in _OUTPUT_LIMIT_REASONS
    )


def _build_final_result(
    payload: LLM_RESPONSE_TUPLE,
    *,
    mode: ResponseMode,
    schema_version: str,
    attempts: list[ResponseAttempt],
    repair_performed: bool,
) -> FinalResponseResult:
    return FinalResponseResult(
        payload=payload,
        metadata=ResponseDeliveryMetadata(
            response_mode=mode.value,
            schema_version=schema_version,
            promises_authoritative=mode is not ResponseMode.LEGACY_TAGS,
            repair_performed=repair_performed,
        ),
        attempts=tuple(attempts),
    )


def _repair_missing_response_fields(
    requester: Callable[[ResponseAttempt], ProviderResponse],
    *,
    payload: LLM_RESPONSE_TUPLE,
    requirements: ResponseRequirements,
    mode: ResponseMode,
    schema_version: str,
    attempts: list[ResponseAttempt],
) -> FinalResponseResult:
    repair_fields = get_missing_response_repair_fields(
        payload,
        requirements=requirements,
    )
    if not repair_fields:
        return _build_final_result(
            payload,
            mode=mode,
            schema_version=schema_version,
            attempts=attempts,
            repair_performed=False,
        )

    repair_attempt = ResponseAttempt(
        phase="repair",
        mode=mode,
        repair_fields=repair_fields,
        preserved_reply=payload[0],
        expand_output_budget=False,
    )
    attempts.append(repair_attempt)
    try:
        response = requester(repair_attempt)
    except MemoryError:
        raise
    except Exception:
        return _build_final_result(
            payload,
            mode=mode,
            schema_version=schema_version,
            attempts=attempts,
            repair_performed=True,
        )

    repaired_fields: dict[str, str] = {}
    if (
        isinstance(response, ProviderResponse)
        and response.mode is mode
        and response.status is ResponseStatus.COMPLETE
    ):
        repaired_fields = decode_response_repair(
            response.carrier,
            mode=mode,
            fields=repair_fields,
        )

    merged_payload = list(payload)
    if "tts_text" in repair_fields and "tts_text" in repaired_fields:
        merged_payload[2] = repaired_fields["tts_text"]
    if "thought" in repair_fields and "thought" in repaired_fields:
        merged_payload[6] = repaired_fields["thought"]
    return _build_final_result(
        tuple(merged_payload),
        mode=mode,
        schema_version=schema_version,
        attempts=attempts,
        repair_performed=True,
    )


def execute_final_response(
    requester: Callable[[ResponseAttempt], ProviderResponse],
    *,
    requirements: ResponseRequirements,
    initial_mode: ResponseMode = ResponseMode.JSON_SCHEMA,
    mark_unsupported: Callable[[ResponseMode], None] | None = None,
    schema_version: str = RESPONSE_ENVELOPE_SCHEMA_VERSION,
) -> FinalResponseResult:
    """최종 응답을 검증하고 명시적 미지원 또는 무효 응답만 제한 재시도한다."""
    attempts: list[ResponseAttempt] = []
    current_mode = initial_mode
    phase = "primary"
    expand_output_budget = False
    regeneration_used = False
    downgrade_used = False

    while True:
        attempt = ResponseAttempt(
            phase=phase,
            mode=current_mode,
            expand_output_budget=expand_output_budget,
        )
        attempts.append(attempt)

        try:
            response = requester(attempt)
        except StructuredOutputUnsupported as error:
            if current_mode is ResponseMode.LEGACY_TAGS or downgrade_used:
                raise
            if error.mode is not current_mode:
                raise InvalidFinalResponseError() from None
            if mark_unsupported is not None:
                mark_unsupported(current_mode)
            downgrade_used = True
            current_mode = ResponseMode.LEGACY_TAGS
            continue

        if not isinstance(response, ProviderResponse) or response.mode is not current_mode:
            raise InvalidFinalResponseError()
        finish_reason = str(response.finish_reason or "").strip().lower()
        if response.status is ResponseStatus.REFUSAL or (
            response.status is ResponseStatus.INCOMPLETE
            and finish_reason == "content_filter"
        ):
            raise ProviderRefusalError()

        payload = _decode_provider_response(response, requirements=requirements)
        if has_valid_response_payload(payload):
            assert payload is not None
            return _repair_missing_response_fields(
                requester,
                payload=payload,
                requirements=requirements,
                mode=current_mode,
                schema_version=schema_version,
                attempts=attempts,
            )

        if regeneration_used:
            raise InvalidFinalResponseError()
        regeneration_used = True
        phase = "regenerate"
        expand_output_budget = _needs_expanded_output_budget(response)
