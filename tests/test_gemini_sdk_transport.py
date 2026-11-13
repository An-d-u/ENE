"""실제 Gemini SDK 전송을 합성 응답의 로컬 HTTP 서버로 검증한다."""

import asyncio
import base64
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

from google import genai
from google.genai import types
from PIL import Image
import pytest

from src.ai.embedding import GeminiEmbeddingGenerator
from src.ai.llm_client import GeminiClient
from tests.gemini_structured_fixtures import FakeSdkClient
from tests.structured_response_fixtures import valid_envelope_json


@pytest.mark.parametrize("client_type", ["chat", "embedding"])
def test_gemini_clients_pin_api_version(monkeypatch, client_type):
    captured = {}
    def create_client(**kwargs):
        captured.update(kwargs)
        return FakeSdkClient(chat_responses=[])
    monkeypatch.setattr(genai, "Client", create_client)
    monkeypatch.setattr("src.ai.llm_client.build_runtime_system_prompt", lambda **kwargs: "합성 지침")
    if client_type == "chat":
        GeminiClient(api_key="synthetic-key")
    else:
        GeminiEmbeddingGenerator(api_key="synthetic-key")
    assert types.HttpOptions.model_validate(captured.get("http_options", {})).api_version == "v1beta"


@pytest.fixture
def sdk_server():
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append((self.path, payload, self.headers.get("x-goog-api-key")))
            if "embedcontent" in self.path.lower():
                response = {"embeddings": [{"values": [0.1, 0.2, 0.3]}]}
            else:
                response = {"candidates": [{
                    "content": {"role": "model", "parts": [{"text": valid_envelope_json(reply="합성 응답")}]},
                    "finishReason": "STOP",
                }], "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 4, "totalTokenCount": 7}}
            encoded = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_installed_sdk_serializes_chat_image_json_async_and_embeddings(monkeypatch, sdk_server):
    base_url, captured = sdk_server
    real_client = genai.Client
    def create_client(**kwargs):
        options = types.HttpOptions.model_validate(kwargs.get("http_options", {}))
        options.base_url = base_url
        options.timeout = 5000
        options.retry_options = types.HttpRetryOptions(attempts=1)
        return real_client(**{**kwargs, "http_options": options})
    monkeypatch.setattr(genai, "Client", create_client)
    monkeypatch.setattr("src.ai.llm_client.build_runtime_system_prompt", lambda **kwargs: "합성 지침")
    client = GeminiClient(api_key="synthetic-key", model_name="gemini-4-argon", settings={
        "structured_response_mode": "auto", "ui_language": "ko", "prompt_language": "ko", "tts_language": "ko",
        "enable_response_analysis": False, "enable_schedule_recognition": False,
        "enable_conversation_promises": False, "enable_ene_goals": False,
        "enable_ene_thoughts": False, "enable_proactive_conversation": False,
        "enable_synthetic_gestures": False,
    })
    try:
        assert client.send_message("합성 도형을 설명하세요.")[0] == "합성 응답"
        image_bytes = io.BytesIO()
        Image.new("RGB", (2, 2), "navy").save(image_bytes, format="PNG")
        image_url = "data:image/png;base64," + base64.b64encode(image_bytes.getvalue()).decode("ascii")
        async def generate_once():
            try:
                reply = await client.send_message_with_images("합성 이미지", [{"dataUrl": image_url}])
                assert reply[0] == "합성 응답"
                return await client.generate_life_record_once("합성 기록")
            finally:
                await client.client.aio.aclose()
        assert asyncio.run(generate_once()).text
        embedding = GeminiEmbeddingGenerator(api_key="synthetic-key", client=client.client)
        assert embedding._request_batch(["합성 자료"]) == [[0.1, 0.2, 0.3]]
    finally:
        client.client.close()
    assert len(captured) == 4
    for path, payload, key in captured:
        assert path.startswith("/v1beta/")
        assert key == "synthetic-key"
        config = payload.get("generationConfig", {})
        assert "temperature" not in config
        assert "topP" not in config
    assert "responseJsonSchema" in captured[0][1]["generationConfig"]
    image_contents = captured[1][1]["contents"]
    assert image_contents[1]["parts"] == [{"text": "합성 응답"}]
    inline_data = image_contents[-1]["parts"][0]["inlineData"]
    assert types.Blob.model_validate(inline_data).mime_type == "image/png"
