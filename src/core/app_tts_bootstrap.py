"""
앱 시작 시 TTS 클라이언트와 오디오 플레이어를 생성하는 유틸리티.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class TTSRuntime:
    """TTS 클라이언트와 오디오 플레이어 묶음."""

    tts_client: Any = None
    audio_player: Any = None


def build_tts_runtime(
    settings,
    *,
    tts_client_factory: Callable[..., Any] | None = None,
    provider_defaults_factory: Callable[..., dict] | None = None,
    audio_player_factory: Callable[..., Any] | None = None,
) -> TTSRuntime:
    """설정에서 TTS 클라이언트와 오디오 플레이어를 만든다."""
    if not bool(settings.get("enable_tts", True)):
        print("INFO: TTS 비활성화 상태로 초기화를 건너뜁니다.")
        return TTSRuntime()

    if tts_client_factory is None or provider_defaults_factory is None:
        from src.ai.tts_client import create_tts_client, get_tts_provider_defaults

        tts_client_factory = tts_client_factory or create_tts_client
        provider_defaults_factory = provider_defaults_factory or get_tts_provider_defaults
    if audio_player_factory is None:
        from src.core.audio_player import AudioPlayer

        audio_player_factory = AudioPlayer

    tts_provider = str(settings.get("tts_provider", "gpt_sovits_http")).strip().lower()
    tts_provider_configs = settings.get("tts_provider_configs", {})
    if not isinstance(tts_provider_configs, dict):
        tts_provider_configs = {}

    provider_config = provider_defaults_factory(tts_provider)
    raw_provider_config = tts_provider_configs.get(tts_provider, {})
    if isinstance(raw_provider_config, dict):
        provider_config.update(raw_provider_config)

    tts_api_keys = settings.get("tts_api_keys", {})
    if not isinstance(tts_api_keys, dict):
        tts_api_keys = {}

    try:
        tts_client = tts_client_factory(
            tts_provider,
            provider_config,
            api_key=str(tts_api_keys.get(tts_provider, "")).strip(),
        )
    except ValueError:
        print(f"WARNING: 아직 지원하지 않는 TTS 공급자입니다: {tts_provider}")
        return TTSRuntime()

    audio_player = audio_player_factory(
        output_device_id=str(settings.get("tts_output_device_id", "")).strip(),
        volume=float(settings.get("tts_output_volume", 0.8) or 0.8),
    )

    if tts_client.is_available():
        print(f"OK: TTS 클라이언트 초기화 성공 ({tts_provider})")
        return TTSRuntime(tts_client=tts_client, audio_player=audio_player)

    print(f"WARNING: TTS 공급자 설정이 충분하지 않습니다. provider={tts_provider}")
    return TTSRuntime()


def apply_tts_runtime_to_bridge(bridge, settings, runtime: TTSRuntime) -> None:
    """현재 TTS 설정과 런타임 객체를 브리지에 반영한다."""
    bridge.enable_tts = bool(settings.get("enable_tts", False))
    bridge.tts_streaming_enabled = bool(settings.get("tts_streaming_enabled", False))
    bridge.tts_streaming_emit_message_on_first_chunk = bool(
        settings.get("tts_streaming_emit_message_on_first_chunk", True)
    )
    bridge.set_tts(runtime.tts_client, runtime.audio_player)
