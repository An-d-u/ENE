"""
다중 TTS 공급자 추상화 레이어.
현재 ENE는 GPT-SoVITS HTTP, OpenAI Audio Speech,
OpenAI Compatible Audio Speech, ElevenLabs를 지원한다.
"""
from __future__ import annotations

import aiohttp
import asyncio
import io
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class TTSClientProtocol(Protocol):
    async def generate_speech(self, text: str) -> bytes:
        ...

    def is_available(self) -> bool:
        ...


@dataclass(frozen=True)
class TTSProviderMeta:
    provider: str
    display_name: str
    description: str
    requires_api_key: bool
    default_config: dict


GPT_SOVITS_TEXT_SPLIT_METHODS: tuple[str, ...] = (
    "cut0",
    "cut1",
    "cut2",
    "cut3",
    "cut4",
    "cut5",
)


TTS_PROVIDER_CATALOG: dict[str, TTSProviderMeta] = {
    "gpt_sovits_http": TTSProviderMeta(
        provider="gpt_sovits_http",
        display_name="GPT-SoVITS HTTP",
        description="참조 음성과 프롬프트 텍스트를 사용하는 로컬/원격 GPT-SoVITS 서버",
        requires_api_key=False,
        default_config={
            "api_url": "http://127.0.0.1:9880",
            "ref_audio_path": "assets/ref_audio/refvoice.wav",
            "ref_text": "人間さんはどんな色が一番好き？ ん？ なんで聞いたかって？ ふふん～ 内緒",
            "ref_language": "ja",
            "target_language": "ja",
            "speed_factor": 1.0,
            "top_k": 15,
            "top_p": 1.0,
            "temperature": 1.0,
            "text_split_method": "cut5",
        },
    ),
    "openai_audio_speech": TTSProviderMeta(
        provider="openai_audio_speech",
        display_name="OpenAI Audio Speech",
        description="OpenAI 공식 Audio Speech API",
        requires_api_key=True,
        default_config={
            "api_url": "https://api.openai.com/v1",
            "model": "gpt-4o-mini-tts",
            "voice": "alloy",
            "speed": 1.0,
            "response_format": "wav",
        },
    ),
    "openai_compatible_audio_speech": TTSProviderMeta(
        provider="openai_compatible_audio_speech",
        display_name="OpenAI Compatible Audio Speech",
        description="OpenAI 음성 합성 스펙을 따르는 호환 API",
        requires_api_key=False,
        default_config={
            "api_url": "http://127.0.0.1:8000/v1",
            "model": "tts-1",
            "voice": "alloy",
            "speed": 1.0,
            "response_format": "wav",
        },
    ),
    "elevenlabs": TTSProviderMeta(
        provider="elevenlabs",
        display_name="ElevenLabs",
        description="ElevenLabs Text to Speech API",
        requires_api_key=True,
        default_config={
            "api_url": "https://api.elevenlabs.io/v1",
            "model": "eleven_multilingual_v2",
            "voice": "EXAVITQu4vr4xnSDxMaL",
            "speed": 1.0,
            "stability": 0.5,
            "similarity_boost": 0.75,
            "style": 0.0,
            "use_speaker_boost": True,
            "output_format": "pcm_44100",
        },
    ),
    "browser_speech": TTSProviderMeta(
        provider="browser_speech",
        display_name="브라우저 기본 TTS",
        description="QWebEngine 내부 speechSynthesis를 사용하는 테스트용/폴백용 TTS",
        requires_api_key=False,
        default_config={
            "lang": "ja-JP",
            "voice": "",
            "rate": 1.0,
            "pitch": 1.0,
            "volume": 1.0,
        },
    ),
}


def get_tts_provider_catalog() -> dict[str, TTSProviderMeta]:
    return dict(TTS_PROVIDER_CATALOG)


def get_tts_provider_defaults(provider: str) -> dict:
    meta = TTS_PROVIDER_CATALOG.get((provider or "").strip().lower())
    if meta is None:
        return {}
    return dict(meta.default_config)


def get_gpt_sovits_text_split_methods() -> tuple[str, ...]:
    return GPT_SOVITS_TEXT_SPLIT_METHODS


class BaseTTSClient:
    """여러 공급자가 공유하는 기본 유틸리티."""

    def __init__(self, provider_name: str):
        self.provider_name = provider_name

    @staticmethod
    def _normalize_tts_text(text: str) -> str:
        """
        전송 전 텍스트 줄바꿈을 정규화한다.
        - CRLF/CR -> LF
        - 연속 빈 줄 축약
        - 줄 앞뒤 공백 정리
        """
        normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n")
        normalized_lines = [line.strip() for line in normalized.split("\n")]

        compact_lines = []
        prev_blank = False
        for line in normalized_lines:
            is_blank = (line == "")
            if is_blank and prev_blank:
                continue
            compact_lines.append(line)
            prev_blank = is_blank

        return "\n".join(compact_lines).strip()

    @staticmethod
    def _normalize_base_url(url: str, fallback: str) -> str:
        resolved = str(url or "").strip() or fallback
        return resolved.rstrip("/")

    @staticmethod
    def _pcm_to_wav_bytes(
        pcm_data: bytes,
        *,
        sample_rate: int = 44100,
        channels: int = 1,
        sample_width: int = 2,
    ) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_data)
        return buffer.getvalue()


class GPTSoVITSHTTPClient(BaseTTSClient):
    """GPT-SoVITS API 클라이언트."""

    def __init__(
        self,
        api_url: str = "http://127.0.0.1:9880",
        ref_audio_path: str = "assets/ref_audio/refvoice.wav",
        ref_text: str = "人間さんはどんな色が一番好き？ ん？ なんで聞いたかって？ ふふん～ 内緒",
        ref_language: str = "ja",
        target_language: str = "ja",
        speed_factor: float = 1.0,
        top_k: int = 15,
        top_p: float = 1.0,
        temperature: float = 1.0,
        text_split_method: str = "cut5",
    ):
        super().__init__("gpt_sovits_http")
        self.api_url = self._normalize_base_url(api_url, "http://127.0.0.1:9880")
        self.ref_audio_path = str(ref_audio_path or "").strip()
        self.ref_text = str(ref_text or "").strip()
        self.ref_language = str(ref_language or "ja").strip() or "ja"
        self.target_language = str(target_language or "ja").strip() or "ja"
        self.speed_factor = float(speed_factor or 1.0)
        self.top_k = int(top_k or 15)
        self.top_p = float(top_p or 1.0)
        self.temperature = float(temperature or 1.0)
        self.text_split_method = str(text_split_method or "cut5").strip() or "cut5"
        if self.text_split_method not in GPT_SOVITS_TEXT_SPLIT_METHODS:
            self.text_split_method = "cut5"

        print(f"[TTS][GPT-SoVITS] API: {self.api_url}")
        print(f"[TTS][GPT-SoVITS] Reference audio: {self.ref_audio_path}")

    async def generate_speech(self, text: str) -> bytes:
        normalized_text = self._normalize_tts_text(text)
        if not normalized_text:
            raise ValueError("Text cannot be empty")

        ref_path = Path(self.ref_audio_path)
        if not ref_path.exists():
            raise FileNotFoundError(f"Reference audio not found: {self.ref_audio_path}")

        params = {
            "text": normalized_text,
            "text_lang": self.target_language,
            "ref_audio_path": str(ref_path.absolute()),
            "prompt_text": self.ref_text,
            "prompt_lang": self.ref_language,
            "speed_factor": self.speed_factor,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "temperature": self.temperature,
            "text_split_method": self.text_split_method,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.api_url}/tts",
                    json=params,
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"TTS API error ({response.status}): {error_text}")
                    return await response.read()
        except asyncio.TimeoutError:
            raise RuntimeError("TTS API timeout - server may be offline")
        except aiohttp.ClientError as e:
            raise RuntimeError(f"TTS API connection error: {e}")

    def is_available(self) -> bool:
        return Path(self.ref_audio_path).exists()


class OpenAISpeechClient(BaseTTSClient):
    """OpenAI 계열 Audio Speech API 클라이언트."""

    def __init__(
        self,
        provider_name: str,
        *,
        api_url: str,
        api_key: str,
        model: str,
        voice: str,
        speed: float = 1.0,
        response_format: str = "wav",
        require_api_key: bool = True,
    ):
        super().__init__(provider_name)
        self.api_url = self._normalize_base_url(api_url, "https://api.openai.com/v1")
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip() or "tts-1"
        self.voice = str(voice or "").strip() or "alloy"
        self.speed = float(speed or 1.0)
        self.response_format = str(response_format or "wav").strip() or "wav"
        self.require_api_key = bool(require_api_key)
        print(f"[TTS][{self.provider_name}] API: {self.api_url} / model={self.model} / voice={self.voice}")

    async def generate_speech(self, text: str) -> bytes:
        normalized_text = self._normalize_tts_text(text)
        if not normalized_text:
            raise ValueError("Text cannot be empty")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "model": self.model,
            "input": normalized_text,
            "voice": self.voice,
            "response_format": self.response_format,
            "speed": max(0.25, min(self.speed, 4.0)),
        }

        endpoint = self.api_url if self.api_url.endswith("/audio/speech") else f"{self.api_url}/audio/speech"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=45),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"TTS API error ({response.status}): {error_text}")
                    return await response.read()
        except asyncio.TimeoutError:
            raise RuntimeError("TTS API timeout - server may be offline")
        except aiohttp.ClientError as e:
            raise RuntimeError(f"TTS API connection error: {e}")

    def is_available(self) -> bool:
        if not self.api_url:
            return False
        if self.require_api_key and not self.api_key:
            return False
        return bool(self.model and self.voice)


class ElevenLabsSpeechClient(BaseTTSClient):
    """ElevenLabs TTS 클라이언트."""

    def __init__(
        self,
        *,
        api_url: str,
        api_key: str,
        model: str,
        voice: str,
        speed: float = 1.0,
        stability: float = 0.5,
        similarity_boost: float = 0.75,
        style: float = 0.0,
        use_speaker_boost: bool = True,
        output_format: str = "pcm_44100",
    ):
        super().__init__("elevenlabs")
        self.api_url = self._normalize_base_url(api_url, "https://api.elevenlabs.io/v1")
        self.api_key = str(api_key or "").strip()
        self.model = str(model or "").strip() or "eleven_multilingual_v2"
        self.voice = str(voice or "").strip()
        self.speed = float(speed or 1.0)
        self.stability = float(stability or 0.5)
        self.similarity_boost = float(similarity_boost or 0.75)
        self.style = float(style or 0.0)
        self.use_speaker_boost = bool(use_speaker_boost)
        self.output_format = str(output_format or "pcm_44100").strip() or "pcm_44100"
        print(f"[TTS][ElevenLabs] API: {self.api_url} / model={self.model} / voice={self.voice}")

    async def generate_speech(self, text: str) -> bytes:
        normalized_text = self._normalize_tts_text(text)
        if not normalized_text:
            raise ValueError("Text cannot be empty")
        if not self.voice:
            raise ValueError("Voice ID cannot be empty")

        params = {"output_format": self.output_format}
        headers = {
            "Content-Type": "application/json",
            "xi-api-key": self.api_key,
        }
        payload = {
            "text": normalized_text,
            "model_id": self.model,
            "voice_settings": {
                "stability": max(0.0, min(self.stability, 1.0)),
                "similarity_boost": max(0.0, min(self.similarity_boost, 1.0)),
                "style": max(0.0, min(self.style, 1.0)),
                "use_speaker_boost": self.use_speaker_boost,
                "speed": max(0.5, min(self.speed, 2.0)),
            },
        }

        if self.api_url.endswith(f"/text-to-speech/{self.voice}"):
            endpoint = self.api_url
        else:
            endpoint = f"{self.api_url}/text-to-speech/{self.voice}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    params=params,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"TTS API error ({response.status}): {error_text}")
                    raw_audio = await response.read()
        except asyncio.TimeoutError:
            raise RuntimeError("TTS API timeout - server may be offline")
        except aiohttp.ClientError as e:
            raise RuntimeError(f"TTS API connection error: {e}")

        if self.output_format.lower() == "pcm_44100":
            return self._pcm_to_wav_bytes(raw_audio, sample_rate=44100)
        return raw_audio

    def is_available(self) -> bool:
        return bool(self.api_url and self.api_key and self.model and self.voice)


class BrowserSpeechClient(BaseTTSClient):
    """웹뷰의 speechSynthesis를 사용하는 테스트용 TTS 클라이언트."""

    uses_browser_playback = True

    def __init__(
        self,
        *,
        lang: str = "ja-JP",
        voice: str = "",
        rate: float = 1.0,
        pitch: float = 1.0,
        volume: float = 1.0,
    ):
        super().__init__("browser_speech")
        self.lang = str(lang or "ja-JP").strip() or "ja-JP"
        self.voice = str(voice or "").strip()
        self.rate = float(rate or 1.0)
        self.pitch = float(pitch or 1.0)
        self.volume = float(volume or 1.0)
        print(f"[TTS][Browser] lang={self.lang} / voice={self.voice or 'default'}")

    def build_request(self, text: str) -> dict:
        normalized_text = self._normalize_tts_text(text)
        if not normalized_text:
            raise ValueError("Text cannot be empty")
        return {
            "text": normalized_text,
            "lang": self.lang,
            "voice": self.voice,
            "rate": max(0.1, min(self.rate, 3.0)),
            "pitch": max(0.0, min(self.pitch, 2.0)),
            "volume": max(0.0, min(self.volume, 1.0)),
        }

    async def generate_speech(self, text: str) -> bytes:
        raise RuntimeError("Browser speech provider does not generate audio bytes directly")

    def is_available(self) -> bool:
        return True


def create_tts_client(provider: str, config: dict | None = None, api_key: str = "") -> TTSClientProtocol:
    normalized = str(provider or "").strip().lower() or "gpt_sovits_http"
    merged = get_tts_provider_defaults(normalized)
    if isinstance(config, dict):
        merged.update(config)

    if normalized == "gpt_sovits_http":
        return GPTSoVITSHTTPClient(
            api_url=str(merged.get("api_url", "http://127.0.0.1:9880")).strip(),
            ref_audio_path=str(merged.get("ref_audio_path", "assets/ref_audio/refvoice.wav")).strip(),
            ref_text=str(merged.get("ref_text", "")).strip(),
            ref_language=str(merged.get("ref_language", "ja")).strip() or "ja",
            target_language=str(merged.get("target_language", "ja")).strip() or "ja",
            speed_factor=float(merged.get("speed_factor", 1.0) or 1.0),
            top_k=int(merged.get("top_k", 15) or 15),
            top_p=float(merged.get("top_p", 1.0) or 1.0),
            temperature=float(merged.get("temperature", 1.0) or 1.0),
            text_split_method=str(merged.get("text_split_method", "cut5")).strip() or "cut5",
        )

    if normalized == "openai_audio_speech":
        return OpenAISpeechClient(
            "openai_audio_speech",
            api_url=str(merged.get("api_url", "https://api.openai.com/v1")).strip(),
            api_key=str(api_key or "").strip(),
            model=str(merged.get("model", "gpt-4o-mini-tts")).strip() or "gpt-4o-mini-tts",
            voice=str(merged.get("voice", "alloy")).strip() or "alloy",
            speed=float(merged.get("speed", 1.0) or 1.0),
            response_format=str(merged.get("response_format", "wav")).strip() or "wav",
            require_api_key=True,
        )

    if normalized == "openai_compatible_audio_speech":
        return OpenAISpeechClient(
            "openai_compatible_audio_speech",
            api_url=str(merged.get("api_url", "http://127.0.0.1:8000/v1")).strip(),
            api_key=str(api_key or "").strip(),
            model=str(merged.get("model", "tts-1")).strip() or "tts-1",
            voice=str(merged.get("voice", "alloy")).strip() or "alloy",
            speed=float(merged.get("speed", 1.0) or 1.0),
            response_format=str(merged.get("response_format", "wav")).strip() or "wav",
            require_api_key=False,
        )

    if normalized == "elevenlabs":
        return ElevenLabsSpeechClient(
            api_url=str(merged.get("api_url", "https://api.elevenlabs.io/v1")).strip(),
            api_key=str(api_key or "").strip(),
            model=str(merged.get("model", "eleven_multilingual_v2")).strip() or "eleven_multilingual_v2",
            voice=str(merged.get("voice", "")).strip(),
            speed=float(merged.get("speed", 1.0) or 1.0),
            stability=float(merged.get("stability", 0.5) or 0.5),
            similarity_boost=float(merged.get("similarity_boost", 0.75) or 0.75),
            style=float(merged.get("style", 0.0) or 0.0),
            use_speaker_boost=bool(merged.get("use_speaker_boost", True)),
            output_format=str(merged.get("output_format", "pcm_44100")).strip() or "pcm_44100",
        )

    if normalized == "browser_speech":
        return BrowserSpeechClient(
            lang=str(merged.get("lang", "ja-JP")).strip() or "ja-JP",
            voice=str(merged.get("voice", "")).strip(),
            rate=float(merged.get("rate", 1.0) or 1.0),
            pitch=float(merged.get("pitch", 1.0) or 1.0),
            volume=float(merged.get("volume", 1.0) or 1.0),
        )

    supported = ", ".join(sorted(TTS_PROVIDER_CATALOG.keys()))
    raise ValueError(f"지원하지 않는 TTS 공급자입니다: {normalized} (지원: {supported})")


# 하위 호환성을 위해 기존 이름을 유지한다.
TTSClient = GPTSoVITSHTTPClient

