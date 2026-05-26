"""
Gemini 외 공급자용 HTTP 기반 LLM 클라이언트.
OpenAI 호환, Anthropic, Ollama 경로를 제공한다.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

import requests

from ..conversation_format import prepend_message_time
from .memory_context_builder import build_memory_context as build_common_memory_context
from .persona_names import resolve_prompt_persona_names
from .prompt import build_runtime_system_prompt, get_parseable_emotions
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
from .runtime_prompt_settings import build_runtime_prompt_settings_source
from .summary_prompt import build_summary_prompt, build_summary_prompt_from_text
DEFAULT_GENERATION_PARAMS = {
    "temperature": 0.9,
    "top_p": 1.0,
    "max_tokens": 2048,
}

LLM_RESPONSE_TUPLE = Tuple[str, str, str | None, List[Dict], Dict[str, str], List[Dict], str, Dict[str, str], List[Dict]]


def _parse_summary_memory_meta_lines(meta_lines: list[str]) -> dict:
    """요약 응답의 MEMORY_META 줄을 정규화된 딕셔너리로 변환한다."""
    return parse_summary_memory_meta(meta_lines)


def _build_summary_prompt(conversation_text: str) -> str:
    """HTTP 공급자 공통 요약 프롬프트를 생성한다."""
    return build_summary_prompt_from_text(conversation_text).prompt


def _extract_error_detail(response) -> str:
    try:
        data = response.json()
    except Exception:
        data = None

    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = data.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()

    text = getattr(response, "text", "")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ""


def _raise_for_status_with_detail(response, provider_name: str) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        detail = _extract_error_detail(response)
        if detail:
            raise requests.HTTPError(f"{exc} | {provider_name}: {detail}", response=response) from exc
        raise


def _normalize_generation_params(params: dict | None) -> dict:
    normalized = dict(DEFAULT_GENERATION_PARAMS)
    if not isinstance(params, dict):
        return normalized

    try:
        normalized["temperature"] = max(0.0, min(2.0, float(params.get("temperature", normalized["temperature"]))))
    except (TypeError, ValueError):
        pass

    try:
        normalized["top_p"] = max(0.0, min(1.0, float(params.get("top_p", normalized["top_p"]))))
    except (TypeError, ValueError):
        pass

    try:
        normalized["max_tokens"] = max(0, int(params.get("max_tokens", normalized["max_tokens"])))
    except (TypeError, ValueError):
        pass

    return normalized


class _CommonMixin:
    def _runtime_prompt_settings_source(self):
        """현재 선제 대화 쿨다운 상태를 반영한 프롬프트 설정을 반환한다."""
        return build_runtime_prompt_settings_source(
            getattr(self, "settings", None),
            proactive_manager=getattr(self, "proactive_manager", None),
        )

    def _empty_text_fallback_response(self) -> LLM_RESPONSE_TUPLE:
        return "음... 무슨 일이 있었나봐요.", "confused", None, [], {}, [], "", {}, []

    def _parse_response_with_empty_fallback(self, response_text: str) -> LLM_RESPONSE_TUPLE:
        if not str(response_text or "").strip():
            return self._empty_text_fallback_response()
        return self._parse_response(response_text)

    def _assistant_history_content_for_response(self, response_text: str, parsed_payload: LLM_RESPONSE_TUPLE) -> str:
        raw_text = str(response_text or "").strip()
        if raw_text:
            return response_text
        return str(parsed_payload[0] or "")

    def _prompt_language(self) -> str:
        return resolve_prompt_language(settings_source=getattr(self, "settings", None))

    def _build_summary_prompt_for_messages(self, messages: list) -> str:
        language = self._prompt_language()
        names = resolve_prompt_persona_names(settings_source=getattr(self, "settings", None), language=language)
        return build_summary_prompt(
            messages,
            user_profile=getattr(self, "user_profile", None),
            language=language,
            assistant_name=names.assistant,
            user_name=names.user,
        ).prompt

    def _remember_turn(self, user_content, assistant_content) -> None:
        self._history.append({"role": "user", "content": user_content})
        self._history.append({"role": "assistant", "content": assistant_content})

    def _to_openai_input_content(self, content) -> list[dict]:
        items = []
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    items.append({"type": "input_text", "text": str(part.get("text", ""))})
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url", {}) or {}
                    url = image_url.get("url")
                    if url:
                        items.append({"type": "input_image", "detail": "auto", "image_url": str(url)})
        if items:
            return items
        return [{"type": "input_text", "text": str(content)}]

    def _to_google_parts_from_history(self, content) -> list[dict]:
        if isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if text is not None:
                    parts.append({"text": str(text)})
                    continue
                inline_data = part.get("inlineData")
                if isinstance(inline_data, dict) and inline_data.get("data"):
                    parts.append(
                        {
                            "inlineData": {
                                "mimeType": str(inline_data.get("mimeType", "image/png")),
                                "data": str(inline_data.get("data", "")),
                            }
                        }
                    )
            if parts:
                return parts
        return [{"text": str(content)}]

    def _to_anthropic_blocks_from_history(self, content) -> list[dict]:
        if isinstance(content, list):
            blocks = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    blocks.append({"type": "text", "text": str(block.get("text", ""))})
                    continue
                if block.get("type") == "image":
                    source = block.get("source", {}) or {}
                    if source.get("data"):
                        blocks.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": str(source.get("type", "base64")),
                                    "media_type": str(source.get("media_type", "image/png")),
                                    "data": str(source.get("data", "")),
                                },
                            }
                        )
            if blocks:
                return blocks
        return [{"type": "text", "text": str(content)}]

    def _to_ollama_message_from_history(self, item: dict) -> dict:
        role = str(item.get("role", "user"))
        content = item.get("content", "")
        if role == "user" and isinstance(content, dict):
            message = {"role": role, "content": str(content.get("content", ""))}
            images = [str(image) for image in (content.get("images") or []) if image]
            if images:
                message["images"] = images
            return message
        return {"role": role, "content": str(content)}

    def _parse_analysis_lines(self, raw_block: str) -> Dict[str, str]:
        """analysis 메타 블록의 key=value 줄을 파싱한다."""
        return parse_analysis_lines(raw_block)

    def _extract_analysis_block(self, response_text: str) -> Tuple[str, Dict[str, str]]:
        """응답의 analysis 블록 또는 상단 메타 줄을 분리한다."""
        return extract_analysis_block(response_text)

    def _extract_thought_block(self, response_text: str) -> Tuple[str, str]:
        """응답 본문에서 에네의 짧은 속마음 블록을 분리한다."""
        return extract_thought_metadata(response_text)

    def _extract_goal_update_block(self, response_text: str) -> Tuple[str, Dict[str, str]]:
        """응답 본문에서 목표 업데이트 메타데이터 블록을 분리한다."""
        return extract_goal_update_metadata(response_text)

    def _extract_legacy_japanese_tts_lines(self, text: str) -> Tuple[str, str | None]:
        """구형 일본어 TTS 줄을 표시 텍스트와 분리한다."""
        return extract_legacy_japanese_tts_lines(text)

    def _extract_tts_text(self, text: str) -> Tuple[str, str | None]:
        """명시적 TTS 블록 또는 설정 언어에 따라 TTS용 텍스트를 분리한다."""
        return extract_tts_text(text, settings_source=getattr(self, "settings", None))

    def _build_diary_markdown_prompt(self, message: str, memory_context: str) -> str:
        return build_markdown_document_prompt(
            message,
            memory_context=memory_context,
            language=self._prompt_language(),
        )

    async def generate_markdown_document(self, message: str) -> str:
        memory_context = await self._build_memory_context(message)
        diary_prompt = self._build_diary_markdown_prompt(message, memory_context)
        response_text = self._request_one_shot_raw(diary_prompt, include_sub_prompt=False)
        return (response_text or "").strip()

    async def generate_diary_completion_reply(
        self,
        context_message: str,
    ) -> LLM_RESPONSE_TUPLE:
        response_text = self._request_one_shot_raw(context_message, include_sub_prompt=True)
        return self._parse_response(response_text)

    async def generate_note_command_plan(self, context_message: str) -> str:
        memory_context = await self._build_memory_context(context_message)
        enhanced = f"{memory_context}\n\n{context_message}" if memory_context else context_message
        response_text = self._request_one_shot_raw(enhanced, include_sub_prompt=False)
        return (response_text or "").strip()

    async def generate_note_execution_report(
        self,
        context_message: str,
    ) -> LLM_RESPONSE_TUPLE:
        response_text = self._request_one_shot_raw(context_message, include_sub_prompt=True)
        return self._parse_response(response_text)

    def _parse_response(self, response_text: str) -> LLM_RESPONSE_TUPLE:
        return parse_llm_response(
            response_text,
            settings_source=getattr(self, "settings", None),
            available_emotions=get_parseable_emotions(),
        )

    def _parse_summary_response(self, response_text: str) -> tuple[str, list[str], list[str], dict]:
        return parse_summary_response(response_text)

    def _is_japanese(self, text: str) -> bool:
        return is_japanese(text)

    async def _build_memory_context(
        self,
        query: str,
        recent_context: str = "",
        head_pat_count_before_message: int | None = None,
    ) -> str:
        return await build_common_memory_context(
            self,
            query,
            recent_context=recent_context,
            head_pat_count_before_message=head_pat_count_before_message,
        )

    def _messages_for_openai(self, user_content, include_sub_prompt: bool = True):
        messages = [{
            "role": "system",
            "content": build_runtime_system_prompt(
                include_sub_prompt=include_sub_prompt,
                include_analysis_appendix=True,
                settings_source=self._runtime_prompt_settings_source(),
            ),
        }]
        messages.extend(self._history)
        messages.append({"role": "user", "content": user_content})
        return messages

    def clear_context(self):
        self._history = []

    def _get_item_role(self, item) -> str:
        if isinstance(item, dict):
            return str(item.get("role", "")).lower()
        return str(getattr(item, "role", "")).lower()

    def rollback_last_assistant_turn(self) -> bool:
        if len(self._history) < 2:
            return False
        if self._get_item_role(self._history[-1]) != "assistant":
            return False
        if self._get_item_role(self._history[-2]) != "user":
            return False
        self._history = self._history[:-2]
        return True

    def rebuild_context_from_conversation(self, conversation_buffer: list) -> bool:
        try:
            rebuilt = []
            for item in conversation_buffer or []:
                if not item or len(item) < 2:
                    continue
                role = str(item[0]).strip().lower()
                raw_content = str(item[1]) if item[1] is not None else ""
                timestamp = str(item[2]).strip() if len(item) >= 3 and item[2] else ""
                content = prepend_message_time(raw_content, timestamp)
                if role == "assistant":
                    rebuilt.append({"role": "assistant", "content": content})
                elif role == "user":
                    rebuilt.append({"role": "user", "content": content})
            self._history = rebuilt
            return True
        except Exception:
            return False

    def get_conversation_history(self):
        return list(self._history)


