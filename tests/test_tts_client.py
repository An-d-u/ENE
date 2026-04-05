import asyncio
import aiohttp
import pytest

from src.ai.tts_client import TTSClient, create_tts_client, get_tts_provider_defaults


def test_normalize_tts_text_normalizes_newlines_and_blanks():
    raw = "  1행\r\n\r\n\r\n 2행 \r3행\n\n"
    normalized = TTSClient._normalize_tts_text(raw)
    assert normalized == "1행\n\n2행\n3행"


def test_gpt_sovits_defaults_include_sampling_controls():
    defaults = get_tts_provider_defaults("gpt_sovits_http")

    assert defaults["speed_factor"] == 1.0
    assert defaults["top_k"] == 15
    assert defaults["top_p"] == 1.0
    assert defaults["temperature"] == 1.0
    assert defaults["text_split_method"] == "cut5"


def test_genie_tts_defaults_include_fixed_character_fields():
    defaults = get_tts_provider_defaults("genie_tts_http")

    assert defaults["api_url"] == "http://127.0.0.1:7860"
    assert defaults["character_name"] == ""
    assert defaults["ref_audio_path"] == "assets/ref_audio/refvoice.wav"
    assert defaults["ref_language"] == "ja"
    assert defaults["split_sentence"] is True


def test_create_tts_client_returns_genie_client():
    client = create_tts_client("genie_tts_http", {"character_name": "demo"})
    assert client.__class__.__name__ == "GenieTTSHTTPClient"


def test_genie_client_initializes_server_before_tts(tmp_path, monkeypatch):
    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"fake")
    calls = []

    class DummyResponse:
        def __init__(self, payload=b"", status=200):
            self.status = status
            self._payload = payload

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def read(self):
            return self._payload

        async def text(self):
            return ""

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, timeout=None):
            calls.append((url, json))
            if url.endswith("/tts"):
                return DummyResponse(b"wav")
            return DummyResponse()

    monkeypatch.setattr(aiohttp, "ClientSession", DummySession)

    client = create_tts_client(
        "genie_tts_http",
        {
            "api_url": "http://127.0.0.1:7860",
            "character_name": "ene",
            "onnx_model_dir": "models/ene",
            "model_language": "ja",
            "ref_audio_path": str(ref_audio),
            "ref_text": "테스트 참조 문장",
            "ref_language": "ja",
            "split_sentence": True,
        },
    )

    audio = asyncio.run(client.generate_speech("안녕"))

    assert audio == b"wav"
    assert calls[0][0] == "http://127.0.0.1:7860/load_character"
    assert calls[0][1]["character_name"] == "ene"
    assert calls[0][1]["onnx_model_dir"] == "models/ene"
    assert calls[0][1]["language"] == "jp"
    assert calls[1][0] == "http://127.0.0.1:7860/set_reference_audio"
    assert calls[1][1]["character_name"] == "ene"
    assert calls[1][1]["audio_path"] == str(ref_audio.resolve())
    assert calls[1][1]["audio_text"] == "테스트 참조 문장"
    assert calls[1][1]["language"] == "jp"
    assert calls[2][0] == "http://127.0.0.1:7860/tts"
    assert calls[2][1]["character_name"] == "ene"
    assert calls[2][1]["text"] == "안녕"
    assert calls[2][1]["split_sentence"] is True


def test_genie_client_reuses_initialized_state(tmp_path, monkeypatch):
    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"fake")
    calls = []

    class DummyResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def read(self):
            return b"wav"

        async def text(self):
            return ""

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, timeout=None):
            calls.append(url)
            return DummyResponse()

    monkeypatch.setattr(aiohttp, "ClientSession", DummySession)

    client = create_tts_client(
        "genie_tts_http",
        {
            "api_url": "http://127.0.0.1:7860",
            "character_name": "ene",
            "onnx_model_dir": "models/ene",
            "model_language": "ko",
            "ref_audio_path": str(ref_audio),
            "ref_text": "테스트 참조 문장",
            "ref_language": "ko",
        },
    )

    asyncio.run(client.generate_speech("첫 번째"))
    asyncio.run(client.generate_speech("두 번째"))

    assert calls.count("http://127.0.0.1:7860/load_character") == 1
    assert calls.count("http://127.0.0.1:7860/set_reference_audio") == 1
    assert calls.count("http://127.0.0.1:7860/tts") == 2


def test_genie_client_raises_when_reference_audio_is_missing(tmp_path):
    client = create_tts_client(
        "genie_tts_http",
        {
            "api_url": "http://127.0.0.1:7860",
            "character_name": "ene",
            "onnx_model_dir": "models/ene",
            "model_language": "ja",
            "ref_audio_path": str(tmp_path / "missing.wav"),
            "ref_text": "테스트 참조 문장",
            "ref_language": "ja",
        },
    )

    with pytest.raises(FileNotFoundError):
        asyncio.run(client.generate_speech("안녕"))


def test_gpt_sovits_client_posts_extended_controls(tmp_path, monkeypatch):
    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"fake")

    captured = {}

    class DummyResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return ""

        async def read(self):
            return b"wav-bytes"

    class DummySession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json, timeout):
            captured["url"] = url
            captured["json"] = json
            captured["timeout"] = timeout
            return DummyResponse()

    monkeypatch.setattr(aiohttp, "ClientSession", DummySession)

    client = create_tts_client(
        "gpt_sovits_http",
        {
            "api_url": "http://127.0.0.1:9880",
            "ref_audio_path": str(ref_audio),
            "ref_text": "테스트 프롬프트",
            "ref_language": "ja",
            "target_language": "ko",
            "speed_factor": 1.2,
            "top_k": 22,
            "top_p": 0.82,
            "temperature": 0.66,
            "text_split_method": "cut2",
        },
    )

    audio = asyncio.run(client.generate_speech("안녕\n\n하세요"))

    assert audio == b"wav-bytes"
    assert captured["url"] == "http://127.0.0.1:9880/tts"
    assert captured["json"]["text"] == "안녕\n\n하세요"
    assert captured["json"]["text_lang"] == "ko"
    assert captured["json"]["prompt_text"] == "테스트 프롬프트"
    assert captured["json"]["prompt_lang"] == "ja"
    assert captured["json"]["speed_factor"] == 1.2
    assert captured["json"]["top_k"] == 22
    assert captured["json"]["top_p"] == 0.82
    assert captured["json"]["temperature"] == 0.66
    assert captured["json"]["text_split_method"] == "cut2"


def test_gpt_sovits_client_resolves_relative_reference_audio_from_bundle_root(tmp_path, monkeypatch):
    from src.ai.tts_client import GPTSoVITSHTTPClient

    bundle_root = tmp_path / "bundle"
    ref_audio = bundle_root / "assets" / "ref_audio" / "refvoice.wav"
    ref_audio.parent.mkdir(parents=True, exist_ok=True)
    ref_audio.write_bytes(b"fake")

    monkeypatch.setenv("ENE_USER_DATA_DIR", str(tmp_path / "user"))
    monkeypatch.setenv("ENE_BUNDLE_DIR", str(bundle_root))

    client = GPTSoVITSHTTPClient(ref_audio_path="assets/ref_audio/refvoice.wav")

    resolved = client._resolve_reference_audio_path()

    assert resolved == ref_audio.resolve()
