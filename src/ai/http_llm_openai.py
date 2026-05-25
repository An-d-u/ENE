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


class OpenAICompatibleClient(_CommonMixin):
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        endpoint: str,
        provider_name: str,
        memory_manager=None,
        user_profile=None,
        ene_profile=None,
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        goal_manager=None,
        extra_headers: dict | None = None,
        generation_params: dict | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.endpoint = endpoint
        self.provider_name = provider_name
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.ene_profile = ene_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.goal_manager = goal_manager
        self.extra_headers = extra_headers or {}
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []

    def _headers(self):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        return headers

    def _request_openai(self, user_content, include_sub_prompt: bool = True) -> str:
        payload = {
            "model": self.model_name,
            "messages": self._messages_for_openai(user_content, include_sub_prompt=include_sub_prompt),
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
            "stream": False,
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_tokens"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            return "\n".join([c.get("text", "") for c in content if isinstance(c, dict)]).strip()
        return str(content).strip()

    def _request_one_shot_raw(self, user_content, include_sub_prompt: bool = True) -> str:
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
                {"role": "user", "content": user_content},
            ],
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
            "stream": False,
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_tokens"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            return "\n".join([c.get("text", "") for c in content if isinstance(c, dict)]).strip()
        return str(content).strip()

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
        parts = [{"type": "text", "text": enhanced}]
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})

        raw_response_text = self._request_openai(parts)
        clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(parts, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update)))
        return clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update

    def send_message(self, message: str) -> LLM_RESPONSE_TUPLE:
        raw_response_text = self._request_openai(message)
        clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(message, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update)))
        return clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str], list[str], dict]:
        prompt = self._build_summary_prompt_for_messages(messages)
        response_text = self._request_one_shot_raw(prompt)
        return self._parse_summary_response(response_text)


class OpenAIResponseAPIClient(_CommonMixin):
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
        self.endpoint = endpoint or "https://api.openai.com/v1/responses"
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.ene_profile = ene_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.goal_manager = goal_manager
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []
        self.provider_name = "openai"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _input_items(self, user_content) -> list[dict]:
        items = []
        for h in self._history:
            role = str(h.get("role", "user"))
            content = h.get("content", "")
            if role not in {"user", "assistant"}:
                continue
            if role == "assistant":
                items.append(
                    {
                        "type": "message",
                        "status": "complete",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": str(content), "annotations": []}],
                    }
                )
            else:
                items.append(
                    {
                        "role": "user",
                        "content": self._to_openai_input_content(content),
                    }
                )

        user_item = {"role": "user", "content": self._to_openai_input_content(user_content)}
        items.append(user_item)
        return items

    def _extract_text(self, data: dict) -> str:
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content", []) or []:
                if not isinstance(part, dict):
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    def _request_responses(self, user_content) -> str:
        payload = {
            "model": self.model_name,
            "instructions": build_runtime_system_prompt(
                include_sub_prompt=True,
                include_analysis_appendix=True,
                settings_source=self.settings,
            ),
            "input": self._input_items(user_content),
            "store": False,
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_output_tokens"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        return self._extract_text(data)

    def _request_one_shot_raw(self, user_content, include_sub_prompt: bool = True) -> str:
        user_item = {"role": "user", "content": []}
        if isinstance(user_content, list):
            for part in user_content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    user_item["content"].append({"type": "input_text", "text": str(part.get("text", ""))})
                elif part.get("type") == "image_url":
                    image_url = part.get("image_url", {}) or {}
                    url = image_url.get("url")
                    if url:
                        user_item["content"].append({"type": "input_image", "detail": "auto", "image_url": url})
        else:
            user_item["content"].append({"type": "input_text", "text": str(user_content)})

        payload = {
            "model": self.model_name,
            "instructions": build_runtime_system_prompt(
                include_sub_prompt=include_sub_prompt,
                include_analysis_appendix=True,
                settings_source=self.settings,
            ),
            "input": [user_item],
            "store": False,
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_output_tokens"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        return self._extract_text(data)

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
        parts = [{"type": "text", "text": enhanced}]
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})

        raw_response_text = self._request_responses(parts)
        clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        self._remember_turn(parts, self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update)))
        return clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update

    def send_message(self, message: str) -> LLM_RESPONSE_TUPLE:
        raw_response_text = self._request_responses(message)
        clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update = self._parse_response_with_empty_fallback(raw_response_text)
        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": self._assistant_history_content_for_response(raw_response_text, (clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update))})
        return clean_text, emotion, japanese_text, events, analysis, promises, thought, goal_update

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str], list[str], dict]:
        prompt = self._build_summary_prompt_for_messages(messages)
        response_text = self._request_one_shot_raw(prompt)
        return self._parse_summary_response(response_text)


class MistralClient(OpenAICompatibleClient):
    def _mistral_messages(self, user_content, include_sub_prompt: bool = True) -> list[dict]:
        source = self._messages_for_openai(user_content, include_sub_prompt=include_sub_prompt)
        reformatted = []
        for idx, msg in enumerate(source):
            role = str(msg.get("role", "user"))
            content = msg.get("content", "")
            if isinstance(content, list):
                text_parts = [str(p.get("text", "")) for p in content if isinstance(p, dict)]
                content = "\n".join([t for t in text_parts if t]).strip()
            content = str(content)

            if idx == 0:
                if role in {"user", "system"}:
                    reformatted.append({"role": role, "content": content})
                else:
                    reformatted.append({"role": "system", "content": f"{role}: {content}"})
                continue

            prev = reformatted[-1] if reformatted else None
            if prev and prev.get("role") == role:
                prev["content"] = f"{prev.get('content', '')}\n{content}".strip()
                continue
            if role == "system":
                if prev and prev.get("role") == "user":
                    prev["content"] = f"{prev.get('content', '')}\nSystem:{content}".strip()
                else:
                    reformatted.append({"role": "user", "content": f"System:{content}"})
            elif role in {"function", "tool"}:
                reformatted.append({"role": "user", "content": content})
            else:
                reformatted.append({"role": role, "content": content})
        return reformatted

    def _request_openai(self, user_content, include_sub_prompt: bool = True) -> str:
        payload = {
            "model": self.model_name,
            "messages": self._mistral_messages(user_content, include_sub_prompt=include_sub_prompt),
            "safe_prompt": False,
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
            "stream": False,
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_tokens"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return str(content).strip()

    def _request_one_shot_raw(self, user_content, include_sub_prompt: bool = True) -> str:
        content = str(user_content)
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
                {"role": "user", "content": content},
            ],
            "safe_prompt": False,
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
            "stream": False,
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_tokens"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return str(content).strip()


