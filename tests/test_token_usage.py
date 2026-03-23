import sys
import types


fake_google = types.ModuleType("google")
fake_google.genai = types.SimpleNamespace(Client=object)
sys.modules.setdefault("google", fake_google)
sys.modules.setdefault("google.genai", fake_google.genai)

from src.ai.llm_client import GeminiClient


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
