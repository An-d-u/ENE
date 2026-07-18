from dataclasses import FrozenInstanceError
import json

import pytest
import requests

import src.ai.response_pipeline as response_pipeline
from src.ai.response_pipeline import (
    FinalResponseResult,
    ResponseAttempt,
    execute_final_response,
)
from src.ai.response_protocol import (
    InvalidFinalResponseError,
    ProviderRefusalError,
    ProviderResponse,
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    ResponseMode,
    ResponseStatus,
    StructuredOutputUnsupported,
)
from tests.structured_response_fixtures import (
    all_enabled_requirements,
    make_requirements,
    make_valid_envelope,
    no_repair_requirements,
    thought_and_tts_requirements,
    valid_envelope_json,
)


class RecordingRequester:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.attempts = []
        self.marked_unsupported_modes = []

    def __call__(self, attempt):
        self.attempts.append(attempt)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def mark_unsupported(self, mode):
        self.marked_unsupported_modes.append(mode)


def provider_response(
    carrier,
    *,
    mode=ResponseMode.JSON_SCHEMA,
    status=ResponseStatus.COMPLETE,
    finish_reason="",
):
    return ProviderResponse(
        carrier=carrier,
        status=status,
        mode=mode,
        finish_reason=finish_reason,
    )


def structured_unsupported(mode=ResponseMode.JSON_SCHEMA):
    return StructuredOutputUnsupported(mode, provider="synthetic_provider")


def http_error(status_code):
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError("synthetic_http_error", response=response)


def test_response_attempt_is_immutable_and_hides_preserved_reply_from_repr():
    preserved_reply = "synthetic-preserved-reply"
    attempt = ResponseAttempt(
        phase="repair",
        mode=ResponseMode.JSON_SCHEMA,
        repair_fields=("thought",),
        preserved_reply=preserved_reply,
    )

    assert preserved_reply not in repr(attempt)
    with pytest.raises(FrozenInstanceError):
        attempt.phase = "primary"


@pytest.mark.parametrize(
    "invalid_response",
    [
        provider_response("synthetic-not-json"),
        provider_response(json.dumps({"emotion": "normal"})),
        provider_response("", status=ResponseStatus.EMPTY),
        provider_response(
            "synthetic-incomplete-carrier",
            status=ResponseStatus.INCOMPLETE,
            finish_reason="stop",
        ),
    ],
    ids=("invalid-root", "missing-reply", "empty", "incomplete"),
)
def test_invalid_primary_retries_once_in_the_same_native_mode(invalid_response):
    requester = RecordingRequester(
        [
            invalid_response,
            provider_response(valid_envelope_json(reply="재생성된 합성 답변")),
        ]
    )

    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
        initial_mode=ResponseMode.JSON_SCHEMA,
        mark_unsupported=requester.mark_unsupported,
    )

    assert [attempt.phase for attempt in requester.attempts] == [
        "primary",
        "regenerate",
    ]
    assert [attempt.mode for attempt in requester.attempts] == [
        ResponseMode.JSON_SCHEMA,
        ResponseMode.JSON_SCHEMA,
    ]
    assert result.payload[0] == "재생성된 합성 답변"
    assert result.attempts == tuple(requester.attempts)
    assert requester.marked_unsupported_modes == []


@pytest.mark.parametrize(
    "second_response",
    [
        provider_response("synthetic-second-invalid-json"),
        provider_response("", status=ResponseStatus.EMPTY),
        provider_response(
            "synthetic-second-incomplete",
            status=ResponseStatus.INCOMPLETE,
            finish_reason="length",
        ),
    ],
    ids=("invalid-root", "empty", "incomplete"),
)
def test_second_invalid_response_raises_content_free_terminal_error(second_response):
    first_carrier = "synthetic-first-invalid-json"
    requester = RecordingRequester([provider_response(first_carrier), second_response])

    with pytest.raises(InvalidFinalResponseError) as caught:
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            mark_unsupported=requester.mark_unsupported,
        )

    error = caught.value
    rendered = repr(error)
    assert str(error) == "invalid_final_response"
    assert first_carrier not in rendered
    if second_response.carrier:
        assert second_response.carrier not in rendered
    assert not hasattr(error, "carrier")
    assert not hasattr(error, "reply")
    assert len(requester.attempts) == 2
    assert requester.marked_unsupported_modes == []
    with pytest.raises(TypeError):
        InvalidFinalResponseError("synthetic-raw-content")


@pytest.mark.parametrize(
    ("finish_reason", "expected_expansion"),
    [
        ("length", True),
        ("max_tokens", True),
        ("max_output_tokens", True),
        ("stop", False),
        ("", False),
    ],
)
def test_incomplete_sets_expanded_budget_only_for_length_reasons(
    finish_reason,
    expected_expansion,
):
    requester = RecordingRequester(
        [
            provider_response(
                "synthetic-incomplete-carrier",
                status=ResponseStatus.INCOMPLETE,
                finish_reason=finish_reason,
            ),
            provider_response(valid_envelope_json()),
        ]
    )

    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
    )

    assert [attempt.expand_output_budget for attempt in requester.attempts] == [
        False,
        expected_expansion,
    ]
    assert result.attempts == tuple(requester.attempts)


@pytest.mark.parametrize(
    ("status", "finish_reason"),
    [
        (ResponseStatus.EMPTY, ""),
        (ResponseStatus.INCOMPLETE, "stop"),
    ],
    ids=("empty", "incomplete"),
)
def test_noncomplete_status_takes_precedence_over_valid_carrier(
    status,
    finish_reason,
):
    skipped_reply = "채택하면 안 되는 합성 답변"
    final_reply = "재생성된 최종 합성 답변"
    requester = RecordingRequester(
        [
            provider_response(
                valid_envelope_json(reply=skipped_reply),
                status=status,
                finish_reason=finish_reason,
            ),
            provider_response(valid_envelope_json(reply=final_reply)),
        ]
    )

    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
    )

    assert result.payload[0] == final_reply
    assert [attempt.phase for attempt in result.attempts] == ["primary", "regenerate"]


def test_complete_malformed_carrier_does_not_expand_regeneration_budget():
    requester = RecordingRequester(
        [
            provider_response("synthetic-malformed-carrier", finish_reason="length"),
            provider_response(valid_envelope_json()),
        ]
    )

    execute_final_response(requester, requirements=no_repair_requirements())

    assert [attempt.expand_output_budget for attempt in requester.attempts] == [
        False,
        False,
    ]


def test_explicit_unsupported_mode_downgrades_once_then_uses_legacy():
    requester = RecordingRequester(
        [
            structured_unsupported(),
            provider_response(
                "레거시 합성 답변 [normal]",
                mode=ResponseMode.LEGACY_TAGS,
            ),
        ]
    )

    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
        initial_mode=ResponseMode.JSON_SCHEMA,
        mark_unsupported=requester.mark_unsupported,
    )

    assert [attempt.phase for attempt in requester.attempts] == ["primary", "primary"]
    assert [attempt.mode for attempt in requester.attempts] == [
        ResponseMode.JSON_SCHEMA,
        ResponseMode.LEGACY_TAGS,
    ]
    assert requester.marked_unsupported_modes == [ResponseMode.JSON_SCHEMA]
    assert result.metadata.response_mode == "legacy_tags"
    assert result.attempts == tuple(requester.attempts)


def test_native_invalid_then_regeneration_unsupported_uses_legacy_regeneration():
    requester = RecordingRequester(
        [
            provider_response("synthetic-invalid-primary"),
            structured_unsupported(),
            provider_response(
                "레거시 재생성 합성 답변 [normal]",
                mode=ResponseMode.LEGACY_TAGS,
            ),
        ]
    )

    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
        mark_unsupported=requester.mark_unsupported,
    )

    assert [(item.phase, item.mode) for item in requester.attempts] == [
        ("primary", ResponseMode.JSON_SCHEMA),
        ("regenerate", ResponseMode.JSON_SCHEMA),
        ("regenerate", ResponseMode.LEGACY_TAGS),
    ]
    assert result.payload[0] == "레거시 재생성 합성 답변"
    assert result.attempts == tuple(requester.attempts)
    assert requester.marked_unsupported_modes == [ResponseMode.JSON_SCHEMA]


def test_native_unsupported_then_invalid_legacy_regenerates_legacy_once():
    requester = RecordingRequester(
        [
            structured_unsupported(),
            provider_response("", mode=ResponseMode.LEGACY_TAGS),
            provider_response(
                "레거시 최종 합성 답변 [normal]",
                mode=ResponseMode.LEGACY_TAGS,
            ),
        ]
    )

    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
        mark_unsupported=requester.mark_unsupported,
    )

    assert [(item.phase, item.mode) for item in requester.attempts] == [
        ("primary", ResponseMode.JSON_SCHEMA),
        ("primary", ResponseMode.LEGACY_TAGS),
        ("regenerate", ResponseMode.LEGACY_TAGS),
    ]
    assert result.payload[0] == "레거시 최종 합성 답변"
    assert result.attempts == tuple(requester.attempts)
    assert requester.marked_unsupported_modes == [ResponseMode.JSON_SCHEMA]


def test_length_regeneration_keeps_expanded_budget_when_downgraded():
    requester = RecordingRequester(
        [
            provider_response(
                "synthetic-truncated-primary",
                status=ResponseStatus.INCOMPLETE,
                finish_reason="max_output_tokens",
            ),
            structured_unsupported(),
            provider_response(
                "레거시 확장 합성 답변 [normal]",
                mode=ResponseMode.LEGACY_TAGS,
            ),
        ]
    )

    result = execute_final_response(
        requester,
        requirements=no_repair_requirements(),
        mark_unsupported=requester.mark_unsupported,
    )

    assert [attempt.expand_output_budget for attempt in requester.attempts] == [
        False,
        True,
        True,
    ]
    assert result.attempts == tuple(requester.attempts)


def test_initial_legacy_unsupported_is_propagated_without_cache_change():
    unsupported = structured_unsupported(ResponseMode.LEGACY_TAGS)
    requester = RecordingRequester([unsupported])

    with pytest.raises(StructuredOutputUnsupported) as caught:
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            initial_mode=ResponseMode.LEGACY_TAGS,
            mark_unsupported=requester.mark_unsupported,
        )

    assert caught.value is unsupported
    assert requester.marked_unsupported_modes == []
    assert len(requester.attempts) == 1


def test_callback_response_mode_mismatch_stops_without_retry_or_downgrade():
    carrier = "synthetic-mode-mismatch-carrier"
    requester = RecordingRequester(
        [provider_response(carrier, mode=ResponseMode.LEGACY_TAGS)]
    )

    with pytest.raises(InvalidFinalResponseError) as caught:
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            initial_mode=ResponseMode.JSON_SCHEMA,
            mark_unsupported=requester.mark_unsupported,
        )

    assert carrier not in repr(caught.value)
    assert len(requester.attempts) == 1
    assert requester.marked_unsupported_modes == []


def test_refusal_carrier_is_not_parsed_or_downgraded(monkeypatch):
    carrier = "synthetic-refusal-carrier"
    requester = RecordingRequester(
        [provider_response(carrier, status=ResponseStatus.REFUSAL)]
    )

    def fail_if_parsed(*_args, **_kwargs):
        pytest.fail("거절 carrier를 파싱하면 안 됩니다.")

    monkeypatch.setattr(response_pipeline, "decode_response_envelope", fail_if_parsed)
    monkeypatch.setattr(response_pipeline, "parse_llm_response", fail_if_parsed)

    with pytest.raises(ProviderRefusalError) as caught:
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            mark_unsupported=requester.mark_unsupported,
        )

    assert carrier not in repr(caught.value)
    assert len(requester.attempts) == 1
    assert requester.marked_unsupported_modes == []


@pytest.mark.parametrize("finish_reason", ("content_filter", " CONTENT_FILTER "))
def test_incomplete_content_filter_is_terminal_without_parsing_or_downgrade(
    finish_reason,
    monkeypatch,
):
    carrier = valid_envelope_json(reply="파싱하면 안 되는 합성 답변")
    requester = RecordingRequester(
        [
            provider_response(
                carrier,
                status=ResponseStatus.INCOMPLETE,
                finish_reason=finish_reason,
            )
        ]
    )

    def fail_if_parsed(*_args, **_kwargs):
        pytest.fail("콘텐츠 필터 carrier를 파싱하면 안 됩니다.")

    monkeypatch.setattr(response_pipeline, "decode_response_envelope", fail_if_parsed)
    monkeypatch.setattr(response_pipeline, "parse_llm_response", fail_if_parsed)

    with pytest.raises(ProviderRefusalError):
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            mark_unsupported=requester.mark_unsupported,
        )

    assert len(requester.attempts) == 1
    assert requester.marked_unsupported_modes == []


@pytest.mark.parametrize(
    "outcome",
    [
        requests.Timeout("synthetic_timeout"),
        http_error(429),
        http_error(503),
    ],
    ids=("timeout", "429", "5xx"),
)
def test_transient_errors_do_not_downgrade_or_regenerate(outcome):
    requester = RecordingRequester([outcome])

    with pytest.raises(type(outcome)) as caught:
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            mark_unsupported=requester.mark_unsupported,
        )

    assert caught.value is outcome
    assert len(requester.attempts) == 1
    assert requester.marked_unsupported_modes == []


def test_malformed_output_never_marks_capability_legacy():
    requester = RecordingRequester(
        [
            provider_response("synthetic-malformed-primary"),
            provider_response("synthetic-malformed-regeneration"),
        ]
    )

    with pytest.raises(InvalidFinalResponseError):
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            mark_unsupported=requester.mark_unsupported,
        )

    assert requester.marked_unsupported_modes == []


def test_structured_valid_reply_with_invalid_optional_fields_succeeds_without_retry():
    envelope = make_valid_envelope(
        reply="선택 필드 오류와 무관한 합성 답변",
        thought="합성 내면 반응",
        events=[{"date": "2026-08-01", "title": "합성 일정"}],
        promises=[
            {
                "trigger_at": "",
                "title": "폐기할 합성 약속",
                "source": "user",
                "source_excerpt": "",
            }
        ],
    )
    requester = RecordingRequester(
        [provider_response(json.dumps(envelope, ensure_ascii=False))]
    )

    result = execute_final_response(
        requester,
        requirements=all_enabled_requirements(),
    )

    assert result.payload[0] == "선택 필드 오류와 무관한 합성 답변"
    assert result.payload[3] == []
    assert result.payload[5] == []
    assert len(requester.attempts) == 1
    assert result.metadata.repair_performed is False


def test_missing_thought_and_translation_tts_succeeds_without_task9_repair():
    requester = RecordingRequester(
        [provider_response(valid_envelope_json(reply="복구 전 합성 답변"))]
    )

    result = execute_final_response(
        requester,
        requirements=thought_and_tts_requirements(),
    )

    assert result.payload[0] == "복구 전 합성 답변"
    assert result.payload[2] is None
    assert result.payload[6] == ""
    assert len(requester.attempts) == 1
    assert result.metadata.repair_performed is False


def test_side_effects_from_failed_attempt_are_not_exposed():
    invalid_envelope = make_valid_envelope(
        reply="",
        events=[
            {
                "date": "2026-08-01",
                "title": "폐기할 합성 일정",
                "description": "",
            }
        ],
    )
    requester = RecordingRequester(
        [
            provider_response(json.dumps(invalid_envelope, ensure_ascii=False)),
            provider_response(valid_envelope_json(reply="최종 합성 답변")),
        ]
    )

    result = execute_final_response(
        requester,
        requirements=make_requirements(enable_events=True),
    )

    assert result.payload[0] == "최종 합성 답변"
    assert result.payload[3] == []


@pytest.mark.parametrize(
    "mode",
    (
        ResponseMode.JSON_SCHEMA,
        ResponseMode.STRICT_TOOL,
        ResponseMode.JSON_OBJECT,
    ),
)
def test_structured_modes_mark_discarded_promises_authoritative(mode):
    envelope = make_valid_envelope(
        promises=[
            {
                "trigger_at": "",
                "title": "폐기할 합성 약속",
                "source": "user",
                "source_excerpt": "",
            }
        ]
    )
    requester = RecordingRequester(
        [provider_response(json.dumps(envelope, ensure_ascii=False), mode=mode)]
    )

    result = execute_final_response(
        requester,
        requirements=make_requirements(enable_promises=True),
        initial_mode=mode,
    )

    assert result.payload[5] == []
    assert result.metadata.promises_authoritative is True
    assert result.metadata.response_mode == mode.value
    assert result.metadata.schema_version == RESPONSE_ENVELOPE_SCHEMA_VERSION


def test_legacy_mode_marks_empty_promises_non_authoritative():
    requester = RecordingRequester(
        [
            provider_response(
                "레거시 합성 답변 [normal]",
                mode=ResponseMode.LEGACY_TAGS,
            )
        ]
    )

    result = execute_final_response(
        requester,
        requirements=make_requirements(enable_promises=True),
        initial_mode=ResponseMode.LEGACY_TAGS,
        schema_version="synthetic-schema-version",
    )

    assert isinstance(result, FinalResponseResult)
    assert result.payload[5] == []
    assert result.metadata.promises_authoritative is False
    assert result.metadata.response_mode == "legacy_tags"
    assert result.metadata.schema_version == "synthetic-schema-version"
    assert result.metadata.repair_performed is False


def test_legacy_pipeline_uses_only_supplied_requirements_snapshot(monkeypatch):
    requirements = make_requirements(
        response_language="ko",
        tts_language="ja",
        require_tts_text=True,
        enable_events=True,
        enable_promises=True,
        allowed_emotions=("normal", "joy"),
    )

    def fail_if_requirements_are_rebuilt(*_args, **_kwargs):
        pytest.fail("파이프라인이 전달한 요구사항 스냅샷을 다시 만들면 안 됩니다.")

    monkeypatch.setattr(
        "src.ai.response_parser.build_response_requirements",
        fail_if_requirements_are_rebuilt,
    )
    requester = RecordingRequester(
        [
            provider_response(
                """레거시 합성 표시 답변 [event:2026-08-02|합성 일정|중립 설명]
[약속:2026-08-02T12:00:00+09:00|합성 약속|user|중립 근거] [joy]
これは合成音声です。""",
                mode=ResponseMode.LEGACY_TAGS,
            )
        ]
    )

    result = execute_final_response(
        requester,
        requirements=requirements,
        initial_mode=ResponseMode.LEGACY_TAGS,
    )

    assert result.payload[0] == "레거시 합성 표시 답변"
    assert result.payload[1] == "joy"
    assert result.payload[2] == "これは合成音声です。"
    assert result.payload[3] == [
        {
            "date": "2026-08-02",
            "title": "합성 일정",
            "description": "중립 설명",
        }
    ]
    assert result.payload[5] == [
        {
            "trigger_at": "2026-08-02T12:00:00+09:00",
            "title": "합성 약속",
            "source": "user",
            "source_excerpt": "중립 근거",
        }
    ]


def test_regeneration_refusal_remains_terminal_without_downgrade():
    requester = RecordingRequester(
        [
            provider_response("synthetic-invalid-primary"),
            provider_response(
                valid_envelope_json(reply="채택하면 안 되는 거절 carrier"),
                status=ResponseStatus.REFUSAL,
            ),
        ]
    )

    with pytest.raises(ProviderRefusalError):
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            mark_unsupported=requester.mark_unsupported,
        )

    assert [attempt.phase for attempt in requester.attempts] == [
        "primary",
        "regenerate",
    ]
    assert requester.marked_unsupported_modes == []


@pytest.mark.parametrize(
    "outcome",
    [
        requests.Timeout("synthetic_regeneration_timeout"),
        http_error(429),
        http_error(503),
    ],
    ids=("timeout", "429", "5xx"),
)
def test_regeneration_transport_errors_propagate_without_downgrade(outcome):
    requester = RecordingRequester(
        [
            provider_response("synthetic-invalid-primary"),
            outcome,
        ]
    )

    with pytest.raises(type(outcome)) as caught:
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            mark_unsupported=requester.mark_unsupported,
        )

    assert caught.value is outcome
    assert [attempt.phase for attempt in requester.attempts] == [
        "primary",
        "regenerate",
    ]
    assert requester.marked_unsupported_modes == []


def test_downgrade_during_regeneration_does_not_reset_global_budget():
    unused_fourth_response = provider_response(
        "사용하면 안 되는 네 번째 합성 답변 [normal]",
        mode=ResponseMode.LEGACY_TAGS,
    )
    requester = RecordingRequester(
        [
            provider_response("synthetic-invalid-primary"),
            structured_unsupported(),
            provider_response("", mode=ResponseMode.LEGACY_TAGS),
            unused_fourth_response,
        ]
    )

    with pytest.raises(InvalidFinalResponseError):
        execute_final_response(
            requester,
            requirements=no_repair_requirements(),
            mark_unsupported=requester.mark_unsupported,
        )

    assert [(attempt.phase, attempt.mode) for attempt in requester.attempts] == [
        ("primary", ResponseMode.JSON_SCHEMA),
        ("regenerate", ResponseMode.JSON_SCHEMA),
        ("regenerate", ResponseMode.LEGACY_TAGS),
    ]
    assert requester.outcomes == [unused_fourth_response]
    assert requester.marked_unsupported_modes == [ResponseMode.JSON_SCHEMA]
