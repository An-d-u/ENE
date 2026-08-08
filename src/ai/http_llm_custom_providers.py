from __future__ import annotations

import requests
from .http_llm_common import (
    HTTPFinalRequestDescriptor,
    HTTPStructuredOneShotRequestDescriptor,
    HTTPStructuredOneShotResponse,
    LLM_RESPONSE_TUPLE,
    _CommonMixin,
    _normalize_generation_params,
    _post_with_safe_errors,
    _raise_for_status_with_detail,
    _thaw_transport_value,
    normalize_one_shot_usage,
)
from .response_protocol import (
    LLMRequestKind,
    OneShotGenerationResult,
    ResponseMode,
    ResponseStatus,
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
        self.provider_name = "custom_api"
        self.wire_format = "google_cloud"
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

    def _life_record_headers(self):
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-goog-api-key"] = self.api_key
        return headers

    @staticmethod
    def _life_record_endpoint(
        endpoint: str,
        model_name: str,
    ) -> str:
        resolved = endpoint.replace("{model}", model_name)
        if "{model}" not in endpoint and ":generateContent" not in resolved:
            return (
                resolved.rstrip("/")
                + f"/v1beta/models/{model_name}:generateContent"
            )
        return resolved

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
        *,
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ) -> str:
        context = (
            request_descriptor.context
            if request_descriptor is not None
            else self._build_request_context(
                message,
                provider_format="google_cloud",
                request_kind=LLMRequestKind.FINAL_REPLY,
                include_sub_prompt=include_sub_prompt,
                attachments_metadata=self._image_context_metadata(images_data),
            )
        )
        generation_params = context.generation_params
        if request_descriptor is not None and request_descriptor.attempt.phase == "repair":
            images_data = None
        contents = []
        for h in context.history:
            role = "model" if h.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": self._to_google_parts_from_history(h.get("content", ""))})
        contents.append({"role": "user", "parts": self._to_parts(context.user_content, images_data)})
        payload = {
            "contents": contents,
            "generation_config": {
                "temperature": generation_params["temperature"],
                "topP": generation_params["top_p"],
            },
            "systemInstruction": {
                "parts": [{
                    "text": context.system_prompt
                }]
            },
        }
        if generation_params["max_tokens"] > 0:
            payload["generation_config"]["maxOutputTokens"] = generation_params["max_tokens"]
        timeout = request_descriptor.timeout_seconds if request_descriptor is not None else 60
        response = _post_with_safe_errors(self.provider_name, self._endpoint(), requests.post, headers=self._headers(), json=payload, timeout=timeout)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        candidates = data.get("candidates", []) or []
        for cand in candidates:
            content = cand.get("content", {}) or {}
            for part in content.get("parts", []) or []:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    def _request_one_shot_raw(
        self,
        message: str,
        *,
        request_kind: LLMRequestKind,
        include_sub_prompt: bool = True,
    ) -> str:
        context = self._build_request_context(
            message,
            provider_format="google_cloud_one_shot",
            request_kind=request_kind,
            include_sub_prompt=include_sub_prompt,
            include_history=False,
        )
        payload = {
            "contents": [{"role": "user", "parts": [{"text": str(context.user_content)}]}],
            "generation_config": {
                "temperature": self.generation_params["temperature"],
                "topP": self.generation_params["top_p"],
            },
            "systemInstruction": {
                "parts": [{
                    "text": context.system_prompt
                }]
            },
        }
        if self.generation_params["max_tokens"] > 0:
            payload["generation_config"]["maxOutputTokens"] = self.generation_params["max_tokens"]
        response = _post_with_safe_errors(self.provider_name, self._endpoint(), requests.post, headers=self._headers(), json=payload, timeout=60)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        candidates = data.get("candidates", []) or []
        for cand in candidates:
            content = cand.get("content", {}) or {}
            for part in content.get("parts", []) or []:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        return ""

    def _request_google_life_record(
        self,
        descriptor: HTTPStructuredOneShotRequestDescriptor,
    ) -> HTTPStructuredOneShotResponse:
        request = descriptor.request
        generation_params = _thaw_transport_value(request.generation_params)
        schema = _thaw_transport_value(request.schema)
        headers = _thaw_transport_value(descriptor.headers)
        generation_config = {
            "temperature": generation_params["temperature"],
            "topP": generation_params["top_p"],
        }
        if generation_params["max_tokens"] > 0:
            generation_config["maxOutputTokens"] = generation_params["max_tokens"]
        if descriptor.response_mode is ResponseMode.JSON_SCHEMA:
            generation_config["responseFormat"] = {
                "text": {
                    "mimeType": "application/json",
                    "schema": schema,
                }
            }
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": request.prompt}],
                }
            ],
            "generation_config": generation_config,
            "systemInstruction": {
                "parts": [{"text": request.system_instruction}]
            },
        }
        response = _post_with_safe_errors(
            descriptor.profile.provider,
            self._life_record_endpoint(
                descriptor.profile.endpoint,
                descriptor.profile.model,
            ),
            requests.post,
            headers=headers,
            json=payload,
            timeout=descriptor.timeout_seconds,
        )
        _raise_for_status_with_detail(response, descriptor.profile.provider)
        data = response.json()
        candidates = data.get("candidates", []) or []
        candidate = (
            candidates[0]
            if candidates and isinstance(candidates[0], dict)
            else {}
        )
        content = candidate.get("content")
        if not isinstance(content, dict):
            content = {}
        text = "\n".join(
            part.get("text", "")
            for part in content.get("parts", []) or []
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        ).strip()
        finish_reason = str(
            candidate.get("finishReason", "") or ""
        ).strip().lower()
        prompt_feedback = data.get("promptFeedback")
        block_reason = (
            str(prompt_feedback.get("blockReason", "") or "").strip().lower()
            if isinstance(prompt_feedback, dict)
            else ""
        )
        if block_reason or finish_reason in {
            "safety",
            "recitation",
            "prohibited_content",
        }:
            status = ResponseStatus.REFUSAL
            finish_reason = finish_reason or block_reason
        elif finish_reason not in {"", "stop"}:
            status = ResponseStatus.INCOMPLETE
        elif text:
            status = ResponseStatus.COMPLETE
        else:
            status = ResponseStatus.EMPTY
        return HTTPStructuredOneShotResponse(
            text=text,
            status=status,
            finish_reason=finish_reason,
            usage=normalize_one_shot_usage(
                data.get("usageMetadata"),
                input_key="promptTokenCount",
                output_key="candidatesTokenCount",
                total_key="totalTokenCount",
            ),
        )

    async def generate_life_record_once(
        self,
        prompt: str,
    ) -> OneShotGenerationResult:
        """Google generateContent 형식으로 생활 기록을 한 번 생성한다."""
        return await self._generate_life_record_once(
            prompt,
            self._request_google_life_record,
        )

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
        history_parts = self._to_parts(message, images_data)
        return self._execute_final_response(
            lambda descriptor: self._request_google(
                descriptor.context.user_content,
                images_data=images_data,
                request_descriptor=descriptor,
            ),
            user_content=enhanced,
            history_user_content=history_parts,
            provider_format=self.wire_format,
            attachments_metadata=self._image_context_metadata(images_data),
        )

    def send_message(self, message: str, history_user_content: str | None = None) -> LLM_RESPONSE_TUPLE:
        return self._execute_final_response(
            lambda descriptor: self._request_google(
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
        self.provider_name = "custom_api"
        self.wire_format = "cohere"
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

    def _request_cohere(
        self,
        message: str,
        include_sub_prompt: bool = True,
        *,
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ) -> str:
        context = (
            request_descriptor.context
            if request_descriptor is not None
            else self._build_request_context(
                message,
                provider_format="cohere",
                request_kind=LLMRequestKind.FINAL_REPLY,
                include_sub_prompt=include_sub_prompt,
            )
        )
        generation_params = context.generation_params
        chat_history = []
        preamble = context.system_prompt
        for h in context.history:
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
            "message": context.user_content,
            "chat_history": chat_history,
            "preamble": preamble,
            "temperature": generation_params["temperature"],
            "p": generation_params["top_p"],
        }
        if generation_params["max_tokens"] > 0:
            payload["max_tokens"] = generation_params["max_tokens"]

        timeout = request_descriptor.timeout_seconds if request_descriptor is not None else 60
        response = _post_with_safe_errors(self.provider_name, self.endpoint, requests.post, headers=self._headers(), json=payload, timeout=timeout)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        text = data.get("text")
        if isinstance(text, str):
            return text.strip()
        return ""

    def _request_one_shot_raw(
        self,
        message: str,
        *,
        request_kind: LLMRequestKind,
        include_sub_prompt: bool = True,
    ) -> str:
        context = self._build_request_context(
            message,
            provider_format="cohere_one_shot",
            request_kind=request_kind,
            include_sub_prompt=include_sub_prompt,
            include_history=False,
        )
        payload = {
            "model": self.model_name,
            "message": context.user_content,
            "chat_history": [],
            "preamble": context.system_prompt,
            "temperature": self.generation_params["temperature"],
            "p": self.generation_params["top_p"],
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_tokens"] = self.generation_params["max_tokens"]
        response = _post_with_safe_errors(self.provider_name, self.endpoint, requests.post, headers=self._headers(), json=payload, timeout=60)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        text = data.get("text")
        if isinstance(text, str):
            return text.strip()
        return ""

    def _request_cohere_life_record(
        self,
        descriptor: HTTPStructuredOneShotRequestDescriptor,
    ) -> HTTPStructuredOneShotResponse:
        request = descriptor.request
        generation_params = _thaw_transport_value(request.generation_params)
        schema = _thaw_transport_value(request.schema)
        headers = _thaw_transport_value(descriptor.headers)
        payload = {
            "model": descriptor.profile.model,
            "message": request.prompt,
            "chat_history": [],
            "preamble": request.system_instruction,
            "temperature": generation_params["temperature"],
            "p": generation_params["top_p"],
        }
        if generation_params["max_tokens"] > 0:
            payload["max_tokens"] = generation_params["max_tokens"]
        if descriptor.response_mode is ResponseMode.JSON_SCHEMA:
            payload["response_format"] = {
                "type": "json_object",
                "schema": schema,
            }
        response = _post_with_safe_errors(
            descriptor.profile.provider,
            descriptor.profile.endpoint,
            requests.post,
            headers=headers,
            json=payload,
            timeout=descriptor.timeout_seconds,
        )
        _raise_for_status_with_detail(response, descriptor.profile.provider)
        data = response.json()
        raw_text = data.get("text")
        text = raw_text.strip() if isinstance(raw_text, str) else ""
        finish_reason = str(
            data.get("finish_reason", "") or ""
        ).strip().lower()
        if finish_reason in {"error_toxic", "safety", "refusal"}:
            status = ResponseStatus.REFUSAL
        elif finish_reason not in {"", "complete", "stop", "end_turn"}:
            status = ResponseStatus.INCOMPLETE
        elif text:
            status = ResponseStatus.COMPLETE
        else:
            status = ResponseStatus.EMPTY
        meta = data.get("meta")
        billed_units = (
            meta.get("billed_units")
            if isinstance(meta, dict)
            else None
        )
        return HTTPStructuredOneShotResponse(
            text=text,
            status=status,
            finish_reason=finish_reason,
            usage=normalize_one_shot_usage(
                billed_units,
                input_key="input_tokens",
                output_key="output_tokens",
            ),
        )

    async def generate_life_record_once(
        self,
        prompt: str,
    ) -> OneShotGenerationResult:
        """Cohere Chat 형식으로 생활 기록을 한 번 생성한다."""
        return await self._generate_life_record_once(
            prompt,
            self._request_cohere_life_record,
        )

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
        return self.send_message(enhanced, history_user_content=message)

    def send_message(self, message: str, history_user_content: str | None = None) -> LLM_RESPONSE_TUPLE:
        return self._execute_final_response(
            lambda descriptor: self._request_cohere(
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
