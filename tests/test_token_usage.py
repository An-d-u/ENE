import asyncio
import sys
import types

import pytest


fake_google = types.ModuleType("google")
fake_google.genai = types.SimpleNamespace(Client=object)
sys.modules.setdefault("google", fake_google)
sys.modules.setdefault("google.genai", fake_google.genai)

from src.ai import response_protocol  # noqa: E402
from src.ai.llm_client import GeminiClient  # noqa: E402


def test_turn_token_usage_accumulates_primary_retry_and_repair():
    accumulator = response_protocol.TurnTokenUsageAccumulator()

    accumulator.record({"input_tokens": 10, "output_tokens": 4, "total_tokens": 14})
    accumulator.record({"input_tokens": 8, "output_tokens": 3, "total_tokens": 11})
    accumulator.record({"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})

    assert accumulator.attempt_count == 3
    assert accumulator.snapshot() == {
        "input_tokens": 20,
        "output_tokens": 8,
        "total_tokens": 28,
    }


@pytest.mark.parametrize(
    ("incomplete_usage", "expected_input"),
    [
        ({"output_tokens": 4, "total_tokens": 14}, None),
        ({"input_tokens": None, "output_tokens": 4, "total_tokens": 14}, None),
        ({"input_tokens": "10", "output_tokens": 4, "total_tokens": 14}, None),
        ({"input_tokens": True, "output_tokens": 4, "total_tokens": 14}, None),
        ({"input_tokens": -1, "output_tokens": 4, "total_tokens": 14}, None),
        ({"input_tokens": 9_007_199_254_740_992, "output_tokens": 4, "total_tokens": 14}, None),
    ],
)
def test_turn_token_usage_keeps_each_sum_null_when_any_attempt_is_invalid(
    incomplete_usage,
    expected_input,
):
    accumulator = response_protocol.TurnTokenUsageAccumulator()

    accumulator.record(incomplete_usage)
    accumulator.record({"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})

    assert accumulator.snapshot() == {
        "input_tokens": expected_input,
        "output_tokens": 5,
        "total_tokens": 17,
    }


def test_turn_token_usage_does_not_infer_total_from_input_and_output():
    accumulator = response_protocol.TurnTokenUsageAccumulator()

    accumulator.record({"input_tokens": 10, "output_tokens": 4})

    assert accumulator.snapshot() == {
        "input_tokens": 10,
        "output_tokens": 4,
        "total_tokens": None,
    }


def test_turn_token_usage_zero_attempt_snapshot_is_copy():
    accumulator = response_protocol.TurnTokenUsageAccumulator()

    first = accumulator.snapshot()
    first["input_tokens"] = 999

    assert accumulator.attempt_count == 0
    assert accumulator.snapshot() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_next_final_reply_resets_previous_turn_usage():
    client = GeminiClient.__new__(GeminiClient)
    client._begin_response_turn_usage()
    client._record_response_turn_usage(
        {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
    )
    client._finish_response_turn_usage()

    client._begin_response_turn_usage()
    client._record_response_turn_usage(
        {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
    )
    client._finish_response_turn_usage()

    assert client.get_last_token_usage() == {
        "input_tokens": 2,
        "output_tokens": 1,
        "total_tokens": 3,
    }


def test_log_turn_token_usage_stores_latest_usage_snapshot():
    client = GeminiClient.__new__(GeminiClient)
    client._last_token_usage = None

    GeminiClient._log_turn_token_usage(
        client,
        {
            "usage_metadata": {
                "prompt_token_count": 321,
                "candidates_token_count": 123,
                "total_token_count": 444,
            }
        },
        label="텍스트",
    )

    assert client.get_last_token_usage() == {
        "input_tokens": 321,
        "output_tokens": 123,
        "total_tokens": 444,
    }


def test_log_turn_token_usage_keeps_na_fields_when_usage_is_missing():
    client = GeminiClient.__new__(GeminiClient)
    client._last_token_usage = None

    GeminiClient._log_turn_token_usage(client, {}, label="텍스트")

    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_log_turn_token_usage_rejects_boolean_counts():
    client = GeminiClient.__new__(GeminiClient)
    client._last_token_usage = None

    GeminiClient._log_turn_token_usage(
        client,
        {
            "usage_metadata": {
                "prompt_token_count": True,
                "candidates_token_count": False,
                "total_token_count": True,
            }
        },
        label="합성",
    )

    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,

    }

def test_multimodal_preprocessing_error_resets_final_turn_usage():
    client = GeminiClient.__new__(GeminiClient)
    client._last_token_usage = {
        "input_tokens": 30,
        "output_tokens": 20,
        "total_tokens": 50,
    }

    result = asyncio.run(
        client.send_message_with_images(
            "이미지 전처리 합성 입력",
            [object()],
        )
    )

    assert result[1] == "confused"
    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


def test_multimodal_preprocessing_error_resets_delivery_metadata():
    client = GeminiClient.__new__(GeminiClient)
    client._last_response_delivery_metadata = response_protocol.ResponseDeliveryMetadata(
        response_mode="json_schema",
        schema_version="synthetic-v1",
        promises_authoritative=True,
        repair_performed=True,
    )

    result = asyncio.run(
        client.send_message_with_images(
            "메타데이터 전처리 합성 입력",
            [object()],
        )
    )

    assert result[1] == "confused"
    assert (
        client.get_last_response_delivery_metadata()
        == response_protocol.ResponseDeliveryMetadata.empty()
    )


def test_multimodal_compatibility_path_records_usage_in_outer_transaction(
    monkeypatch,
):
    client = GeminiClient.__new__(GeminiClient)
    client.settings = {}

    async def empty_memory_context(*_args, **_kwargs):
        return ""

    client._build_memory_context = empty_memory_context
    client._refresh_chat_session_for_runtime_prompt_if_needed = (
        lambda *_args, **_kwargs: None
    )
    response = types.SimpleNamespace(
        text="합성 호환 응답 [normal]",
        usage_metadata=types.SimpleNamespace(
            prompt_token_count=3,
            candidates_token_count=2,
            total_token_count=5,
        ),
    )
    client.chat = types.SimpleNamespace(send_message=lambda _contents: response)
    client._parse_response = lambda _text: (
        "합성 호환 응답",
        "normal",
        None,
        [],
        {},
        [],
        "",
        {},
        [],
        "",
    )
    monkeypatch.setattr(
        "PIL.Image.open",
        lambda _stream: types.SimpleNamespace(size=(1, 1)),
    )

    result = asyncio.run(
        client.send_message_with_images(
            "멀티모달 호환 합성 입력",
            [{"dataUrl": "data:image/png;base64,c3ludGhldGlj"}],
        )
    )

    assert result[0] == "합성 호환 응답"
    assert client.get_last_token_usage() == {
        "input_tokens": 3,
        "output_tokens": 2,
        "total_tokens": 5,
    }


def test_nested_response_turn_usage_preserves_outer_accumulator():
    client = GeminiClient.__new__(GeminiClient)
    client._last_token_usage = {
        "input_tokens": 90,
        "output_tokens": 60,
        "total_tokens": 150,
    }

    client._begin_response_turn_usage()
    client._record_response_turn_usage(
        {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14}
    )
    client._begin_response_turn_usage()
    client._record_response_turn_usage(
        {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11}
    )
    client._finish_response_turn_usage()
    client._record_response_turn_usage(
        {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3}
    )
    client._finish_response_turn_usage()

    assert client.get_last_token_usage() == {
        "input_tokens": 20,
        "output_tokens": 8,
        "total_tokens": 28,
    }


def test_turn_token_usage_accepts_zero_and_js_safe_integer_boundary():
    accumulator = response_protocol.TurnTokenUsageAccumulator()

    accumulator.record(
        {
            "input_tokens": 9_007_199_254_740_991,
            "output_tokens": 0,
            "total_tokens": 9_007_199_254_740_991,
        }
    )

    assert accumulator.snapshot() == {
        "input_tokens": 9_007_199_254_740_991,
        "output_tokens": 0,
        "total_tokens": 9_007_199_254_740_991,
    }


def test_turn_token_usage_marks_sum_unknown_when_safe_integer_overflows():
    accumulator = response_protocol.TurnTokenUsageAccumulator()

    accumulator.record(
        {
            "input_tokens": 9_007_199_254_740_991,
            "output_tokens": 0,
            "total_tokens": 9_007_199_254_740_991,
        }
    )
    accumulator.record({"input_tokens": 1, "output_tokens": 0, "total_tokens": 1})

    assert accumulator.snapshot() == {
        "input_tokens": None,
        "output_tokens": 0,
        "total_tokens": None,
    }


@pytest.mark.parametrize("invalid_count", [-1, 9_007_199_254_740_992])
def test_log_turn_token_usage_rejects_out_of_safe_range_counts(invalid_count):
    client = GeminiClient.__new__(GeminiClient)

    GeminiClient._log_turn_token_usage(
        client,
        {
            "usage_metadata": {
                "prompt_token_count": invalid_count,
                "candidates_token_count": invalid_count,
                "total_token_count": invalid_count,
            }
        },
        label="합성",
    )

    assert client.get_last_token_usage() == {
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }
