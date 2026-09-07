import asyncio
import io
import json
import wave

import aiohttp
import pytest

from src.ai.tts_client import create_tts_client, get_tts_provider_catalog, get_tts_provider_defaults
from src.core.settings import Settings


@pytest.fixture
def fish_http(monkeypatch):
    calls = []

    class Response:
        status = 200
        audio = b"\x00\x00\x10\x00" * 64

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def read(self):
            return self.audio

        async def text(self):
            return "가상 비밀 응답: 테스트용 키와 합성 원문"

    response = Response()

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        def post(self, url, **kwargs):
            calls.append((url, kwargs))
            return response

    monkeypatch.setattr("src.ai.tts_client.aiohttp.ClientSession", Session)
    return response, calls


def test_fish_audio_is_registered_with_matching_settings_defaults():
    assert "fish_audio" in get_tts_provider_catalog()
    meta = get_tts_provider_catalog()["fish_audio"]
    assert meta.display_name == "Fish Audio"
    assert meta.requires_api_key is True
    assert get_tts_provider_defaults("fish_audio") == Settings.DEFAULT_CONFIG["tts_provider_configs"]["fish_audio"]
    assert Settings.DEFAULT_SECRET_CONFIG["tts_api_keys"]["fish_audio"] == ""


@pytest.mark.parametrize("model", ["s2.1-pro", "s2.1-pro-free", "s2-pro", "s1"])
def test_fish_audio_posts_official_contract_and_returns_playable_wav(fish_http, model):
    response, calls = fish_http
    client = create_tts_client(
        "fish_audio",
        {"model": model, "reference_id": "synthetic-voice-id", "speed": 1.15},
        api_key=" synthetic-fish-key ",
    )
    audio = asyncio.run(client.generate_speech("  작은 로봇이 인사합니다.\r\n  별빛이 반짝입니다.  "))

    assert client.is_available() is True
    assert not getattr(client, "uses_browser_playback", False)
    assert client.supports_streaming is False
    assert len(calls) == 1
    url, request = calls[0]
    assert url == "https://api.fish.audio/v1/tts"
    assert request["headers"] == {
        "Authorization": "Bearer synthetic-fish-key",
        "Content-Type": "application/json",
        "model": model,
    }
    assert request["json"] == {
        "text": "작은 로봇이 인사합니다.\n별빛이 반짝입니다.",
        "reference_id": "synthetic-voice-id",
        "format": "pcm",
        "sample_rate": 44100,
        "prosody": {"speed": 1.15},
    }
    assert 0 < request["timeout"].total <= 90
    with wave.open(io.BytesIO(audio), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (44100, 1, 2)
        assert wav.readframes(wav.getnframes()) == response.audio


@pytest.mark.parametrize("api_url", ["https://api.fish.audio/v1/", "https://api.fish.audio/v1/tts"])
def test_fish_audio_normalizes_endpoint_and_omits_blank_voice(fish_http, api_url):
    _, calls = fish_http
    client = create_tts_client("fish_audio", {"api_url": api_url, "reference_id": " "}, api_key="synthetic-key")
    asyncio.run(client.generate_speech("가상의 안내 음성입니다."))
    assert calls[0][0] == "https://api.fish.audio/v1/tts"
    assert "reference_id" not in calls[0][1]["json"]


@pytest.mark.parametrize("speed, expected", [(0.1, 0.5), (3.0, 2.0)])
def test_fish_audio_clamps_speed_to_api_range(fish_http, speed, expected):
    _, calls = fish_http
    client = create_tts_client("fish_audio", {"speed": speed}, api_key="synthetic-key")
    asyncio.run(client.generate_speech("가상의 안내 음성입니다."))
    assert calls[0][1]["json"]["prosody"]["speed"] == expected


def test_fish_audio_missing_key_does_not_send_request(fish_http):
    _, calls = fish_http
    client = create_tts_client("fish_audio", api_key=" ")
    assert client.is_available() is False
    with pytest.raises(ValueError, match="API 키"):
        asyncio.run(client.generate_speech("가상의 안내 음성입니다."))
    assert calls == []


def test_fish_audio_blank_text_does_not_send_request(fish_http):
    _, calls = fish_http
    client = create_tts_client("fish_audio", api_key="synthetic-key")
    with pytest.raises(ValueError, match="텍스트"):
        asyncio.run(client.generate_speech(" \r\n "))
    assert calls == []


@pytest.mark.parametrize("status, message", [(401, "API 키"), (402, "크레딧"), (403, "권한"), (422, "설정"), (429, "요청 한도"), (500, "서버")])
def test_fish_audio_http_errors_are_actionable_and_do_not_expose_body(fish_http, status, message):
    response, _ = fish_http
    response.status = status
    client = create_tts_client("fish_audio", api_key="synthetic-key")
    with pytest.raises(RuntimeError, match=message) as exc:
        asyncio.run(client.generate_speech("가상의 안내 음성입니다."))
    assert str(status) in str(exc.value)
    assert "가상 비밀 응답" not in str(exc.value)
    assert "synthetic-key" not in str(exc.value)


@pytest.mark.parametrize("error, message", [(asyncio.TimeoutError("가상 비밀"), "시간"), (aiohttp.ClientConnectionError("가상 비밀"), "연결")])
def test_fish_audio_network_errors_do_not_expose_details(monkeypatch, error, message):
    def fail_session():
        raise error

    monkeypatch.setattr("src.ai.tts_client.aiohttp.ClientSession", fail_session)
    client = create_tts_client("fish_audio", api_key="synthetic-key")
    with pytest.raises(RuntimeError, match=message) as exc:
        asyncio.run(client.generate_speech("가상의 안내 음성입니다."))
    assert "가상 비밀" not in str(exc.value)


@pytest.mark.parametrize("audio", [b"", b"\x00"])
def test_fish_audio_rejects_empty_or_incomplete_pcm(fish_http, audio):
    response, _ = fish_http
    response.audio = audio
    client = create_tts_client("fish_audio", api_key="synthetic-key")
    with pytest.raises(RuntimeError, match="오디오"):
        asyncio.run(client.generate_speech("가상의 안내 음성입니다."))


def test_fish_audio_settings_upgrade_and_keep_key_in_secret_file(tmp_path, monkeypatch):
    monkeypatch.setattr(Settings, "_migrate_legacy_embedding_key_file", lambda self: None)
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    config_path.write_text(json.dumps({"tts_provider": "elevenlabs", "tts_provider_configs": {"elevenlabs": {"speed": 1.1}}}), encoding="utf-8")
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert "fish_audio" in settings.get("tts_provider_configs")
    assert settings.get("tts_provider_configs")["elevenlabs"]["speed"] == 1.1
    configs = settings.get("tts_provider_configs")
    configs["fish_audio"].update({"reference_id": "synthetic-voice-id", "speed": 1.2})
    settings.update({"tts_provider": "fish_audio", "tts_provider_configs": configs, "tts_api_keys": {"fish_audio": "synthetic-fish-key"}})
    settings.save()

    public_config = config_path.read_text(encoding="utf-8")
    assert "synthetic-fish-key" not in public_config
    assert "tts_api_keys" not in json.loads(public_config)
    assert json.loads(secret_path.read_text(encoding="utf-8"))["tts_api_keys"]["fish_audio"] == "synthetic-fish-key"
    reopened = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert reopened.get("tts_provider") == "fish_audio"
    assert reopened.get("tts_provider_configs")["fish_audio"]["reference_id"] == "synthetic-voice-id"
    assert reopened.get("tts_api_keys")["fish_audio"] == "synthetic-fish-key"
