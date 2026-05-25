from __future__ import annotations

import requests

from .prompt import build_runtime_system_prompt
from .http_llm_common import (
    DEFAULT_GENERATION_PARAMS,
    LLM_RESPONSE_TUPLE,
    _CommonMixin,
    _normalize_generation_params,
    _raise_for_status_with_detail,
)


class OllamaClient(_CommonMixin):
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

    def _request_ollama(
        self,
        message: str,
        images_data: list | None = None,
        include_sub_prompt: bool = True,
    ) -> str:
        messages = [{
            "role": "system",
            "content": build_runtime_system_prompt(
                include_sub_prompt=include_sub_prompt,
                include_analysis_appendix=True,
                settings_source=self.settings,
            ),
        }]
        for item in self._history:
            messages.append(self._to_ollama_message_from_history(item))
        user_msg = {"role": "user", "content": message}
        if images_data:
            images = []
            for img in images_data:
                data_url = img.get("dataUrl", "")
                if data_url and "," in data_url:
                    _, b64 = data_url.split(",", 1)
                    images.append(b64)
            if images:
                user_msg["images"] = images
        messages.append(user_msg)
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": self.generation_params["temperature"],
                "top_p": self.generation_params["top_p"],
            },
        }
        if self.generation_params["max_tokens"] > 0:
            payload["options"]["num_predict"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return str(data.get("message", {}).get("content", "")).strip()

    def _request_one_shot_raw(self, message: str, include_sub_prompt: bool = True) -> str:
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": build_runtime_system_prompt(
                        include_sub_prompt=include_sub_prompt,
                        include_analysis_appendix=True,
                        settings_source=self.settings,
                    ),
                },
                {"role": "user", "content": str(message)},
            ],
            "stream": False,
            "options": {
                "temperature": self.generation_params["temperature"],
                "top_p": self.generation_params["top_p"],
            },
        }
        if self.generation_params["max_tokens"] > 0:
            payload["options"]["num_predict"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return str(data.get("message", {}).get("content", "")).strip()

    async def send_message_with_memory(
        self,
        message: str,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        search_query = str(memory_search_text or "").strip() or message
        primary_query = str(latest_user_message or "").strip() or search_query
        support_context = str(recent_memory_context or "").strip()
        memory_context = await self._build_memory_context(
            primary_query,
            recent_context=support_context,
            head_pat_count_before_message=head_pat_count_before_message,
        )
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        return self.send_message(enhanced)

    async def send_message_with_images(
        self,
        message: str,
        images_data: list,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        search_query = str(memory_search_text or "").strip() or message
        primary_query = str(latest_user_message or "").strip() or search_query
        support_context = str(recent_memory_context or "").strip()
        memory_context = await self._build_memory_context(
            primary_query,
            recent_context=support_context,
            head_pat_count_before_message=head_pat_count_before_message,
        )
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        raw_response_text = self._request_ollama(enhanced, images_data=images_data)
        clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        user_content = {"content": enhanced}
        images = []
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if data_url and "," in data_url:
                _, b64 = data_url.split(",", 1)
                images.append(b64)
        if images:
            user_content["images"] = images
        self._remember_turn(user_content, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update)))
        return clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update

    def send_message(self, message: str) -> LLM_RESPONSE_TUPLE:
        raw_response_text = self._request_ollama(message)
        clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(message, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update)))
        return clean_text, emotion, tts_text, events, analysis, promises, thought, goal_update

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str], list[str], dict]:
        prompt = self._build_summary_prompt_for_messages(messages)
        response_text = self._request_one_shot_raw(prompt)
        return self._parse_summary_response(response_text)
