from src.core.app_tts_bootstrap import (
    TTSRuntime,
    apply_tts_runtime_to_bridge,
    build_tts_runtime,
)


class _Settings:
    def __init__(self, values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class _Client:
    def __init__(self, available=True):
        self.available = available

    def is_available(self):
        return self.available


def test_build_tts_runtime_skips_factories_when_tts_disabled():
    settings = _Settings({"enable_tts": False})

    runtime = build_tts_runtime(
        settings,
        tts_client_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
        provider_defaults_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
        audio_player_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    assert runtime == TTSRuntime(tts_client=None, audio_player=None)


def test_build_tts_runtime_merges_provider_config_and_creates_audio_player():
    calls = {}
    client = _Client(available=True)

    def provider_defaults_factory(provider):
        calls["defaults_provider"] = provider
        return {"api_url": "http://default", "voice": "base"}

    def tts_client_factory(provider, config, api_key=""):
        calls["client"] = {
            "provider": provider,
            "config": dict(config),
            "api_key": api_key,
        }
        return client

    def audio_player_factory(*, output_device_id, volume):
        calls["audio"] = {
            "output_device_id": output_device_id,
            "volume": volume,
        }
        return "audio-player"

    settings = _Settings(
        {
            "enable_tts": True,
            "tts_provider": "gpt_sovits_http",
            "tts_provider_configs": {
                "gpt_sovits_http": {"voice": "custom", "speed": 1.2}
            },
            "tts_api_keys": {"gpt_sovits_http": "tts-key"},
            "tts_output_device_id": "device-1",
            "tts_output_volume": "0.7",
        }
    )

    runtime = build_tts_runtime(
        settings,
        tts_client_factory=tts_client_factory,
        provider_defaults_factory=provider_defaults_factory,
        audio_player_factory=audio_player_factory,
    )

    assert runtime == TTSRuntime(tts_client=client, audio_player="audio-player")
    assert calls["defaults_provider"] == "gpt_sovits_http"
    assert calls["client"] == {
        "provider": "gpt_sovits_http",
        "config": {"api_url": "http://default", "voice": "custom", "speed": 1.2},
        "api_key": "tts-key",
    }
    assert calls["audio"] == {"output_device_id": "device-1", "volume": 0.7}


def test_build_tts_runtime_returns_empty_runtime_when_provider_is_unavailable():
    settings = _Settings({"enable_tts": True, "tts_provider": "unknown"})

    runtime = build_tts_runtime(
        settings,
        tts_client_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("unknown")),
        provider_defaults_factory=lambda _provider: {},
        audio_player_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError()),
    )

    assert runtime == TTSRuntime(tts_client=None, audio_player=None)


def test_apply_tts_runtime_to_bridge_updates_flags_and_client_binding():
    calls = []

    class Bridge:
        def set_tts(self, tts_client, audio_player):
            calls.append((tts_client, audio_player))

    bridge = Bridge()
    settings = _Settings(
        {
            "enable_tts": True,
            "tts_streaming_enabled": True,
            "tts_streaming_emit_message_on_first_chunk": False,
        }
    )
    runtime = TTSRuntime(tts_client="client", audio_player="audio")

    apply_tts_runtime_to_bridge(bridge, settings, runtime)

    assert bridge.enable_tts is True
    assert bridge.tts_streaming_enabled is True
    assert bridge.tts_streaming_emit_message_on_first_chunk is False
    assert calls == [("client", "audio")]
