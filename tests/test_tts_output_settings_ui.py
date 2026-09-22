"""개인 설정을 읽지 않는 출력 선택·저장·취소·표시 검증."""

from pathlib import Path
from types import SimpleNamespace
import re

import pytest
from PyQt6.QtCore import QObject, pyqtSignal

from src.core.settings import Settings
from tests.test_fish_audio_settings_ui import dialog_factory  # noqa: F401
from tests.test_ui_i18n_smoke import _load_app_class


@pytest.mark.parametrize("value,expected", [(None, "auto"), ([], "auto"), ("pc", "pc"), ("phone", "phone")])
def test_output_selection_load_collect_reopen(dialog_factory, value, expected):
    dialog = dialog_factory({"tts_output_target": value})
    assert dialog.tts_output_target_combo.currentData() == expected
    assert [dialog.tts_output_target_combo.itemData(i) for i in range(3)] == ["auto", "pc", "phone"]
    dialog.tts_output_target_combo.setCurrentIndex(2)
    values = dialog._get_current_values()
    assert values["tts_output_target"] == "phone"
    assert dialog_factory(values).tts_output_target_combo.currentData() == "phone"


def test_status_connection_is_scoped_and_retranslated(dialog_factory):
    class Bridge(QObject):
        companion_audio_status_changed = pyqtSignal(object)
        def companion_audio_status(self):
            return {"preference": "phone", "output": "none", "state": "stopped", "reason": "prepare_timeout"}
    bridge = Bridge()
    dialog = dialog_factory()
    dialog._bridge = bridge
    dialog._connect_tts_audio_bridge()
    dialog._connect_tts_audio_bridge()
    assert bridge.receivers(bridge.companion_audio_status_changed) == 1
    assert "준비 시간" in dialog.tts_output_status_label.text()
    for language in ("en", "ja"):
        dialog._set_dialog_preview_language(language)
        dialog._retranslate_ui()
        assert not re.search("[가-힣]", dialog.tts_output_status_label.text())
        assert not re.search("[가-힣]", dialog.tts_output_target_combo.itemText(2))
    dialog.close()
    assert bridge.receivers(bridge.companion_audio_status_changed) == 0


def test_save_target_without_rebuilding_and_preview_cancel_do_not_apply(tmp_path):
    application = _load_app_class()
    settings = Settings(config_path=str(tmp_path / "synthetic.json"), secret_path=str(tmp_path / "secrets.json"))
    bridge = SimpleNamespace(tts_output_target="auto", enable_tts=False)
    notifications, rebuilds = [], []
    bridge._companion_tts_settings_changed = lambda: notifications.append(bridge.tts_output_target)
    app = application.__new__(application)
    app.settings = settings
    def save(values):
        settings.config.update(values)
        settings.save()
    app.overlay_window = SimpleNamespace(bridge=bridge, apply_new_settings=save,
        preview_settings=lambda _: None, restore_settings=lambda: None)
    app.global_ptt = None
    app._refresh_tts_runtime_bindings = lambda: rebuilds.append(True)
    application._on_settings_preview(app, {"tts_output_target": "phone"})
    application._on_settings_cancelled(app)
    assert bridge.tts_output_target == "auto"
    result = application._on_settings_changed(app, {"tts_output_target": "phone"})
    assert result["status"] == "accepted"
    assert bridge.tts_output_target == "phone" and notifications[-1] == "phone"
    assert rebuilds == []
    restarted = Settings(config_path=str(tmp_path / "synthetic.json"), secret_path=str(tmp_path / "secrets.json"))
    assert restarted.get("tts_output_target") == "phone"


def test_new_audio_labels_exist_in_all_languages():
    import json
    locales = Path(__file__).resolve().parents[1] / "src/locales"
    messages = {language: json.loads((locales / f"{language}.json").read_text(encoding="utf-8-sig")) for language in ("ko", "en", "ja")}
    keys = {key for key in messages["ko"] if key.startswith("settings.tts.output.")}
    assert len(keys) >= 20
    for language in ("en", "ja"):
        assert keys <= messages[language].keys()
        assert all(not re.search("[가-힣]", messages[language][key]) for key in keys)


def test_failed_target_save_does_not_change_runtime_or_saved_choice(tmp_path, monkeypatch):
    application = _load_app_class()
    settings = Settings(config_path=str(tmp_path / "synthetic.json"), secret_path=str(tmp_path / "secrets.json"))
    app = application.__new__(application)
    app.settings = settings
    applied = []
    bridge = SimpleNamespace(tts_output_target="auto")
    app.overlay_window = SimpleNamespace(bridge=bridge, apply_new_settings=applied.append)
    monkeypatch.setattr("src.core.settings.save_json_data_atomic", lambda *a, **kw: (_ for _ in ()).throw(OSError("synthetic")))
    result = application._on_settings_changed(app, {"tts_output_target": "phone"})
    assert result["status"] == "rejected"
    assert bridge.tts_output_target == settings.get("tts_output_target") == "auto"
    assert applied == []
