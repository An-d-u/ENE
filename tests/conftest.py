import pytest


_HTTP_LLM_TEST_MODULES = {
    "test_http_llm_clients_multimodal_history",
    "test_http_llm_clients_openai",
    "test_http_llm_clients_provider_parity",
    "test_http_llm_privacy_logging",
    "test_http_llm_structured_outputs",
    "test_life_record_http_native_providers",
    "test_life_record_http_format_parity",
    "test_response_capabilities",
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


@pytest.fixture(autouse=True)
def _reset_http_response_capability_cache(request):
    """HTTP 관련 테스트 사이에 process-local capability 판정이 새지 않게 한다."""
    module_name = getattr(request.module, "__name__", "").rsplit(".", 1)[-1]
    if module_name not in _HTTP_LLM_TEST_MODULES:
        yield
        return

    from src.ai.http_llm_common import clear_http_response_capability_cache

    clear_http_response_capability_cache()
    yield
    clear_http_response_capability_cache()


@pytest.fixture
def gemini_harness(monkeypatch):
    from tests.gemini_structured_fixtures import GeminiHarness

    return GeminiHarness(monkeypatch)


@pytest.fixture(autouse=True)
def _reset_gemini_response_capability_cache():
    """Gemini capability 판정이 테스트 사이에 새지 않게 한다."""
    from src.ai.llm_client import clear_gemini_response_capability_cache

    clear_gemini_response_capability_cache()
    yield
    clear_gemini_response_capability_cache()
