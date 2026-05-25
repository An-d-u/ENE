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


class GoogleCloudClient(_CommonMixin):
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
        self.endpoint = endpoint or "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.ene_profile = ene_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.goal_manager = goal_manager
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []

    def _endpoint(self) -> str:
        endpoint = self.endpoint.replace("{model}", self.model_name)
        if "{model}" not in self.endpoint and ":generateContent" not in endpoint:
            endpoint = endpoint.rstrip("/") + f"/v1beta/models/{self.model_name}:generateContent"
        if self.api_key and "key=" not in endpoint:
            sep = "&" if "?" in endpoint else "?"
            endpoint = f"{endpoint}{sep}key={self.api_key}"
        return endpoint

    def _headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key and "key=" in self.endpoint:
            headers["x-goog-api-key"] = self.api_key
        return headers

    def _to_parts(self, message: str, images_data: list | None = None) -> list[dict]:
        parts = [{"text": message}]
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if not data_url or "," not in data_url:
                continue
            header, b64 = data_url.split(",", 1)
            media_type = "image/png"
            if ":" in header and ";" in header:
                media_type = header.split(":", 1)[1].split(";", 1)[0]
            parts.append({"inlineData": {"mimeType": media_type, "data": b64}})
        return parts

    def _request_google(
        self,
        message: str,
        images_data: list | None = None,
        include_sub_prompt: bool = True,
    ) -> str:
        contents = []
        for h in self._history:
            role = "model" if h.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": self._to_google_parts_from_history(h.get("content", ""))})
        contents.append({"role": "user", "parts": self._to_parts(message, images_data)})
        payload = {
            "contents": contents,
            "generation_config": {
                "temperature": self.generation_params["temperature"],
                "topP": self.generation_params["top_p"],
            },
            "systemInstruction": {
                "parts": [{
                    "text": build_runtime_system_prompt(
                        include_sub_prompt=include_sub_prompt,
                        include_analysis_appendix=True,
                        settings_source=self.settings,
                    )
                }]
            },
        }
        if self.generation_params["max_tokens"] > 0:
            payload["generation_config"]["maxOutputTokens"] = self.generation_params["max_tokens"]
        response = requests.post(self._endpoint(), headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", []) or []
        for cand in candidates:
            content = cand.get("content", {}) or {}
            for part in content.get("parts", []) or []:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    def _request_one_shot_raw(self, message: str, include_sub_prompt: bool = True) -> str:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": str(message)}]}],
            "generation_config": {
                "temperature": self.generation_params["temperature"],
                "topP": self.generation_params["top_p"],
            },
            "systemInstruction": {
                "parts": [{
                    "text": build_runtime_system_prompt(
                        include_sub_prompt=include_sub_prompt,
                        include_analysis_appendix=True,
                        settings_source=self.settings,
                    )
                }]
            },
        }
        if self.generation_params["max_tokens"] > 0:
            payload["generation_config"]["maxOutputTokens"] = self.generation_params["max_tokens"]
        response = requests.post(self._endpoint(), headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        candidates = data.get("candidates", []) or []
        for cand in candidates:
            content = cand.get("content", {}) or {}
            for part in content.get("parts", []) or []:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

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
        user_parts = self._to_parts(enhanced, images_data)
        raw_response_text = self._request_google(enhanced, images_data=images_data)
        clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(user_parts, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update)))
        return clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update

    def send_message(self, message: str) -> LLM_RESPONSE_TUPLE:
        raw_response_text = self._request_google(message)
        clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(message, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update)))
        return clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str], list[str], dict]:
        prompt = self._build_summary_prompt_for_messages(messages)
        response_text = self._request_one_shot_raw(prompt)
        return self._parse_summary_response(response_text)


class CohereClient(_CommonMixin):
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
        self.endpoint = endpoint or "https://api.cohere.com/v1/chat"
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
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request_cohere(self, message: str, include_sub_prompt: bool = True) -> str:
        chat_history = []
        preamble = build_runtime_system_prompt(
            include_sub_prompt=include_sub_prompt,
            include_analysis_appendix=True,
            settings_source=self.settings,
        )
        for h in self._history:
            role = str(h.get("role", "user"))
            content = str(h.get("content", ""))
            if role == "assistant":
                chat_history.append({"role": "CHATBOT", "message": content})
            elif role == "system":
                chat_history.append({"role": "SYSTEM", "message": content})
            else:
                chat_history.append({"role": "USER", "message": content})

        payload = {
            "model": self.model_name,
            "message": message,
            "chat_history": chat_history,
            "preamble": preamble,
            "temperature": self.generation_params["temperature"],
            "p": self.generation_params["top_p"],
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_tokens"] = self.generation_params["max_tokens"]

        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        text = data.get("text")
        if isinstance(text, str):
            return text.strip()
        return ""

    def _request_one_shot_raw(self, message: str, include_sub_prompt: bool = True) -> str:
        payload = {
            "model": self.model_name,
            "message": message,
            "chat_history": [],
            "preamble": build_runtime_system_prompt(
                include_sub_prompt=include_sub_prompt,
                include_analysis_appendix=True,
                settings_source=self.settings,
            ),
            "temperature": self.generation_params["temperature"],
            "p": self.generation_params["top_p"],
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_tokens"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        text = data.get("text")
        if isinstance(text, str):
            return text.strip()
        return ""

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
        return self.send_message(enhanced)

    def send_message(self, message: str) -> LLM_RESPONSE_TUPLE:
        raw_response_text = self._request_cohere(message)
        clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(message, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update)))
        return clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str], list[str], dict]:
        prompt = self._build_summary_prompt_for_messages(messages)
        response_text = self._request_one_shot_raw(prompt)
        return self._parse_summary_response(response_text)


