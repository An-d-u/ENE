"""원본 로그와 별도로, 공개를 허용한 값만 담은 진단 기록을 만든다."""

import json
from pathlib import Path
import sys
from typing import Iterator


# 사용자 설정이나 플러그인이 추가한 식별자를 공개 목록으로 사용하지 않는다.
_PUBLIC_MODELS = {
    "llm": {
        "gemini": ("gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-pro"),
        "openai": ("gpt-4o-mini", "gpt-4o", "gpt-4.1", "gpt-4.1-mini", "gpt-5", "gpt-5-mini"),
        "anthropic": ("claude-sonnet-4-6", "claude-3-5-sonnet-latest"),
        "openrouter": ("openai/gpt-4o-mini",),
        "deepseek": ("deepseek-chat", "deepseek-reasoner"),
        "ollama": ("llama3.1",),
        "custom_api": (),
    },
    "tts": {
        "gpt_sovits_http": (),
        "genie_tts_http": (),
        "openai_audio_speech": ("gpt-4o-mini-tts", "tts-1", "tts-1-hd"),
        "openai_compatible_audio_speech": (),
        "elevenlabs": ("eleven_multilingual_v2", "eleven_turbo_v2_5", "eleven_flash_v2_5"),
        "fish_audio": ("s2.1-pro", "s2.1-pro-free", "s2-pro", "s1"),
    },
}


def _error_category(code, error_type):
    if code == 429:
        return "rate_limit"
    if code in (401, 403):
        return "authorization"
    if code in (408, 504) or error_type in ("Timeout", "TimeoutError", "ReadTimeout", "ConnectTimeout"):
        return "timeout"
    if code is not None:
        return "http_error"
    if error_type in ("ConnectionError", "ClientConnectionError", "ClientConnectorError"):
        return "connection"
    return "other"


def _shareable_result(event) -> dict | None:
    if not isinstance(event, dict) or event.get("event") != "result":
        return None
    stage = event.get("stage")
    status = event.get("status")
    if stage not in ("llm", "tts") or status not in ("success", "error", "cancelled"):
        return None

    row = {"stage": stage, "status": status}
    provider = event.get("provider")
    if isinstance(provider, str) and provider in _PUBLIC_MODELS[stage]:
        row["provider"] = provider
        model = event.get("model")
        if model in _PUBLIC_MODELS[stage][provider]:
            row["model"] = model

    seconds = event.get("elapsed_seconds")
    if type(seconds) in (int, float) and 0 <= seconds <= sys.float_info.max:
        row["elapsed_seconds"] = round(seconds, 3)
    code = event.get("status_code")
    if type(code) is int and 100 <= code <= 599:
        row["status_code"] = code
    if status == "error":
        row["error_category"] = _error_category(row.get("status_code"), event.get("error_type"))
    return row


def diagnostic_records(path: Path) -> Iterator[dict | None]:
    """열었을 때의 파일 끝까지만 읽고, 한 줄씩 처리해 UI에 제어를 돌려준다."""
    with path.open("rb") as stream:
        end = stream.seek(0, 2)
        stream.seek(0)
        while stream.tell() < end:
            line = stream.readline(end - stream.tell())
            if not line:
                break
            try:
                row = _shareable_result(json.loads(line))
            except (ValueError, RecursionError):
                row = None
            yield row
