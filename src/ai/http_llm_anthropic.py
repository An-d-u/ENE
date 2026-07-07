from __future__ import annotations

import requests
from .http_llm_common import (
    DEFAULT_GENERATION_PARAMS,
    LLM_RESPONSE_TUPLE,
    _CommonMixin,
    _normalize_generation_params,
)
class AnthropicClient(_CommonMixin):
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        endpoint: str,
        memory_manager=None,
        user_profile=None,
        ene_profile=None,
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        goal_manager=None,
        generation_params: dict | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.endpoint = endpoint
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.ene_profile = ene_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.goal_manager = goal_manager
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []

    def _headers(self):
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _request_anthropic(self, user_content_blocks: list[dict], include_sub_prompt: bool = True) -> str:
        context = self._build_request_context(
            user_content_blocks,
            provider_format="anthropic",
            include_sub_prompt=include_sub_prompt,
        )
        messages = []
        for h in context.history:
            role = h.get("role", "user")
            content = h.get("content", "")
            messages.append({"role": role, "content": self._to_anthropic_blocks_from_history(content)})
        messages.append({"role": "user", "content": context.user_content})
        payload = {
            "model": self.model_name,
            "max_tokens": max(1, self.generation_params["max_tokens"] or DEFAULT_GENERATION_PARAMS["max_tokens"]),
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
            "system": context.system_prompt,
            "messages": messages,
        }
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        text_parts = [p.get("text", "") for p in data.get("content", []) if p.get("type") == "text"]
        return "\n".join(text_parts).strip()

    def _request_one_shot_raw(self, message: str, include_sub_prompt: bool = True) -> str:
        context = self._build_request_context(
            message,
            provider_format="anthropic_one_shot",
            include_sub_prompt=include_sub_prompt,
            include_history=False,
        )
        payload = {
            "model": self.model_name,
            "max_tokens": max(1, self.generation_params["max_tokens"] or DEFAULT_GENERATION_PARAMS["max_tokens"]),
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
            "system": context.system_prompt,
            "messages": [{"role": "user", "content": [{"type": "text", "text": str(context.user_content)}]}],
        }
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        text_parts = [p.get("text", "") for p in data.get("content", []) if p.get("type") == "text"]
        return "\n".join(text_parts).strip()

    async def send_message_with_memory(
        self,
        message: str,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
    ) -> LLM_RESPONSE_TUPLE:
        enhanced = await self._build_contextual_message(
            message,
            memory_search_text=memory_search_text,
            latest_user_message=latest_user_message,
            recent_memory_context=recent_memory_context,
            head_pat_count_before_message=head_pat_count_before_message,
            progress_callback=progress_callback,
        )
        return self.send_message(enhanced, history_user_content=message)

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
        enhanced = await self._build_contextual_message(
            message,
            memory_search_text=memory_search_text,
            latest_user_message=latest_user_message,
            recent_memory_context=recent_memory_context,
            head_pat_count_before_message=head_pat_count_before_message,
            progress_callback=progress_callback,
        )
        blocks = [{"type": "text", "text": enhanced}]
        history_blocks = [{"type": "text", "text": message}]
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if not data_url or "," not in data_url:
                continue
            header, b64_data = data_url.split(",", 1)
            media_type = "image/png"
            if ":" in header and ";" in header:
                media_type = header.split(":", 1)[1].split(";", 1)[0]
            blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64_data},
                }
            )
            history_blocks.append(
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": b64_data},
                }
            )
        raw_response_text = self._request_anthropic(blocks)
        clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(history_blocks, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture)))
        return clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture

    def send_message(self, message: str, history_user_content: str | None = None) -> LLM_RESPONSE_TUPLE:
        raw_response_text = self._request_anthropic([{"type": "text", "text": message}])
        clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(history_user_content if history_user_content is not None else message, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture)))
        return clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update, proactive_conversations, gesture

    async def summarize_conversation(
        self,
        messages: list,
        loaded_topic_memory_context: str = "",
    ) -> tuple[str, list[str], list[str], dict, list]:
        return self._summarize_conversation_from_messages(
            messages,
            loaded_topic_memory_context=loaded_topic_memory_context,
        )
