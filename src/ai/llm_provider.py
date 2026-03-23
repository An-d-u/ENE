"""
LLM 공급자 추상화 레이어.
현재는 Gemini를 기본 제공하며, 동일 인터페이스로 공급자를 확장할 수 있다.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Protocol, Tuple, runtime_checkable


@runtime_checkable
class LLMClientProtocol(Protocol):
    async def send_message_with_memory(
        self,
        message: str,
        memory_search_text: str | None = None,
    ) -> Tuple[str, str, str | None, List[Dict], Dict[str, str]]:
        ...

    async def send_message_with_images(
        self,
        message: str,
        images_data: list,
        memory_search_text: str | None = None,
    ) -> Tuple[str, str, str | None, List[Dict], Dict[str, str]]:
        ...

    def send_message(self, message: str) -> Tuple[str, str, str | None, List[Dict], Dict[str, str]]:
        ...

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str]]:
        ...

    async def generate_markdown_document(self, message: str) -> str:
        ...

    async def generate_diary_completion_reply(self, context_message: str) -> Tuple[str, str, str | None, List[Dict], Dict[str, str]]:
        ...

    async def generate_note_command_plan(self, context_message: str) -> str:
        ...

    async def generate_note_execution_report(self, context_message: str) -> Tuple[str, str, str | None, List[Dict], Dict[str, str]]:
        ...

    def clear_context(self):
        ...

    def rollback_last_assistant_turn(self) -> bool:
        ...

    def rebuild_context_from_conversation(self, conversation_buffer: list) -> bool:
        ...

    def get_conversation_history(self):
        ...


@dataclass
class LLMProviderConfig:
    provider: str = "gemini"
    api_key: str = ""
    model_name: str = ""
    generation_params: dict | None = None


class LLMFormat(str, Enum):
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"
    OPENAI_RESPONSE_API = "openai_response_api"
    ANTHROPIC = "anthropic"
    MISTRAL = "mistral"
    GOOGLE_CLOUD = "google_cloud"
    COHERE = "cohere"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class LLMCapability(str, Enum):
    IMAGE_INPUT = "image_input"
    AUDIO_INPUT = "audio_input"
    VIDEO_INPUT = "video_input"
    STREAMING = "streaming"
    THINKING = "thinking"


@dataclass(frozen=True)
class LLMProviderMeta:
    provider: str
    display_name: str
    format: LLMFormat
    default_model: str
    key_identifier: str
    recommended: bool = True
    capabilities: list[LLMCapability] = field(default_factory=list)


ProviderBuilder = Callable[..., LLMClientProtocol]


def _build_gemini_client(
    *,
    api_key: str,
    model_name: str,
    generation_params=None,
    memory_manager=None,
    user_profile=None,
    settings=None,
    calendar_manager=None,
    mood_manager=None,
) -> LLMClientProtocol:
    # 순환 의존성과 불필요한 import 비용을 피하기 위해 지연 import를 사용한다.
    from .llm_client import GeminiClient

    resolved_model = model_name or "gemini-3-flash-preview"
    return GeminiClient(
        api_key=api_key,
        model_name=resolved_model,
        generation_params=generation_params,
        memory_manager=memory_manager,
        user_profile=user_profile,
        settings=settings,
        calendar_manager=calendar_manager,
        mood_manager=mood_manager,
    )


def _build_openai_client(
    *,
    api_key: str,
    model_name: str,
    generation_params=None,
    memory_manager=None,
    user_profile=None,
    settings=None,
    calendar_manager=None,
    mood_manager=None,
) -> LLMClientProtocol:
    from .http_llm_clients import OpenAIResponseAPIClient

    return OpenAIResponseAPIClient(
        api_key=api_key,
        model_name=model_name or "gpt-4o-mini",
        endpoint="https://api.openai.com/v1/responses",
        generation_params=generation_params,
        memory_manager=memory_manager,
        user_profile=user_profile,
        settings=settings,
        calendar_manager=calendar_manager,
        mood_manager=mood_manager,
    )


def _build_openrouter_client(
    *,
    api_key: str,
    model_name: str,
    generation_params=None,
    memory_manager=None,
    user_profile=None,
    settings=None,
    calendar_manager=None,
    mood_manager=None,
) -> LLMClientProtocol:
    from .http_llm_clients import OpenAICompatibleClient

    return OpenAICompatibleClient(
        api_key=api_key,
        model_name=model_name or "openai/gpt-4o-mini",
        endpoint="https://openrouter.ai/api/v1/chat/completions",
        provider_name="openrouter",
        generation_params=generation_params,
        memory_manager=memory_manager,
        user_profile=user_profile,
        settings=settings,
        calendar_manager=calendar_manager,
        mood_manager=mood_manager,
    )


def _build_deepseek_client(
    *,
    api_key: str,
    model_name: str,
    generation_params=None,
    memory_manager=None,
    user_profile=None,
    settings=None,
    calendar_manager=None,
    mood_manager=None,
) -> LLMClientProtocol:
    from .http_llm_clients import OpenAICompatibleClient

    return OpenAICompatibleClient(
        api_key=api_key,
        model_name=model_name or "deepseek-chat",
        endpoint="https://api.deepseek.com/chat/completions",
        provider_name="deepseek",
        generation_params=generation_params,
        memory_manager=memory_manager,
        user_profile=user_profile,
        settings=settings,
        calendar_manager=calendar_manager,
        mood_manager=mood_manager,
    )


def _build_anthropic_client(
    *,
    api_key: str,
    model_name: str,
    generation_params=None,
    memory_manager=None,
    user_profile=None,
    settings=None,
    calendar_manager=None,
    mood_manager=None,
) -> LLMClientProtocol:
    from .http_llm_clients import AnthropicClient

    return AnthropicClient(
        api_key=api_key,
        model_name=model_name or "claude-3-5-sonnet-latest",
        endpoint="https://api.anthropic.com/v1/messages",
        generation_params=generation_params,
        memory_manager=memory_manager,
        user_profile=user_profile,
        settings=settings,
        calendar_manager=calendar_manager,
        mood_manager=mood_manager,
    )


def _build_ollama_client(
    *,
    api_key: str,
    model_name: str,
    generation_params=None,
    memory_manager=None,
    user_profile=None,
    settings=None,
    calendar_manager=None,
    mood_manager=None,
) -> LLMClientProtocol:
    from .http_llm_clients import OllamaClient

    endpoint = "http://127.0.0.1:11434/api/chat"
    if settings:
        endpoint = str(settings.get("custom_api_url", endpoint) or endpoint)
    return OllamaClient(
        api_key=api_key,
        model_name=model_name or "llama3.1",
        endpoint=endpoint,
        generation_params=generation_params,
        memory_manager=memory_manager,
        user_profile=user_profile,
        settings=settings,
        calendar_manager=calendar_manager,
        mood_manager=mood_manager,
    )


def _build_custom_api_client(
    *,
    api_key: str,
    model_name: str,
    generation_params=None,
    memory_manager=None,
    user_profile=None,
    settings=None,
    calendar_manager=None,
    mood_manager=None,
) -> LLMClientProtocol:
    from .http_llm_clients import (
        AnthropicClient,
        CohereClient,
        GoogleCloudClient,
        MistralClient,
        OllamaClient,
        OpenAICompatibleClient,
        OpenAIResponseAPIClient,
    )

    format_value = str(settings.get("custom_api_format", LLMFormat.OPENAI_COMPATIBLE.value)) if settings else LLMFormat.OPENAI_COMPATIBLE.value
    endpoint = str(settings.get("custom_api_url", "") if settings else "").strip()
    if not endpoint:
        if format_value == LLMFormat.OPENAI_RESPONSE_API.value:
            endpoint = "http://127.0.0.1:8000/v1/responses"
        elif format_value == LLMFormat.ANTHROPIC.value:
            endpoint = "http://127.0.0.1:8000/v1/messages"
        elif format_value == LLMFormat.MISTRAL.value:
            endpoint = "http://127.0.0.1:8000/v1/chat/completions"
        elif format_value == LLMFormat.GOOGLE_CLOUD.value:
            endpoint = "http://127.0.0.1:8000/v1beta/models/{model}:generateContent"
        elif format_value == LLMFormat.COHERE.value:
            endpoint = "http://127.0.0.1:8000/v1/chat"
        else:
            endpoint = "http://127.0.0.1:8000/v1/chat/completions"

    request_model = str(settings.get("custom_api_request_model", "") if settings else "").strip() or model_name or "custom-model"

    if format_value == LLMFormat.ANTHROPIC.value:
        return AnthropicClient(
            api_key=api_key,
            model_name=request_model,
            endpoint=endpoint,
            generation_params=generation_params,
            memory_manager=memory_manager,
            user_profile=user_profile,
            settings=settings,
            calendar_manager=calendar_manager,
            mood_manager=mood_manager,
        )
    if format_value == LLMFormat.OPENAI_RESPONSE_API.value:
        return OpenAIResponseAPIClient(
            api_key=api_key,
            model_name=request_model,
            endpoint=endpoint,
            generation_params=generation_params,
            memory_manager=memory_manager,
            user_profile=user_profile,
            settings=settings,
            calendar_manager=calendar_manager,
            mood_manager=mood_manager,
        )
    if format_value == LLMFormat.MISTRAL.value:
        return MistralClient(
            api_key=api_key,
            model_name=request_model,
            endpoint=endpoint,
            generation_params=generation_params,
            memory_manager=memory_manager,
            user_profile=user_profile,
            settings=settings,
            calendar_manager=calendar_manager,
            mood_manager=mood_manager,
        )
    if format_value == LLMFormat.GOOGLE_CLOUD.value:
        return GoogleCloudClient(
            api_key=api_key,
            model_name=request_model,
            endpoint=endpoint,
            generation_params=generation_params,
            memory_manager=memory_manager,
            user_profile=user_profile,
            settings=settings,
            calendar_manager=calendar_manager,
            mood_manager=mood_manager,
        )
    if format_value == LLMFormat.COHERE.value:
        return CohereClient(
            api_key=api_key,
            model_name=request_model,
            endpoint=endpoint,
            generation_params=generation_params,
            memory_manager=memory_manager,
            user_profile=user_profile,
            settings=settings,
            calendar_manager=calendar_manager,
            mood_manager=mood_manager,
        )
    if format_value == LLMFormat.OLLAMA.value:
        return OllamaClient(
            api_key=api_key,
            model_name=request_model,
            endpoint=endpoint,
            generation_params=generation_params,
            memory_manager=memory_manager,
            user_profile=user_profile,
            settings=settings,
            calendar_manager=calendar_manager,
            mood_manager=mood_manager,
        )
    return OpenAICompatibleClient(
        api_key=api_key,
        model_name=request_model,
        endpoint=endpoint,
        provider_name="custom_api",
        generation_params=generation_params,
        memory_manager=memory_manager,
        user_profile=user_profile,
        settings=settings,
        calendar_manager=calendar_manager,
        mood_manager=mood_manager,
    )


PROVIDER_BUILDERS: Dict[str, ProviderBuilder] = {
    "gemini": _build_gemini_client,
    "openai": _build_openai_client,
    "openrouter": _build_openrouter_client,
    "deepseek": _build_deepseek_client,
    "anthropic": _build_anthropic_client,
    "ollama": _build_ollama_client,
    "custom_api": _build_custom_api_client,
}


# RisuAI의 모델/공급자 메타 관리 방식을 참고해,
# 실행 로직과 별개로 공급자 카탈로그를 유지한다.
PROVIDER_CATALOG: Dict[str, LLMProviderMeta] = {
    "gemini": LLMProviderMeta(
        provider="gemini",
        display_name="Google Gemini",
        format=LLMFormat.GEMINI,
        default_model="gemini-3-flash-preview",
        key_identifier="gemini",
        capabilities=[
            LLMCapability.IMAGE_INPUT,
            LLMCapability.AUDIO_INPUT,
            LLMCapability.VIDEO_INPUT,
            LLMCapability.STREAMING,
            LLMCapability.THINKING,
        ],
    ),
    "openai": LLMProviderMeta(
        provider="openai",
        display_name="OpenAI",
        format=LLMFormat.OPENAI_RESPONSE_API,
        default_model="gpt-4o-mini",
        key_identifier="openai",
        capabilities=[LLMCapability.IMAGE_INPUT, LLMCapability.STREAMING],
    ),
    "anthropic": LLMProviderMeta(
        provider="anthropic",
        display_name="Anthropic Claude",
        format=LLMFormat.ANTHROPIC,
        default_model="claude-3-5-sonnet-latest",
        key_identifier="anthropic",
        capabilities=[LLMCapability.IMAGE_INPUT, LLMCapability.STREAMING, LLMCapability.THINKING],
    ),
    "openrouter": LLMProviderMeta(
        provider="openrouter",
        display_name="OpenRouter",
        format=LLMFormat.OPENAI_COMPATIBLE,
        default_model="openai/gpt-4o-mini",
        key_identifier="openrouter",
        capabilities=[LLMCapability.IMAGE_INPUT, LLMCapability.STREAMING],
    ),
    "deepseek": LLMProviderMeta(
        provider="deepseek",
        display_name="DeepSeek",
        format=LLMFormat.OPENAI_COMPATIBLE,
        default_model="deepseek-chat",
        key_identifier="deepseek",
        capabilities=[LLMCapability.STREAMING, LLMCapability.THINKING],
    ),
    "ollama": LLMProviderMeta(
        provider="ollama",
        display_name="Ollama",
        format=LLMFormat.OLLAMA,
        default_model="llama3.1",
        key_identifier="ollama",
        capabilities=[LLMCapability.STREAMING],
    ),
    "custom_api": LLMProviderMeta(
        provider="custom_api",
        display_name="Custom API",
        format=LLMFormat.CUSTOM,
        default_model="",
        key_identifier="custom_api",
        capabilities=[LLMCapability.STREAMING],
        recommended=False,
    ),
}


def register_llm_provider(name: str, builder: ProviderBuilder):
    """외부 모듈에서 새 공급자를 등록할 때 사용."""
    normalized = (name or "").strip().lower()
    if not normalized:
        raise ValueError("Provider name cannot be empty")
    PROVIDER_BUILDERS[normalized] = builder


def get_supported_llm_providers() -> list[str]:
    return sorted(PROVIDER_BUILDERS.keys())


def get_llm_provider_catalog() -> dict[str, LLMProviderMeta]:
    return dict(PROVIDER_CATALOG)


def get_llm_provider_meta(provider: str) -> LLMProviderMeta | None:
    normalized = (provider or "").strip().lower()
    return PROVIDER_CATALOG.get(normalized)


def create_llm_client(
    config: LLMProviderConfig,
    *,
    memory_manager=None,
    user_profile=None,
    settings=None,
    calendar_manager=None,
    mood_manager=None,
) -> LLMClientProtocol:
    provider = (config.provider or "").strip().lower() or "gemini"
    builder = PROVIDER_BUILDERS.get(provider)
    if builder is None:
        supported = ", ".join(get_supported_llm_providers())
        raise ValueError(f"지원하지 않는 LLM 공급자입니다: {provider} (지원: {supported})")

    return builder(
        api_key=config.api_key,
        model_name=config.model_name,
        generation_params=config.generation_params or {},
        memory_manager=memory_manager,
        user_profile=user_profile,
        settings=settings,
        calendar_manager=calendar_manager,
        mood_manager=mood_manager,
    )
