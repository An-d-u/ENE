import pytest

pytest.importorskip("google.genai")

from src.ai.llm_client import GeminiClient
from src.ai.response_protocol import LLMRequestKind


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


def test_gemini_summary_request_retries_with_explicit_summary_kind_and_legacy_config():
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
    request_kinds = []
    build_summary_config = client._build_summary_config

    def capture_summary_config(*, request_kind):
        request_kinds.append(request_kind)
        return build_summary_config(request_kind=request_kind)

    client._build_summary_config = capture_summary_config

    response_text = GeminiClient._request_summary_text(client, "요약 프롬프트")

    assert "요약 대상 대화만 정리했다." in response_text
    assert request_kinds == [LLMRequestKind.SUMMARY, LLMRequestKind.SUMMARY]
    assert [config["max_output_tokens"] for config in client.client.models.configs] == [4096, 4096]
    assert all(
        "response_schema" not in config
        and "response_json_schema" not in config
        and "response_mime_type" not in config
        and "tools" not in config
        and "tool_config" not in config
        for config in client.client.models.configs
    )
    assert "중간에 끊겼거나" in client.client.models.contents[1]
