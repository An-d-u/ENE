import pytest


_HTTP_LLM_TEST_MODULES = {
    "test_http_llm_clients_multimodal_history",
    "test_http_llm_clients_openai",
    "test_http_llm_clients_provider_parity",
}


@pytest.fixture(autouse=True)
def _skip_store_python_prompt_sync_for_http_llm_tests(monkeypatch, request):
    """HTTP LLM 테스트는 Store Python 프롬프트 동기화 비용을 검증 범위에서 제외한다."""
    module_name = getattr(request.module, "__name__", "").rsplit(".", 1)[-1]
    if module_name not in _HTTP_LLM_TEST_MODULES:
        return

    monkeypatch.setattr(
        "src.ai.prompt_config._should_sync_store_python_prompt_dirs",
        lambda: False,
    )
