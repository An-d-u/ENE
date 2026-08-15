from __future__ import annotations

from typing import Mapping
import requests
from .http_llm_common import (
    HTTPFinalRequestDescriptor,
    HTTPStructuredOneShotRequestDescriptor,
    HTTPStructuredOneShotResponse,
    LLM_RESPONSE_TUPLE,
    _CommonMixin,
    _normalize_generation_params,
    _official_profile_for_endpoint,
    _post_with_safe_errors,
    _raise_for_status_with_detail,
    _thaw_transport_value,
    normalize_one_shot_usage,
)
from .openai_model_policy import normalize_reasoning_effort, resolve_openai_model_policy
from .response_protocol import (
    LLMRequestKind,
    OneShotGenerationResult,
    ProviderResponse,
    ResponseMode,
    ResponseStatus,
)


_OPENROUTER_CHAT_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_JSON_OBJECT_SYSTEM_INSTRUCTION = (
    "Return the final response as a valid JSON object."
)


def _life_record_model_policy_provider(
    descriptor: HTTPStructuredOneShotRequestDescriptor,
) -> str:
    provider = str(descriptor.profile.provider or "").strip().lower()
    if provider != "custom_api":
        return provider
    official = _official_profile_for_endpoint(
        descriptor.profile.wire_format,
        descriptor.profile.endpoint,
    )
    if official is not None and official[0] == "openai":
        return "openai"
    return provider


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
        self.wire_format = str(getattr(type(self), "wire_format", "openai_chat"))
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
        return min(
            cap,
            max(current_tokens + 512, current_tokens * 2),
        )

    def _apply_structured_response_payload(
        self,
        payload: dict,
        request_descriptor: HTTPFinalRequestDescriptor | None,
    ) -> None:
        if (
            request_descriptor is None
            or request_descriptor.context.request_kind is not LLMRequestKind.FINAL_REPLY
            or not request_descriptor.schema_name
            or request_descriptor.schema is None
        ):
            return

        mode = request_descriptor.attempt.mode
        if mode is ResponseMode.JSON_SCHEMA:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request_descriptor.schema_name,
                    "strict": True,
                    "schema": request_descriptor.schema,
                },
            }
            provider_name = str(self.provider_name or "").strip().lower()
            if (
                provider_name == "openrouter"
                or self.endpoint.casefold()
                == _OPENROUTER_CHAT_ENDPOINT.casefold()
            ):
                payload["provider"] = {"require_parameters": True}
            return

        if mode is ResponseMode.JSON_OBJECT:
            payload["response_format"] = {"type": "json_object"}
            messages = payload.get("messages")
            if not isinstance(messages, list):
                return
            for index, message in enumerate(messages):
                if (
                    not isinstance(message, dict)
                    or message.get("role") != "system"
                ):
                    continue
                content = message.get("content")
                if not isinstance(content, str):
                    return
                copied_message = dict(message)
                if _JSON_OBJECT_SYSTEM_INSTRUCTION not in content:
                    copied_message["content"] = (
                        f"{content}\n\n{_JSON_OBJECT_SYSTEM_INSTRUCTION}"
                        if content
                        else _JSON_OBJECT_SYSTEM_INSTRUCTION
                    )
                copied_messages = list(messages)
                copied_messages[index] = copied_message
                payload["messages"] = copied_messages
                return
            return

        if mode is ResponseMode.STRICT_TOOL:
            function_name = f"emit_{request_descriptor.schema_name}"
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "strict": True,
                        "parameters": request_descriptor.schema,
                    },
                }
            ]
            payload["tool_choice"] = {
                "type": "function",
                "function": {"name": function_name},
            }

    @staticmethod
    def _message_content_text(message: dict) -> str:
        content = message.get("content", "")
        if isinstance(content, list):
            return "\n".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            ).strip()
        if content is None:
            return ""
        return str(content).strip()

    @staticmethod
    def _strict_tool_arguments(message: dict, function_name: str) -> str:
        for tool_call in message.get("tool_calls", []) or []:
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get("function")
            if not isinstance(function, dict) or function.get("name") != function_name:
                continue
            arguments = function.get("arguments")
            if isinstance(arguments, str) and arguments.strip():
                return arguments.strip()
        return ""

    def _provider_response_from_chat_data(
        self,
        data: dict,
        request_descriptor: HTTPFinalRequestDescriptor,
    ) -> ProviderResponse:
        choices = data.get("choices", []) or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = choice.get("message")
        if not isinstance(message, dict):
            message = {}
        finish_reason = str(choice.get("finish_reason", "") or "").strip().lower()
        refusal = message.get("refusal")
        if refusal is not None:
            return ProviderResponse(
                carrier=str(refusal or "").strip(),
                status=ResponseStatus.REFUSAL,
                mode=request_descriptor.attempt.mode,
                finish_reason=finish_reason,
            )

        if request_descriptor.attempt.mode is ResponseMode.STRICT_TOOL:
            carrier = self._strict_tool_arguments(
                message,
                f"emit_{request_descriptor.schema_name}",
            )
        else:
            carrier = self._message_content_text(message)

        complete_finish_reasons = {"", "stop", "tool_calls", "function_call"}
        if finish_reason not in complete_finish_reasons:
            status = ResponseStatus.INCOMPLETE
        elif carrier:
            status = ResponseStatus.COMPLETE
        else:
            status = ResponseStatus.EMPTY
        return ProviderResponse(
            carrier=carrier,
            status=status,
            mode=request_descriptor.attempt.mode,
            finish_reason=finish_reason,
        )

    def _request_openai_life_record(
        self,
        descriptor: HTTPStructuredOneShotRequestDescriptor,
    ) -> HTTPStructuredOneShotResponse:
        request = descriptor.request
        generation_params = _thaw_transport_value(request.generation_params)
        schema = _thaw_transport_value(request.schema)
        headers = _thaw_transport_value(descriptor.headers)
        policy = resolve_openai_model_policy(
            _life_record_model_policy_provider(descriptor),
            descriptor.profile.model,
        )
        payload = {
            "model": descriptor.profile.model,
            "messages": [
                {
                    "role": (
                        "developer"
                        if policy.supports_reasoning_effort
                        else "system"
                    ),
                    "content": request.system_instruction,
                },
                {"role": "user", "content": request.prompt},
            ],
            "stream": False,
        }
        if descriptor.response_mode is ResponseMode.JSON_SCHEMA:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.schema_id,
                    "strict": True,
                    "schema": schema,
                },
            }
        if policy.supports_temperature:
            payload["temperature"] = generation_params["temperature"]
        if policy.supports_top_p:
            payload["top_p"] = generation_params["top_p"]
        if policy.supports_reasoning_effort:
            payload["reasoning_effort"] = normalize_reasoning_effort(
                generation_params.get("reasoning_effort"),
                default=policy.default_reasoning_effort,
                allowed_efforts=policy.allowed_reasoning_efforts,
            )
        if generation_params["max_tokens"] > 0:
            token_field = (
                "max_completion_tokens"
                if policy.supports_reasoning_effort
                else "max_tokens"
            )
            payload[token_field] = generation_params["max_tokens"]
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
        choices = data.get("choices", []) or []
        choice = choices[0] if choices and isinstance(choices[0], dict) else {}
        message = choice.get("message")
        if not isinstance(message, dict):
            message = {}
        finish_reason = str(choice.get("finish_reason", "") or "").strip().lower()
        refusal = message.get("refusal")
        if refusal is not None:
            text = str(refusal or "").strip()
            status = ResponseStatus.REFUSAL
        else:
            text = self._message_content_text(message)
            if finish_reason not in {"", "stop", "tool_calls", "function_call"}:
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
                data.get("usage"),
                input_key="prompt_tokens",
                output_key="completion_tokens",
            ),
        )

    async def generate_life_record_once(
        self,
        prompt: str,
    ) -> OneShotGenerationResult:
        """OpenAI Chat native JSON schema로 생활 기록을 한 번 생성한다."""
        return await self._generate_life_record_once(
            prompt,
            self._request_openai_life_record,
        )

    def _request_openai(
        self,
        user_content,
        include_sub_prompt: bool = True,
        *,
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ) -> str | ProviderResponse:
        generation_params = dict(
            request_descriptor.context.generation_params
            if request_descriptor is not None
            else self.generation_params
        )
        if (
            request_descriptor is not None
            and request_descriptor.attempt.expand_output_budget
        ):
            generation_params["max_tokens"] = self._expanded_output_token_budget(
                generation_params.get("max_tokens")
            )
        payload = {
            "model": self.model_name,
            "messages": self._messages_for_openai(
                user_content,
                include_sub_prompt=include_sub_prompt,
                request_descriptor=request_descriptor,
            ),
            "temperature": generation_params["temperature"],
            "top_p": generation_params["top_p"],
            "stream": False,
        }
        if generation_params["max_tokens"] > 0:
            payload["max_tokens"] = generation_params["max_tokens"]
        self._apply_structured_response_payload(payload, request_descriptor)
        timeout = request_descriptor.timeout_seconds if request_descriptor is not None else 60
        response = _post_with_safe_errors(self.provider_name, self.endpoint, requests.post, headers=self._headers(), json=payload, timeout=timeout)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        if request_descriptor is None:
            choices = data.get("choices", []) or []
            choice = choices[0] if choices and isinstance(choices[0], dict) else {}
            message = choice.get("message")
            return self._message_content_text(message if isinstance(message, dict) else {})
        return self._provider_response_from_chat_data(data, request_descriptor)

    def _request_one_shot_raw(
        self,
        user_content,
        *,
        request_kind: LLMRequestKind,
        include_sub_prompt: bool = True,
    ) -> str:
        context = self._build_request_context(
            user_content,
            provider_format="openai_chat_one_shot",
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
                {"role": "user", "content": context.user_content},
            ],
            "temperature": self.generation_params["temperature"],
            "top_p": self.generation_params["top_p"],
            "stream": False,
        }
        if self.generation_params["max_tokens"] > 0:
            payload["max_tokens"] = self.generation_params["max_tokens"]
        response = _post_with_safe_errors(self.provider_name, self.endpoint, requests.post, headers=self._headers(), json=payload, timeout=60)
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
        progress_callback=None,
        include_life_record_context: bool = False,
        *,
        mood_event_context: Mapping[str, str] | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        enhanced = await self._build_contextual_message(
            message,
            memory_search_text=memory_search_text,
            latest_user_message=latest_user_message,
            recent_memory_context=recent_memory_context,
            head_pat_count_before_message=head_pat_count_before_message,
            include_life_record_context=include_life_record_context,
            progress_callback=progress_callback,
        )
        return self.send_message(
            enhanced,
            history_user_content=message,
            mood_event_context=mood_event_context,
        )

    async def send_message_with_images(
        self,
        message: str,
        images_data: list,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
        include_life_record_context: bool = False,
        *,
        mood_event_context: Mapping[str, str] | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        enhanced = await self._build_contextual_message(
            message,
            memory_search_text=memory_search_text,
            latest_user_message=latest_user_message,
            recent_memory_context=recent_memory_context,
            head_pat_count_before_message=head_pat_count_before_message,
            include_life_record_context=include_life_record_context,
            progress_callback=progress_callback,
        )
        parts = [{"type": "text", "text": enhanced}]
        history_parts = [{"type": "text", "text": message}]
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
                history_parts.append({"type": "image_url", "image_url": {"url": data_url}})

        return self._execute_final_response(
            lambda descriptor: self._request_openai(
                descriptor.context.user_content,
                request_descriptor=descriptor,
            ),
            user_content=parts,
            history_user_content=history_parts,
            provider_format=self.wire_format,
            mood_event_context=mood_event_context,
        )

    def send_message(
        self,
        message: str,
        history_user_content: str | None = None,
        *,
        mood_event_context: Mapping[str, str] | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        return self._execute_final_response(
            lambda descriptor: self._request_openai(
                descriptor.context.user_content,
                request_descriptor=descriptor,
            ),
            user_content=message,
            history_user_content=(
                history_user_content if history_user_content is not None else message
            ),
            provider_format=self.wire_format,
            mood_event_context=mood_event_context,
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


class OpenAIResponseAPIClient(_CommonMixin):
    def __init__(
        self,
        *,
        api_key: str,
        model_name: str,
        endpoint: str = "https://api.openai.com/v1/responses",
        provider_name: str = "openai",
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
        self.provider_name = str(provider_name or "openai").strip().lower()
        self.wire_format = "openai_responses"

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _input_items(self, user_content, history: list[dict] | None = None) -> list[dict]:
        items = []
        for h in (self._history if history is None else history):
            role = str(h.get("role", "user"))
            content = h.get("content", "")
            if role not in {"user", "assistant"}:
                continue
            if role == "assistant":
                items.append(
                    {
                        "type": "message",
                        "status": "completed",
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
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content", []) or []:
                if not isinstance(part, dict) or part.get("type") != "output_text":
                    continue
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()
        return ""

    def _extract_refusal(self, data: dict) -> str | None:
        for item in data.get("output", []) or []:
            if not isinstance(item, dict):
                continue
            for part in item.get("content", []) or []:
                if not isinstance(part, dict) or part.get("type") != "refusal":
                    continue
                refusal = part.get("refusal")
                if isinstance(refusal, str):
                    return refusal.strip()
                return ""
        return None

    def _provider_response_from_data(
        self,
        data: dict,
        *,
        mode: ResponseMode,
    ) -> ProviderResponse:
        carrier = self._extract_text(data)
        refusal = self._extract_refusal(data)
        top_status = str(data.get("status", "") or "").strip().lower()
        output_items = [
            item
            for item in data.get("output", []) or []
            if isinstance(item, dict)
        ]
        item_statuses = [
            str(item.get("status", "") or "").strip().lower()
            for item in output_items
        ]
        finish_reason = ""
        detail_candidates = [data.get("incomplete_details")]
        detail_candidates.extend(
            item.get("incomplete_details") for item in output_items
        )
        for details in detail_candidates:
            if not isinstance(details, dict):
                continue
            reason = str(details.get("reason", "") or "").strip()
            if reason:
                finish_reason = reason
                break

        if refusal is not None:
            return ProviderResponse(
                carrier=refusal,
                status=ResponseStatus.REFUSAL,
                mode=mode,
                finish_reason=finish_reason,
            )

        nonterminal_status = next(
            (
                status
                for status in [top_status, *item_statuses]
                if status and status != "completed"
            ),
            "",
        )
        if nonterminal_status:
            return ProviderResponse(
                carrier=carrier,
                status=ResponseStatus.INCOMPLETE,
                mode=mode,
                finish_reason=finish_reason or nonterminal_status,
            )
        return ProviderResponse(
            carrier=carrier,
            status=ResponseStatus.COMPLETE if carrier else ResponseStatus.EMPTY,
            mode=mode,
            finish_reason=finish_reason,
        )

    def _request_responses_life_record(
        self,
        descriptor: HTTPStructuredOneShotRequestDescriptor,
    ) -> HTTPStructuredOneShotResponse:
        request = descriptor.request
        generation_params = _thaw_transport_value(request.generation_params)
        schema = _thaw_transport_value(request.schema)
        headers = _thaw_transport_value(descriptor.headers)
        payload = {
            "model": descriptor.profile.model,
            "instructions": request.system_instruction,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": request.prompt}
                    ],
                }
            ],
            "store": False,
        }
        if descriptor.response_mode is ResponseMode.JSON_SCHEMA:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_id,
                    "strict": True,
                    "schema": schema,
                }
            }
        policy = resolve_openai_model_policy(
            _life_record_model_policy_provider(descriptor),
            descriptor.profile.model,
        )
        if policy.supports_temperature:
            payload["temperature"] = generation_params["temperature"]
        if policy.supports_top_p:
            payload["top_p"] = generation_params["top_p"]
        if policy.supports_reasoning_effort:
            payload["reasoning"] = {
                "effort": normalize_reasoning_effort(
                    generation_params.get("reasoning_effort"),
                    default=policy.default_reasoning_effort,
                    allowed_efforts=policy.allowed_reasoning_efforts,
                )
            }
        if generation_params["max_tokens"] > 0:
            payload["max_output_tokens"] = generation_params["max_tokens"]
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
        provider_response = self._provider_response_from_data(
            data,
            mode=descriptor.response_mode,
        )
        return HTTPStructuredOneShotResponse(
            text=provider_response.carrier,
            status=provider_response.status,
            finish_reason=provider_response.finish_reason,
            usage=normalize_one_shot_usage(
                data.get("usage"),
                input_key="input_tokens",
                output_key="output_tokens",
            ),
        )

    async def generate_life_record_once(
        self,
        prompt: str,
    ) -> OneShotGenerationResult:
        """OpenAI Responses native JSON schema로 생활 기록을 한 번 생성한다."""
        return await self._generate_life_record_once(
            prompt,
            self._request_responses_life_record,
        )

    def _response_output_token_cap(self) -> int:
        model_name = str(self.model_name or "").strip().lower()
        known_caps = {
            "gpt-4o": 16384,
            "gpt-4o-mini": 16384,
        }
        return known_caps.get(model_name, 8192)

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

    def _apply_generation_payload(self, payload: dict, generation_params: dict | None = None) -> None:
        params = generation_params or self.generation_params
        policy = resolve_openai_model_policy(self.provider_name, self.model_name)
        if policy.supports_temperature:
            payload["temperature"] = params["temperature"]
        if policy.supports_top_p:
            payload["top_p"] = params["top_p"]
        if policy.supports_reasoning_effort:
            payload["reasoning"] = {
                "effort": normalize_reasoning_effort(
                    params.get("reasoning_effort"),
                    default=policy.default_reasoning_effort,
                )
            }
        if params["max_tokens"] > 0:
            payload["max_output_tokens"] = params["max_tokens"]

    def _request_responses(
        self,
        user_content,
        *,
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ) -> str | ProviderResponse:
        context = (
            request_descriptor.context
            if request_descriptor is not None
            else self._build_request_context(
                user_content,
                provider_format="openai_responses",
                request_kind=LLMRequestKind.FINAL_REPLY,
            )
        )
        payload = {
            "model": self.model_name,
            "instructions": context.system_prompt,
            "input": self._input_items(context.user_content, history=context.history),
            "store": False,
        }
        if (
            request_descriptor is not None
            and request_descriptor.attempt.mode is ResponseMode.JSON_SCHEMA
            and context.request_kind is LLMRequestKind.FINAL_REPLY
            and request_descriptor.schema_name
            and request_descriptor.schema is not None
        ):
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request_descriptor.schema_name,
                    "strict": True,
                    "schema": request_descriptor.schema,
                }
            }
        generation_params = dict(context.generation_params)
        if (
            request_descriptor is not None
            and request_descriptor.attempt.expand_output_budget
        ):
            generation_params["max_tokens"] = self._expanded_output_token_budget(
                generation_params.get("max_tokens")
            )
        self._apply_generation_payload(payload, generation_params)
        timeout = request_descriptor.timeout_seconds if request_descriptor is not None else 60
        response = _post_with_safe_errors(self.provider_name, self.endpoint, requests.post, headers=self._headers(), json=payload, timeout=timeout)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        if request_descriptor is None:
            return self._extract_text(data)
        return self._provider_response_from_data(
            data,
            mode=request_descriptor.attempt.mode,
        )

    def _request_one_shot_raw(
        self,
        user_content,
        *,
        request_kind: LLMRequestKind,
        include_sub_prompt: bool = True,
    ) -> str:
        context = self._build_request_context(
            user_content,
            provider_format="openai_responses_one_shot",
            request_kind=request_kind,
            include_sub_prompt=include_sub_prompt,
            include_history=False,
        )
        user_item = {"role": "user", "content": []}
        if isinstance(context.user_content, list):
            for part in context.user_content:
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
            user_item["content"].append({"type": "input_text", "text": str(context.user_content)})

        payload = {
            "model": self.model_name,
            "instructions": context.system_prompt,
            "input": [user_item],
            "store": False,
        }
        self._apply_generation_payload(payload)
        response = _post_with_safe_errors(self.provider_name, self.endpoint, requests.post, headers=self._headers(), json=payload, timeout=60)
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
        progress_callback=None,
        include_life_record_context: bool = False,
        *,
        mood_event_context: Mapping[str, str] | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        enhanced = await self._build_contextual_message(
            message,
            memory_search_text=memory_search_text,
            latest_user_message=latest_user_message,
            recent_memory_context=recent_memory_context,
            head_pat_count_before_message=head_pat_count_before_message,
            include_life_record_context=include_life_record_context,
            progress_callback=progress_callback,
        )
        return self.send_message(
            enhanced,
            history_user_content=message,
            mood_event_context=mood_event_context,
        )

    async def send_message_with_images(
        self,
        message: str,
        images_data: list,
        memory_search_text: str | None = None,
        latest_user_message: str | None = None,
        recent_memory_context: str | None = None,
        head_pat_count_before_message: int | None = None,
        progress_callback=None,
        include_life_record_context: bool = False,
        *,
        mood_event_context: Mapping[str, str] | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        enhanced = await self._build_contextual_message(
            message,
            memory_search_text=memory_search_text,
            latest_user_message=latest_user_message,
            recent_memory_context=recent_memory_context,
            head_pat_count_before_message=head_pat_count_before_message,
            include_life_record_context=include_life_record_context,
            progress_callback=progress_callback,
        )
        parts = [{"type": "text", "text": enhanced}]
        history_parts = [{"type": "text", "text": message}]
        for img in images_data or []:
            data_url = img.get("dataUrl", "")
            if data_url:
                parts.append({"type": "image_url", "image_url": {"url": data_url}})
                history_parts.append({"type": "image_url", "image_url": {"url": data_url}})

        return self._execute_final_response(
            lambda descriptor: self._request_responses(
                descriptor.context.user_content,
                request_descriptor=descriptor,
            ),
            user_content=parts,
            history_user_content=history_parts,
            provider_format=self.wire_format,
            mood_event_context=mood_event_context,
        )

    def send_message(
        self,
        message: str,
        history_user_content: str | None = None,
        *,
        mood_event_context: Mapping[str, str] | None = None,
    ) -> LLM_RESPONSE_TUPLE:
        return self._execute_final_response(
            lambda descriptor: self._request_responses(
                descriptor.context.user_content,
                request_descriptor=descriptor,
            ),
            user_content=message,
            history_user_content=(
                history_user_content if history_user_content is not None else message
            ),
            provider_format=self.wire_format,
            mood_event_context=mood_event_context,
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


class MistralClient(OpenAICompatibleClient):
    wire_format = "mistral"

    def _mistral_messages(
        self,
        user_content,
        include_sub_prompt: bool = True,
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ) -> list[dict]:
        source = self._messages_for_openai(
            user_content,
            include_sub_prompt=include_sub_prompt,
            provider_format="mistral",
            request_descriptor=request_descriptor,
        )
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

    def _request_openai(
        self,
        user_content,
        include_sub_prompt: bool = True,
        *,
        request_descriptor: HTTPFinalRequestDescriptor | None = None,
    ) -> str:
        generation_params = (
            request_descriptor.context.generation_params
            if request_descriptor is not None
            else self.generation_params
        )
        payload = {
            "model": self.model_name,
            "messages": self._mistral_messages(
                user_content,
                include_sub_prompt=include_sub_prompt,
                request_descriptor=request_descriptor,
            ),
            "safe_prompt": False,
            "temperature": generation_params["temperature"],
            "top_p": generation_params["top_p"],
            "stream": False,
        }
        if generation_params["max_tokens"] > 0:
            payload["max_tokens"] = generation_params["max_tokens"]
        timeout = request_descriptor.timeout_seconds if request_descriptor is not None else 60
        response = _post_with_safe_errors(self.provider_name, self.endpoint, requests.post, headers=self._headers(), json=payload, timeout=timeout)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return str(content).strip()

    def _request_one_shot_raw(
        self,
        user_content,
        *,
        request_kind: LLMRequestKind,
        include_sub_prompt: bool = True,
    ) -> str:
        context = self._build_request_context(
            user_content,
            provider_format="mistral_one_shot",
            request_kind=request_kind,
            include_sub_prompt=include_sub_prompt,
            include_history=False,
        )
        content = str(context.user_content)
        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": context.system_prompt,
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
        response = _post_with_safe_errors(self.provider_name, self.endpoint, requests.post, headers=self._headers(), json=payload, timeout=60)
        _raise_for_status_with_detail(response, self.provider_name)
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return str(content).strip()
