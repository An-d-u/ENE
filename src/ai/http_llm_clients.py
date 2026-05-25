"""
HTTP 기반 LLM 클라이언트 호환 import 레이어.

실제 구현은 공급자별 모듈에 둔다. 기존 호출부의
``src.ai.http_llm_clients`` import 경로는 계속 지원한다.
"""
from __future__ import annotations

import requests

from ..conversation_format import prepend_message_time
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
from .memory_context_builder import build_memory_context as build_common_memory_context
from .persona_names import resolve_prompt_persona_names
from .prompt import build_runtime_system_prompt, get_available_emotions
from .prompt_language import resolve_prompt_language
from .response_cleanup import extract_goal_update_metadata, extract_thought_metadata
from .response_parser import (
    extract_analysis_block,
    extract_legacy_japanese_tts_lines,
    extract_tts_text,
    is_japanese,
    parse_analysis_lines,
    parse_llm_response,
)
from .summary_parser import parse_summary_memory_meta, parse_summary_response
from .markdown_document_prompt import build_markdown_document_prompt
from .summary_prompt import build_summary_prompt, build_summary_prompt_from_text
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
    "build_common_memory_context",
    "build_markdown_document_prompt",
    "build_runtime_system_prompt",
    "build_summary_prompt",
    "build_summary_prompt_from_text",
    "CohereClient",
    "DEFAULT_GENERATION_PARAMS",
    "extract_analysis_block",
    "extract_goal_update_metadata",
    "extract_legacy_japanese_tts_lines",
    "extract_thought_metadata",
    "extract_tts_text",
    "get_available_emotions",
    "GoogleCloudClient",
    "is_japanese",
    "LLM_RESPONSE_TUPLE",
    "MistralClient",
    "OllamaClient",
    "OpenAICompatibleClient",
    "OpenAIResponseAPIClient",
    "parse_analysis_lines",
    "parse_llm_response",
    "parse_summary_memory_meta",
    "parse_summary_response",
    "prepend_message_time",
    "_CommonMixin",
    "_build_summary_prompt",
    "_extract_error_detail",
    "_normalize_generation_params",
    "_parse_summary_memory_meta_lines",
    "_raise_for_status_with_detail",
    "resolve_prompt_language",
    "resolve_prompt_persona_names",
    "requests",
]
