"""
런타임 프롬프트에 넣을 동적 설정 값을 조립한다.
"""

from __future__ import annotations


def _settings_to_dict(settings_source: object | None) -> dict:
    if settings_source is None:
        return {}
    if isinstance(settings_source, dict):
        return dict(settings_source)
    config = getattr(settings_source, "config", None)
    if isinstance(config, dict):
        return dict(config)
    getter = getattr(settings_source, "get", None)
    if callable(getter):
        try:
            from ..core.settings import Settings

            keys = list(Settings.DEFAULT_CONFIG.keys())
        except Exception:
            keys = [
                "ui_language",
                "tts_language",
                "enable_ene_goals",
                "enable_ene_thoughts",
                "enable_proactive_conversation",
                "assistant_display_name",
                "user_address_name",
                "model_json_path",
            ]
        values = {}
        for key in keys:
            try:
                values[key] = getter(key, None)
            except TypeError:
                try:
                    values[key] = getter(key)
                except Exception:
                    continue
            except Exception:
                continue
        return values
    return {}


def build_runtime_prompt_settings_source(
    settings_source: object | None,
    *,
    proactive_manager: object | None = None,
) -> object | None:
    """정적 설정에 현재 선제 대화 쿨다운 상태를 합쳐 프롬프트 빌더에 넘긴다."""
    available_keys = None
    getter = getattr(proactive_manager, "available_cooldown_keys", None)
    if callable(getter):
        try:
            available_keys = list(getter())
        except Exception:
            available_keys = None
    if available_keys is None:
        return settings_source

    merged = _settings_to_dict(settings_source)
    merged["proactive_available_cooldown_keys"] = available_keys
    return merged
