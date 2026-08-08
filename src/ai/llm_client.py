"""
Gemini LLM 클라이언트 (google-genai SDK 사용)
"""

import copy
from datetime import datetime
import hashlib
import re
from typing import Tuple, List, Dict
from google import genai

from ..conversation_format import prepend_message_time
from .memory_context_builder import (
    _format_context_full_date as _format_context_full_date,
    _format_context_month_day as _format_context_month_day,
    _format_context_month_day_time as _format_context_month_day_time,
    build_goal_context_block,
    build_memory_context as build_common_memory_context,
    build_overdue_promise_context,
    build_recent_incomplete_past_event_context,
    memory_context_labels,
    normalize_int_setting,
)
from .persona_names import resolve_prompt_persona_names
from .prompt import (
    build_life_record_system_instruction,
    build_runtime_system_prompt,
    get_parseable_emotions,
)
from .prompt_config import get_runtime_emotions
from .prompt_language import resolve_prompt_language
from .response_contract import build_response_repair_prompt
from .response_envelope import (
    build_response_requirements,
    get_response_envelope_v1_schema,
    get_response_repair_schema,
)
from .response_pipeline import ResponseAttempt, execute_final_response
from .response_protocol import (
    InvalidFinalResponseError,
    LIFE_RECORD_SCHEMA_ID,
    LIFE_RECORD_SCHEMA_VERSION,
    LLMRequestKind,
    OneShotGenerationResult,
    OneShotTokenUsage,
    ProviderProfile,
    ProviderResponse,
    RESPONSE_ENVELOPE_SCHEMA_VERSION,
    ResponseDeliveryMetadata,
    ResponseMode,
    ResponseStatus,
    StructuredOutputUnsupported,
    TurnTokenUsageAccumulator,
    get_life_record_output_schema,
    is_valid_token_count,
)
from .http_llm_common import (
    ResponseCapabilityRegistry,
    build_capability_key,
)
from .response_cleanup import extract_goal_update_metadata, extract_thought_metadata
from .runtime_prompt_settings import build_runtime_prompt_settings_source
from .response_parser import (
    extract_analysis_block,
    extract_legacy_japanese_tts_lines,
    extract_tts_text,
    is_japanese,
    parse_analysis_lines,
    parse_llm_response,
)
from .summary_parser import (
    is_complete_summary_response,
    missing_summary_response_sections,
    parse_summary_memory_meta,
    parse_summary_response,
    parse_summary_response_with_topic_memory,
)
from .markdown_document_prompt import build_markdown_document_prompt
from .summary_prompt import build_summary_prompt
from .tool_calling import (
    build_web_search_context_from_settings,
    compose_contextual_message,
    create_web_search_decision_provider,
)

LLM_RESPONSE_TUPLE = Tuple[
    str,
    str,
    str | None,
    List[Dict],
    Dict[str, str],
    List[Dict],
    str,
    Dict[str, str],
    List[Dict],
    str,
]
SUMMARY_MIN_OUTPUT_TOKENS = 4096
GEMINI_MAX_OUTPUT_TOKENS = 8192
_GEMINI_RESPONSE_CAPABILITY_REGISTRY = ResponseCapabilityRegistry()

_SAFE_GEMINI_ENUM_CATEGORIES = {
    "block_reason_unspecified",
    "blocked_reason_unspecified",
    "blocklist",
    "content_filter",
    "finish_reason_unspecified",
    "image_prohibited_content",
    "image_recitation",
    "image_safety",
    "max_tokens",
    "prohibited_content",
    "recitation",
    "safety",
    "spii",
    "stop",
}
_SAFE_GEMINI_LOG_LABELS = {
    "one-shot": "one_shot",
    "멀티모달": "multimodal",
    "요약": "summary",
    "요약 재시도": "summary_retry",
    "제한 복구": "repair",
    "최종 응답": "final_response",
    "텍스트": "text",
}


def _safe_builtin_count(value) -> int | None:
    """사용자 정의 길이 hook을 호출하지 않고 내장 컨테이너 수만 센다."""
    if type(value) in {dict, list, set, str, tuple}:
        return len(value)
    return None


def clear_gemini_response_capability_cache() -> None:
    """테스트와 런타임 재설정을 위해 Gemini capability 캐시를 비운다."""
    _GEMINI_RESPONSE_CAPABILITY_REGISTRY.clear()


class GeminiClient:
    """Gemini API 클라이언트"""

    def __init__(
        self,
        api_key: str,
        model_name: str = "gemini-3-flash-preview",
        generation_params: dict | None = None,
        memory_manager=None,
        user_profile=None,
        ene_profile=None,
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        goal_manager=None,
    ):
        """
        Gemini API 클라이언트 초기화
        
        Args:
            api_key: Gemini API 키
            memory_manager: 메모리 매니저 인스턴스 (옵션)
            user_profile: 사용자 프로필 인스턴스 (옵션)
            settings: 설정 매니저 인스턴스 (옵션)
            calendar_manager: 캘린더 매니저 인스턴스 (옵션)
        """
        # genai 클라이언트 초기화
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.generation_params = self._normalize_generation_params(generation_params)
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.ene_profile = ene_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.goal_manager = goal_manager
        self.proactive_manager = None
        self._last_token_usage = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
        self._response_turn_usage_stack = []
        
        # Chat 세션 생성
        self.chat = self._create_chat_session()
        self._last_runtime_prompt_signature = self._runtime_prompt_signature()
        
        print("[LLM] category=session_created provider=gemini model_family=gemini")
        if self.memory_manager:
            print("[LLM] Memory manager connected")

    def _runtime_prompt_settings_source(self):
        """현재 선제 대화 쿨다운 상태를 반영한 프롬프트 설정을 반환한다."""
        return build_runtime_prompt_settings_source(
            self.settings,
            proactive_manager=getattr(self, "proactive_manager", None),
        )

    def _settings_snapshot(self) -> dict:
        """현재 설정을 요청 단위의 독립 복사본으로 고정한다."""
        source = self._runtime_prompt_settings_source()
        if isinstance(source, dict):
            return copy.deepcopy(source)
        config = getattr(source, "config", None)
        if isinstance(config, dict):
            return copy.deepcopy(config)
        return {}

    def _response_profile(self) -> ProviderProfile:
        return ProviderProfile(
            provider="gemini",
            wire_format="gemini",
            endpoint="",
            model=str(getattr(self, "model_name", "") or ""),
        )

    def _resolve_response_mode(
        self, settings_snapshot: dict | None = None
    ) -> ResponseMode:
        settings = (
            settings_snapshot
            if settings_snapshot is not None
            else self._settings_snapshot()
        )
        configured = str(settings.get("structured_response_mode", "auto") or "auto")
        profile = self._response_profile()
        key = build_capability_key(profile)
        return _GEMINI_RESPONSE_CAPABILITY_REGISTRY.resolve(
            profile,
            configured,
            capability_key=key,
        )

    def _runtime_prompt_signature(
        self,
        *,
        response_mode: ResponseMode | None = None,
        settings_source: dict | None = None,
    ) -> tuple:
        source = settings_source if settings_source is not None else self._settings_snapshot()
        proactive_enabled = True
        keys = []
        avatar_mode = "live2d"
        image_avatar_folder = ""
        if isinstance(source, dict):
            proactive_enabled = bool(source.get("enable_proactive_conversation", True))
            keys = list(source.get("proactive_available_cooldown_keys") or [])
            avatar_mode = (
                str(source.get("avatar_mode", "live2d") or "live2d").strip().lower()
            )
            image_avatar_folder = str(
                source.get("image_avatar_folder", "") or ""
            ).strip()
        else:
            getter = getattr(source, "get", None)
            if callable(getter):
                try:
                    proactive_enabled = bool(
                        getter("enable_proactive_conversation", True)
                    )
                except Exception:
                    proactive_enabled = True
                try:
                    avatar_mode = (
                        str(getter("avatar_mode", "live2d") or "live2d").strip().lower()
                    )
                except Exception:
                    avatar_mode = "live2d"
                try:
                    image_avatar_folder = str(
                        getter("image_avatar_folder", "") or ""
                    ).strip()
                except Exception:
                    image_avatar_folder = ""
            config = getattr(source, "config", None)
            if isinstance(config, dict):
                proactive_enabled = bool(
                    config.get("enable_proactive_conversation", proactive_enabled)
                )
                avatar_mode = (
                    str(config.get("avatar_mode", avatar_mode) or avatar_mode)
                    .strip()
                    .lower()
                )
                image_avatar_folder = str(
                    config.get("image_avatar_folder", image_avatar_folder) or ""
                ).strip()
        try:
            runtime_emotions = tuple(get_runtime_emotions(settings_source=source))
        except Exception:
            runtime_emotions = ()
        mode = response_mode or self._resolve_response_mode(source)
        final_prompt = build_runtime_system_prompt(
            include_sub_prompt=True,
            include_analysis_appendix=True,
            settings_source=source,
            request_kind=LLMRequestKind.FINAL_REPLY,
            response_mode=mode,
        )
        prompt_fingerprint = hashlib.sha256(final_prompt.encode("utf-8")).hexdigest()
        return (
            proactive_enabled,
            tuple(str(key) for key in keys),
            avatar_mode,
            image_avatar_folder,
            runtime_emotions,
            mode.value,
            RESPONSE_ENVELOPE_SCHEMA_VERSION,
            prompt_fingerprint,
        )

    def _refresh_chat_session_for_runtime_prompt_if_needed(
        self,
        *,
        settings_source: dict | None = None,
        response_mode: ResponseMode | None = None,
    ) -> None:
        frozen_settings = (
            settings_source if settings_source is not None else self._settings_snapshot()
        )
        mode = response_mode or self._resolve_response_mode(frozen_settings)
        signature = self._runtime_prompt_signature(
            response_mode=mode,
            settings_source=frozen_settings,
        )
        previous = getattr(self, "_last_runtime_prompt_signature", None)
        if previous == signature:
            return
        if not hasattr(self, "model_name") or not hasattr(self, "client"):
            self._last_runtime_prompt_signature = signature
            return
        history = self.get_conversation_history()
        self.chat = self._create_chat_session(
            history=history,
            response_mode=mode,
            settings_source=frozen_settings,
        )
        self._last_runtime_prompt_signature = signature


    def _create_chat_session(
        self,
        history=None,
        *,
        response_mode: ResponseMode | None = None,
        generation_params: dict | None = None,
        settings_source: dict | None = None,
    ):
        """Gemini chat 세션을 생성한다."""
        resolver = getattr(self, "_resolve_response_mode", None)
        mode = response_mode or (
            resolver(settings_source) if callable(resolver) else ResponseMode.LEGACY_TAGS
        )
        config_kwargs = {
            "include_sub_prompt": True,
            "request_kind": LLMRequestKind.FINAL_REPLY,
        }
        if callable(resolver):
            config_kwargs["response_mode"] = mode
        if generation_params is not None:
            config_kwargs["generation_params"] = generation_params
        if settings_source is not None:
            config_kwargs["settings_source"] = settings_source
        kwargs = {
            "model": self.model_name,
            "config": self._build_chat_config(**config_kwargs),
        }
        if history is not None:
            kwargs["history"] = history
        return self.client.chats.create(**kwargs)

    def _normalize_generation_params(self, params: dict | None) -> dict:
        defaults = {
            "temperature": 0.9,
            "top_p": 1.0,
            "max_tokens": 2048,
        }
        if not isinstance(params, dict):
            return defaults

        normalized = dict(defaults)
        try:
            normalized["temperature"] = max(0.0, min(2.0, float(params.get("temperature", defaults["temperature"]))))
        except (TypeError, ValueError):
            pass
        try:
            normalized["top_p"] = max(0.0, min(1.0, float(params.get("top_p", defaults["top_p"]))))
        except (TypeError, ValueError):
            pass
        try:
            normalized["max_tokens"] = max(0, int(params.get("max_tokens", defaults["max_tokens"])))
        except (TypeError, ValueError):
            pass
        return normalized

    def _build_chat_config(
        self,
        include_sub_prompt: bool = True,
        *,
        request_kind: LLMRequestKind,
        response_mode: ResponseMode = ResponseMode.LEGACY_TAGS,
        response_schema: dict | None = None,
        generation_params: dict | None = None,
        settings_source: dict | None = None,
    ) -> dict:
        params = dict(generation_params or self.generation_params)
        system_instruction = build_runtime_system_prompt(
            include_sub_prompt=include_sub_prompt,
            include_analysis_appendix=True,
            settings_source=(
                settings_source
                if settings_source is not None
                else self._runtime_prompt_settings_source()
            ),
            request_kind=request_kind,
            response_mode=response_mode,
        )
        config = {
            "system_instruction": system_instruction,
            "temperature": params["temperature"],
            "top_p": params["top_p"],
        }
        if params["max_tokens"] > 0:
            config["max_output_tokens"] = params["max_tokens"]
        if (
            request_kind is LLMRequestKind.FINAL_REPLY
            and response_mode is ResponseMode.JSON_SCHEMA
        ):
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = copy.deepcopy(
                response_schema or get_response_envelope_v1_schema()
            )
        return config

    def _build_life_record_config(
        self,
        *,
        system_instruction: str,
        use_native_schema: bool,
        generation_params: dict,
    ) -> dict:
        """생활 기록 one-shot의 native 또는 엄격 JSON 텍스트 config를 만든다."""
        config = {
            "system_instruction": system_instruction,
            "temperature": generation_params["temperature"],
            "top_p": generation_params["top_p"],
        }
        if generation_params["max_tokens"] > 0:
            config["max_output_tokens"] = generation_params["max_tokens"]
        if use_native_schema:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = get_life_record_output_schema()
        return config

    def _summary_output_token_budget(self) -> int:
        """요약은 메타 섹션까지 생성해야 하므로 일반 답변보다 큰 최소 출력 예산을 쓴다."""
        current = 0
        try:
            current = int((self.generation_params or {}).get("max_tokens") or 0)
        except (TypeError, ValueError):
            current = 0
        return max(SUMMARY_MIN_OUTPUT_TOKENS, current)

    def _build_summary_config(self, *, request_kind: LLMRequestKind) -> dict:
        if request_kind is not LLMRequestKind.SUMMARY:
            raise ValueError("요약 config에는 SUMMARY request kind가 필요합니다.")

        return {
            "temperature": 0.5,
            "top_p": self.generation_params["top_p"],
            "max_output_tokens": self._summary_output_token_budget(),
        }

    def _summary_retry_prompt(self, prompt: str, missing_sections: list[str]) -> str:
        missing = ", ".join(missing_sections) if missing_sections else "필수 섹션"
        return (
            f"{prompt}\n\n"
            "이전 요약 응답이 중간에 끊겼거나 형식이 불완전했습니다. "
            f"빠진 부분: {missing}. "
            "[SUMMARY], [MASTER_INFO], [ENE_INFO], [MEMORY_META] 네 섹션을 모두 포함해서 처음부터 다시 작성하세요."
        )

    def _request_summary_text(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=self._build_summary_config(request_kind=LLMRequestKind.SUMMARY),
        )
        response_text = self._extract_response_text_or_empty(response, label="요약")
        if not response_text or is_complete_summary_response(response_text):
            return response_text

        missing_sections = missing_summary_response_sections(response_text)
        missing_count = _safe_builtin_count(missing_sections)
        print(
            f"[LLM] category=summary_retry missing_count={missing_count or 0}"
        )
        retry_response = self.client.models.generate_content(
            model=self.model_name,
            contents=self._summary_retry_prompt(prompt, missing_sections),
            config=self._build_summary_config(request_kind=LLMRequestKind.SUMMARY),
        )
        return self._extract_response_text_or_empty(retry_response, label="요약 재시도")

    def _generate_one_shot_text(
        self,
        message: str,
        *,
        request_kind: LLMRequestKind,
        include_sub_prompt: bool,
    ) -> str:
        """히스토리를 남기지 않는 일회성 생성 호출."""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=message,
            config=self._build_chat_config(
                include_sub_prompt=include_sub_prompt,
                request_kind=request_kind,
            ),
        )
        return self._extract_response_text_or_empty(response, label="one-shot")

    async def generate_life_record_once(
        self,
        prompt: str,
    ) -> OneShotGenerationResult:
        """현재 설정으로 생활 기록을 히스토리 없이 한 번 생성한다."""
        setup_failed = False
        try:
            settings_source = self._runtime_prompt_settings_source()
            system_instruction = build_life_record_system_instruction(settings_source)
            generation_params = dict(self.generation_params)
            profile = self._response_profile()
            capability_key = build_capability_key(
                profile,
                request_kind=LLMRequestKind.LIFE_RECORD,
                schema_id=LIFE_RECORD_SCHEMA_ID,
                schema_version=LIFE_RECORD_SCHEMA_VERSION,
            )
            response_mode = _GEMINI_RESPONSE_CAPABILITY_REGISTRY.resolve(
                profile,
                "auto",
                capability_key=capability_key,
            )
        except Exception:
            setup_failed = True
        if setup_failed:
            raise RuntimeError("life_record_generation_failed")
        use_native_schema = response_mode is ResponseMode.JSON_SCHEMA
        result_mode = (
            ResponseMode.JSON_SCHEMA
            if use_native_schema
            else ResponseMode.LEGACY_TAGS
        )
        usage_accumulator = TurnTokenUsageAccumulator()

        native_failed = False
        fallback_required = False
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=self._build_life_record_config(
                    system_instruction=system_instruction,
                    use_native_schema=use_native_schema,
                    generation_params=generation_params,
                ),
            )
        except Exception as failure:
            native_failed = True
            try:
                failure_usage = self._response_usage(failure)
            except Exception:
                failure_usage = None
            usage_accumulator.record(failure_usage)
            try:
                fallback_required = (
                    use_native_schema
                    and self._is_explicit_structured_output_unsupported(failure)
                )
            except Exception:
                fallback_required = False
        if native_failed and not fallback_required:
            raise RuntimeError("life_record_generation_failed")
        if fallback_required:
            _GEMINI_RESPONSE_CAPABILITY_REGISTRY.mark_legacy(capability_key)
            result_mode = ResponseMode.LEGACY_TAGS
            fallback_failed = False
            try:
                response = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=self._build_life_record_config(
                        system_instruction=system_instruction,
                        use_native_schema=False,
                        generation_params=generation_params,
                    ),
                )
            except Exception as fallback_failure:
                try:
                    failure_usage = self._response_usage(fallback_failure)
                except Exception:
                    failure_usage = None
                usage_accumulator.record(failure_usage)
                fallback_failed = True
            if fallback_failed:
                raise RuntimeError("life_record_generation_failed")

        normalization_failed = False
        try:
            usage_accumulator.record(self._response_usage(response))
            provider_response = self._provider_response(
                response,
                result_mode,
            )
            usage = usage_accumulator.snapshot()
            result = OneShotGenerationResult(
                text=provider_response.carrier,
                status=provider_response.status,
                finish_reason=provider_response.finish_reason,
                token_usage=OneShotTokenUsage(
                    input_tokens=usage["input_tokens"],
                    output_tokens=usage["output_tokens"],
                    total_tokens=usage["total_tokens"],
                ),
            )
        except Exception:
            normalization_failed = True
        if normalization_failed:
            raise RuntimeError("life_record_generation_failed")
        return result

    def _create_web_search_decision_provider(self):
        return create_web_search_decision_provider(
            lambda prompt: self._generate_one_shot_text(
                prompt,
                request_kind=LLMRequestKind.DECISION,
                include_sub_prompt=False,
            )
        )

    def _empty_text_fallback_response(self) -> LLM_RESPONSE_TUPLE:
        """LLM이 텍스트 없는 응답을 반환했을 때 사용자에게 보여줄 안전한 fallback."""
        return "음... 무슨 일이 있었나봐요.", "confused", None, [], {}, [], "", {}, [], ""

    def _read_runtime_setting_for_log(self, key: str, default=None):
        """진단 로그용으로 dict/Settings 객체에서 설정값을 읽는다."""
        settings_source = getattr(self, "settings", None)
        if isinstance(settings_source, dict):
            return settings_source.get(key, default)
        getter = getattr(settings_source, "get", None)
        if callable(getter):
            try:
                return getter(key, default)
            except TypeError:
                pass
        config = getattr(settings_source, "config", None)
        if isinstance(config, dict):
            return config.get(key, default)
        return default

    def _debug_field(self, value, field: str, default=None):
        """dict와 SDK 객체 양쪽에서 진단 필드를 읽는다."""
        if isinstance(value, dict):
            return value.get(field, default)
        return getattr(value, field, default)

    def _safe_log_label(self, value) -> str:
        """호출자가 준 label을 고정 내부 category로만 바꾼다."""
        if type(value) is not str:
            return "other"
        return _SAFE_GEMINI_LOG_LABELS.get(value, "other")

    def _safe_exception_class(self, failure: BaseException) -> str:
        """예외 본문이나 문자열 hook 없이 클래스 이름만 반환한다."""
        name = type(failure).__name__
        if type(name) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            return name
        return "Exception"

    def _log_empty_response_diagnostics(self, response, label: str):
        """Gemini 빈 응답을 SDK 원문 없이 분류해 기록한다."""
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = self._debug_field(prompt_feedback, "block_reason")
        block_category = self._normalized_enum_text(block_reason) or "none"

        candidates = getattr(response, "candidates", None)
        if type(candidates) is list:
            candidate_count = list.__len__(candidates)
            iterable = candidates[:3]
        elif type(candidates) is tuple:
            candidate_count = tuple.__len__(candidates)
            iterable = candidates[:3]
        else:
            candidate_count = None
            iterable = ()

        print(
            "[LLM] 빈 텍스트 응답 감지 "
            "category=empty_response "
            f"request_kind={self._safe_log_label(label)} "
            f"candidate_count={candidate_count if candidate_count is not None else 'unknown'} "
            f"block_category={block_category}"
        )

        for index, candidate in enumerate(iterable):
            finish_reason = self._debug_field(candidate, "finish_reason")
            finish_message = self._debug_field(candidate, "finish_message")
            safety_ratings = self._debug_field(candidate, "safety_ratings")
            safety_count = _safe_builtin_count(safety_ratings)
            print(
                "[LLM] category=empty_response_candidate "
                f"candidate_index={index} "
                f"finish_category={self._normalized_enum_text(finish_reason) or 'none'} "
                f"finish_message_present={finish_message is not None} "
                f"safety_count={safety_count if safety_count is not None else 'unknown'}"
            )

    def _extract_response_text_or_empty(self, response, label: str) -> str:
        """Gemini 응답에서 텍스트를 안전하게 꺼내고, 비어 있으면 진단 로그를 남긴다."""
        raw_text = getattr(response, "text", None)
        response_text = raw_text.strip() if type(raw_text) is str else ""
        if response_text:
            return response_text
        self._log_empty_response_diagnostics(response, label)
        return ""

    def _expanded_output_token_budget(self, generation_params: dict) -> int:
        try:
            current = int(generation_params.get("max_tokens") or 0)
        except (TypeError, ValueError):
            current = 0
        if current <= 0:
            return GEMINI_MAX_OUTPUT_TOKENS
        if current >= GEMINI_MAX_OUTPUT_TOKENS:
            return current
        return min(
            GEMINI_MAX_OUTPUT_TOKENS,
            max(current + 512, current * 2),
        )

    def _normalized_enum_text(self, value) -> str:
        if value is None:
            return ""
        if type(value) is str:
            normalized = value
        else:
            name = getattr(value, "name", None)
            raw_value = getattr(value, "value", None)
            if type(name) is str:
                normalized = name
            elif type(raw_value) is str:
                normalized = raw_value
            else:
                return "other"
        normalized = normalized.strip().split(".")[-1].lower()
        if not normalized:
            return ""
        if normalized in _SAFE_GEMINI_ENUM_CATEGORIES:
            return normalized
        return "other"

    def _finish_reason_text(self, response) -> str:
        candidates = getattr(response, "candidates", None)
        if type(candidates) is list:
            if list.__len__(candidates) == 0:
                return ""
            candidate = candidates[0]
        elif type(candidates) is tuple:
            if tuple.__len__(candidates) == 0:
                return ""
            candidate = candidates[0]
        else:
            return ""
        reason = self._debug_field(candidate, "finish_reason")
        return self._normalized_enum_text(reason)

    def _response_usage(self, response) -> dict[str, int | None]:
        unknown = {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
        try:
            usage = getattr(response, "usage_metadata", None)
            if isinstance(response, dict):
                usage = response.get("usage_metadata")

            def read(*names):
                for name in names:
                    value = self._debug_field(usage, name)
                    if is_valid_token_count(value):
                        return value
                return None

            return {
                "input_tokens": read(
                    "prompt_token_count",
                    "input_token_count",
                    "prompt_tokens",
                    "input_tokens",
                ),
                "output_tokens": read(
                    "candidates_token_count",
                    "output_token_count",
                    "completion_token_count",
                    "output_tokens",
                    "completion_tokens",
                ),
                "total_tokens": read("total_token_count", "total_tokens"),
            }
        except Exception:
            return unknown

    def _provider_response(self, response, mode: ResponseMode) -> ProviderResponse:
        carrier = self._extract_response_text_or_empty(response, label="최종 응답")
        finish_reason = self._finish_reason_text(response)
        normal_reasons = {"", "stop", "finish_reason_unspecified"}
        refusal_reasons = {
            "safety",
            "recitation",
            "blocklist",
            "prohibited_content",
            "spii",
            "content_filter",
            "image_safety",
            "image_prohibited_content",
            "image_recitation",
        }
        if finish_reason == "max_tokens":
            status = ResponseStatus.INCOMPLETE
        elif finish_reason in refusal_reasons:
            status = ResponseStatus.REFUSAL
            finish_reason = "content_filter"
        elif finish_reason not in normal_reasons:
            status = ResponseStatus.INCOMPLETE
        elif carrier:
            status = ResponseStatus.COMPLETE
        else:
            block_reason = self._debug_field(
                getattr(response, "prompt_feedback", None),
                "block_reason",
            )
            normalized_block_reason = self._normalized_enum_text(block_reason)
            status = (
                ResponseStatus.REFUSAL
                if normalized_block_reason
                not in {
                    "",
                    "block_reason_unspecified",
                    "blocked_reason_unspecified",
                }
                else ResponseStatus.EMPTY
            )
        return ProviderResponse(
            carrier=carrier,
            status=status,
            mode=mode,
            finish_reason=finish_reason,
            usage=self._response_usage(response),
        )

    def _is_explicit_structured_output_unsupported(
        self, failure: BaseException
    ) -> bool:
        response = getattr(failure, "response", None)
        status = getattr(failure, "code", None)
        if status is None:
            status = getattr(response, "status_code", None)
        try:
            status_code = int(status)
        except (TypeError, ValueError):
            return False
        if status_code not in {400, 404, 422}:
            return False
        details = []
        message = getattr(failure, "message", None)
        if type(message) is str:
            details.append(message)
        args = getattr(failure, "args", ())
        if type(args) is tuple and tuple.__len__(args) > 0 and type(args[0]) is str:
            details.append(args[0])
        response_text = getattr(response, "text", None)
        if type(response_text) is str:
            details.append(response_text)
        detail = " ".join(details).lower()
        if any(
            phrase in detail
            for phrase in (
                "invalid schema",
                "malformed schema",
                "schema validation",
                "does not match schema",
            )
        ):
            return False
        marker = (
            r"(?:response_json_schema|response_mime_type|"
            r"responsejsonschema|responsemimetype)"
        )
        direct_marker = rf"{marker}(?!(?:[\w/\[\]-]|\.(?!\s|$)))"
        direct_patterns = (
            rf"\bunknown\s+(?:parameter|field)\s*:?\s*[\"']?{direct_marker}",
            rf"\bunrecognized\s+(?:parameter|field)\s*:?\s*[\"']?{direct_marker}",
            rf"\b(?:unsupported|not supported)\s+(?:parameter|field)\s*:?\s*[\"']?{direct_marker}",
            rf"\b{direct_marker}\s+(?:parameter|field)\s+(?:is\s+)?(?:unsupported|not supported|unknown|unrecognized)\b",
            rf"\bunknown\s+name\s+[\"']?{direct_marker}[\"']?.*?\bcannot\s+find\s+field\b",
            rf"\bunexpected\s+keyword(?:\s+argument)?\s*:?\s*[\"']?{direct_marker}",
            rf"\b{direct_marker}\s+is\s+(?:unsupported|not supported)\b",
            rf"\bmodel\s+(?:does\s+not|doesn't)\s+support\s+[\"']?{direct_marker}",
        )
        return any(
            re.search(pattern, detail, flags=re.DOTALL)
            for pattern in direct_patterns
        )


    def _get_sdk_history_views(self) -> list[list]:
        chat = getattr(self, "chat", None)
        histories = []
        getter = getattr(chat, "get_history", None)
        if callable(getter):
            try:
                histories.extend([getter(curated=True), getter(curated=False)])
            except TypeError:
                histories.append(getter())
            except Exception:
                histories = []
        if not histories:
            try:
                histories.append(getattr(chat, "history", None))
            except Exception:
                histories = []

        unique_histories = []
        seen_ids = set()
        for history in histories:
            if history is None or id(history) in seen_ids:
                continue
            seen_ids.add(id(history))
            unique_histories.append(history)
        return unique_histories

    def _get_sdk_history(self, *, deep_copy: bool) -> list:
        histories = self._get_sdk_history_views()
        values = list(histories[0]) if histories else []
        if not deep_copy:
            return values
        try:
            return copy.deepcopy(values)
        except Exception:
            return list(values)

    def _restore_history_snapshot(
        self,
        history_snapshot: list,
        *,
        response_mode: ResponseMode,
        generation_params: dict | None = None,
        settings_source: dict | None = None,
    ) -> None:
        self.chat = self._create_chat_session(
            history=copy.deepcopy(history_snapshot),
            response_mode=response_mode,
            generation_params=generation_params,
            settings_source=settings_source,
        )

    def _replace_latest_model_history_with_visible_reply(self, reply: str) -> None:
        for history in self._get_sdk_history_views():
            for item in reversed(history):
                if self._get_item_role(item) not in {"model", "assistant"}:
                    continue
                if isinstance(item, dict):
                    item["parts"] = [{"text": reply}]
                    break
                try:
                    item.parts = [genai.types.Part.from_text(text=reply)]
                except Exception:
                    break
                break

    def _build_repair_config(
        self,
        *,
        response_mode: ResponseMode,
        schema: dict | None,
        generation_params: dict,
    ) -> dict:
        config = {
            "temperature": generation_params["temperature"],
            "top_p": generation_params["top_p"],
        }
        if generation_params.get("max_tokens", 0) > 0:
            config["max_output_tokens"] = generation_params["max_tokens"]
        if response_mode is ResponseMode.JSON_SCHEMA and schema is not None:
            config["response_mime_type"] = "application/json"
            config["response_json_schema"] = copy.deepcopy(schema)
        return config

    def _execute_final_response(
        self,
        contents,
        *,
        history_user_content: str,
        label: str,
        settings_source: dict | None = None,
        response_mode: ResponseMode | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        """Gemini final 응답 호출 전체를 하나의 usage transaction으로 처리한다."""
        self._begin_response_turn_usage()
        try:
            return self._execute_final_response_transaction(
                contents,
                history_user_content=history_user_content,
                label=label,
                settings_source=settings_source,
                response_mode=response_mode,
            )
        finally:
            self._finish_response_turn_usage()

    def _execute_final_response_transaction(
        self,
        contents,
        *,
        history_user_content: str,
        label: str,
        settings_source: dict | None = None,
        response_mode: ResponseMode | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        """Gemini 자동 history를 한 턴 단위 transaction으로 검증하고 확정한다."""
        self._last_response_delivery_metadata = ResponseDeliveryMetadata.empty()
        settings_snapshot = (
            copy.deepcopy(settings_source)
            if settings_source is not None
            else self._settings_snapshot()
        )
        generation_snapshot = dict(self.generation_params)
        requirements = build_response_requirements(
            settings_snapshot,
            get_parseable_emotions(settings_source=settings_snapshot),
        )
        profile = self._response_profile()
        capability_key = build_capability_key(profile)
        initial_mode = response_mode or _GEMINI_RESPONSE_CAPABILITY_REGISTRY.resolve(
            profile,
            str(settings_snapshot.get("structured_response_mode", "auto") or "auto"),
            capability_key=capability_key,
        )
        history_snapshot = self._get_sdk_history(deep_copy=True)
        non_repair_attempts = 0

        def requester(attempt: ResponseAttempt) -> ProviderResponse:
            nonlocal non_repair_attempts
            if attempt.phase == "repair":
                prompt = build_response_repair_prompt(
                    attempt.preserved_reply,
                    requirements.response_language,
                    requirements.tts_language,
                    attempt.repair_fields,
                    attempt.mode,
                )
                schema = (
                    get_response_repair_schema(attempt.repair_fields)
                    if attempt.mode is ResponseMode.JSON_SCHEMA
                    else None
                )
                try:
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=self._build_repair_config(
                            response_mode=attempt.mode,
                            schema=schema,
                            generation_params=generation_snapshot,
                        ),
                    )
                except Exception:
                    self._record_response_turn_usage(None)
                    raise
                self._record_and_print_response_turn_usage(response, label="제한 복구")
                return self._provider_response(response, attempt.mode)

            attempt_params = dict(generation_snapshot)
            if attempt.expand_output_budget:
                attempt_params["max_tokens"] = self._expanded_output_token_budget(
                    attempt_params
                )
            request_config = None
            if non_repair_attempts:
                self._restore_history_snapshot(
                    history_snapshot,
                    response_mode=attempt.mode,
                    generation_params=generation_snapshot,
                    settings_source=settings_snapshot,
                )
                request_config = self._build_chat_config(
                    include_sub_prompt=True,
                    request_kind=LLMRequestKind.FINAL_REPLY,
                    response_mode=attempt.mode,
                    generation_params=attempt_params,
                    settings_source=settings_snapshot,
                )
            non_repair_attempts += 1
            try:
                if request_config is None:
                    response = self.chat.send_message(contents)
                else:
                    response = self.chat.send_message(
                        contents,
                        config=request_config,
                    )
            except Exception as failure:
                self._record_response_turn_usage(None)
                if (
                    attempt.mode is not ResponseMode.LEGACY_TAGS
                    and self._is_explicit_structured_output_unsupported(failure)
                ):
                    raise StructuredOutputUnsupported(
                        attempt.mode,
                        provider="gemini",
                    ) from failure
                raise
            self._record_and_print_response_turn_usage(response, label=label)
            return self._provider_response(response, attempt.mode)

        try:
            result = execute_final_response(
                requester,
                requirements=requirements,
                initial_mode=initial_mode,
                mark_unsupported=lambda _mode: (
                    _GEMINI_RESPONSE_CAPABILITY_REGISTRY.mark_legacy(capability_key)
                ),
            )
        except InvalidFinalResponseError:
            self._restore_history_snapshot(
                history_snapshot,
                response_mode=self._resolve_response_mode(settings_snapshot),
                generation_params=generation_snapshot,
                settings_source=settings_snapshot,
            )
            return self._empty_text_fallback_response()
        except Exception:
            self._restore_history_snapshot(
                history_snapshot,
                response_mode=self._resolve_response_mode(settings_snapshot),
                generation_params=generation_snapshot,
                settings_source=settings_snapshot,
            )
            raise

        self._replace_latest_user_history_text(history_user_content)
        self._replace_latest_model_history_with_visible_reply(result.payload[0])
        self._last_response_delivery_metadata = result.metadata
        final_mode = ResponseMode(result.metadata.response_mode)
        self._last_runtime_prompt_signature = self._runtime_prompt_signature(
            response_mode=final_mode,
            settings_source=settings_snapshot,
        )
        return result.payload

    def get_last_response_delivery_metadata(self) -> ResponseDeliveryMetadata:
        return getattr(
            self,
            "_last_response_delivery_metadata",
            ResponseDeliveryMetadata.empty(),
        )

    def _prompt_language(self) -> str:
        return resolve_prompt_language(settings_source=self.settings)

    def _memory_context_labels(self) -> dict[str, str]:
        return memory_context_labels(self)

    def _now_for_context(self) -> datetime:
        return datetime.now().astimezone()

    def _build_overdue_promise_context(self, labels: dict[str, str], language: str = "ko") -> str:
        return build_overdue_promise_context(self, labels, language)

    def _build_recent_incomplete_past_event_context(self, labels: dict[str, str], language: str = "ko") -> str:
        return build_recent_incomplete_past_event_context(self, labels, language)

    async def generate_markdown_document(self, message: str) -> str:
        """sub prompt 없이 마크다운 문서를 생성한다."""
        memory_context = await self._build_memory_context(message)
        diary_prompt = build_markdown_document_prompt(
            message,
            memory_context=memory_context,
            language=self._prompt_language(),
        )
        return self._generate_one_shot_text(
            diary_prompt,
            request_kind=LLMRequestKind.MARKDOWN,
            include_sub_prompt=False,
        )

    async def generate_diary_completion_reply(
        self,
        context_message: str,
    ) -> LLM_RESPONSE_TUPLE:
        """파일 작성 완료 안내 응답을 생성한다."""
        response_text = self._generate_one_shot_text(
            context_message,
            request_kind=LLMRequestKind.PLAIN_TEXT,
            include_sub_prompt=True,
        )
        return self._parse_response(response_text)

    async def generate_note_command_plan(self, context_message: str) -> str:
        """sub prompt 없이 /note 실행 계획(Markdown)을 생성한다."""
        memory_context = await self._build_memory_context(context_message)
        enhanced = f"{memory_context}\n\n{context_message}" if memory_context else context_message
        return self._generate_one_shot_text(
            enhanced,
            request_kind=LLMRequestKind.DECISION,
            include_sub_prompt=False,
        )

    async def generate_note_execution_report(
        self,
        context_message: str,
    ) -> LLM_RESPONSE_TUPLE:
        """sub prompt 적용 상태로 /note 실행 결과 보고 응답을 생성한다."""
        response_text = self._generate_one_shot_text(
            context_message,
            request_kind=LLMRequestKind.PLAIN_TEXT,
            include_sub_prompt=True,
        )
        return self._parse_response(response_text)

    async def send_message_with_memory(
        self,
        message: str,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
        include_life_record_context: bool = False,
    ) -> LLM_RESPONSE_TUPLE:
        """
        메모리를 활용한 메시지 전송
        
        Args:
            message: 사용자 메시지
            
        Returns:
            (응답 텍스트, 감정 태그, TTS 텍스트, 이벤트 리스트, analysis 메타, 약속 리스트, 속마음, 목표 업데이트) 튜플
        """
        # 메모리 컨텍스트 구성
        search_query = str(memory_search_text or "").strip() or message
        primary_query = str(latest_user_message or "").strip() or search_query
        support_context = str(recent_memory_context or "").strip()
        memory_context_kwargs = {
            "recent_context": support_context,
            "head_pat_count_before_message": head_pat_count_before_message,
        }
        if include_life_record_context is True:
            memory_context_kwargs["include_life_record_context"] = True
        memory_context = await self._build_memory_context(
            primary_query,
            **memory_context_kwargs,
        )
        web_search_context = build_web_search_context_from_settings(
            getattr(self, "settings", None),
            message=message,
            latest_user_message=str(latest_user_message or ""),
            recent_context=support_context,
            progress_callback=progress_callback,
            decision_provider=GeminiClient._create_web_search_decision_provider(self),
            search_cache=GeminiClient._get_web_search_cache(self),
            turn_index=GeminiClient._next_web_search_turn_index(self),
        )
        
        # 메모리가 있으면 메시지 앞에 추가
        enhanced_message = compose_contextual_message(
            message,
            memory_context=memory_context,
            web_search_context=web_search_context,
        )
        if memory_context:
            print(
                "[LLM] category=memory_context_added "
                f"char_count={_safe_builtin_count(memory_context) or 0}"
            )
        
        # 일반 메시지 전송. 모델 입력에는 컨텍스트를 붙이되, SDK 히스토리에는 사용자 원문을 남긴다.
        return self.send_message(enhanced_message, history_user_content=message)

    async def send_message_with_images(
        self,
        message: str,
        images_data: list,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
        include_life_record_context: bool = False,
    ) -> LLM_RESPONSE_TUPLE:
        """이미지 final 응답의 전처리부터 usage transaction으로 처리한다."""
        self._last_response_delivery_metadata = ResponseDeliveryMetadata.empty()
        self._begin_response_turn_usage()
        try:
            return await self._send_message_with_images_transaction(
                message,
                images_data,
                memory_search_text=memory_search_text,
                latest_user_message=latest_user_message,
                recent_memory_context=recent_memory_context,
                head_pat_count_before_message=head_pat_count_before_message,
                include_life_record_context=include_life_record_context,
                progress_callback=progress_callback,
            )
        finally:
            self._finish_response_turn_usage()

    async def _send_message_with_images_transaction(
        self,
        message: str,
        images_data: list,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
        include_life_record_context: bool = False,
    ) -> LLM_RESPONSE_TUPLE:
        """
        이미지와 함께 메시지 전송 (멀티모달)
        
        Args:
            message: 사용자 메시지
            images_data: 이미지 데이터 리스트 [{"dataUrl": ..., "name": ...}, ...]
            
        Returns:
            (응답 텍스트, 감정 태그, TTS 텍스트, 이벤트 리스트, analysis 메타, 약속 리스트, 속마음, 목표 업데이트) 튜플
        """
        import base64
        from PIL import Image
        import io
        
        image_count = _safe_builtin_count(images_data)
        print(
            "[LLM] category=final_request request_kind=multimodal "
            f"image_count={image_count if image_count is not None else 'unknown'} "
            f"prompt_chars={_safe_builtin_count(message) or 0}"
        )
        
        try:
            # 이미지 준비
            pil_images = []
            for img_data in images_data:
                if type(img_data) is not dict:
                    continue
                data_url = img_data.get('dataUrl', '')
                data_url = data_url if type(data_url) is str else ""
                if not data_url:
                    continue
                
                # base64 디코딩
                # data:image/png;base64,... 형식에서 데이터 부분만 추출
                if ',' in data_url:
                    header, base64_data = data_url.split(',', 1)
                else:
                    base64_data = data_url
                
                try:
                    image_bytes = base64.b64decode(base64_data)
                    pil_image = Image.open(io.BytesIO(image_bytes))
                    pil_images.append(pil_image)
                    print("[LLM] category=image_decode_success")
                except Exception as failure:
                    print(
                        "[LLM] category=image_decode_error "
                        f"exception_class={GeminiClient._safe_exception_class(self, failure)}"
                    )
            
            if not pil_images:
                print("[LLM] 유효한 이미지가 없음, 텍스트만 전송")
                return await self.send_message_with_memory(
                    message,
                    memory_search_text,
                    latest_user_message,
                    recent_memory_context,
                    head_pat_count_before_message,
                    include_life_record_context=include_life_record_context,
                    progress_callback=progress_callback,
                )
            
            # 메모리 컨텍스트 추가
            search_query = str(memory_search_text or "").strip() or message
            primary_query = str(latest_user_message or "").strip() or search_query
            support_context = str(recent_memory_context or "").strip()
            memory_context_kwargs = {
                "recent_context": support_context,
                "head_pat_count_before_message": head_pat_count_before_message,
            }
            if include_life_record_context is True:
                memory_context_kwargs["include_life_record_context"] = True
            memory_context = await self._build_memory_context(
                primary_query,
                **memory_context_kwargs,
            )
            web_search_context = build_web_search_context_from_settings(
                getattr(self, "settings", None),
                message=message,
                latest_user_message=str(latest_user_message or ""),
                recent_context=support_context,
                progress_callback=progress_callback,
                decision_provider=GeminiClient._create_web_search_decision_provider(self),
                search_cache=GeminiClient._get_web_search_cache(self),
                turn_index=GeminiClient._next_web_search_turn_index(self),
            )
            enhanced_message = compose_contextual_message(
                message,
                memory_context=memory_context,
                web_search_context=web_search_context,
            )
            
            # Gemini에 멀티모달 요청
            # contents에 이미지와 텍스트를 함께 전달
            contents = pil_images + [enhanced_message]
            
            if all(
                hasattr(self, attribute)
                for attribute in ("client", "model_name", "generation_params")
            ):
                settings_snapshot = self._settings_snapshot()
                response_mode = self._resolve_response_mode(settings_snapshot)
                self._refresh_chat_session_for_runtime_prompt_if_needed(
                    settings_source=settings_snapshot,
                    response_mode=response_mode,
                )
                result = self._execute_final_response(
                    contents,
                    history_user_content=message,
                    label="멀티모달",
                    settings_source=settings_snapshot,
                    response_mode=response_mode,
                )
                GeminiClient._log_final_response_metadata(
                    self, result, request_kind="multimodal"
                )
                return result
            self._refresh_chat_session_for_runtime_prompt_if_needed()
            response = self.chat.send_message(contents)
            self._log_turn_token_usage(response, label="멀티모달")
            
            response_text = self._extract_response_text_or_empty(response, label="멀티모달")
            GeminiClient._replace_latest_user_history_text(self, message)
            if not response_text:
                return self._empty_text_fallback_response()
            # 응답에서 텍스트, 감정, 일정 분리 (기존 메서드 활용)
            result = self._parse_response(response_text)
            GeminiClient._log_final_response_metadata(self, result, request_kind="multimodal")
            return result

            
        except Exception as failure:
            print(
                "[LLM] category=multimodal_error "
                f"exception_class={GeminiClient._safe_exception_class(self, failure)}"
            )
            return "이미지를 처리하는 중에 문제가 생겼어요.", "confused", None, [], {}, [], "", {}, [], ""

    def _build_goal_context_block(self, prompt_language: str | None = None) -> str:
        """메모리 매니저와 독립적으로 활성 목표 컨텍스트를 만든다."""
        return build_goal_context_block(self, prompt_language)

    async def _build_memory_context(
        self,
        query: str,
        recent_context: str = "",
        head_pat_count_before_message: int | None = None,
        include_life_record_context: bool = False,
    ) -> str:
        """메모리 기반 컨텍스트 구성."""
        return await build_common_memory_context(
            self,
            query,
            recent_context=recent_context,
            head_pat_count_before_message=head_pat_count_before_message,
            include_life_record_context=include_life_record_context,
        )

    def _normalize_int_setting(
        self,
        value,
        *,
        default: int,
        min_value: int,
        max_value: int,
    ) -> int:
        """정수 설정값을 안전하게 정규화한다."""
        return normalize_int_setting(value, default=default, min_value=min_value, max_value=max_value)

    def _begin_response_turn_usage(self) -> None:
        stack = getattr(self, "_response_turn_usage_stack", None)
        if not isinstance(stack, list):
            stack = []
            self._response_turn_usage_stack = stack
        stack.append(TurnTokenUsageAccumulator())

    def _record_response_turn_usage(
        self,
        usage: dict[str, int | None] | None,
    ) -> None:
        stack = getattr(self, "_response_turn_usage_stack", None)
        for accumulator in tuple(stack) if isinstance(stack, list) else ():
            accumulator.record(usage)

    def _finish_response_turn_usage(self) -> None:
        stack = getattr(self, "_response_turn_usage_stack", None)
        if not isinstance(stack, list) or not stack:
            return
        accumulator = stack.pop()
        if not stack:
            self._last_token_usage = accumulator.snapshot()

    def _print_token_usage(
        self,
        usage: dict[str, int | None],
        *,
        label: str,
    ) -> None:
        def display(key: str) -> str:
            value = usage.get(key)
            if is_valid_token_count(value) and type(value) is int:
                return int.__repr__(value)
            return "N/A"

        print(
            "[LLM] category=token_usage "
            f"request_kind={self._safe_log_label(label)} "
            f"input={display('input_tokens')}, "
            f"output={display('output_tokens')}, "
            f"total={display('total_tokens')}"
        )

    def _log_final_response_metadata(
        self,
        payload: LLM_RESPONSE_TUPLE,
        *,
        request_kind: str,
    ) -> None:
        """파싱된 응답 본문 대신 길이와 item 수만 기록한다."""
        if type(payload) is not tuple or tuple.__len__(payload) < 10:
            print("[LLM] category=final_response result=invalid_shape")
            return
        request_category = (
            request_kind if request_kind in {"text", "multimodal"} else "other"
        )
        goal_update = payload[7]
        goal_count = (
            1
            if type(goal_update) is dict and dict.__len__(goal_update) > 0
            else 0
        )
        print(
            "[LLM] category=final_response "
            f"request_kind={request_category} "
            f"reply_chars={_safe_builtin_count(payload[0]) or 0} "
            f"tts_chars={_safe_builtin_count(payload[2]) or 0} "
            f"event_count={_safe_builtin_count(payload[3]) or 0} "
            f"analysis_count={_safe_builtin_count(payload[4]) or 0} "
            f"promise_count={_safe_builtin_count(payload[5]) or 0} "
            f"thought_chars={_safe_builtin_count(payload[6]) or 0} "
            f"goal_count={goal_count} "
            f"proactive_count={_safe_builtin_count(payload[8]) or 0}"
        )

    def _record_and_print_response_turn_usage(self, response, *, label: str) -> None:
        usage = self._response_usage(response)
        self._record_response_turn_usage(usage)
        self._print_token_usage(usage, label=label)

    def _log_turn_token_usage(self, response, label: str = "텍스트"):
        """활성 transaction에는 누산하고, 아니면 최신 스냅샷을 덮어쓴다."""
        usage = self._response_usage(response)
        stack = getattr(self, "_response_turn_usage_stack", None)
        if isinstance(stack, list) and stack:
            self._record_response_turn_usage(usage)
        else:
            self._last_token_usage = usage
        self._print_token_usage(usage, label=label)

    def get_last_token_usage(self) -> dict:
        """가장 최근 응답의 토큰 사용량 스냅샷을 반환한다."""
        usage = getattr(self, "_last_token_usage", None)
        if not isinstance(usage, dict):
            return {
                "input_tokens": None,
                "output_tokens": None,
                "total_tokens": None,
            }
        return {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
            "total_tokens": usage.get("total_tokens"),
        }

    def _replace_latest_user_history_text(self, text: str) -> None:
        """Gemini SDK가 자동 저장한 최신 사용자 턴의 텍스트를 화면 원문으로 되돌린다."""
        for history in GeminiClient._get_sdk_history_views(self):
            for item in reversed(list(history)):
                if GeminiClient._get_item_role(self, item) != "user":
                    continue
                parts = (
                    item.get("parts")
                    if isinstance(item, dict)
                    else getattr(item, "parts", None)
                )
                if not parts:
                    break
                for part in reversed(list(parts)):
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        part["text"] = text
                        break
                    part_text = getattr(part, "text", None)
                    if isinstance(part_text, str):
                        try:
                            setattr(part, "text", text)
                        except Exception:
                            pass
                        break
                break

    def _get_web_search_cache(self) -> dict:
        cache = getattr(self, "_web_search_cache", None)
        if not isinstance(cache, dict):
            cache = {}
            self._web_search_cache = cache
        return cache

    def _next_web_search_turn_index(self) -> int:
        current = getattr(self, "_web_search_turn_index", 0)
        try:
            current = int(current)
        except (TypeError, ValueError):
            current = 0
        current += 1
        self._web_search_turn_index = current
        return current

    def send_message(
        self,
        message: str,
        history_user_content: str | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        """
        메시지 전송 및 응답 받기
        
        Args:
            message: 사용자 메시지
            
        Returns:
            (응답 텍스트, 감정 태그, TTS 텍스트, 이벤트 리스트, analysis 메타, 약속 리스트, 속마음, 목표 업데이트) 튜플
        """
        try:
            print(
                "[LLM] category=final_request request_kind=text "
                f"prompt_chars={_safe_builtin_count(message) or 0}"
            )
            if all(
                hasattr(self, attribute)
                for attribute in ("client", "model_name", "generation_params")
            ):
                settings_snapshot = self._settings_snapshot()
                response_mode = self._resolve_response_mode(settings_snapshot)
                self._refresh_chat_session_for_runtime_prompt_if_needed(
                    settings_source=settings_snapshot,
                    response_mode=response_mode,
                )
                result = self._execute_final_response(
                    message,
                    history_user_content=history_user_content or message,
                    label="텍스트",
                    settings_source=settings_snapshot,
                    response_mode=response_mode,
                )
                GeminiClient._log_final_response_metadata(self, result, request_kind="text")
                return result

            self._refresh_chat_session_for_runtime_prompt_if_needed()
            response = self.chat.send_message(message)
            self._log_turn_token_usage(response, label="텍스트")
            response_text = self._extract_response_text_or_empty(response, label="텍스트")
            if history_user_content is not None:
                GeminiClient._replace_latest_user_history_text(self, history_user_content)
            if not response_text:
                return self._empty_text_fallback_response()
            result = self._parse_response(response_text)
            GeminiClient._log_final_response_metadata(self, result, request_kind="text")
            return result
        except Exception as failure:
            print(
                "[LLM] category=provider_error "
                f"exception_class={GeminiClient._safe_exception_class(self, failure)}"
            )
            raise

    async def summarize_conversation(
        self,
        messages: list,
        loaded_topic_memory_context: str = "",
    ) -> tuple[str, list[str], list[str], dict, list]:
        """
        대화 내용 요약 및 사용자 정보 추출
        
        Args:
            messages: [(role, content), ...] 형식의 메시지 리스트
            
        Returns:
            (요약 텍스트, 사용자 정보 목록, 에네 정보 목록, 메모리 메타데이터) 튜플
        """
        message_count = _safe_builtin_count(messages) or 0
        try:
            prompt_language = self._prompt_language()
            prompt_names = resolve_prompt_persona_names(
                settings_source=getattr(self, "settings", None),
                language=prompt_language,
            )
            summary_prompt = build_summary_prompt(
                messages,
                user_profile=self.user_profile,
                language=prompt_language,
                assistant_name=prompt_names.assistant,
                user_name=prompt_names.user,
                loaded_topic_memory_context=loaded_topic_memory_context,
            )
            summarize_prompt = summary_prompt.prompt
            time_range = summary_prompt.time_range

            print(
                "[LLM] category=summary_request "
                f"message_count={message_count}"
            )
            
            # 일회성 요청으로 요약 생성 (Chat 세션과 별도)
            response_text = self._request_summary_text(summarize_prompt)
            if not response_text:
                return "대화 내용을 요약하지 못했어요.", [], [], {
                    "memory_type": "general",
                    "importance_reason": "empty_llm_response",
                    "confidence": 0.0,
                    "entity_names": [],
                }, []
            
            # 응답 파싱
            summary, user_facts, ene_facts, memory_meta, topic_hints = (
                self._parse_summary_response_with_topic_memory(response_text)
            )

            # 요약에 날짜 정보가 없으면 최소한 시간 범위를 보강
            has_date = (
                re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", summary) is not None
                or re.search(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일", summary) is not None
            )
            if not has_date:
                summary = f"[{time_range}] {summary}".strip()
            
            print(
                "[LLM] category=summary_success "
                f"summary_chars={_safe_builtin_count(summary) or 0} "
                f"user_fact_count={_safe_builtin_count(user_facts) or 0} "
                f"ene_fact_count={_safe_builtin_count(ene_facts) or 0} "
                f"memory_meta_count={_safe_builtin_count(memory_meta) or 0} "
                f"topic_hint_count={_safe_builtin_count(topic_hints) or 0}"
            )
            
            return summary, user_facts, ene_facts, memory_meta, topic_hints
            
        except Exception as failure:
            print(
                "[LLM] category=summary_error "
                f"exception_class={GeminiClient._safe_exception_class(self, failure)}"
            )
            return f"대화 {message_count}개 메시지", [], [], {}, []

    def _parse_summary_memory_meta(self, meta_lines: list[str]) -> dict:
        """요약 응답의 MEMORY_META 섹션을 정규화된 딕셔너리로 파싱한다."""
        return parse_summary_memory_meta(meta_lines)

    def _parse_summary_response(self, response_text: str) -> tuple[str, list[str], list[str], dict]:
        """요약 응답 파싱 ([SUMMARY], [MASTER_INFO], [ENE_INFO], [MEMORY_META] 분리)."""
        return parse_summary_response(response_text)

    def _parse_summary_response_with_topic_memory(self, response_text: str) -> tuple[str, list[str], list[str], dict, list]:
        """요약 응답에서 TOPIC_MEMORY 힌트까지 함께 분리한다."""
        return parse_summary_response_with_topic_memory(response_text)

    def _parse_analysis_lines(self, raw_block: str) -> Dict[str, str]:
        """analysis 메타 블록의 key=value 줄을 안전하게 파싱한다."""
        return parse_analysis_lines(raw_block)

    def _extract_analysis_block(self, response_text: str) -> tuple[str, Dict[str, str]]:
        """응답의 analysis 블록 또는 상단 메타 줄을 분리해 구조화된 딕셔너리로 반환한다."""
        return extract_analysis_block(response_text)

    def _extract_thought_block(self, response_text: str) -> tuple[str, str]:
        """응답 본문에서 에네의 짧은 속마음 블록을 분리한다."""
        return extract_thought_metadata(response_text)

    def _extract_goal_update_block(self, response_text: str) -> tuple[str, Dict[str, str]]:
        """응답 본문에서 목표 업데이트 메타데이터 블록을 분리한다."""
        return extract_goal_update_metadata(response_text)

    def _extract_legacy_japanese_tts_lines(self, text: str) -> tuple[str, str | None]:
        """구형 일본어 TTS 줄을 표시 텍스트와 분리한다."""
        return extract_legacy_japanese_tts_lines(text)

    def _extract_tts_text(self, text: str) -> tuple[str, str | None]:
        """명시적 TTS 블록 또는 설정 언어에 따라 TTS용 텍스트를 분리한다."""
        return extract_tts_text(text, settings_source=getattr(self, "settings", None))

    def _parse_response(self, response_text: str) -> LLM_RESPONSE_TUPLE:
        """
        응답 텍스트에서 감정 태그, TTS 텍스트, 일정 추출
        
        Args:
            response_text: AI 응답 텍스트
            
        Returns:
            (텍스트, 감정, TTS 텍스트, 이벤트 리스트, analysis 메타, 약속 리스트, 속마음, 목표 업데이트) 튜플
        """
        return parse_llm_response(
            response_text,
            settings_source=getattr(self, "settings", None),
            available_emotions=get_parseable_emotions(settings_source=getattr(self, "settings", None)),
            log_event=lambda _event: print(
                "[LLM] category=schedule_event_extracted event_count=1"
            ),
        )

    def _is_japanese(self, text: str) -> bool:
        """일본어 텍스트인지 확인"""
        return is_japanese(text)

    def clear_context(self):
        """대화 컨텍스트 초기화 - 새로운 Chat 세션 생성"""
        self.chat = self._create_chat_session()
        self._last_runtime_prompt_signature = self._runtime_prompt_signature()
        self._web_search_cache = {}
        self._web_search_turn_index = 0
        print("[LLM] Chat session reset")

    def _get_item_role(self, item) -> str:
        """히스토리 아이템에서 role 값을 안전하게 추출한다."""
        if item is None:
            return ""
        if type(item) is dict:
            role = item.get("role", "")
        else:
            role = getattr(item, "role", "")
        if type(role) is not str:
            return ""
        normalized = role.strip().lower()
        if normalized in {"assistant", "model", "system", "user"}:
            return normalized
        return "other"

    def rollback_last_assistant_turn(self) -> bool:
        """
        리롤 직전 턴(user+assistant)을 롤백한 히스토리로 chat 세션을 재구성한다.
        끝부분이 [user, model] 형태일 때만 안전하게 롤백하고,
        모호한 히스토리 구조에서는 실패로 반환해 리롤을 중단하게 한다.
        """
        try:
            history = self.get_conversation_history()
            if not history:
                print("[LLM] rollback skipped: history empty")
                return False

            trimmed_history = list(history)
            if not trimmed_history:
                print("[LLM] rollback skipped: history conversion failed")
                return False

            # 리롤은 마지막 assistant 응답 1개를 기준으로 동작하므로
            # 히스토리 tail이 반드시 model/assistant여야 한다.
            last_role = self._get_item_role(trimmed_history[-1])
            if last_role not in ("assistant", "model"):
                print("[LLM] rollback skipped category=unexpected_tail_role")
                return False

            # 마지막 assistant/model 제거
            trimmed_history.pop()

            # 직전 user 제거 (같은 user 입력 재전송 시 누적 방지)
            if not trimmed_history:
                print("[LLM] rollback skipped: missing user turn before assistant")
                return False
            last_user_role = self._get_item_role(trimmed_history[-1])
            if last_user_role != "user":
                print("[LLM] rollback skipped category=missing_user_before_assistant")
                return False
            trimmed_history.pop()

            self.chat = self._create_chat_session(history=trimmed_history)
            print("[LLM] rollback_last_assistant_turn: success (user+assistant rolled back)")
            return True
        except Exception:
            print("[LLM] category=history_rollback_error")
            return False

    def rebuild_context_from_conversation(self, conversation_buffer: list) -> bool:
        """
        Bridge의 conversation_buffer를 기반으로 chat 세션을 재구성한다.
        SDK history 접근이 비어있는 환경에서 리롤 폴백 용도로 사용한다.
        """
        try:
            history = []
            source = (
                conversation_buffer
                if type(conversation_buffer) in {list, tuple}
                else ()
            )
            for item in source:
                item_count = _safe_builtin_count(item)
                if item_count is None or item_count < 2:
                    continue
                role = item[0].strip().lower() if type(item[0]) is str else ""
                raw_content = item[1] if type(item[1]) is str else ""
                timestamp = item[2].strip() if item_count >= 3 and type(item[2]) is str else ""
                content = prepend_message_time(raw_content, timestamp)
                if role == "assistant":
                    role = "model"
                elif role != "user":
                    continue
                history.append({
                    "role": role,
                    "parts": [{"text": content}],
                })

            self.chat = self._create_chat_session(history=history)
            print(f"[LLM] category=history_rebuild_success turn_count={list.__len__(history)}")
            return True
        except Exception as failure:
            print(
                "[LLM] category=history_rebuild_error "
                f"exception_class={GeminiClient._safe_exception_class(self, failure)}"
            )
            return False

    def get_conversation_history(self):
        """대화 내역 반환"""
        return self._get_sdk_history(deep_copy=False)
