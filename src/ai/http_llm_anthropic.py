from __future__ import annotations

import requests
from .http_llm_common import (
    DEFAULT_GENERATION_PARAMS,
    HTTPFinalRequestDescriptor,
    LLM_RESPONSE_TUPLE,
    _CommonMixin,
    _normalize_generation_params,
)
from .response_protocol import (
    LLMRequestKind,
    ProviderResponse,
    ResponseMode,
    ResponseStatus,
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
        self.provider_name = "anthropic"
        self.wire_format = "anthropic"
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

    def _response_output_token_cap(self) -> int:
        return 8192

    def _expanded_output_token_budget(self, current: object) -> int:
        try:
            current_tokens = max(0, int(current or 0))
        except (TypeError, ValueError):
            current_tokens = 0
        cap = self._response_output_token_cap()
        if current_tokens <= 0:
            return cap
        if current_tokens >= cap:
            return current_tokens
        return min(cap, max(current_tokens + 512, current_tokens * 2))

    @staticmethod
    def _response_text(data: dict) -> str:
        text_parts = [
            part.get("text", "")
            for part in data.get("content", [])
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        return "\n".join(text_parts).strip()

    def _provider_response_from_data(
        self,
        data: dict,
        request_descriptor: HTTPFinalRequestDescriptor,
    ) -> ProviderResponse:
        carrier = self._response_text(data)
        stop_reason = str(data.get("stop_reason", "") or "").strip().lower()
        if stop_reason == "refusal":
            status = ResponseStatus.REFUSAL
        elif stop_reason == "max_tokens":
            status = ResponseStatus.INCOMPLETE
        elif stop_reason not in {"", "end_turn", "stop_sequence"}:
            status = ResponseStatus.INCOMPLETE
        elif carrier:
            status = ResponseStatus.COMPLETE
        else:
            status = ResponseStatus.EMPTY
        return ProviderResponse(
            carrier=carrier,
            status=status,
            mode=request_descriptor.attempt.mode,
            finish_reason=stop_reason,
        )

    def _request_anthropic(
        self,
        user_content_blocks: list[dict],
        include_sub_prompt: bool = True,
        *,
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ) -> str | ProviderResponse:
        context = (
            request_descriptor.context
            if request_descriptor is not None
            else self._build_request_context(
                user_content_blocks,
                provider_format="anthropic",
                request_kind=LLMRequestKind.FINAL_REPLY,
                include_sub_prompt=include_sub_prompt,
            )
        )
        generation_params = dict(context.generation_params)
        if (
            request_descriptor is not None
            and request_descriptor.attempt.phase == "regenerate"
            and request_descriptor.attempt.expand_output_budget
        ):
            generation_params["max_tokens"] = self._expanded_output_token_budget(
                generation_params.get("max_tokens")
            )
        messages = []
        for h in context.history:
            role = h.get("role", "user")
            content = h.get("content", "")
            messages.append({"role": role, "content": self._to_anthropic_blocks_from_history(content)})
        current_content = context.user_content
        if not isinstance(current_content, list):
            current_content = [{"type": "text", "text": str(current_content)}]
        messages.append({"role": "user", "content": current_content})
        payload = {
            "model": self.model_name,
            "max_tokens": max(1, generation_params["max_tokens"] or DEFAULT_GENERATION_PARAMS["max_tokens"]),
            "temperature": generation_params["temperature"],
            "top_p": generation_params["top_p"],
            "system": context.system_prompt,
            "messages": messages,
        }
        if (
            request_descriptor is not None
            and request_descriptor.attempt.mode is ResponseMode.JSON_SCHEMA
            and context.request_kind is LLMRequestKind.FINAL_REPLY
            and request_descriptor.schema is not None
        ):
            payload["output_config"] = {
                "format": {
                    "type": "json_schema",
                    "schema": request_descriptor.schema,
                }
            }
        timeout = request_descriptor.timeout_seconds if request_descriptor is not None else 60
        response = requests.post(self.endpoint, headers=self._headers(), json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if request_descriptor is None:
            return self._response_text(data)
        return self._provider_response_from_data(data, request_descriptor)

    def _request_one_shot_raw(
        self,
        message: str,
        *,
        request_kind: LLMRequestKind,
        include_sub_prompt: bool = True,
    ) -> str:
        context = self._build_request_context(
            message,
            provider_format="anthropic_one_shot",
            request_kind=request_kind,
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
        return self._execute_final_response(
            lambda descriptor: self._request_anthropic(
                descriptor.context.user_content,
                request_descriptor=descriptor,
            ),
            user_content=blocks,
            history_user_content=history_blocks,
            provider_format=self.wire_format,
        )

    def send_message(self, message: str, history_user_content: str | None = None) -> LLM_RESPONSE_TUPLE:
        return self._execute_final_response(
            lambda descriptor: self._request_anthropic(
                descriptor.context.user_content,
                request_descriptor=descriptor,
            ),
            user_content=[{"type": "text", "text": message}],
            history_user_content=(
                history_user_content if history_user_content is not None else message
            ),
            provider_format=self.wire_format,
        )

    async def summarize_conversation(
        self,
        messages: list,
        loaded_topic_memory_context: str = "",
    ) -> tuple[str, list[str], list[str], dict, list]:
        return self._summarize_conversation_from_messages(
            messages,
            loaded_topic_memory_context=loaded_topic_memory_context,
        )
