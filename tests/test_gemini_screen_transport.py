"""합성 HTTP 전송으로 Gemini SDK의 화면 권한 및 이력 경계를 검증한다."""

import asyncio
import base64
import io
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from google import genai
import httpx
from PIL import Image
import pytest

from src.ai.llm_client import GeminiClient
from src.core.debug_logging import configure_debug_logging
from src.core.screen_frame import SCREEN_UNAVAILABLE_HINT, ScreenFrame
from tests.structured_response_fixtures import valid_envelope_json


def jpeg():
    buffer = io.BytesIO()
    Image.new("RGB", (3, 2), "navy").save(buffer, format="JPEG")
    return buffer.getvalue()


def response(text):
    return httpx.Response(200, json={"candidates": [{
        "finishReason": "STOP", "content": {"role": "model", "parts": [{"text": text}]},
    }]})


@pytest.fixture
def sdk(monkeypatch):
    requests = []
    real_client = genai.Client
    clients = []

    def make(handler=None):
        def handle(request):
            body = json.loads(request.content)
            requests.append(body)
            if handler:
                return handler(body)
            return response(valid_envelope_json(reply="가상 기호 응답"))

        def create_client(**kwargs):
            options = {**kwargs["http_options"],
                       "client_args": {**kwargs["http_options"].get("client_args", {}),
                                       "transport": httpx.MockTransport(handle)},
                       "retry_options": {"attempts": 3, "initial_delay": 0.001}}
            return real_client(**{**kwargs, "http_options": options})

        monkeypatch.setattr(genai, "Client", create_client)
        monkeypatch.setattr("src.ai.llm_client.build_runtime_system_prompt", lambda **kwargs: "합성 역할 지침")
        client = GeminiClient("synthetic-key", model_name="gemini-synthetic", settings={
            "ui_language": "ko", "tts_language": "ko", "structured_response_mode": "auto",
            "enable_response_analysis": False, "enable_schedule_recognition": False,
            "enable_conversation_promises": False, "enable_ene_goals": False,
            "enable_ene_thoughts": False, "enable_proactive_conversation": False,
            "enable_synthetic_gestures": False, "enable_web_search": False,
        })
        clients.append(client)
        return client, requests

    yield make
    for client in clients:
        client.client.close()


def test_screen_question_only_sends_jpeg_once_and_preserves_user_turn(sdk, monkeypatch, tmp_path):
    client, requests = sdk()
    pixels = jpeg()
    marker = base64.urlsafe_b64encode(pixels).decode("ascii")
    context_ready = False

    async def memory(query, **kwargs):
        nonlocal context_ready
        assert query == "가상 격자"
        assert kwargs["memory_request_id"] == "synthetic-turn"
        context_ready = True
        return "합성 도형 문맥"

    monkeypatch.setattr(client, "_build_memory_context", memory)
    configure_debug_logging({"debug_mode": True}, root=tmp_path)
    try:
        client.send_message("가상의 이전 질문")
        result = asyncio.run(client.send_screen_question(
            "가상 격자", ScreenFrame(pixels, lambda: context_ready), latest_user_message="가상 격자",
            request_device="pc", memory_request_id="synthetic-turn",
        ))
        assert len(result) == 11 and result[0] == "가상 기호 응답"
        question = requests[1]
        assert question["contents"][0]["parts"] == [{"text": "가상의 이전 질문"}]
        assert question["systemInstruction"]["parts"] == [{"text": "합성 역할 지침"}]
        parts = question["contents"][-1]["parts"]
        assert [p["inlineData"] for p in parts if "inlineData" in p] == [{"mimeType": "image/jpeg", "data": marker}]
        assert "합성 도형 문맥" in parts[-1]["text"] and "PC" in parts[-1]["text"]
        for curated in (True, False):
            history = client.chat.get_history(curated=curated)
            assert history[-2].parts[0].text == "가상 격자"
            assert len(history[-2].parts) == 1
        client.send_message("가상의 다음 질문")
        assert marker not in json.dumps(requests[-1])
        assert client.rollback_last_assistant_turn()
        assert client.rollback_last_assistant_turn()
        client.send_message("가상 격자")
        assert marker not in json.dumps(requests[-1])
    finally:
        configure_debug_logging({}, root=tmp_path)
    logs = list((tmp_path / "log").glob("*.jsonl"))
    assert logs
    for log in logs:
        text = log.read_text(encoding="utf-8")
        assert marker not in text and base64.b64encode(pixels).decode("ascii") not in text


def test_screen_regeneration_checks_revoked_guard_and_sends_hint(sdk):
    available = True
    calls = 0

    def handle(body):
        nonlocal available, calls
        calls += 1
        if calls == 1:
            available = False
            return response("형식 오류")
        return response(valid_envelope_json())

    client, requests = sdk(handle)
    result = asyncio.run(client.send_screen_question("합성 재시도", ScreenFrame(jpeg(), lambda: available)))
    assert result[0] and calls == 2
    assert "inlineData" in requests[0]["contents"][-1]["parts"][0]
    assert "inlineData" not in str(requests[1])
    assert SCREEN_UNAVAILABLE_HINT in requests[1]["contents"][-1]["parts"][0]["text"]
    assert SCREEN_UNAVAILABLE_HINT not in str(client.get_conversation_history())


def test_missing_screen_preserves_the_prior_manual_attachment(sdk):
    client, requests = sdk()
    manual = io.BytesIO()
    Image.new("RGB", (2, 2), "green").save(manual, format="PNG")
    url = "data:image/png;base64," + base64.b64encode(manual.getvalue()).decode("ascii")
    asyncio.run(client.send_message_with_images("가상 파일", [{"dataUrl": url}]))
    asyncio.run(client.send_screen_question("빈 장면", None))
    client.send_message("가상 후속 입력")
    assert len(requests) == 3
    for body in requests:
        attachments = [part["inlineData"] for turn in body["contents"] for part in turn["parts"]
                       if "inlineData" in part]
        assert len(attachments) == 1 and attachments[0]["mimeType"] == "image/png"
        assert base64.urlsafe_b64decode(attachments[0]["data"]) == manual.getvalue()
    assert SCREEN_UNAVAILABLE_HINT in requests[1]["contents"][-1]["parts"][-1]["text"]
    assert SCREEN_UNAVAILABLE_HINT not in str(requests[2])


def test_screen_http_errors_do_not_replay_serialized_pixels(sdk):
    def unavailable(body):
        return httpx.Response(503, json={"error": {"code": 503, "message": "합성 오류"}})

    client, requests = sdk(unavailable)
    with pytest.raises(genai.errors.ServerError):
        asyncio.run(client.send_screen_question("합성 사각형", ScreenFrame(jpeg(), lambda: True)))
    assert len(requests) == 1
    assert not client.get_conversation_history()


@pytest.mark.parametrize("status", [307, 308])
@pytest.mark.parametrize("observation", [False, True])
def test_screen_redirects_stop_at_the_original_request(sdk, status, observation):
    def redirect(body):
        if len(requests) == 1:
            return httpx.Response(status, headers={"Location": "https://example.invalid/synthetic-route"})
        return response(valid_envelope_json())

    client, requests = sdk(redirect)
    frame = ScreenFrame(jpeg(), lambda: True)
    if observation:
        assert client.observe_screen_once("합성 표식", frame) == ""
    else:
        with pytest.raises(genai.errors.APIError) as error:
            asyncio.run(client.send_screen_question("합성 표식", frame))
        assert error.value.code == status
    assert len(requests) == 1 and not client.get_conversation_history()


def test_observation_is_stateless_while_user_request_runs(sdk):
    started, release = Event(), Event()
    raw = '{"speak":false}'

    def handle(body):
        turn = body["contents"][-1]["parts"]
        if any(part.get("text") == "가상 관찰" for part in turn):
            started.set()
            assert release.wait(5)
            return response(raw)
        return response(valid_envelope_json(reply="가상 대화 응답"))

    client, requests = sdk(handle)
    frame = ScreenFrame(jpeg(), lambda: True)
    with ThreadPoolExecutor() as pool:
        observation = pool.submit(client.observe_screen_once, "가상 관찰", frame)
        try:
            assert started.wait(5)
            assert client.send_message("가상 도형 질문")[0] == "가상 대화 응답"
            history = client.get_conversation_history()
            diagnostics = client.get_last_response_diagnostics()
        finally:
            release.set()
        assert observation.result(timeout=5) == raw
    assert client.get_conversation_history() == history
    assert client.get_last_response_diagnostics() == diagnostics
    assert len(requests[0]["contents"]) == 1
    assert "inlineData" in str(requests[0]) and "systemInstruction" not in requests[0]
    assert "가상 관찰" not in str(requests[1]) and "inlineData" not in str(requests[1])
    frame.close()
    assert client.observe_screen_once("가상 관찰", frame) == ""
    assert len(requests) == 2
