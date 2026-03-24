import json
from codecs import BOM_UTF8
from pathlib import Path
import sys

from src.core.i18n import (
    I18n,
    configure_i18n,
    get_default_locales_dir,
    load_locale_file,
    resolve_language,
    tr,
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


def test_explicit_language_selection_wins_over_system_locale(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        '{"language.name": "English"}',
        encoding="utf-8-sig",
    )
    (locales_dir / "ja.json").write_text(
        '{"language.name": "日本語"}',
        encoding="utf-8-sig",
    )

    i18n = I18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    assert i18n.language == "ja"
    assert i18n.t("language.name") == "日本語"


def test_translation_formats_placeholders(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        '{"count.items": "{count} items"}',
        encoding="utf-8-sig",
    )

    i18n = I18n(language="en", locales_dir=locales_dir)

    assert i18n.t("count.items", count=3) == "3 items"


def test_translation_placeholder_mismatch_falls_back_safely(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        '{"count.items": "{count} items"}',
        encoding="utf-8-sig",
    )

    i18n = I18n(language="en", locales_dir=locales_dir)

    assert i18n.t("count.items") == "{count} items"


def test_nested_dotted_key_lookup(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        '{"settings": {"window": {"title": "Settings"}}}',
        encoding="utf-8-sig",
    )

    i18n = I18n(language="en", locales_dir=locales_dir)

    assert i18n.t("settings.window.title") == "Settings"


def test_malformed_locale_json_degrades_safely(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        '{"valid.key": "ok"}',
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text(
        '{"broken.key": ',
        encoding="utf-8-sig",
    )

    i18n = I18n(language="ko", locales_dir=locales_dir)

    assert i18n.t("valid.key") == "ok"
    assert i18n.t("broken.key") == "broken.key"


def test_locale_file_read_problem_degrades_safely(monkeypatch, tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    unreadable = locales_dir / "ko.json"
    unreadable.write_text('{"hello": "안녕하세요"}', encoding="utf-8-sig")

    real_open = open

    def failing_open(path, *args, **kwargs):
        if Path(path) == unreadable:
            raise OSError("read failed")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", failing_open)

    i18n = I18n(language="ko", locales_dir=locales_dir)
    assert i18n.t("hello") == "hello"


def test_default_locales_dir_prefers_meipass(monkeypatch, tmp_path):
    frozen_root = tmp_path / "bundle"
    (frozen_root / "src" / "locales").mkdir(parents=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(frozen_root), raising=False)

    assert get_default_locales_dir() == frozen_root / "src" / "locales"


def test_runtime_language_switch_reloads_catalog_and_uses_fallback(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        json.dumps(
            {
                "tray.settings": "Settings",
                "obsidian.error.connection_failed": "Connection failed: {error}",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text(
        json.dumps(
            {
                "tray.settings": "설정",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )
    (locales_dir / "ja.json").write_text("{}", encoding="utf-8-sig")

    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="en_US")

    assert tr("tray.settings") == "설정"
    assert tr("obsidian.error.connection_failed", error="boom") == "Connection failed: boom"

    (locales_dir / "ko.json").write_text(
        json.dumps(
            {
                "tray.settings": "환경설정",
                "obsidian.error.connection_failed": "연결 실패: {error}",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="en_US")

    assert tr("tray.settings") == "환경설정"
    assert tr("obsidian.error.connection_failed", error="boom") == "연결 실패: boom"
