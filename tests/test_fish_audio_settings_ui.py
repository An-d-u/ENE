from pathlib import Path

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QLineEdit

from src.ai import prompt_config
from src.core.i18n import configure_i18n


QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
_QAPP = None


@pytest.fixture
def dialog_factory(tmp_path, monkeypatch):
    global _QAPP
    _QAPP = QApplication.instance() or QApplication([])
    from src.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)
    monkeypatch.setattr("src.ai.prompt.get_available_emotions", lambda: ["normal"])
    monkeypatch.setattr("src.ui.settings_dialog.get_user_data_dir", lambda: tmp_path)
    monkeypatch.setattr("src.ui.settings_dialog.get_user_file", lambda name: tmp_path / name)
    monkeypatch.setattr("src.ui.settings_dialog_tts.AudioPlayer.list_output_devices", lambda: [])
    for name in ("BASE_SYSTEM_PROMPT_PATH", "SUB_PROMPT_BODY_PATH", "LIFE_WORLD_PROMPT_PATH"):
        monkeypatch.setattr(prompt_config, name, tmp_path / (name + ".md"))
    configure_i18n(language="ko", locales_dir=Path(__file__).resolve().parents[1] / "src" / "locales", system_locale="ko_KR")
    dialogs = []

    def create(values=None):
        dialog = SettingsDialog({"ui_language": "ko", "enable_tts": True, **(values or {})})
        dialogs.append(dialog)
        dialog._set_section_index(4)
        return dialog

    yield create
    for dialog in dialogs:
        dialog.close()


def test_fish_audio_selection_shows_masked_key_below_provider(dialog_factory):
    dialog = dialog_factory()
    index = dialog.tts_provider_combo.findData("fish_audio")
    assert index >= 0
    assert not dialog.tts_fish_api_key_edit.isVisibleTo(dialog)
    dialog.tts_provider_combo.setCurrentIndex(index)
    assert dialog.tts_provider_stack.currentWidget() is dialog._tts_provider_pages["fish_audio"]
    assert dialog.tts_fish_api_key_edit.isVisibleTo(dialog)
    assert dialog.tts_fish_api_key_edit.echoMode() == QLineEdit.EchoMode.Password
    assert not dialog.tts_elevenlabs_api_key_edit.isVisibleTo(dialog)
    container = dialog.tts_provider_stack.parentWidget()
    layout = container.layout()
    assert layout.indexOf(dialog.tts_provider_stack) == 1
    assert dialog.tts_fish_api_key_edit.text() == ""
    dialog.tts_fish_api_key_toggle_button.click()
    assert dialog.tts_fish_api_key_edit.echoMode() == QLineEdit.EchoMode.Normal
    dialog.tts_provider_combo.setCurrentIndex(dialog.tts_provider_combo.findData("elevenlabs"))
    assert not dialog.tts_fish_api_key_edit.isVisibleTo(dialog)
    assert dialog.tts_elevenlabs_api_key_edit.isVisibleTo(dialog)


def test_fish_audio_settings_roundtrip_preserves_provider_keys_and_voice(dialog_factory):
    dialog = dialog_factory({"tts_provider": "fish_audio", "tts_api_keys": {"elevenlabs": "synthetic-eleven-key"}})
    assert dialog.tts_fish_api_url_edit.text() == "https://api.fish.audio/v1"
    assert dialog.tts_fish_model_combo.currentData() == "s2.1-pro"
    assert dialog.tts_fish_speed_spin.value() == 1.0
    assert dialog.tts_fish_reference_id_edit.text() == ""
    dialog.tts_fish_api_key_edit.setText(" synthetic-fish-key ")
    dialog.tts_fish_reference_id_edit.setText(" synthetic-voice-id ")
    dialog.tts_fish_model_combo.setCurrentIndex(dialog.tts_fish_model_combo.findData("s2.1-pro-free"))
    dialog.tts_fish_speed_spin.setValue(1.2)
    values = dialog._get_current_values()
    assert values["tts_api_keys"]["fish_audio"] == "synthetic-fish-key"
    assert values["tts_api_keys"]["elevenlabs"] == "synthetic-eleven-key"
    assert values["tts_provider_configs"]["fish_audio"] == {
        "api_url": "https://api.fish.audio/v1", "model": "s2.1-pro-free",
        "reference_id": "synthetic-voice-id", "speed": 1.2,
    }
    reopened = dialog_factory(values)
    assert reopened.tts_provider_combo.currentData() == "fish_audio"
    assert reopened.tts_fish_api_key_edit.text() == "synthetic-fish-key"
    assert reopened.tts_fish_reference_id_edit.text() == "synthetic-voice-id"
    assert reopened.tts_fish_model_combo.currentData() == "s2.1-pro-free"
    assert reopened.tts_fish_speed_spin.value() == 1.2
    assert reopened.tts_fish_api_key_edit.echoMode() == QLineEdit.EchoMode.Password
