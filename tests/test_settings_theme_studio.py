import pytest

from src.core.system_theme import THEME_VARIANT_PRESETS
from tests.test_ui_i18n_smoke import _stub_prompt_module


@pytest.fixture
def theme_dialog(tmp_path, monkeypatch):
    monkeypatch.setenv("ENE_USER_DATA_DIR", str(tmp_path))
    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr("src.ui.settings_dialog.tiktoken", None)
        colors = THEME_VARIANT_PRESETS["light"]["light_sand"]["colors"]
        dialog = SettingsDialog({"ui_language": "ko", "theme_mode": "light", **colors})
        yield dialog
        dialog.close()


def test_mode_shows_three_matching_palettes_and_preserves_draft(theme_dialog, monkeypatch):
    dialog = theme_dialog
    assert getattr(dialog, "theme_palette_name", None) is not None
    assert dialog.theme_palette_name.text() == "웜 샌드"
    assert not dialog._theme_variant_frames["light_sand"].isHidden()
    assert dialog._theme_variant_frames["dark_forest"].isHidden()
    dialog._theme_preset_frames["dark"].click()
    dialog._theme_variant_frames["dark_forest"].click()
    assert dialog.theme_palette_name.text() == "딥 포레스트"
    assert dialog._theme_variant_frames["light_sand"].isHidden()
    dialog._theme_preset_frames["light"].click()
    assert dialog.theme_palette_name.text() == "웜 샌드"
    monkeypatch.setattr("src.ui.settings_dialog_theme.get_windows_theme_mode", lambda: "dark")
    dialog.follow_system_theme_check.click()
    assert dialog._get_current_values()["follow_system_theme"]
    assert not dialog.theme_edit_button.isEnabled()
    assert not dialog._theme_variant_frames["dark_forest"].isHidden()
    dialog._theme_variant_frames["dark_graphite"].click()
    assert not dialog._get_current_values()["follow_system_theme"]
    assert dialog.theme_edit_button.isEnabled()


def test_color_editor_cancel_apply_and_preset_reset(theme_dialog):
    dialog = theme_dialog
    assert getattr(dialog, "theme_edit_button", None) is not None
    key = "chat_user_bubble_color"
    original = THEME_VARIANT_PRESETS["light"]["light_sand"]["colors"][key]
    edit = dialog._theme_color_edits[key]
    dialog.theme_edit_button.click()
    assert dialog.theme_color_dialog.isVisible()
    edit.setText("#112233")
    assert dialog._get_current_values()[key] == original
    dialog.theme_color_dialog.reject()
    assert edit.text() == original
    dialog.theme_edit_button.click()
    edit.setText("#12")
    assert not dialog.theme_color_apply_button.isEnabled()
    edit.setText("#123456")
    dialog.theme_color_apply_button.click()
    assert dialog._get_current_values()[key] == "#123456"
    assert "#123456" in dialog.theme_chat_user.styleSheet()
    dialog.theme_edit_button.click()
    dialog._theme_color_reset_buttons[key].click()
    assert edit.text() == original
    dialog.theme_color_apply_button.click()
    assert dialog._get_current_values()[key] == original


def test_saved_custom_palette_survives_mode_switch_and_save(theme_dialog):
    dialog = theme_dialog
    key = "chat_panel_bg_color"
    dialog._original_settings[key] = "#223344"
    dialog._load_values()
    assert dialog.theme_palette_name.text() == "사용자 지정"
    dialog._theme_preset_frames["dark"].click()
    dialog._theme_preset_frames["light"].click()
    assert dialog._get_current_values()[key] == "#223344"
    saved = []
    dialog.settings_changed.connect(saved.append)
    dialog._settings_save_handler = lambda values, baseline: {"status": "accepted", "values": values}
    dialog._save_settings()
    assert saved[0][key] == "#223344"
