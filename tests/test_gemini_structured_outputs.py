from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest
import subprocess
import sys

from src.ai.response_envelope import RESPONSE_ENVELOPE_V1_SCHEMA
from src.ai.response_protocol import (
    LLMRequestKind,
    ProviderRefusalError,
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    ResponseMode,
    ResponseStatus,
)
from tests.gemini_structured_fixtures import valid_envelope_json


def test_gemini_final_reply_config_uses_json_schema_and_json_mime_type(
    gemini_harness,
):
    client = gemini_harness.client([valid_envelope_json()])

    config = client._build_chat_config(
        request_kind=LLMRequestKind.FINAL_REPLY,
        response_mode=ResponseMode.JSON_SCHEMA,
    )

    assert config["response_mime_type"] == "application/json"
    assert config["response_json_schema"] == RESPONSE_ENVELOPE_V1_SCHEMA
    assert config["response_json_schema"] is not RESPONSE_ENVELOPE_V1_SCHEMA


def test_gemini_non_final_configs_omit_envelope_schema(gemini_harness):
    client = gemini_harness.client([valid_envelope_json()])

    for request_kind in (
        LLMRequestKind.SUMMARY,
        LLMRequestKind.DECISION,
        LLMRequestKind.MARKDOWN,
        LLMRequestKind.PLAIN_TEXT,
    ):
        config = client._build_chat_config(
            include_sub_prompt=True,
            request_kind=request_kind,
            response_mode=ResponseMode.JSON_SCHEMA,
        )
        assert "response_mime_type" not in config
        assert "response_json_schema" not in config
        assert "response_schema" not in config


def test_gemini_session_signature_changes_with_mode_schema_and_final_prompt(
    gemini_harness,
):
    client = gemini_harness.client([valid_envelope_json()])
    first = client._runtime_prompt_signature(response_mode=ResponseMode.JSON_SCHEMA)
    second = client._runtime_prompt_signature(response_mode=ResponseMode.LEGACY_TAGS)
    assert first != second
    assert RESPONSE_ENVELOPE_SCHEMA_VERSION in first

    old = client._runtime_prompt_signature(response_mode=ResponseMode.JSON_SCHEMA)
    client.settings["enable_ene_thoughts"] = True
    new = client._runtime_prompt_signature(response_mode=ResponseMode.JSON_SCHEMA)
    assert old != new

    old = new
    client.settings["tts_language"] = "ja"
    new = client._runtime_prompt_signature(response_mode=ResponseMode.JSON_SCHEMA)
    assert old != new


def test_gemini_invalid_primary_restores_pre_turn_history_before_regeneration(
    gemini_harness,
):
    initial_history = [
        {"role": "user", "parts": [{"text": "이전 합성 질문"}]},
        {"role": "model", "parts": [{"text": "이전 합성 답변"}]},
    ]
    client = gemini_harness.client(
        ["not-json", valid_envelope_json(reply="재생성된 합성 답변")],
        history=initial_history,
    )

    result = client.send_message("현재 합성 질문")

    assert result[0] == "재생성된 합성 답변"
    assert gemini_harness.created_histories[-1] == initial_history
    history = client.get_conversation_history()
    assert history[-2] == {
        "role": "user",
        "parts": [{"text": "현재 합성 질문"}],
    }
    assert history[-1] == {
        "role": "model",
        "parts": [{"text": "재생성된 합성 답변"}],
    }
    assert "not-json" not in str(history)


def test_gemini_success_history_stores_visible_reply_not_raw_envelope(
    gemini_harness,
):
    raw = valid_envelope_json(reply="표시할 합성 답변")
    client = gemini_harness.client([raw])

    client.send_message("중립 합성 입력")

    history = client.get_conversation_history()
    assert history[-1]["parts"] == [{"text": "표시할 합성 답변"}]
    assert raw not in str(history)
    assert client.chat.get_history_calls[0] is True


def test_gemini_repair_is_historyless_and_uses_reduced_schema(gemini_harness):
    raw = valid_envelope_json(reply="복구 전 합성 답변", thought="")
    client = gemini_harness.client(
        [raw],
        repair_responses=['{"thought":"복구된 합성 생각"}'],
        settings={"enable_ene_thoughts": True},
    )
    history_before = deepcopy(client.get_conversation_history())

    result = client.send_message("복구용 합성 입력")

    assert result[0] == "복구 전 합성 답변"
    assert result[6] == "복구된 합성 생각"
    assert len(gemini_harness.repair_calls) == 1
    repair = gemini_harness.repair_calls[0]
    assert repair["config"]["response_mime_type"] == "application/json"
    assert set(repair["config"]["response_json_schema"]["properties"]) == {"thought"}
    assert "system_instruction" not in repair["config"]
    assert "복구용 합성 입력" not in str(repair["contents"])
    assert client.get_conversation_history()[: len(history_before)] == history_before


def test_gemini_max_tokens_retries_with_expanded_copy_only(gemini_harness):
    first = gemini_harness.response(
        valid_envelope_json(reply="잘린 합성 답변"),
        finish_reason="MAX_TOKENS",
    )
    client = gemini_harness.client(
        [first, valid_envelope_json(reply="완성된 합성 답변")],
        max_tokens=256,
    )

    result = client.send_message("길이 재시도 합성 입력")

    assert result[0] == "완성된 합성 답변"
    assert client.generation_params["max_tokens"] == 256
    assert gemini_harness.sdk.send_message_configs[-1]["max_output_tokens"] > 256


def test_gemini_multimodal_retry_preserves_image_and_visible_history(
    gemini_harness,
):
    initial = [{"role": "model", "parts": [{"text": "이전 합성 답변"}]}]
    client = gemini_harness.client(
        ["not-json", valid_envelope_json(reply="이미지 합성 답변")],
        history=initial,
    )
    contents = [object(), "이미지를 설명해 주세요"]

    result = client._execute_final_response(
        contents,
        history_user_content="이미지를 설명해 주세요",
        label="멀티모달",
    )

    assert result[0] == "이미지 합성 답변"
    latest_user = client.get_conversation_history()[-2]
    assert latest_user["parts"][0] == {"inline_data": {"synthetic": True}}
    assert latest_user["parts"][-1] == {"text": "이미지를 설명해 주세요"}
    assert client.get_conversation_history()[-1]["parts"] == [
        {"text": "이미지 합성 답변"}
    ]


class _SyntheticGeminiError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def test_gemini_explicit_native_parameter_unsupported_downgrades_and_caches(
    gemini_harness,
):
    unsupported = _SyntheticGeminiError(
        400,
        "Unknown parameter: response_json_schema is unsupported",
    )
    client = gemini_harness.client(
        [unsupported, "하향된 합성 답변 [normal]"],
    )

    result = client.send_message("합성 하향 입력")

    assert result[0] == "하향된 합성 답변"
    assert client.get_last_response_delivery_metadata().response_mode == "legacy_tags"
    assert "response_json_schema" not in gemini_harness.created_configs[-1]

    cached = gemini_harness.client(["캐시된 합성 답변 [normal]"])
    assert "response_json_schema" not in gemini_harness.created_configs[0]
    assert cached.send_message("합성 캐시 입력")[0] == "캐시된 합성 답변"


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (400, "Invalid schema validation for response_json_schema"),
        (429, "response_json_schema request rate exceeded"),
        (500, "response_json_schema upstream failure"),
    ],
)
def test_gemini_non_unsupported_errors_do_not_downgrade_or_leak_history(
    gemini_harness,
    code,
    message,
):
    initial = [{"role": "model", "parts": [{"text": "이전 합성 답변"}]}]
    client = gemini_harness.client(
        [_SyntheticGeminiError(code, message)],
        history=initial,
    )

    with pytest.raises(_SyntheticGeminiError):
        client.send_message("오류 합성 입력")

    assert client.get_conversation_history() == initial
    assert client.get_last_response_delivery_metadata().response_mode == ""
    probe = gemini_harness.client([valid_envelope_json(reply="네이티브 합성 답변")])
    assert "response_json_schema" in gemini_harness.created_configs[0]
    assert probe.send_message("합성 확인 입력")[0] == "네이티브 합성 답변"


def test_gemini_refusal_restores_history_without_capability_downgrade(
    gemini_harness,
):
    initial = [{"role": "model", "parts": [{"text": "이전 합성 답변"}]}]
    refusal = gemini_harness.response(
        valid_envelope_json(reply="표시하면 안 되는 합성 carrier"),
        finish_reason="SAFETY",
    )
    client = gemini_harness.client([refusal], history=initial)

    with pytest.raises(ProviderRefusalError):
        client.send_message("거절 합성 입력")

    assert client.get_conversation_history() == initial
    probe = gemini_harness.client([valid_envelope_json(reply="후속 합성 답변")])
    assert "response_json_schema" in gemini_harness.created_configs[0]
    assert probe.send_message("후속 합성 입력")[0] == "후속 합성 답변"


def test_gemini_candidate_absence_returns_fallback_and_resets_metadata(
    gemini_harness,
):
    client = gemini_harness.client([valid_envelope_json(reply="첫 합성 답변")])
    assert client.send_message("첫 합성 입력")[0] == "첫 합성 답변"
    assert client.get_last_response_delivery_metadata().response_mode == "json_schema"

    gemini_harness.sdk.chat_responses.extend(
        [
            gemini_harness.response(None, finish_reason=""),
            gemini_harness.response(None, finish_reason=""),
        ]
    )
    result = client.send_message("빈 후보 합성 입력")

    assert result[1] == "confused"
    assert client.get_last_response_delivery_metadata().response_mode == ""
    assert "빈 후보 합성 입력" not in str(client.get_conversation_history())


def test_gemini_unknown_finish_reason_regenerates_without_downgrade(
    gemini_harness,
):
    unknown = gemini_harness.response(
        valid_envelope_json(reply="미완료 합성 carrier"),
        finish_reason="UNEXPECTED_STOP",
    )
    client = gemini_harness.client(
        [unknown, valid_envelope_json(reply="재생성 합성 답변")]
    )

    assert client.send_message("종료 상태 합성 입력")[0] == "재생성 합성 답변"
    assert client.get_last_response_delivery_metadata().response_mode == "json_schema"
    assert "미완료 합성 carrier" not in str(client.get_conversation_history())


@pytest.mark.parametrize(
    ("initial_budget", "expected_retry_budget"),
    [
        (0, 8192),
        (256, 768),
        (8192, 8192),
        (16384, 16384),
    ],
)
def test_gemini_max_tokens_budget_boundaries_keep_base_snapshot(
    gemini_harness,
    initial_budget,
    expected_retry_budget,
):
    incomplete = gemini_harness.response(
        valid_envelope_json(reply="잘린 합성 carrier"),
        finish_reason="MAX_TOKENS",
    )
    client = gemini_harness.client(
        [incomplete, valid_envelope_json(reply="완성 합성 답변")],
        max_tokens=initial_budget,
    )

    assert client.send_message("예산 경계 합성 입력")[0] == "완성 합성 답변"
    assert client.generation_params["max_tokens"] == initial_budget
    assert (
        gemini_harness.sdk.send_message_configs[-1]["max_output_tokens"]
        == expected_retry_budget
    )


def test_gemini_curated_and_comprehensive_history_hide_raw_carrier(
    gemini_harness,
):
    raw = valid_envelope_json(reply="표시 전용 합성 답변")
    client = gemini_harness.client([raw])

    client.send_message("history 합성 입력")

    curated = client.chat.get_history(curated=True)
    comprehensive = client.chat.get_history(curated=False)
    assert raw not in str(curated)
    assert raw not in str(comprehensive)
    assert curated[-1]["parts"] == [{"text": "표시 전용 합성 답변"}]
    assert comprehensive[-1]["parts"] == [{"text": "표시 전용 합성 답변"}]


def test_gemini_sdk_content_history_rewrite_preserves_image_part(monkeypatch):
    class _Part:
        def __init__(self, *, text=None, inline_data=None):
            self.text = text
            self.inline_data = inline_data

        @classmethod
        def from_bytes(cls, *, data, mime_type):
            return cls(inline_data={"data": data, "mime_type": mime_type})

        @classmethod
        def from_text(cls, *, text):
            return cls(text=text)

    class _Content:
        def __init__(self, *, role, parts):
            self.role = role
            self.parts = parts

    image = _Part.from_bytes(data=b"synthetic", mime_type="image/png")
    text = _Part.from_text(text="Synthetic extended prompt")
    model = _Part.from_text(text="Synthetic raw carrier")
    history = [
        _Content(role="user", parts=[image, text]),
        _Content(role="model", parts=[model]),
    ]

    class _Chat:
        def get_history(self, curated=False):
            return history

    llm_module = __import__("src.ai.llm_client", fromlist=["GeminiClient"])
    monkeypatch.setattr(
        llm_module.genai,
        "types",
        SimpleNamespace(Part=_Part),
        raising=False,
    )
    client = object.__new__(llm_module.GeminiClient)
    client.chat = _Chat()

    client._replace_latest_user_history_text("Visible synthetic prompt")
    client._replace_latest_model_history_with_visible_reply("Visible synthetic reply")

    assert history[0].parts[0].inline_data is not None
    assert history[0].parts[1].text == "Visible synthetic prompt"
    assert len(history[1].parts) == 1
    assert history[1].parts[0].text == "Visible synthetic reply"


def test_google_genai_generate_content_config_accepts_json_schema():
    script = "\n".join(
        [
            "from google.genai import types",
            "config = types.GenerateContentConfig(",
            "    response_mime_type='application/json',",
            "    response_json_schema={'type': 'object', 'properties': {}},",
            ")",
            "assert config.response_mime_type == 'application/json'",
            "assert config.response_json_schema == {'type': 'object', 'properties': {}}",
        ]
    )
    completed = subprocess.run(
        [sys.executable, "-c", script], check=False, capture_output=True, text=True
    )

    assert completed.returncode == 0, completed.stderr


def test_gemini_rewrites_distinct_curated_and_comprehensive_histories():
    raw = valid_envelope_json(reply="Visible synthetic reply")

    class _Chat:
        def __init__(self):
            self.curated = [
                {
                    "role": "user",
                    "parts": [
                        {"inline_data": {"synthetic": True}},
                        {"text": "raw synthetic prompt"},
                    ],
                },
                {"role": "model", "parts": [{"text": raw}]},
            ]
            self.comprehensive = deepcopy(self.curated)

        def get_history(self, curated=False):
            return self.curated if curated else self.comprehensive

    client = object.__new__(
        __import__("src.ai.llm_client", fromlist=["GeminiClient"]).GeminiClient
    )
    client.chat = _Chat()

    client._replace_latest_user_history_text("Visible synthetic prompt")
    client._replace_latest_model_history_with_visible_reply("Visible synthetic reply")

    for history in (client.chat.curated, client.chat.comprehensive):
        assert raw not in str(history)
        assert history[-2]["parts"][0] == {"inline_data": {"synthetic": True}}
        assert history[-2]["parts"][-1] == {"text": "Visible synthetic prompt"}
        assert history[-1]["parts"] == [{"text": "Visible synthetic reply"}]


def test_gemini_length_retry_does_not_stick_expanded_budget(gemini_harness):
    incomplete = gemini_harness.response(
        valid_envelope_json(reply="Truncated synthetic reply"),
        finish_reason="MAX_TOKENS",
    )
    client = gemini_harness.client(
        [
            incomplete,
            valid_envelope_json(reply="Completed synthetic reply"),
            valid_envelope_json(reply="Next synthetic reply"),
        ],
        max_tokens=256,
    )

    assert (
        client.send_message("First synthetic prompt")[0] == "Completed synthetic reply"
    )
    assert gemini_harness.created_configs[-1]["max_output_tokens"] == 256
    assert gemini_harness.sdk.send_message_configs[-1]["max_output_tokens"] == 768

    assert client.send_message("Next synthetic prompt")[0] == "Next synthetic reply"
    assert gemini_harness.sdk.send_message_configs[-1] is None


@pytest.mark.parametrize(
    "finish_reason",
    ["IMAGE_SAFETY", "IMAGE_PROHIBITED_CONTENT", "IMAGE_RECITATION"],
)
def test_gemini_image_safety_finish_reasons_are_refusals(
    gemini_harness,
    finish_reason,
):
    client = gemini_harness.client([valid_envelope_json()])
    response = gemini_harness.response(
        valid_envelope_json(reply="Blocked synthetic carrier"),
        finish_reason=finish_reason,
    )

    provider_response = client._provider_response(response, ResponseMode.JSON_SCHEMA)

    assert provider_response.status is ResponseStatus.REFUSAL
    assert provider_response.finish_reason == "content_filter"


@pytest.mark.parametrize(
    "block_reason_name",
    ["BLOCK_REASON_UNSPECIFIED", "BLOCKED_REASON_UNSPECIFIED"],
)
def test_gemini_unspecified_prompt_block_reason_is_empty_not_refusal(
    gemini_harness,
    block_reason_name,
):
    client = gemini_harness.client([valid_envelope_json()])
    response = gemini_harness.response(None, finish_reason="")
    response.prompt_feedback = SimpleNamespace(
        block_reason=SimpleNamespace(name=block_reason_name)
    )

    provider_response = client._provider_response(response, ResponseMode.JSON_SCHEMA)

    assert provider_response.status is ResponseStatus.EMPTY


def test_gemini_camel_case_native_parameter_unsupported_downgrades_and_caches(
    gemini_harness,
):
    unsupported = _SyntheticGeminiError(
        400,
        "Unknown field: responseJsonSchema is unsupported",
    )
    client = gemini_harness.client(
        [unsupported, "Downgraded synthetic reply [normal]"],
    )

    assert (
        client.send_message("Synthetic downgrade prompt")[0]
        == "Downgraded synthetic reply"
    )
    assert client.get_last_response_delivery_metadata().response_mode == "legacy_tags"

    cached = gemini_harness.client(["Cached synthetic reply [normal]"])
    assert "response_json_schema" not in gemini_harness.created_configs[0]
    assert cached.send_message("Synthetic cache prompt")[0] == "Cached synthetic reply"


def test_gemini_camel_case_invalid_schema_does_not_downgrade(gemini_harness):
    client = gemini_harness.client(
        [_SyntheticGeminiError(400, "Invalid schema for responseJsonSchema")],
    )

    with pytest.raises(_SyntheticGeminiError):
        client.send_message("Synthetic invalid schema prompt")



def test_gemini_turn_uses_one_frozen_settings_snapshot_across_retry(
    gemini_harness,
):
    holder = {}

    def mutate_settings_during_first_response():
        holder["client"].settings["enable_ene_thoughts"] = True
        return gemini_harness.response("not-json")

    client = gemini_harness.client(
        [
            mutate_settings_during_first_response,
            valid_envelope_json(reply="Frozen synthetic reply"),
            valid_envelope_json(
                reply="Next synthetic reply",
                thought="Next synthetic thought",
            ),
        ],
    )
    holder["client"] = client
    first_prompt = gemini_harness.created_configs[0]["system_instruction"]

    assert client.send_message("Frozen synthetic prompt")[0] == "Frozen synthetic reply"
    assert gemini_harness.created_configs[-1]["system_instruction"] == first_prompt
    assert (
        gemini_harness.sdk.send_message_configs[-1]["system_instruction"]
        == first_prompt
    )

    session_count = len(gemini_harness.created_configs)
    assert client.send_message("Next synthetic prompt")[0] == "Next synthetic reply"
    assert len(gemini_harness.created_configs) == session_count + 1
    assert gemini_harness.created_configs[-1]["system_instruction"] != first_prompt


@pytest.mark.parametrize(
    "message",
    [
        "response_json_schema has unsupported schema keyword additionalProperties",
        "Unknown field: minLength at responseJsonSchema.properties.reply",
        "unsupported field: response_json_schema.properties.reply",
        "unsupported field: response_json_schema[properties][reply]",
        "unknown field: response_json_schema/properties/reply",
        "unsupported parameter: response_json_schema-extra",
    ],
)
def test_gemini_nested_unsupported_schema_keyword_does_not_downgrade(
    gemini_harness,
    message,
):
    client = gemini_harness.client([valid_envelope_json()])
    failure = _SyntheticGeminiError(400, message)

    assert client._is_explicit_structured_output_unsupported(failure) is False


def test_gemini_unknown_name_cannot_find_field_is_direct_unsupported(
    gemini_harness,
):
    client = gemini_harness.client([valid_envelope_json()])
    failure = _SyntheticGeminiError(
        400,
        'Unknown name "responseJsonSchema" at generation_config: Cannot find field',
    )

    assert client._is_explicit_structured_output_unsupported(failure) is True


@pytest.mark.parametrize(
    "message",
    [
        "response_json_schema is not supported for this model",
        "This model does not support responseJsonSchema",
    ],
)
def test_gemini_direct_model_parameter_unsupported_is_detected(
    gemini_harness,
    message,
):
    client = gemini_harness.client([valid_envelope_json()])
    failure = _SyntheticGeminiError(400, message)

    assert client._is_explicit_structured_output_unsupported(failure) is True
    probe = gemini_harness.client([valid_envelope_json(reply="Native synthetic reply")])
    assert "response_json_schema" in gemini_harness.created_configs[0]
    assert probe.send_message("Synthetic probe prompt")[0] == "Native synthetic reply"


def test_gemini_token_usage_accumulates_primary_regeneration_and_repair(
    gemini_harness,
):
    primary = gemini_harness.response("not-json", input_tokens=10, output_tokens=4)
    regeneration = gemini_harness.response(
        valid_envelope_json(reply="복구 전 합성 답변", thought=""),
        input_tokens=8,
        output_tokens=3,
    )
    repair = gemini_harness.response(
        '{"thought":"복구된 합성 생각"}',
        input_tokens=2,
        output_tokens=1,
    )
    client = gemini_harness.client(
        [primary, regeneration],
        repair_responses=[repair],
        settings={"enable_ene_thoughts": True},
    )

    assert client.send_message("누산 합성 입력")[0] == "복구 전 합성 답변"
    assert client.get_last_token_usage() == {
        "input_tokens": 20,
        "output_tokens": 8,
        "total_tokens": 28,
    }


def test_gemini_max_tokens_retry_accumulates_both_attempts(gemini_harness):
    incomplete = gemini_harness.response(
        valid_envelope_json(reply="잘린 합성 답변"),
        finish_reason="MAX_TOKENS",
    )
    client = gemini_harness.client(
        [incomplete, valid_envelope_json(reply="완성 합성 답변")]
    )

    client.send_message("길이 누산 합성 입력")

    assert client.get_last_token_usage() == {
        "input_tokens": 6,
        "output_tokens": 10,
        "total_tokens": 16,
    }


def test_gemini_multimodal_retry_accumulates_both_attempts(gemini_harness):
    client = gemini_harness.client(
        ["not-json", valid_envelope_json(reply="이미지 합성 답변")]
    )

    client._execute_final_response(
        [object(), "이미지 합성 입력"],
        history_user_content="이미지 합성 입력",
        label="멀티모달",
    )

    assert client.get_last_token_usage() == {
        "input_tokens": 6,
        "output_tokens": 10,
        "total_tokens": 16,
    }


def test_gemini_unsupported_fallback_keeps_unknown_aggregate(gemini_harness):
    unsupported = _SyntheticGeminiError(
        400,
        "Unknown parameter: response_json_schema is unsupported",
    )
    client = gemini_harness.client([unsupported, "하향 합성 답변 [normal]"])

    assert client.send_message("하향 usage 합성 입력")[0] == "하향 합성 답변"
    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


@pytest.mark.parametrize(
    ("code", "message"),
    [
        (429, "synthetic rate limit"),
        (500, "synthetic upstream failure"),
    ],
)
def test_gemini_call_exception_records_unknown_attempt_usage(
    gemini_harness,
    code,
    message,
):
    client = gemini_harness.client([_SyntheticGeminiError(code, message)])

    with pytest.raises(_SyntheticGeminiError):
        client.send_message("예외 usage 합성 입력")

    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_gemini_refusal_response_usage_is_recorded(gemini_harness):
    refusal = gemini_harness.response(
        valid_envelope_json(reply="거절 carrier"),
        finish_reason="SAFETY",
        input_tokens=7,
        output_tokens=2,
    )
    client = gemini_harness.client([refusal])

    with pytest.raises(ProviderRefusalError):
        client.send_message("거절 usage 합성 입력")

    assert client.get_last_token_usage() == {
        "input_tokens": 7,
        "output_tokens": 2,
        "total_tokens": 9,
    }


def test_gemini_repair_exception_preserves_reply_and_nulls_turn_usage(
    gemini_harness,
):
    client = gemini_harness.client(
        [valid_envelope_json(reply="보존할 합성 답변", thought="")],
        repair_responses=[TimeoutError("synthetic_repair_timeout")],
        settings={"enable_ene_thoughts": True},
    )

    result = client.send_message("복구 예외 합성 입력")

    assert result[0] == "보존할 합성 답변"
    assert result[6] == ""
    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_gemini_partial_usage_keeps_only_complete_aggregate_keys(gemini_harness):
    first = gemini_harness.response("not-json", input_tokens=10, output_tokens=4)
    first.usage_metadata.candidates_token_count = None
    second = gemini_harness.response(
        valid_envelope_json(reply="완성 합성 답변"),
        input_tokens=2,
        output_tokens=1,
    )
    client = gemini_harness.client([first, second])

    client.send_message("부분 usage 합성 입력")

    assert client.get_last_token_usage() == {
        "input_tokens": 12,
        "output_tokens": None,
        "total_tokens": 17,
    }


def test_gemini_next_final_turn_resets_previous_aggregate(gemini_harness):
    client = gemini_harness.client(
        [
            "not-json",
            valid_envelope_json(reply="첫 합성 답변"),
            valid_envelope_json(reply="둘째 합성 답변"),
        ]
    )

    assert client.send_message("첫 누산 합성 입력")[0] == "첫 합성 답변"
    assert client.get_last_token_usage()["total_tokens"] == 16
    assert client.send_message("둘째 누산 합성 입력")[0] == "둘째 합성 답변"
    assert client.get_last_token_usage() == {
        "input_tokens": 3,
        "output_tokens": 5,
        "total_tokens": 8,
    }


def test_gemini_one_shot_does_not_overwrite_latest_final_turn_usage(
    gemini_harness,
):
    one_shot = gemini_harness.response(
        "일회성 합성 결과",
        input_tokens=90,
        output_tokens=30,
    )
    client = gemini_harness.client(
        [valid_envelope_json(reply="최종 합성 답변")],
        repair_responses=[one_shot],
    )
    client.send_message("최종 합성 입력")
    final_usage = client.get_last_token_usage()

    assert (
        client._generate_one_shot_text(
            "일회성 합성 입력",
            request_kind=LLMRequestKind.DECISION,
            include_sub_prompt=False,
        )
        == "일회성 합성 결과"
    )
    assert client.get_last_token_usage() == final_usage


def test_gemini_main_timeout_records_unknown_attempt_usage(gemini_harness):
    client = gemini_harness.client([TimeoutError("synthetic_main_timeout")])

    with pytest.raises(TimeoutError):
        client.send_message("timeout usage 합성 입력")

    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_gemini_empty_response_usage_is_included_before_regeneration(
    gemini_harness,
):
    empty = gemini_harness.response(
        None,
        finish_reason="",
        input_tokens=11,
        output_tokens=0,
    )
    complete = gemini_harness.response(
        valid_envelope_json(reply="빈 응답 뒤 합성 답변"),
        input_tokens=3,
        output_tokens=2,
    )
    client = gemini_harness.client([empty, complete])

    assert (
        client.send_message("빈 응답 usage 합성 입력")[0]
        == "빈 응답 뒤 합성 답변"
    )
    assert client.get_last_token_usage() == {
        "input_tokens": 14,
        "output_tokens": 2,
        "total_tokens": 16,
    }


@pytest.mark.parametrize("failure_location", ["response", "field"])
def test_gemini_usage_property_failure_records_one_unknown_attempt(
    gemini_harness,
    failure_location,
):
    unknown_usage = {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }

    class FailingUsage:
        @property
        def prompt_token_count(self):
            raise RuntimeError("synthetic_usage_field_failure")

        candidates_token_count = 5
        total_token_count = 8

    class ResponseUsageFailure:
        text = valid_envelope_json(reply="usage 접근 실패 뒤 합성 답변")
        candidates = [
            SimpleNamespace(
                finish_reason="STOP",
                finish_message="",
                safety_ratings=[],
            )
        ]
        prompt_feedback = None

        @property
        def usage_metadata(self):
            if failure_location == "response":
                raise RuntimeError("synthetic_response_usage_failure")
            return FailingUsage()

    response = ResponseUsageFailure()
    client = gemini_harness.client([lambda: response])
    recorded_attempts = []
    original_record = client._record_response_turn_usage

    def record_usage(usage):
        recorded_attempts.append(usage)
        original_record(usage)

    client._record_response_turn_usage = record_usage

    assert (
        client.send_message("usage 접근 실패 합성 입력")[0]
        == "usage 접근 실패 뒤 합성 답변"
    )
    assert recorded_attempts == [unknown_usage]
    assert client.get_last_token_usage() == unknown_usage
