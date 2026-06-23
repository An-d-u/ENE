"""
LLM 프롬프트 언어 설정 헬퍼.
"""

from __future__ import annotations

from ..core.i18n import resolve_language

SUPPORTED_PROMPT_LANGUAGES = ("ko", "en", "ja")
SUPPORTED_TTS_LANGUAGES = ("same_as_response", "ko", "en", "ja")


def _read_setting(settings_source, key: str, default=None):
    if settings_source is None:
        return default
    if isinstance(settings_source, dict):
        return settings_source.get(key, default)
    if hasattr(settings_source, "get"):
        try:
            return settings_source.get(key, default)
        except Exception:
            pass
    config = getattr(settings_source, "config", None)
    if isinstance(config, dict):
        return config.get(key, default)
    return default


def resolve_prompt_language(language: str | None = None, settings_source=None) -> str:
    value = language if language is not None else _read_setting(settings_source, "ui_language", None)
    if not value:
        return "ko"
    resolved = resolve_language(str(value))
    return resolved if resolved in SUPPORTED_PROMPT_LANGUAGES else "en"


def resolve_tts_language(settings_source=None, response_language: str | None = None) -> str:
    """설정에서 TTS 문장 언어를 읽고, same_as_response를 실제 응답 언어로 해석한다."""
    resolved_response_language = resolve_prompt_language(response_language, settings_source=settings_source)
    value = str(_read_setting(settings_source, "tts_language", "ja") or "ja").strip().lower()
    if value == "same_as_response":
        return resolved_response_language
    return value if value in SUPPORTED_PROMPT_LANGUAGES else "ja"
