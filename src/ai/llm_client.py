"""
Gemini LLM 클라이언트 (google-genai SDK 사용)
"""
from datetime import datetime
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
from .prompt import build_runtime_system_prompt, get_parseable_emotions
from .prompt_config import get_runtime_emotions
from .prompt_language import resolve_prompt_language
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
from .summary_parser import parse_summary_memory_meta, parse_summary_response
from .markdown_document_prompt import build_markdown_document_prompt
from .summary_prompt import build_summary_prompt
from .tool_calling import build_web_search_context_from_settings, compose_contextual_message

LLM_RESPONSE_TUPLE = Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict], str, Dict[str, str], List[Dict], str]


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
        
        # Chat 세션 생성
        self.chat = self._create_chat_session()
        self._last_runtime_prompt_signature = self._runtime_prompt_signature()
        
        print(f"[LLM] Chat session created with model: {self.model_name}")
        if self.memory_manager:
            print("[LLM] Memory manager connected")

    def _runtime_prompt_settings_source(self):
        """현재 선제 대화 쿨다운 상태를 반영한 프롬프트 설정을 반환한다."""
        return build_runtime_prompt_settings_source(
            self.settings,
            proactive_manager=getattr(self, "proactive_manager", None),
        )

    def _runtime_prompt_signature(self) -> tuple:
        source = self._runtime_prompt_settings_source()
        proactive_enabled = True
        keys = []
        avatar_mode = "live2d"
        image_avatar_folder = ""
        if isinstance(source, dict):
            proactive_enabled = bool(source.get("enable_proactive_conversation", True))
            keys = list(source.get("proactive_available_cooldown_keys") or [])
            avatar_mode = str(source.get("avatar_mode", "live2d") or "live2d").strip().lower()
            image_avatar_folder = str(source.get("image_avatar_folder", "") or "").strip()
        else:
            getter = getattr(source, "get", None)
            if callable(getter):
                try:
                    proactive_enabled = bool(getter("enable_proactive_conversation", True))
                except Exception:
                    proactive_enabled = True
                try:
                    avatar_mode = str(getter("avatar_mode", "live2d") or "live2d").strip().lower()
                except Exception:
                    avatar_mode = "live2d"
                try:
                    image_avatar_folder = str(getter("image_avatar_folder", "") or "").strip()
                except Exception:
                    image_avatar_folder = ""
            config = getattr(source, "config", None)
            if isinstance(config, dict):
                proactive_enabled = bool(config.get("enable_proactive_conversation", proactive_enabled))
                avatar_mode = str(config.get("avatar_mode", avatar_mode) or avatar_mode).strip().lower()
                image_avatar_folder = str(config.get("image_avatar_folder", image_avatar_folder) or "").strip()
        try:
            runtime_emotions = tuple(get_runtime_emotions(settings_source=source))
        except Exception:
            runtime_emotions = ()
        return (
            proactive_enabled,
            tuple(str(key) for key in keys),
            avatar_mode,
            image_avatar_folder,
            runtime_emotions,
        )

    def _refresh_chat_session_for_runtime_prompt_if_needed(self) -> None:
        signature = self._runtime_prompt_signature()
        previous = getattr(self, "_last_runtime_prompt_signature", None)
        if previous == signature:
            return
        if not hasattr(self, "model_name") or not hasattr(self, "client"):
            self._last_runtime_prompt_signature = signature
            return
        history = self.get_conversation_history()
        self.chat = self._create_chat_session(history=history)
        self._last_runtime_prompt_signature = signature

    def _create_chat_session(self, history=None):
        """Gemini chat 세션을 생성한다."""
        kwargs = {
            "model": self.model_name,
            "config": self._build_chat_config(include_sub_prompt=True),
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

    def _build_chat_config(self, include_sub_prompt: bool = True) -> dict:
        system_instruction = build_runtime_system_prompt(
            include_sub_prompt=include_sub_prompt,
            include_analysis_appendix=True,
            settings_source=self._runtime_prompt_settings_source(),
        )
        config = {
            "system_instruction": system_instruction,
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
        }
        if self.generation_params["max_tokens"] > 0:
            config["max_output_tokens"] = self.generation_params["max_tokens"]
        return config

    def _generate_one_shot_text(self, message: str, include_sub_prompt: bool) -> str:
        """히스토리를 남기지 않는 일회성 생성 호출."""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=message,
            config=self._build_chat_config(include_sub_prompt=include_sub_prompt),
        )
        return self._extract_response_text_or_empty(response, label="one-shot")

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

    def _summarize_debug_value(self, value, max_length: int = 500) -> str:
        """응답 객체 일부를 로그에 과도하게 길지 않게 남긴다."""
        if value is None:
            return "None"
        try:
            text = repr(value)
        except Exception as exc:
            text = f"<unrepresentable {type(value).__name__}: {exc}>"
        if len(text) > max_length:
            return text[:max_length] + "...(truncated)"
        return text

    def _log_empty_response_diagnostics(self, response, label: str):
        """Gemini가 텍스트 없는 응답을 준 원인 추적에 필요한 정보를 남긴다."""
        print(f"[LLM] 빈 텍스트 응답 감지 ({label})")
        print(
            "[LLM] Empty response settings | "
            f"enable_ene_thoughts={self._read_runtime_setting_for_log('enable_ene_thoughts', True)}, "
            f"include_ene_thoughts_in_context={self._read_runtime_setting_for_log('include_ene_thoughts_in_context', False)}"
        )

        prompt_feedback = getattr(response, "prompt_feedback", None)
        if prompt_feedback is not None:
            print(f"[LLM] Empty response prompt_feedback: {self._summarize_debug_value(prompt_feedback)}")

        candidates = getattr(response, "candidates", None)
        if candidates is None:
            print("[LLM] Empty response candidates: None")
            return

        try:
            candidate_count = len(candidates)
        except Exception:
            candidate_count = "unknown"
        print(f"[LLM] Empty response candidates_count: {candidate_count}")

        try:
            iterable = list(candidates[:3])
        except Exception:
            try:
                iterable = list(candidates)[:3]
            except Exception:
                print(f"[LLM] Empty response candidates_repr: {self._summarize_debug_value(candidates)}")
                return

        for index, candidate in enumerate(iterable):
            finish_reason = self._debug_field(candidate, "finish_reason")
            finish_message = self._debug_field(candidate, "finish_message")
            safety_ratings = self._debug_field(candidate, "safety_ratings")
            print(
                f"[LLM] Empty response candidate[{index}] | "
                f"finish_reason={self._summarize_debug_value(finish_reason, 120)}, "
                f"finish_message={self._summarize_debug_value(finish_message, 200)}, "
                f"safety_ratings={self._summarize_debug_value(safety_ratings, 300)}"
            )

    def _extract_response_text_or_empty(self, response, label: str) -> str:
        """Gemini 응답에서 텍스트를 안전하게 꺼내고, 비어 있으면 진단 로그를 남긴다."""
        raw_text = getattr(response, "text", None)
        response_text = str(raw_text).strip() if raw_text is not None else ""
        if response_text:
            return response_text
        self._log_empty_response_diagnostics(response, label)
        return ""

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
        return self._generate_one_shot_text(diary_prompt, include_sub_prompt=False)

    async def generate_diary_completion_reply(
        self,
        context_message: str,
    ) -> LLM_RESPONSE_TUPLE:
        """파일 작성 완료 안내 응답을 생성한다."""
        response_text = self._generate_one_shot_text(context_message, include_sub_prompt=True)
        return self._parse_response(response_text)

    async def generate_note_command_plan(self, context_message: str) -> str:
        """sub prompt 없이 /note 실행 계획(Markdown)을 생성한다."""
        memory_context = await self._build_memory_context(context_message)
        enhanced = f"{memory_context}\n\n{context_message}" if memory_context else context_message
        return self._generate_one_shot_text(enhanced, include_sub_prompt=False)

    async def generate_note_execution_report(
        self,
        context_message: str,
    ) -> LLM_RESPONSE_TUPLE:
        """sub prompt 적용 상태로 /note 실행 결과 보고 응답을 생성한다."""
        response_text = self._generate_one_shot_text(context_message, include_sub_prompt=True)
        return self._parse_response(response_text)

    async def send_message_with_memory(
        self,
        message: str,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
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
        memory_context = await self._build_memory_context(
            primary_query,
            recent_context=support_context,
            head_pat_count_before_message=head_pat_count_before_message,
        )
        web_search_context = build_web_search_context_from_settings(
            getattr(self, "settings", None),
            message=message,
            latest_user_message=str(latest_user_message or ""),
            recent_context=support_context,
            progress_callback=progress_callback,
        )
        
        # 메모리가 있으면 메시지 앞에 추가
        enhanced_message = compose_contextual_message(
            message,
            memory_context=memory_context,
            web_search_context=web_search_context,
        )
        if memory_context:
            print(f"[LLM] 메모리 컨텍스트 추가 (길이: {len(memory_context)})")
        
        # 일반 메시지 전송
        return self.send_message(enhanced_message)
    
    async def send_message_with_images(
        self,
        message: str,
        images_data: list,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
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
        
        print(f"[LLM] 멀티모달 요청: {len(images_data)}개 이미지")
        
        try:
            # 이미지 준비
            pil_images = []
            for img_data in images_data:
                data_url = img_data.get('dataUrl', '')
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
                    print(f"[LLM] 이미지 로드: {pil_image.size}")
                except Exception as e:
                    print(f"[LLM] 이미지 디코딩 실패: {e}")
            
            if not pil_images:
                print("[LLM] 유효한 이미지가 없음, 텍스트만 전송")
                return await self.send_message_with_memory(
                    message,
                    memory_search_text,
                    latest_user_message,
                    recent_memory_context,
                    head_pat_count_before_message,
                    progress_callback,
                )
            
            # 메모리 컨텍스트 추가
            search_query = str(memory_search_text or "").strip() or message
            primary_query = str(latest_user_message or "").strip() or search_query
            support_context = str(recent_memory_context or "").strip()
            memory_context = await self._build_memory_context(
                primary_query,
                recent_context=support_context,
                head_pat_count_before_message=head_pat_count_before_message,
            )
            web_search_context = build_web_search_context_from_settings(
                getattr(self, "settings", None),
                message=message,
                latest_user_message=str(latest_user_message or ""),
                recent_context=support_context,
                progress_callback=progress_callback,
            )
            enhanced_message = compose_contextual_message(
                message,
                memory_context=memory_context,
                web_search_context=web_search_context,
            )
            
            # Gemini에 멀티모달 요청
            # contents에 이미지와 텍스트를 함께 전달
            contents = pil_images + [enhanced_message]
            
            print(f"[LLM] Gemini 멀티모달 요청 전송...")
            self._refresh_chat_session_for_runtime_prompt_if_needed()
            response = self.chat.send_message(contents)
            self._log_turn_token_usage(response, label="멀티모달")
            
            response_text = self._extract_response_text_or_empty(response, label="멀티모달")
            if not response_text:
                return self._empty_text_fallback_response()
            print(f"[LLM] 멀티모달 응답: {response_text[:100]}...")
            
            # 응답에서 텍스트, 감정, 일정 분리 (기존 메서드 활용)
            clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._parse_response(response_text)
            
            # TTS 텍스트가 있으면 로깅
            if tts_text:
                print(f"[LLM] TTS 텍스트: {tts_text[:30]}...")
            
            # 일정이 있으면 로깅
            if events:
                print(f"[LLM] {len(events)}개 일정 추출됨")
            
            return clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture

            
        except Exception as e:
            print(f"[LLM] 멀티모달 처리 실패: {e}")
            import traceback
            traceback.print_exc()
            return f"이미지를 처리하는 중에 문제가 생겼어요... ({str(e)[:50]})", "confused", None, [], {}, [], "", {}, [], ""

    def _build_goal_context_block(self, prompt_language: str | None = None) -> str:
        """메모리 매니저와 독립적으로 활성 목표 컨텍스트를 만든다."""
        return build_goal_context_block(self, prompt_language)

    
    async def _build_memory_context(
        self,
        query: str,
        recent_context: str = "",
        head_pat_count_before_message: int | None = None,
    ) -> str:
        """메모리 기반 컨텍스트 구성."""
        return await build_common_memory_context(
            self,
            query,
            recent_context=recent_context,
            head_pat_count_before_message=head_pat_count_before_message,
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
    
    def _log_turn_token_usage(self, response, label: str = "텍스트"):
        """응답 메타데이터에서 1회 입력/출력 토큰 사용량을 로깅한다."""
        def _read_field(container, *names):
            if container is None:
                return None
            for name in names:
                if hasattr(container, name):
                    value = getattr(container, name)
                    if value is not None:
                        return value
                if isinstance(container, dict) and name in container:
                    value = container.get(name)
                    if value is not None:
                        return value
            return None

        usage = None
        if hasattr(response, "usage_metadata"):
            usage = getattr(response, "usage_metadata")
        elif isinstance(response, dict):
            usage = response.get("usage_metadata")

        input_tokens = _read_field(
            usage,
            "prompt_token_count",
            "input_token_count",
            "prompt_tokens",
            "input_tokens",
        )
        output_tokens = _read_field(
            usage,
            "candidates_token_count",
            "output_token_count",
            "completion_token_count",
            "output_tokens",
            "completion_tokens",
        )
        total_tokens = _read_field(usage, "total_token_count", "total_tokens")
        self._last_token_usage = {
            "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
            "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
            "total_tokens": total_tokens if isinstance(total_tokens, int) else None,
        }

        in_str = str(input_tokens) if isinstance(input_tokens, int) else "N/A"
        out_str = str(output_tokens) if isinstance(output_tokens, int) else "N/A"
        total_str = str(total_tokens) if isinstance(total_tokens, int) else "N/A"
        print(f"[LLM] 🎫 Token Usage ({label}) | input={in_str}, output={out_str}, total={total_str}")

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

    def send_message(
        self,
        message: str,
    ) -> LLM_RESPONSE_TUPLE:
        """
        메시지 전송 및 응답 받기
        
        Args:
            message: 사용자 메시지
            
        Returns:
            (응답 텍스트, 감정 태그, TTS 텍스트, 이벤트 리스트, analysis 메타, 약속 리스트, 속마음, 목표 업데이트) 튜플
        """
        try:
            print(f"[LLM] Sending message: {message}")
            
            # 토큰 계산 (비동기로 실행하지 않고 로그만 출력)
            # 동기 메서드 내에서 비동기 호출이 어려우므로 여기서는 생략하거나
            # 별도의 동기 메서드로 구현해야 함. 일단은 생략하고 멀티모달에서만 적용
            
            # Chat 세션으로 메시지 전송
            self._refresh_chat_session_for_runtime_prompt_if_needed()
            response = self.chat.send_message(message)
            self._log_turn_token_usage(response, label="텍스트")
            
            # 응답 텍스트 추출
            response_text = self._extract_response_text_or_empty(response, label="텍스트")
            if not response_text:
                return self._empty_text_fallback_response()
            print(f"[LLM] Received response: {response_text[:50]}...")
            
            # 응답에서 텍스트와 감정 분리
            text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._parse_response(response_text)
            
            # TTS 텍스트가 있으면 로깅
            if tts_text:
                print(f"[LLM] TTS 텍스트: {tts_text[:30]}...")
            
            # 일정이 있으면 로깅
            if events:
                print(f"[LLM] {len(events)}개 일정 추출됨")
            
            return text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture
            
        except Exception as e:
            print(f"[LLM] Error: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    async def summarize_conversation(self, messages: list) -> tuple[str, list[str], list[str], dict]:
        """
        대화 내용 요약 및 사용자 정보 추출
        
        Args:
            messages: [(role, content), ...] 형식의 메시지 리스트
            
        Returns:
            (요약 텍스트, 사용자 정보 목록, 에네 정보 목록, 메모리 메타데이터) 튜플
        """
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
            )
            summarize_prompt = summary_prompt.prompt
            time_range = summary_prompt.time_range

            print(f"[LLM] 대화 요약 및 정보 추출 중... (메시지 수: {len(messages)})")
            
            # 일회성 요청으로 요약 생성 (Chat 세션과 별도)
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=summarize_prompt,
                config={'temperature': 0.5}  # 요약은 더 일관성 있게
            )
            
            response_text = self._extract_response_text_or_empty(response, label="요약")
            if not response_text:
                return "대화 내용을 요약하지 못했어요.", [], [], {
                    "memory_type": "general",
                    "importance_reason": "empty_llm_response",
                    "confidence": 0.0,
                    "entity_names": [],
                }
            
            # 응답 파싱
            summary, user_facts, ene_facts, memory_meta = self._parse_summary_response(response_text)

            # 요약에 날짜 정보가 없으면 최소한 시간 범위를 보강
            has_date = (
                re.search(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", summary) is not None
                or re.search(r"\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일", summary) is not None
            )
            if not has_date:
                summary = f"[{time_range}] {summary}".strip()
            
            print(f"[LLM] 요약 생성 완료: {summary[:50]}...")
            if user_facts:
                print(f"[LLM] 마스터 정보 {len(user_facts)}개 추출: {user_facts}")
            if ene_facts:
                print(f"[LLM] 에네 정보 {len(ene_facts)}개 추출: {ene_facts}")
            if memory_meta:
                print(f"[LLM] 메모리 메타 추출: {memory_meta}")
            
            return summary, user_facts, ene_facts, memory_meta
            
        except Exception as e:
            print(f"[LLM] 요약 생성 실패: {e}")
            import traceback
            traceback.print_exc()
            # 실패 시 간단한 요약 반환
            return f"대화 {len(messages)}개 메시지", [], [], {}
    
    def _parse_summary_memory_meta(self, meta_lines: list[str]) -> dict:
        """요약 응답의 MEMORY_META 섹션을 정규화된 딕셔너리로 파싱한다."""
        return parse_summary_memory_meta(meta_lines)

    def _parse_summary_response(self, response_text: str) -> tuple[str, list[str], list[str], dict]:
        """요약 응답 파싱 ([SUMMARY], [MASTER_INFO], [ENE_INFO], [MEMORY_META] 분리)."""
        return parse_summary_response(response_text)

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
            log_event=print,
        )
    
    def _is_japanese(self, text: str) -> bool:
        """일본어 텍스트인지 확인"""
        return is_japanese(text)
    
    def clear_context(self):
        """대화 컨텍스트 초기화 - 새로운 Chat 세션 생성"""
        self.chat = self._create_chat_session()
        self._last_runtime_prompt_signature = self._runtime_prompt_signature()
        print("[LLM] Chat session reset")

    def _get_item_role(self, item) -> str:
        """히스토리 아이템에서 role 값을 안전하게 추출한다."""
        if item is None:
            return ""
        if isinstance(item, dict):
            return str(item.get("role", "")).lower()
        role = getattr(item, "role", "")
        return str(role).lower()

    def rollback_last_assistant_turn(self) -> bool:
        """
        리롤 직전 턴(user+assistant)을 롤백한 히스토리로 chat 세션을 재구성한다.
        끝부분이 [user, model] 형태일 때만 안전하게 롤백하고,
        모호한 히스토리 구조에서는 실패로 반환해 리롤을 중단하게 한다.
        """
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
            print(f"[LLM] rollback skipped: unexpected tail role '{last_role}'")
            return False

        # 마지막 assistant/model 제거
        trimmed_history.pop()

        # 직전 user 제거 (같은 user 입력 재전송 시 누적 방지)
        if not trimmed_history:
            print("[LLM] rollback skipped: missing user turn before assistant")
            return False
        last_user_role = self._get_item_role(trimmed_history[-1])
        if last_user_role != "user":
            print(f"[LLM] rollback skipped: expected user before assistant, got '{last_user_role}'")
            return False
        trimmed_history.pop()

        try:
            self.chat = self._create_chat_session(history=trimmed_history)
            print("[LLM] rollback_last_assistant_turn: success (user+assistant rolled back)")
            return True
        except Exception as e:
            print(f"[LLM] rollback_last_assistant_turn failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def rebuild_context_from_conversation(self, conversation_buffer: list) -> bool:
        """
        Bridge의 conversation_buffer를 기반으로 chat 세션을 재구성한다.
        SDK history 접근이 비어있는 환경에서 리롤 폴백 용도로 사용한다.
        """
        try:
            history = []
            for item in conversation_buffer or []:
                if not item or len(item) < 2:
                    continue
                role = str(item[0]).strip().lower()
                raw_content = str(item[1]) if item[1] is not None else ""
                timestamp = str(item[2]).strip() if len(item) >= 3 and item[2] else ""
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
            print(f"[LLM] rebuild_context_from_conversation: success ({len(history)} turns)")
            return True
        except Exception as e:
            print(f"[LLM] rebuild_context_from_conversation failed: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def get_conversation_history(self):
        """대화 내역 반환"""
        # Chat 세션에서 히스토리를 가져올 수 있다면 반환
        if hasattr(self.chat, 'history'):
            try:
                return list(self.chat.history)
            except Exception:
                return self.chat.history
        return []
