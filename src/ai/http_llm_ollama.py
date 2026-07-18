from __future__ import annotations

import requests
from .http_llm_common import (
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
        self.provider_name = "ollama"
        self.wire_format = "ollama"
        self.memory_manager = memory_manager
        self.user_profile = user_profile
        self.ene_profile = ene_profile
        self.settings = settings
        self.calendar_manager = calendar_manager
        self.mood_manager = mood_manager
        self.goal_manager = goal_manager
        self.generation_params = _normalize_generation_params(generation_params)
        self._history = []

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

    def _provider_response_from_data(
        self,
        data: dict,
        request_descriptor: HTTPFinalRequestDescriptor,
    ) -> ProviderResponse:
        carrier = str(data.get("message", {}).get("content", "")).strip()
        done_reason = str(data.get("done_reason", "") or "").strip().lower()
        done = data.get("done")
        complete_reason = done_reason in {"", "stop"}
        if done is False or not complete_reason:
            status = ResponseStatus.INCOMPLETE
        elif carrier:
            status = ResponseStatus.COMPLETE
        else:
            status = ResponseStatus.EMPTY
        return ProviderResponse(
            carrier=carrier,
            status=status,
            mode=request_descriptor.attempt.mode,
            finish_reason=done_reason,
        )

    def _request_ollama(
        self,
        message: str,
        images_data: list | None = None,
        include_sub_prompt: bool = True,
        *,
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ) -> str | ProviderResponse:
        context = (
            request_descriptor.context
            if request_descriptor is not None
            else self._build_request_context(
                message,
                provider_format="ollama",
                request_kind=LLMRequestKind.FINAL_REPLY,
                include_sub_prompt=include_sub_prompt,
                attachments_metadata=self._image_context_metadata(images_data),
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
        if request_descriptor is not None and request_descriptor.attempt.phase == "repair":
            images_data = None
        messages = [{
            "role": "system",
            "content": context.system_prompt,
        }]
        for item in context.history:
            messages.append(self._to_ollama_message_from_history(item))
        user_msg = {"role": "user", "content": context.user_content}
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
                "temperature": generation_params["temperature"],
                "top_p": generation_params["top_p"],
            },
        }
        if generation_params["max_tokens"] > 0:
            payload["options"]["num_predict"] = generation_params["max_tokens"]
        if (
            request_descriptor is not None
            and request_descriptor.attempt.mode is ResponseMode.JSON_SCHEMA
            and context.request_kind is LLMRequestKind.FINAL_REPLY
            and request_descriptor.schema is not None
        ):
            payload["format"] = request_descriptor.schema
        timeout = request_descriptor.timeout_seconds if request_descriptor is not None else 60
        response = requests.post(self.endpoint, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        if request_descriptor is None:
            return str(data.get("message", {}).get("content", "")).strip()
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
            provider_format="ollama_one_shot",
            request_kind=request_kind,
            include_sub_prompt=include_sub_prompt,
            include_history=False,
        )
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": context.system_prompt,
                },
                {"role": "user", "content": str(context.user_content)},
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
        user_content = {"content": message}
        images = []
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if data_url and "," in data_url:
                _, b64 = data_url.split(",", 1)
                images.append(b64)
        if images:
            user_content["images"] = images
        return self._execute_final_response(
            lambda descriptor: self._request_ollama(
                descriptor.context.user_content,
                images_data=images_data,
                request_descriptor=descriptor,
            ),
            user_content=enhanced,
            history_user_content=user_content,
            provider_format=self.wire_format,
            attachments_metadata=self._image_context_metadata(images_data),
        )

    def send_message(self, message: str, history_user_content: str | None = None) -> LLM_RESPONSE_TUPLE:
        return self._execute_final_response(
            lambda descriptor: self._request_ollama(
                descriptor.context.user_content,
                request_descriptor=descriptor,
            ),
            user_content=message,
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
