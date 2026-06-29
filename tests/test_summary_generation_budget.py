import pytest

pytest.importorskip("google.genai")

from src.ai.llm_client import GeminiClient


class _DummyGeminiResponse:
    def __init__(self, text: str):
        self.text = text


class _DummyGeminiModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.configs = []
        self.contents = []

    def generate_content(self, *, model, contents, config):
        self.configs.append(dict(config))
        self.contents.append(contents)
        return _DummyGeminiResponse(self.responses.pop(0))


class _DummyGeminiSdkClient:
    def __init__(self, responses):
        self.models = _DummyGeminiModels(responses)


def test_gemini_summary_request_retries_incomplete_response_with_larger_budget():
    client = GeminiClient.__new__(GeminiClient)
    client.client = _DummyGeminiSdkClient(
        [
            "[SUMMARY]\n- 첫 응답은 중간에 끊겼다.",
            """
[SUMMARY]
- 요약 대상 대화만 정리했다.

[MASTER_INFO]
- none

[ENE_INFO]
- none

[MEMORY_META]
- none
""".strip(),
        ]
    )
    client.model_name = "gemini-test"
    client.generation_params = {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048}

    response_text = GeminiClient._request_summary_text(client, "요약 프롬프트")

    assert "요약 대상 대화만 정리했다." in response_text
    assert [config["max_output_tokens"] for config in client.client.models.configs] == [4096, 4096]
    assert "중간에 끊겼거나" in client.client.models.contents[1]
