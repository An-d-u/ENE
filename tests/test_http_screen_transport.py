import asyncio
import base64
import copy
from io import BytesIO
import json
from unittest.mock import AsyncMock

import pytest
import requests
from PIL import Image

from src.ai.http_llm_clients import (
    AnthropicClient, CohereClient, GoogleCloudClient, MistralClient,
    OllamaClient, OpenAICompatibleClient, OpenAIResponseAPIClient,
)
from src.core.debug_logging import configure_debug_logging
from src.core.screen_frame import SCREEN_UNAVAILABLE_HINT, ScreenFrame
from tests.http_structured_fixtures import DummyHTTPResponse, legacy_final_reply, native_final_reply, structured_settings


def synthetic_jpeg():
    with BytesIO() as stream:
        Image.new("RGB", (4, 3), "purple").save(stream, format="JPEG")
        return stream.getvalue()


JPEG = synthetic_jpeg()
ENCODED = base64.b64encode(JPEG).decode()
QUESTION = "합성 도형의 색은 무엇인가요?"
ANSWER = "합성 도형은 보라색입니다."
OBSERVATION = '{"speak":false}'
FORMATS = (OpenAICompatibleClient, OpenAIResponseAPIClient, GoogleCloudClient, AnthropicClient, OllamaClient)


def make_client(cls):
    options = {"provider_name": "compat"} if issubclass(cls, OpenAICompatibleClient) else {}
    return cls(
        api_key="synthetic", model_name="synthetic", endpoint="https://example.invalid/api",
        settings=structured_settings(), **options,
    )


def response(wire, text):
    if wire == "openai_chat":
        body = {"choices": [{"message": {"content": text}}]}
    elif wire == "openai_responses":
        body = {"output_text": text, "status": "completed", "id": "synthetic-response-id"}
    elif wire == "google_cloud":
        body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    elif wire == "anthropic":
        body = {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}
    elif wire == "ollama":
        body = {"message": {"content": text}, "done": True}
    return DummyHTTPResponse(body)


def assert_current_image(wire, payload):
    if wire == "google_cloud":
        assert payload["contents"][-1]["parts"][-1]["inlineData"] == {"mimeType": "image/jpeg", "data": ENCODED}
    elif wire == "ollama":
        assert payload["messages"][-1]["images"] == [ENCODED]
    elif wire == "anthropic":
        assert payload["messages"][-1]["content"][-1]["source"] == {
            "type": "base64", "media_type": "image/jpeg", "data": ENCODED,
        }
    elif wire == "openai_responses":
        assert payload["input"][-1]["content"][-1]["image_url"] == "data:image/jpeg;base64," + ENCODED
        assert payload["store"] is False
        assert "previous_response_id" not in payload
    else:
        assert payload["messages"][-1]["content"][-1]["image_url"]["url"] == "data:image/jpeg;base64," + ENCODED


@pytest.mark.parametrize("cls", FORMATS)
def test_screen_question_only_attaches_at_current_transmission(monkeypatch, cls):
    client = make_client(cls)
    client._history = [{"role": "user", "content": "합성 이전 질문"}]
    wire = []
    context = AsyncMock(return_value=QUESTION + " 합성 기억")
    monkeypatch.setattr(client, "_build_contextual_message", context)

    def post(url, **kwargs):
        wire.append(copy.deepcopy(kwargs))
        return response(client.wire_format, legacy_final_reply(ANSWER))

    monkeypatch.setattr(requests, "post", post)
    result = asyncio.run(client.send_screen_question(
        QUESTION, ScreenFrame(JPEG, lambda: True), latest_user_message="합성 최근 질문",
        include_life_record_context=True, request_device="pc",
    ))
    assert result[0] == ANSWER
    assert context.await_args.kwargs["latest_user_message"] == "합성 최근 질문"
    assert context.await_args.kwargs["include_life_record_context"] is True
    assert wire[0]["allow_redirects"] is False
    assert_current_image(client.wire_format, wire[0]["json"])
    for text in ("합성 이전 질문", "합성 기억", QUESTION):
        assert text in str(wire[0]["json"])
    assert client.get_conversation_history()[-2:] == [
        {"role": "user", "content": QUESTION}, {"role": "assistant", "content": ANSWER},
    ]
    assert ENCODED not in str(vars(client))
    client.send_message("합성 후속 질문")
    assert len(wire) == 2
    assert ENCODED not in str(wire[-1])
    assert "synthetic-response-id" not in str(wire[-1])


@pytest.mark.parametrize("cls", FORMATS)
def test_screen_observation_uses_an_isolated_single_request(monkeypatch, cls):
    client = make_client(cls)
    client._history = [{"role": "user", "content": "합성 대화 비공개"}]
    client._last_request_context_fingerprint = {"prior": 1}
    state = copy.deepcopy(vars(client))
    wire = []

    def post(url, **kwargs):
        wire.append(copy.deepcopy(kwargs["json"]))
        return response(client.wire_format, OBSERVATION)

    monkeypatch.setattr(requests, "post", post)
    assert client.observe_screen_once("합성 관찰", ScreenFrame(JPEG, lambda: True)) == OBSERVATION
    assert len(wire) == 1
    assert_current_image(client.wire_format, wire[0])
    assert "합성 관찰" in str(wire[0])
    assert "합성 대화 비공개" not in str(wire[0])
    assert vars(client) == state
    assert client.observe_screen_once("합성 관찰", ScreenFrame(JPEG, lambda: False)) == ""
    assert len(wire) == 1


@pytest.mark.parametrize("cls", FORMATS)
def test_retry_after_revocation_sends_only_text_and_hint(monkeypatch, cls):
    client = make_client(cls)
    frame = ScreenFrame(JPEG, lambda: True)
    wire = []

    def post(url, **kwargs):
        wire.append(copy.deepcopy(kwargs["json"]))
        frame.close()
        return response(client.wire_format, "" if len(wire) == 1 else legacy_final_reply(ANSWER))

    monkeypatch.setattr(requests, "post", post)
    assert asyncio.run(client.send_screen_question(QUESTION, frame))[0] == ANSWER
    assert len(wire) == 2
    assert_current_image(client.wire_format, wire[0])
    assert ENCODED not in str(wire[1])
    assert SCREEN_UNAVAILABLE_HINT in str(wire[1])
    assert client.get_conversation_history()[0]["content"] == QUESTION


def test_revoke_while_preparing_wire_cancels_observation_and_degrades_question(monkeypatch):
    client = make_client(OpenAICompatibleClient)
    wire = []

    def post(url, **kwargs):
        wire.append(kwargs["json"])
        return response(client.wire_format, legacy_final_reply(ANSWER))

    def expiring_frame():
        valid = iter((True, False))
        return ScreenFrame(JPEG, lambda: next(valid, False))

    monkeypatch.setattr(requests, "post", post)
    assert client.observe_screen_once("합성 관찰", expiring_frame()) == ""
    assert not wire
    asyncio.run(client.send_screen_question(QUESTION, expiring_frame()))
    assert ENCODED not in str(wire)
    assert SCREEN_UNAVAILABLE_HINT in str(wire)


def test_screen_error_cannot_echo_original_bytes_into_diagnostics(monkeypatch, tmp_path):
    client = make_client(OpenAICompatibleClient)
    configure_debug_logging({"debug_mode": True}, root=tmp_path)
    monkeypatch.setattr(requests, "post", lambda *a, **kw: DummyHTTPResponse(
        status_code=503, text=json.dumps({"message": ENCODED}),
    ))
    try:
        with pytest.raises(requests.HTTPError) as error:
            asyncio.run(client.send_screen_question(QUESTION, ScreenFrame(JPEG, lambda: True)))
    finally:
        configure_debug_logging({"debug_mode": False}, root=tmp_path)
    assert ENCODED not in str(error.value)
    assert all(ENCODED not in file.read_text("utf-8") for file in tmp_path.rglob("*.jsonl"))


def test_observation_http_failure_is_silent_and_keeps_history(monkeypatch):
    client = make_client(OpenAICompatibleClient)
    monkeypatch.setattr(requests, "post", lambda *a, **kw: DummyHTTPResponse(status_code=500))
    assert client.observe_screen_once("합성 관찰", ScreenFrame(JPEG, lambda: True)) == ""
    assert client.get_conversation_history() == []


@pytest.mark.parametrize("downgrade", (False, True), ids=["repair", "downgrade"])
def test_screen_rechecks_permission_for_native_schema_followup(monkeypatch, downgrade):
    client = make_client(OpenAIResponseAPIClient)
    client.endpoint = "https://api.openai.com/v1/responses"
    client.model_name = "synthetic-screen-schema-" + str(downgrade)
    client.settings["enable_ene_thoughts"] = not downgrade
    frame = ScreenFrame(JPEG, lambda: True)
    wire = []

    def post(url, **kwargs):
        wire.append(copy.deepcopy(kwargs["json"]))
        if len(wire) == 1:
            frame.close()
            if downgrade:
                return DummyHTTPResponse({"error": {"message": "Unknown parameter: text.format"}}, status_code=400)
            return response(client.wire_format, native_final_reply(ANSWER))
        return response(client.wire_format, legacy_final_reply(ANSWER) if downgrade else '{"thought":"합성 보완"}')

    monkeypatch.setattr(requests, "post", post)
    result = asyncio.run(client.send_screen_question(QUESTION, frame))
    assert result[0] == ANSWER
    assert "text" in wire[0]
    assert_current_image(client.wire_format, wire[0])
    if downgrade:
        assert "text" not in wire[1]
    else:
        assert result[6] == "합성 보완"
    assert len(wire) == 2
    assert SCREEN_UNAVAILABLE_HINT in str(wire[1])
    assert ENCODED not in str(wire[1])


@pytest.mark.parametrize("cls", FORMATS)
def test_supported_wire_formats_also_obey_model_image_capability(cls):
    client = make_client(cls)
    assert client.supports_screen_input
    client.supports_image_input = False
    assert not client.supports_screen_input


@pytest.mark.parametrize("cls", (CohereClient, MistralClient))
def test_text_only_wire_formats_do_not_offer_screen(cls):
    assert not getattr(make_client(cls), "supports_screen_input", False)
