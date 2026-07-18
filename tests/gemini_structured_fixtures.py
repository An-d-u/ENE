from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace

from src.ai.llm_client import GeminiClient
from tests.structured_response_fixtures import valid_envelope_json


@dataclass
class FakeResponse:
    text: str | None
    finish_reason: str = "STOP"
    prompt_feedback: object | None = None
    usage_metadata: object | None = None

    def __post_init__(self):
        self.candidates = []
        if self.finish_reason:
            self.candidates = [
                SimpleNamespace(
                    finish_reason=self.finish_reason,
                    finish_message="",
                    safety_ratings=[],
                )
            ]


class FakeChat:
    def __init__(self, sdk, history):
        self._sdk = sdk
        self._curated_history = deepcopy(list(history or []))
        self._comprehensive_history = deepcopy(list(history or []))
        self.get_history_calls: list[bool] = []

    def get_history(self, curated=False):
        self.get_history_calls.append(bool(curated))
        if curated:
            return self._curated_history
        return self._comprehensive_history

    def send_message(self, contents, config=None):
        self._sdk.send_message_configs.append(deepcopy(config))
        if isinstance(contents, list):
            parts = []
            for item in contents:
                if isinstance(item, str):
                    parts.append({"text": item})
                else:
                    parts.append({"inline_data": {"synthetic": True}})
        else:
            parts = [{"text": str(contents)}]
        user_item = {"role": "user", "parts": parts}
        self._curated_history.append(deepcopy(user_item))
        self._comprehensive_history.append(deepcopy(user_item))
        response = self._sdk.chat_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if callable(response):
            response = response()
        raw_text = "" if response.text is None else str(response.text)
        model_item = {"role": "model", "parts": [{"text": raw_text}]}
        self._curated_history.append(deepcopy(model_item))
        self._comprehensive_history.append(deepcopy(model_item))
        return response


class FakeChats:
    def __init__(self, sdk):
        self._sdk = sdk

    def create(self, *, model, config, history=None):
        self._sdk.created_histories.append(deepcopy(list(history or [])))
        self._sdk.created_configs.append(deepcopy(config))
        chat = FakeChat(self._sdk, history)
        self._sdk.created_chats.append(chat)
        return chat


class FakeModels:
    def __init__(self, sdk):
        self._sdk = sdk

    def generate_content(self, **kwargs):
        self._sdk.repair_calls.append(deepcopy(kwargs))
        if not self._sdk.repair_responses:
            raise AssertionError("준비된 historyless 합성 응답이 없습니다.")
        response = self._sdk.repair_responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class FakeSdkClient:
    def __init__(self, *, chat_responses, repair_responses=()):
        self.chat_responses = list(chat_responses)
        self.repair_responses = list(repair_responses)
        self.created_histories = []
        self.created_configs = []
        self.created_chats = []
        self.repair_calls = []
        self.send_message_configs = []
        self.chats = FakeChats(self)
        self.models = FakeModels(self)


class GeminiHarness:
    def __init__(self, monkeypatch):
        self.monkeypatch = monkeypatch
        self.sdk: FakeSdkClient | None = None

    @property
    def created_histories(self):
        assert self.sdk is not None
        return self.sdk.created_histories

    @property
    def created_configs(self):
        assert self.sdk is not None
        return self.sdk.created_configs

    @property
    def repair_calls(self):
        assert self.sdk is not None
        return self.sdk.repair_calls

    def response(
        self,
        text: str | None,
        *,
        finish_reason: str = "STOP",
        input_tokens: int = 3,
        output_tokens: int = 5,
    ) -> FakeResponse:
        return FakeResponse(
            text,
            finish_reason=finish_reason,
            usage_metadata=SimpleNamespace(
                prompt_token_count=input_tokens,
                candidates_token_count=output_tokens,
                total_token_count=input_tokens + output_tokens,
            ),
        )

    def client(
        self,
        responses,
        *,
        history=None,
        repair_responses=(),
        settings=None,
        max_tokens: int = 256,
    ) -> GeminiClient:
        chat_responses = [
            item
            if isinstance(item, (FakeResponse, BaseException)) or callable(item)
            else self.response(item)
            for item in responses
        ]
        normalized_repair = [
            item
            if isinstance(item, (FakeResponse, BaseException))
            else self.response(item)
            for item in repair_responses
        ]
        self.sdk = FakeSdkClient(
            chat_responses=chat_responses,
            repair_responses=normalized_repair,
        )
        self.monkeypatch.setattr(
            "src.ai.llm_client.genai.Client",
            lambda **_kwargs: self.sdk,
        )
        values = {
            "ui_language": "ko",
            "prompt_language": "ko",
            "tts_language": "ko",
            "structured_response_mode": "auto",
            "enable_response_analysis": False,
            "enable_schedule_recognition": False,
            "enable_conversation_promises": False,
            "enable_ene_goals": False,
            "enable_ene_thoughts": False,
            "enable_proactive_conversation": False,
            "enable_synthetic_gestures": False,
        }
        values.update(settings or {})
        client = GeminiClient(
            "synthetic-key",
            model_name="gemini-synthetic",
            generation_params={"max_tokens": max_tokens},
            settings=values,
        )
        if history is not None:
            client.chat = client._create_chat_session(history=deepcopy(history))
        return client


__all__ = ["GeminiHarness", "valid_envelope_json"]
