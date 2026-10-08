"""개인 설정을 사용하지 않고 입력 기기 토글을 검증한다."""

import re
from types import SimpleNamespace
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QGroupBox, QMessageBox

from src.core.settings import Settings
from tests.test_fish_audio_settings_ui import dialog_factory  # noqa: F401
from tests.test_ui_i18n_smoke import _load_app_class


def test_default_is_off():
    assert Settings.DEFAULT_CONFIG["include_input_device_context"] is False


@pytest.mark.parametrize("value", [None, False, True, "true", 1, [], {}])
def test_toggle_load_collect_reopen(dialog_factory, value):
    dialog = dialog_factory({"include_input_device_context": value})
    toggle = dialog.include_input_device_context_check
    assert toggle.isChecked() is (value is True)
    toggle.setChecked(True)
    values = dialog._get_current_values()
    assert values["include_input_device_context"] is True
    assert dialog_factory(values).include_input_device_context_check.isChecked()


def test_context_group_and_keyboard_translation(dialog_factory):
    dialog = dialog_factory()
    toggle = dialog.include_input_device_context_check
    assert toggle.focusPolicy() != Qt.FocusPolicy.NoFocus
    group = toggle.parentWidget()
    assert isinstance(group, QGroupBox)
    assert group.title() == "대화 컨텍스트"
    parent_layout = group.parentWidget().layout()
    assert (
        parent_layout.itemAt(parent_layout.indexOf(group) - 1).widget().title()
        == "표시 요소"
    )
    for language in ("en", "ja"):
        dialog._set_dialog_preview_language(language)
        dialog._retranslate_ui()
        assert not re.search("[가-힣]", group.title() + toggle.text())


def test_preview_cancel_failed_save_and_saved_roundtrip(
    dialog_factory, tmp_path, monkeypatch
):
    settings = Settings(
        config_path=str(tmp_path / "synthetic-config.json"),
        secret_path=str(tmp_path / "synthetic-secrets.json"),
    )
    dialog = dialog_factory(settings.config)
    previews, saved = [], []
    dialog.settings_preview.connect(previews.append)
    dialog.settings_changed.connect(saved.append)
    dialog.include_input_device_context_check.setChecked(True)
    assert previews[-1]["include_input_device_context"] is True
    assert settings.get("include_input_device_context") is False
    dialog._cancel_settings()
    assert settings.get("include_input_device_context") is False
    second = dialog_factory(settings.config)
    second.include_input_device_context_check.setChecked(True)
    second.set_save_handler(lambda *_: {"status": "failed"})
    monkeypatch.setattr(QMessageBox, "warning", lambda *_: None)
    second._save_settings()
    assert settings.get("include_input_device_context") is False

    def save(values, _baseline):
        settings.config.update(values)
        settings.save()
        return {"status": "accepted", "values": values}

    second.set_save_handler(save)
    second._save_settings()
    reopened = Settings(
        config_path=settings.config_path, secret_path=settings.secret_path
    )
    assert reopened.get("include_input_device_context") is True


@pytest.mark.parametrize("before,after", [(False, True), (True, False)])
def test_real_application_storage_failure_keeps_confirmed_value(
    tmp_path, monkeypatch, before, after
):
    settings = Settings(
        config_path=str(tmp_path / "synthetic-config.json"),
        secret_path=str(tmp_path / "synthetic-secrets.json"),
    )
    settings.config["include_input_device_context"] = before
    settings.save()
    application = _load_app_class()
    app = application.__new__(application)
    app.settings = settings
    app.global_ptt = None
    app._refresh_tts_runtime_bindings = lambda: None
    applied = []

    def apply(values):
        applied.append(values)
        settings.update(values)
        settings.save()

    app.overlay_window = SimpleNamespace(
        bridge=SimpleNamespace(enable_tts=False),
        apply_new_settings=apply,
        preview_settings=lambda _: None,
        restore_settings=lambda: None,
    )

    def fail(*_args, **_kwargs):
        raise OSError("synthetic storage failure")

    with monkeypatch.context() as blocked:
        blocked.setattr("src.core.settings.save_json_data_atomic", fail)
        blocked.setattr("src.core.settings.save_json_data", fail)
        decision = application._on_settings_changed(
            app, {"include_input_device_context": after}
        )
        assert decision["status"] == "rejected"
        assert settings.get("include_input_device_context") is before
        assert applied == []
    decision = application._on_settings_changed(
        app, {"include_input_device_context": after}
    )
    assert decision["status"] == "accepted"
    assert settings.get("include_input_device_context") is after
    reopened = Settings(
        config_path=settings.config_path, secret_path=settings.secret_path
    )
    assert reopened.get("include_input_device_context") is after
