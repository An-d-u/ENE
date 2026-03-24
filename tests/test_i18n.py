import json
from codecs import BOM_UTF8
from pathlib import Path
import sys

from src.core.i18n import (
    I18n,
    get_default_locales_dir,
    load_locale_file,
    resolve_language,
)


def test_resolve_language_auto_uses_system_locale_code():
    assert resolve_language("auto", "ko-KR") == "ko"
    assert resolve_language("auto", "en_US") == "en"
    assert resolve_language("auto", "ja-JP") == "ja"
    assert resolve_language("auto", "de-DE") == "en"
    assert resolve_language("auto", "Korean_Korea") == "ko"
    assert resolve_language("auto", "Japanese_Japan") == "ja"
    assert resolve_language("auto", "English_United States") == "en"


def test_load_locale_file_supports_utf8_bom(tmp_path):
    locale_path = tmp_path / "ko.json"
    locale_path.write_bytes(BOM_UTF8 + json.dumps({"hello": "안녕하세요"}, ensure_ascii=False).encode("utf-8"))

    assert load_locale_file(locale_path) == {"hello": "안녕하세요"}


def test_translation_falls_back_to_english_then_key_string(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        '{"fallback.only": "English fallback", "count.items": "{count} items"}',
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text('{"other.key": "값"}', encoding="utf-8-sig")

    i18n = I18n(language="ko", locales_dir=locales_dir)

    assert i18n.t("fallback.only") == "English fallback"
    assert i18n.t("missing.key") == "missing.key"


def test_translation_formats_placeholders(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        '{"count.items": "{count} items"}',
        encoding="utf-8-sig",
    )

    i18n = I18n(language="en", locales_dir=locales_dir)

    assert i18n.t("count.items", count=3) == "3 items"


def test_default_locales_dir_prefers_meipass(monkeypatch, tmp_path):
    frozen_root = tmp_path / "bundle"
    (frozen_root / "src" / "locales").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)

    assert get_default_locales_dir() == frozen_root / "src" / "locales"
