"""
HTTP 기반 LLM 클라이언트 호환 import 레이어.

실제 구현은 공급자별 모듈에 둔다. 기존 호출부의
``src.ai.http_llm_clients`` import 경로는 계속 지원한다.
"""
from __future__ import annotations

import requests

from .http_llm_common import (
    DEFAULT_GENERATION_PARAMS,
    LLM_RESPONSE_TUPLE,
    _CommonMixin,
    _build_summary_prompt,
    _extract_error_detail,
    _normalize_generation_params,
    _parse_summary_memory_meta_lines,
    _raise_for_status_with_detail,
)
from .http_llm_openai import (
    MistralClient,
    OpenAICompatibleClient,
    OpenAIResponseAPIClient,
)
from .http_llm_custom_providers import CohereClient, GoogleCloudClient
from .http_llm_anthropic import AnthropicClient
from .http_llm_ollama import OllamaClient

__all__ = [
    "AnthropicClient",
    "CohereClient",
    "DEFAULT_GENERATION_PARAMS",
    "GoogleCloudClient",
    "LLM_RESPONSE_TUPLE",
    "MistralClient",
    "OllamaClient",
    "OpenAICompatibleClient",
    "OpenAIResponseAPIClient",
    "_CommonMixin",
    "_build_summary_prompt",
    "_extract_error_detail",
    "_normalize_generation_params",
    "_parse_summary_memory_meta_lines",
    "_raise_for_status_with_detail",
    "requests",
]
