"""
ENE UI i18n helper.
"""
from __future__ import annotations

import json
import locale as locale_module
import sys
from pathlib import Path
from typing import Any


SUPPORTED_UI_LANGUAGES = ("ko", "en", "ja")

WINDOWS_LANGUAGE_ALIASES = {
    "korean": "ko",
    "japanese": "ja",
    "english": "en",
}


def normalize_locale_code(value: str | None) -> str:
    if not value:
        return ""
    normalized = str(value).strip().replace("_", "-")
    if not normalized:
        return ""
    primary = normalized.split("-", 1)[0].lower()
    return WINDOWS_LANGUAGE_ALIASES.get(primary, primary)


def resolve_language(ui_language: str | None, system_locale: str | None = None) -> str:
    normalized_ui_language = normalize_locale_code(ui_language)
    if normalized_ui_language and normalized_ui_language != "auto":
        return normalized_ui_language if normalized_ui_language in SUPPORTED_UI_LANGUAGES else "en"

    normalized_system_locale = normalize_locale_code(system_locale)
    if normalized_system_locale in SUPPORTED_UI_LANGUAGES:
        return normalized_system_locale
    return "en"


def load_locale_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            loaded = json.load(f)
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def get_default_locales_dir() -> Path:
    explicit_root = getattr(sys, "_MEIPASS", None)
    if explicit_root:
        frozen_root = Path(explicit_root)
        src_locales = frozen_root / "src" / "locales"
        if src_locales.exists():
            return src_locales
        bundled_locales = frozen_root / "locales"
        if bundled_locales.exists():
            return bundled_locales

    # 배포 번들은 `src/locales/*.json` 또는 번들 루트의 `locales` 디렉터리를 반드시 포함해야 한다.
    # 이 저장소에는 PyInstaller spec/build 파일이 추적되어 있지 않기 때문에,
    # 런타임에서는 위 두 배포 레이아웃과 소스 트리 레이아웃을 모두 순서대로 확인한다.
    return Path(__file__).resolve().parents[1] / "locales"


def resolve_locales_dir(locales_dir: str | Path | None = None) -> Path:
    if locales_dir is not None:
        return Path(locales_dir)
    return get_default_locales_dir()


def _get_system_locale() -> str | None:
    try:
        system_locale, _ = locale_module.getlocale()
    except ValueError:
        system_locale = None
    if not system_locale:
        system_locale = locale_module.setlocale(locale_module.LC_CTYPE, None)
    return system_locale


def _lookup_nested(data: dict[str, Any], key: str) -> Any:
    if key in data:
        return data[key]
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


class I18n:
    def __init__(
        self,
        language: str = "auto",
        locales_dir: str | Path | None = None,
        system_locale: str | None = None,
    ):
        self.locales_dir = resolve_locales_dir(locales_dir)
        self.language = resolve_language(language, system_locale or _get_system_locale())
        self.translations: dict[str, dict[str, Any]] = {}
        self._load_supported_languages()

    def _load_supported_languages(self) -> None:
        for language in SUPPORTED_UI_LANGUAGES:
            self.translations[language] = load_locale_file(self.locales_dir / f"{language}.json")

    def t(self, key: str, **kwargs: Any) -> str:
        value = _lookup_nested(self.translations.get(self.language, {}), key)
        if value is None:
            value = _lookup_nested(self.translations.get("en", {}), key)
        if value is None:
            return key

        if isinstance(value, str) and kwargs:
            try:
                return value.format(**kwargs)
            except Exception:
                return value
        return str(value)


_runtime_i18n: I18n | None = None


def configure_i18n(
    language: str = "auto",
    locales_dir: str | Path | None = None,
    system_locale: str | None = None,
) -> I18n:
    global _runtime_i18n

    resolved_locales_dir = locales_dir
    if resolved_locales_dir is None and _runtime_i18n is not None:
        resolved_locales_dir = _runtime_i18n.locales_dir

    _runtime_i18n = I18n(
        language=language,
        locales_dir=resolved_locales_dir,
        system_locale=system_locale,
    )
    return _runtime_i18n


def get_i18n() -> I18n:
    global _runtime_i18n
    if _runtime_i18n is None:
        _runtime_i18n = I18n()
    return _runtime_i18n


def tr(key: str, **kwargs: Any) -> str:
    return get_i18n().t(key, **kwargs)
