"""
Gemini 외 공급자용 HTTP 기반 LLM 클라이언트.
OpenAI 호환, Anthropic, Ollama 경로를 제공한다.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

import requests

from .prompt import get_system_prompt


DEFAULT_GENERATION_PARAMS = {
    "temperature": 0.9,
    "top_p": 1.0,
    "max_tokens": 2048,
}


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
    def _parse_response(self, response_text: str) -> Tuple[str, str, str, List[Dict]]:
        try:
            from .llm_client import GeminiClient
            return GeminiClient._parse_response(self, response_text)
        except Exception:
            events = []
            event_pattern = r"\[이벤트([^\]]+)\]"
            event_matches = re.findall(event_pattern, response_text)
            for match in event_matches:
                parts = [p.strip() for p in match.split("|")]
                if len(parts) >= 2:
                    events.append(
                        {
                            "date": parts[0],
                            "title": parts[1],
                            "description": parts[2] if len(parts) > 2 else "",
                        }
                    )
            response_text = re.sub(event_pattern, "", response_text)
            emotion_pattern = r"\[(\w+)\]"
            matches = re.findall(emotion_pattern, response_text)
            clean_text = re.sub(emotion_pattern, "", response_text).strip()
            emotion = "normal"
            for match in matches:
                low = match.lower()
                if low in {"normal", "happy", "sad", "angry", "confused", "shy", "surprised"}:
                    emotion = low
                    break
            return clean_text, emotion, None, events

    def _parse_summary_response(self, response_text: str) -> tuple[str, list[str]]:
        try:
            from .llm_client import GeminiClient
            return GeminiClient._parse_summary_response(self, response_text)
        except Exception:
            summary_lines = []
            user_facts = []
            section = None
            for raw in response_text.split("\n"):
                line = raw.strip()
                if not line:
                    continue
                up = line.upper()
                if up in {"[SUMMARY]", "SUMMARY"}:
                    section = "summary"
                    continue
                if up in {"[MASTER_INFO]", "MASTER_INFO"}:
                    section = "facts"
                    continue
                if section == "summary":
                    summary_lines.append(line.lstrip("- ").strip())
                elif section == "facts" and line.startswith("-"):
                    fact = line.lstrip("- ").strip()
                    if fact.lower() not in {"none", "none."}:
                        user_facts.append(fact)
            summary = " ".join(summary_lines).strip()
            if not summary:
                summary = response_text.strip().split("\n")[0].strip()
            return summary, user_facts

    def _is_japanese(self, text: str) -> bool:
        try:
            from .llm_client import GeminiClient
            return GeminiClient._is_japanese(self, text)
        except Exception:
            ranges = [(0x3040, 0x309F), (0x30A0, 0x30FF), (0x4E00, 0x9FFF)]
            count = 0
            for char in text:
                code = ord(char)
                for start, end in ranges:
                    if start <= code <= end:
                        count += 1
                        break
            return count / len(text) > 0.2 if text else False

    async def _build_memory_context(self, query: str) -> str:
        try:
            from .llm_client import GeminiClient
            return await GeminiClient._build_memory_context(self, query)
        except Exception:
            return ""

    def _messages_for_openai(self, user_content):
        messages = [{"role": "system", "content": get_system_prompt()}]
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
                content = str(item[1]) if item[1] is not None else ""
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
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        extra_headers: dict | None = None,
        generation_params: dict | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.endpoint = endpoint
        self.provider_name = provider_name
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
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

    def _request_openai(self, user_content) -> str:
        payload = {
            "model": self.model_name,
            "messages": self._messages_for_openai(user_content),
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
        if isinstance(content, list):
            return "\n".join([c.get("text", "") for c in content if isinstance(c, dict)]).strip()
        return str(content).strip()

    async def send_message_with_memory(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        return self.send_message(enhanced)

    async def send_message_with_images(self, message: str, images_data: list) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        parts = [{"type": "text", "text": enhanced}]
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})

        response_text = self._request_openai(parts)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": enhanced})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    def send_message(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        response_text = self._request_openai(message)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str]]:
        conversation_text = "\n".join(
            [f"{item[0]}: {item[1]}" if len(item) >= 2 else str(item) for item in messages]
        )
        prompt = f"""아래 대화를 요약하고 사용자 정보를 추출하세요.
[CONVERSATION]
{conversation_text}

[OUTPUT_FORMAT]
[SUMMARY]
- 대화 핵심 요약 1~3문장

[MASTER_INFO]
- 없으면 none
- 있으면 아래 형식:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
"""
        response_text = self._request_openai(prompt)
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
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        generation_params: dict | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.endpoint = endpoint or "https://api.openai.com/v1/responses"
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _input_items(self, user_content) -> list[dict]:
        items = []
        for h in self._history:
            role = str(h.get("role", "user"))
            text = str(h.get("content", ""))
            if role not in {"user", "assistant"}:
                continue
            if role == "assistant":
                items.append(
                    {
                        "type": "message",
                        "status": "complete",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": text, "annotations": []}],
                    }
                )
            else:
                items.append(
                    {
                        "role": "user",
                        "content": [{"type": "input_text", "text": text}],
                    }
                )

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
            "input": self._input_items(user_content),
            "store": False,
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_output_tokens"] = self.generation_params["max_tokens"]
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        return self._extract_text(data)

    async def send_message_with_memory(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        return self.send_message(enhanced)

    async def send_message_with_images(self, message: str, images_data: list) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        parts = [{"type": "text", "text": enhanced}]
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})

        response_text = self._request_responses(parts)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": enhanced})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    def send_message(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        response_text = self._request_responses(message)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str]]:
        conversation_text = "\n".join(
            [f"{item[0]}: {item[1]}" if len(item) >= 2 else str(item) for item in messages]
        )
        prompt = f"""아래 대화를 요약하고 사용자 정보를 추출하세요.
[CONVERSATION]
{conversation_text}

[OUTPUT_FORMAT]
[SUMMARY]
- 대화 핵심 요약 1~3문장

[MASTER_INFO]
- 없으면 none
- 있으면 아래 형식:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
"""
        response_text = self._request_responses(prompt)
        return self._parse_summary_response(response_text)


class MistralClient(OpenAICompatibleClient):
    def _mistral_messages(self, user_content) -> list[dict]:
        source = self._messages_for_openai(user_content)
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

    def _request_openai(self, user_content) -> str:
        payload = {
            "model": self.model_name,
            "messages": self._mistral_messages(user_content),
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


class GoogleCloudClient(_CommonMixin):
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        endpoint: str,
        memory_manager=None,
        user_profile=None,
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        generation_params: dict | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.endpoint = endpoint or "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
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

    def _request_google(self, message: str, images_data: list | None = None) -> str:
        contents = []
        for h in self._history:
            role = "model" if h.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": str(h.get("content", ""))}]})
        contents.append({"role": "user", "parts": self._to_parts(message, images_data)})
        payload = {
            "contents": contents,
            "generation_config": {
                "temperature": self.generation_params["temperature"],
                "topP": self.generation_params["top_p"],
            },
            "systemInstruction": {"parts": [{"text": get_system_prompt()}]},
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

    async def send_message_with_memory(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        return self.send_message(enhanced)

    async def send_message_with_images(self, message: str, images_data: list) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        response_text = self._request_google(enhanced, images_data=images_data)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": enhanced})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    def send_message(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        response_text = self._request_google(message)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str]]:
        conversation_text = "\n".join(
            [f"{item[0]}: {item[1]}" if len(item) >= 2 else str(item) for item in messages]
        )
        prompt = f"""아래 대화를 요약하고 사용자 정보를 추출하세요.
[CONVERSATION]
{conversation_text}

[OUTPUT_FORMAT]
[SUMMARY]
- 대화 핵심 요약 1~3문장

[MASTER_INFO]
- 없으면 none
- 있으면 아래 형식:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
"""
        response_text = self._request_google(prompt)
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
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        generation_params: dict | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.endpoint = endpoint or "https://api.cohere.com/v1/chat"
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _request_cohere(self, message: str) -> str:
        chat_history = []
        preamble = get_system_prompt()
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

    async def send_message_with_memory(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        return self.send_message(enhanced)

    async def send_message_with_images(self, message: str, images_data: list) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        return self.send_message(enhanced)

    def send_message(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        response_text = self._request_cohere(message)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str]]:
        conversation_text = "\n".join(
            [f"{item[0]}: {item[1]}" if len(item) >= 2 else str(item) for item in messages]
        )
        prompt = f"""아래 대화를 요약하고 사용자 정보를 추출하세요.
[CONVERSATION]
{conversation_text}

[OUTPUT_FORMAT]
[SUMMARY]
- 대화 핵심 요약 1~3문장

[MASTER_INFO]
- 없으면 none
- 있으면 아래 형식:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
"""
        response_text = self._request_cohere(prompt)
        return self._parse_summary_response(response_text)


class AnthropicClient(_CommonMixin):
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        endpoint: str,
        memory_manager=None,
        user_profile=None,
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        generation_params: dict | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.endpoint = endpoint
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []

    def _headers(self):
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _request_anthropic(self, user_content_blocks: list[dict]) -> str:
        messages = []
        for h in self._history:
            role = h.get("role", "user")
            content = h.get("content", "")
            messages.append({"role": role, "content": [{"type": "text", "text": str(content)}]})
        messages.append({"role": "user", "content": user_content_blocks})
        payload = {
            "model": self.model_name,
            "max_tokens": max(1, self.generation_params["max_tokens"] or DEFAULT_GENERATION_PARAMS["max_tokens"]),
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
            "system": get_system_prompt(),
            "messages": messages,
        }
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()
        text_parts = [p.get("text", "") for p in data.get("content", []) if p.get("type") == "text"]
        return "\n".join(text_parts).strip()

    async def send_message_with_memory(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        return self.send_message(enhanced)

    async def send_message_with_images(self, message: str, images_data: list) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        blocks = [{"type": "text", "text": enhanced}]
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
        response_text = self._request_anthropic(blocks)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": enhanced})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    def send_message(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        response_text = self._request_anthropic([{"type": "text", "text": message}])
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str]]:
        conversation_text = "\n".join(
            [f"{item[0]}: {item[1]}" if len(item) >= 2 else str(item) for item in messages]
        )
        prompt = f"""아래 대화를 요약하고 사용자 정보를 추출하세요.
[CONVERSATION]
{conversation_text}

[OUTPUT_FORMAT]
[SUMMARY]
- 대화 핵심 요약 1~3문장

[MASTER_INFO]
- 없으면 none
- 있으면 아래 형식:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
"""
        response_text = self._request_anthropic([{"type": "text", "text": prompt}])
        return self._parse_summary_response(response_text)


class OllamaClient(_CommonMixin):
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        endpoint: str,
        memory_manager=None,
        user_profile=None,
        settings=None,
        calendar_manager=None,
        mood_manager=None,
        generation_params: dict | None = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.endpoint = endpoint
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []

    def _request_ollama(self, message: str, images_data: list | None = None) -> str:
        messages = [{"role": "system", "content": get_system_prompt()}]
        messages.extend(self._history)
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

    async def send_message_with_memory(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        return self.send_message(enhanced)

    async def send_message_with_images(self, message: str, images_data: list) -> Tuple[str, str, str, List[Dict]]:
        memory_context = await self._build_memory_context(message)
        enhanced = f"{memory_context}\n\n{message}" if memory_context else message
        response_text = self._request_ollama(enhanced, images_data=images_data)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": enhanced})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    def send_message(self, message: str) -> Tuple[str, str, str, List[Dict]]:
        response_text = self._request_ollama(message)
        clean_text, emotion, japanese_text, events = self._parse_response(response_text)
        self._history.append({"role": "user", "content": message})
        self._history.append({"role": "assistant", "content": clean_text})
        return clean_text, emotion, japanese_text, events

    async def summarize_conversation(self, messages: list) -> tuple[str, list[str]]:
        conversation_text = "\n".join(
            [f"{item[0]}: {item[1]}" if len(item) >= 2 else str(item) for item in messages]
        )
        prompt = f"""아래 대화를 요약하고 사용자 정보를 추출하세요.
[CONVERSATION]
{conversation_text}

[OUTPUT_FORMAT]
[SUMMARY]
- 대화 핵심 요약 1~3문장

[MASTER_INFO]
- 없으면 none
- 있으면 아래 형식:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
"""
        response_text = self._request_ollama(prompt)
        return self._parse_summary_response(response_text)
