from pathlib import Path

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtWidgets import QApplication, QMessageBox

from src.ai import prompt_config
from src.core.i18n import configure_i18n


QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
_QAPP = None


def _get_qapp():
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    return _QAPP


@pytest.fixture
def prompt_paths(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "prompts"
    default_dir = tmp_path / "defaults"
    runtime_dir.mkdir()
    default_dir.mkdir()
    for filename, content in {
        "base_system_prompt.md": "기본 시스템 지침",
        "sub_prompt_body.md": "보조 지침",
        "emotion_guides.md": "### [감정 사용 가이드]\n- normal: 기본 상태",
        "life_world.md": "# 조용한 해안 마을\n\n등대와 작은 서점이 있다.",
    }.items():
        (runtime_dir / filename).write_text(content, encoding="utf-8")
        (default_dir / filename).write_text(content, encoding="utf-8")

    mappings = {
        "PROMPT_CONFIG_DIR": runtime_dir,
        "DEFAULT_PROMPT_CONFIG_DIR": default_dir,
        "BASE_SYSTEM_PROMPT_PATH": runtime_dir / "base_system_prompt.md",
        "SUB_PROMPT_BODY_PATH": runtime_dir / "sub_prompt_body.md",
        "EMOTION_GUIDES_PATH": runtime_dir / "emotion_guides.md",
        "LIFE_WORLD_PROMPT_PATH": runtime_dir / "life_world.md",
        "DEFAULT_BASE_SYSTEM_PROMPT_PATH": default_dir / "base_system_prompt.md",
        "DEFAULT_SUB_PROMPT_BODY_PATH": default_dir / "sub_prompt_body.md",
        "DEFAULT_EMOTION_GUIDES_PATH": default_dir / "emotion_guides.md",
        "DEFAULT_LIFE_WORLD_PROMPT_PATH": default_dir / "life_world.md",
    }
    for name, value in mappings.items():
        monkeypatch.setattr(prompt_config, name, value)
    return runtime_dir, default_dir


def _dialog(prompt_paths, monkeypatch, settings=None):
    _get_qapp()
    configure_i18n(
        language="ko",
        locales_dir=Path(__file__).resolve().parents[1] / "src" / "locales",
        system_locale="ko_KR",
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    from src.ui.settings_dialog import SettingsDialog

    dialog = SettingsDialog(
        {
            "ui_language": "ko",
            "llm_provider": "gemini",
            "tts_provider": "gpt_sovits_http",
            "enable_tts": False,
            **(settings or {}),
        }
    )
    return dialog


def test_life_record_behavior_defaults_and_roundtrip(prompt_paths, monkeypatch):
    dialog = _dialog(prompt_paths, monkeypatch)
    assert dialog.enable_life_records_check.isChecked() is False
    assert dialog._life_record_min_inactive_label.isEnabled() is False
    assert dialog.life_record_min_inactive_minutes_spin.isEnabled() is False
    assert dialog.life_record_min_inactive_minutes_spin.minimum() == 1
    assert dialog.life_record_min_inactive_minutes_spin.value() == 60

    dialog.enable_life_records_check.setChecked(True)
    assert dialog._life_record_min_inactive_label.isEnabled() is True
    assert dialog.life_record_min_inactive_minutes_spin.isEnabled() is True
    dialog.life_record_min_inactive_minutes_spin.setValue(95)
    values = dialog._get_current_values()
    dialog.close()

    reopened = _dialog(prompt_paths, monkeypatch, values)
    assert reopened.enable_life_records_check.isChecked() is True
    assert reopened.life_record_min_inactive_minutes_spin.isEnabled() is True
    assert reopened.life_record_min_inactive_minutes_spin.value() == 95
    reopened.close()


def test_life_world_editor_is_full_width_accessible_and_persists_empty(prompt_paths, monkeypatch):
    runtime_dir, _default_dir = prompt_paths
    dialog = _dialog(prompt_paths, monkeypatch)
    dialog.focus_section("prompt")

    editor = dialog.life_world_editor
    assert dialog._life_world_path_label.text() == str(runtime_dir / "life_world.md")
    assert editor.accessibleName()
    assert dialog._life_world_label.buddy() is editor
    assert dialog._life_world_group.property("fullWidth") is True
    assert dialog._life_world_token_label.text()

    editor.setPlainText("")
    dialog._save_prompt_configuration()
    assert (runtime_dir / "life_world.md").read_bytes() == b""
    assert dialog._life_world_warning_label.isVisibleTo(dialog._life_world_group)
    assert dialog._life_world_warning_label.text()
    dialog.close()


def test_life_world_default_button_only_reloads_editor(prompt_paths, monkeypatch):
    runtime_dir, default_dir = prompt_paths
    runtime_path = runtime_dir / "life_world.md"
    default_path = default_dir / "life_world.md"
    runtime_path.write_text("사용자 작성 환경", encoding="utf-8")
    default_path.write_text("기본 제공 환경", encoding="utf-8")

    dialog = _dialog(prompt_paths, monkeypatch)
    dialog.focus_section("prompt")
    dialog.life_world_editor.setPlainText("")
    dialog._load_default_life_world_prompt()

    assert dialog.life_world_editor.toPlainText() == "기본 제공 환경"
    assert runtime_path.read_text(encoding="utf-8") == "사용자 작성 환경"
    dialog.close()


def test_life_world_default_read_failure_preserves_editor_and_shows_safe_status(
    prompt_paths, monkeypatch
):
    _runtime_dir, default_dir = prompt_paths
    dialog = _dialog(prompt_paths, monkeypatch)
    dialog.focus_section("prompt")
    dialog.life_world_editor.setPlainText("현재 편집 중인 환경")
    (default_dir / "life_world.md").unlink()

    dialog._load_default_life_world_prompt()

    assert dialog.life_world_editor.toPlainText() == "현재 편집 중인 환경"
    assert dialog._prompt_status_label.text() == "생활 환경 기본값을 불러오지 못했습니다."
    dialog.close()


def test_life_record_controls_have_accessible_names_and_buddy(prompt_paths, monkeypatch):
    dialog = _dialog(prompt_paths, monkeypatch)
    assert dialog.enable_life_records_check.accessibleName()
    assert dialog.life_record_min_inactive_minutes_spin.accessibleName()
    assert dialog._life_record_min_inactive_label.buddy() is dialog.life_record_min_inactive_minutes_spin
    dialog.close()


def test_settings_geometry_clamps_to_1024_by_768_available_screen(prompt_paths, monkeypatch):
    from src.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr(SettingsDialog, "_available_screen_geometry", lambda self: QRect(0, 0, 1024, 768))
    dialog = _dialog(prompt_paths, monkeypatch)

    assert dialog.minimumWidth() <= 1024
    assert dialog.minimumHeight() <= 768
    assert dialog.width() <= 1024
    assert dialog.height() <= 768
    assert QRect(0, 0, 1024, 768).contains(dialog.frameGeometry())
    dialog.close()


@pytest.mark.parametrize("available", [QRect(0, 0, 1024, 768), QRect(0, 0, 1280, 720)])
def test_prompt_tab_has_no_horizontal_overflow_at_supported_sizes(
    prompt_paths, monkeypatch, available
):
    from src.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr(SettingsDialog, "_available_screen_geometry", lambda self: available)
    dialog = _dialog(prompt_paths, monkeypatch)
    dialog.show()
    dialog.focus_section("prompt")
    dialog._prompt_path_label.setText("C:/" + ("very-long-runtime-folder/" * 20) + "base.md")
    dialog._sub_prompt_path_label.setText("C:/" + ("long-folder/" * 20) + "sub.md")
    dialog._life_world_path_label.setText("C:/" + ("world-folder/" * 20) + "life.md")
    _get_qapp().processEvents()

    assert dialog._prompt_scroll.horizontalScrollBar().maximum() == 0
    assert dialog._prompt_content.width() <= dialog._prompt_scroll.viewport().width()
    assert dialog.life_world_editor.viewport().width() > 0
    item_index = dialog._prompt_grid.indexOf(dialog._life_world_group)
    _row, column, _row_span, column_span = dialog._prompt_grid.getItemPosition(item_index)
    assert (column, column_span) == (0, 2)
    dialog.close()


@pytest.mark.parametrize("failed_position", [1, 2, 3, 4])
def test_prompt_bundle_save_rolls_back_every_file_on_each_write_failure(
    prompt_paths, monkeypatch, failed_position
):
    runtime_dir, _default_dir = prompt_paths
    dialog = _dialog(prompt_paths, monkeypatch)
    dialog.focus_section("prompt")
    paths = [
        runtime_dir / "base_system_prompt.md",
        runtime_dir / "sub_prompt_body.md",
        runtime_dir / "emotion_guides.md",
        runtime_dir / "life_world.md",
    ]
    before = {path: path.read_bytes() for path in paths}
    dialog.base_prompt_editor.setPlainText("새 시스템 지침")
    dialog.sub_prompt_editor.setPlainText("새 보조 지침")
    dialog.life_world_editor.setPlainText("새 생활 환경")

    original_replace = prompt_config._replace_prompt_bundle_file
    calls = 0

    def fail_at_position(source, target):
        nonlocal calls
        calls += 1
        if calls == failed_position:
            raise OSError("synthetic_write_failure")
        original_replace(source, target)

    monkeypatch.setattr(prompt_config, "_replace_prompt_bundle_file", fail_at_position)
    dialog._save_prompt_configuration()

    assert {path: path.read_bytes() for path in paths} == before
    assert dialog._prompt_status_label.text().startswith("저장 실패:")
    assert "synthetic_write_failure" not in dialog._prompt_status_label.text()
    dialog.close()


def test_prompt_bundle_staging_failure_leaves_no_partial_files_or_temps(
    prompt_paths, monkeypatch
):
    runtime_dir, _default_dir = prompt_paths
    paths = [
        runtime_dir / "base_system_prompt.md",
        runtime_dir / "sub_prompt_body.md",
        runtime_dir / "emotion_guides.md",
        runtime_dir / "life_world.md",
    ]
    before = {path: path.read_bytes() for path in paths}
    original_stage = prompt_config._stage_prompt_bundle_file
    calls = 0

    def fail_third_stage(path, payload):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError("synthetic_stage_failure")
        return original_stage(path, payload)

    monkeypatch.setattr(prompt_config, "_stage_prompt_bundle_file", fail_third_stage)
    with pytest.raises(RuntimeError, match="prompt_bundle_save_failed"):
        prompt_config.save_prompt_bundle(
            {
                "base_system_prompt": "새 시스템 지침",
                "sub_prompt_body": "새 보조 지침",
                "emotions": ["normal"],
                "emotion_guides": {"normal": "기본 상태"},
            },
            "새 생활 환경",
        )

    assert {path: path.read_bytes() for path in paths} == before
    assert list(runtime_dir.glob(".*.tmp")) == []


def test_store_visible_life_write_failure_rolls_back_visible_and_runtime_bundle(
    prompt_paths, monkeypatch, tmp_path
):
    runtime_dir, _default_dir = prompt_paths
    visible_dir = tmp_path / "visible" / "prompts"
    visible_dir.mkdir(parents=True)
    runtime_paths = [
        runtime_dir / "base_system_prompt.md",
        runtime_dir / "sub_prompt_body.md",
        runtime_dir / "emotion_guides.md",
        runtime_dir / "life_world.md",
    ]
    for path in runtime_paths:
        (visible_dir / path.name).write_bytes(path.read_bytes())
    runtime_before = {path: path.read_bytes() for path in runtime_paths}
    visible_before = {
        path: path.read_bytes()
        for path in visible_dir.iterdir()
    }
    monkeypatch.setattr(prompt_config, "_should_sync_store_python_prompt_dirs", lambda: True)
    monkeypatch.setattr(prompt_config, "_get_visible_prompt_config_dir", lambda: visible_dir)
    monkeypatch.setattr(
        prompt_config,
        "_read_prompt_file_via_powershell",
        lambda path: path.read_bytes() if path.exists() else None,
    )
    calls = 0

    def visible_write(path, payload):
        nonlocal calls
        calls += 1
        if calls == 4:
            raise OSError("synthetic_visible_life_failure")
        path.write_bytes(payload)

    monkeypatch.setattr(prompt_config, "_write_prompt_file_via_powershell", visible_write)
    monkeypatch.setattr(
        prompt_config,
        "_delete_prompt_file_via_powershell",
        lambda path: path.unlink(missing_ok=True),
    )
    dialog = _dialog(prompt_paths, monkeypatch)
    dialog.focus_section("prompt")
    dialog.base_prompt_editor.setPlainText("새 시스템 지침")
    dialog.sub_prompt_editor.setPlainText("새 보조 지침")
    dialog.life_world_editor.setPlainText("새 생활 환경")

    dialog._save_prompt_configuration()

    assert {path: path.read_bytes() for path in runtime_paths} == runtime_before
    assert {path: path.read_bytes() for path in visible_dir.iterdir()} == visible_before
    assert "synthetic_visible_life_failure" not in dialog._prompt_status_label.text()
    dialog.close()


def test_life_record_locale_keys_are_nonempty_in_all_languages():
    from src.core.i18n import I18n

    locale_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    required = {
        "settings.behavior.life_records.title",
        "settings.behavior.life_records.enable",
        "settings.behavior.life_records.min_inactive.label",
        "settings.behavior.life_records.min_inactive.suffix",
        "settings.behavior.life_records.hint",
        "settings.prompt.life_world.title",
        "settings.prompt.life_world.label",
        "settings.prompt.life_world.default",
        "settings.prompt.life_world.empty_warning",
        "settings.prompt.life_world.accessible_name",
    }
    for language in ("ko", "en", "ja"):
        i18n = I18n(language=language, locales_dir=locale_dir)
        assert all(i18n.t(key) != key and i18n.t(key).strip() for key in required)
