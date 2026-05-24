"""
프롬프트 안에서 사용할 캐릭터/사용자 호칭을 해석한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from .prompt_language import resolve_prompt_language


@dataclass(frozen=True)
class PromptPersonaNames:
    assistant: str
    user: str


def _read_setting(settings_source, key: str, default=None):
    if settings_source is None:
        return default
    if isinstance(settings_source, dict):
        return settings_source.get(key, default)
    getter = getattr(settings_source, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except Exception:
            pass
    config = getattr(settings_source, "config", None)
    if isinstance(config, dict):
        return config.get(key, default)
    return default


def default_prompt_persona_names(language: str | None = None) -> PromptPersonaNames:
    resolved_language = resolve_prompt_language(language)
    defaults = {
        "ko": PromptPersonaNames(assistant="에네", user="마스터"),
        "en": PromptPersonaNames(assistant="ENE", user="Master"),
        "ja": PromptPersonaNames(assistant="エネ", user="マスター"),
    }
    return defaults[resolved_language]


def _has_korean_final_consonant(text: str) -> bool | None:
    value = str(text or "").strip()
    if not value:
        return None
    code = ord(value[-1])
    if 0xAC00 <= code <= 0xD7A3:
        return (code - 0xAC00) % 28 != 0
    return None


def korean_subject_particle(text: str) -> str:
    has_final = _has_korean_final_consonant(text)
    return "이" if has_final else "가"


def korean_with_and_particle(text: str) -> str:
    has_final = _has_korean_final_consonant(text)
    return "과" if has_final else "와"


def resolve_prompt_persona_names(settings_source=None, language: str | None = None) -> PromptPersonaNames:
    resolved_language = resolve_prompt_language(language, settings_source=settings_source)
    defaults = default_prompt_persona_names(resolved_language)
    assistant_name = str(_read_setting(settings_source, "assistant_display_name", "") or "").strip()
    user_name = str(_read_setting(settings_source, "user_address_name", "") or "").strip()
    return PromptPersonaNames(
        assistant=assistant_name or defaults.assistant,
        user=user_name or defaults.user,
    )


def role_label_for_prompt(role: str, settings_source=None, language: str | None = None) -> str:
    normalized = str(role or "").strip().lower()
    names = resolve_prompt_persona_names(settings_source=settings_source, language=language)
    if normalized == "assistant":
        return names.assistant
    if normalized == "user":
        return names.user
    return normalized
