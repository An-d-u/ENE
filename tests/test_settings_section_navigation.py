import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QComboBox, QGroupBox, QLabel, QTabWidget

from test_fish_audio_settings_ui import dialog_factory


@pytest.fixture(autouse=True)
def _offline_tokenizer(monkeypatch):
    monkeypatch.setattr("src.ui.settings_dialog.tiktoken", None)


def test_compact_navigation_preserves_page_and_escape_reverts_preview(dialog_factory, monkeypatch):
    from src.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr(SettingsDialog, "_available_screen_geometry", lambda self: QRect(0, 0, 1280, 960))
    dialog = dialog_factory()
    dialog.show()
    dialog.focus_section("model")
    dialog._section_nav_cards[4].click()
    assert dialog.content_header_title.text() == "음성 설정"
    assert dialog.breadcrumb.text().endswith("대화")

    dialog.resize(700, 700)
    QApplication.processEvents()
    assert dialog.section_picker.isVisible() and not dialog.sidebar.isVisible()
    assert dialog.section_picker.currentText() == "음성 설정"
    dialog.section_picker.activated.emit(0)
    assert dialog.content_header_title.text() == "창 설정"
    dialog.resize(1040, 700)
    QApplication.processEvents()
    assert dialog.sidebar.isVisible() and dialog._section_nav_cards[0].isChecked()

    cancelled = []
    dialog.settings_cancelled.connect(lambda: cancelled.append(True))
    dialog.window_x_spin.setValue(dialog.window_x_spin.value() + 1)
    QTest.keyClick(dialog, Qt.Key.Key_Escape)
    assert cancelled == [True] and not dialog.isVisible()


def test_settings_sections_group_related_controls_and_preserve_edits(dialog_factory):
    dialog = dialog_factory()
    model = dialog.findChild(QTabWidget, "modelSectionTabs")
    behavior = dialog.findChild(QTabWidget, "behaviorSectionTabs")
    voice = dialog.findChild(QTabWidget, "ttsSectionTabs")
    assert model is not None and behavior is not None and voice is not None
    for tabs, expected in (
        (model, ["모델·배치", "응답 동작", "대기 동작", "터치·시선"]),
        (behavior, ["대화 화면", "대화 반응", "목표·노트", "감지·기록"]),
        (voice, ["음성 출력 (TTS)", "음성 입력 (PTT)"]),
    ):
        assert [tabs.tabText(i) for i in range(tabs.count())] == expected
    for tabs, page, control in (
        (behavior, 0, dialog.show_manual_summary_button_check),
        (behavior, 1, dialog.enable_mood_system_check),
        (behavior, 2, dialog.enable_ene_goals_check),
        (behavior, 3, dialog.observation_sample_seconds_spin),
        (model, 1, dialog.emotion_motion_preset_combo),
        (model, 2, dialog.enable_idle_synthetic_gestures_check),
        (model, 3, dialog.mouse_tracking_check),
        (voice, 1, dialog.enable_global_ptt_check),
    ):
        assert tabs.widget(page).isAncestorOf(control)
    assert dialog.enable_ene_goals_check.parentWidget() is dialog._goal_active_list.parentWidget()
    dialog.enable_global_ptt_check.setChecked(True)
    dialog.mouse_tracking_check.setChecked(False)
    values = dialog._get_current_values()
    assert values["enable_global_ptt"] is True
    assert values["mouse_tracking_enabled"] is False


def test_provider_jumps_and_removed_hints_follow_the_visible_form(dialog_factory):
    dialog = dialog_factory()
    dialog.resize(680, 700)
    dialog.show()
    voice = dialog.findChild(QTabWidget, "ttsSectionTabs")
    jump = voice.findChild(QComboBox, "settingsGroupJump")
    for provider in ("gpt_sovits_http", "fish_audio", "browser_speech"):
        dialog.tts_provider_combo.setCurrentIndex(dialog.tts_provider_combo.findData(provider))
        current = dialog._tts_provider_pages[provider]
        QApplication.processEvents()
        groups = current.findChildren(QGroupBox)
        expected = [group.title() for group in groups]
        assert [jump.itemText(i) for i in range(1, jump.count() - 1)] == expected
        assert jump.isVisibleTo(voice) == (len(expected) + 2 >= 4)
        assert current.height() - groups[-1].geometry().bottom() < 24
        assert voice.currentWidget().horizontalScrollBar().maximum() == 0
    removed = (
        "settings.window.quick.hint", "settings.model.quick.hint", "settings.model.scale.hint",
        "settings.model.position_x.hint", "settings.model.position_y.hint",
        "settings.llm.provider_group.api_key.hint", "settings.behavior.actions.hint",
        "settings.behavior.ptt.hotkey.hint",
    )
    labels = {label.text() for label in dialog.findChildren(QLabel)}
    assert all(dialog._translated_text(key, key) not in labels for key in removed)
    voice.setCurrentIndex(1)
    assert dialog.global_ptt_hotkey_hint_label.isHidden()
    dialog._capturing_ptt_hotkey = True
    dialog._update_ptt_hotkey_ui()
    assert dialog.global_ptt_hotkey_hint_label.isVisibleTo(voice)
    assert "Esc" in dialog.global_ptt_hotkey_hint_label.text()
    dialog._capturing_ptt_hotkey = False
    dialog._update_ptt_hotkey_ui()
    assert dialog.global_ptt_hotkey_hint_label.isHidden()


def test_group_jump_tracks_visible_groups_language_and_subtab(dialog_factory):
    dialog = dialog_factory()
    model = dialog.findChild(QTabWidget, "modelSectionTabs")
    assert model is not None
    jump = model.findChild(QComboBox, "settingsGroupJump")
    assert jump is not None
    dialog._set_section_index(2)
    dialog.show()
    QApplication.processEvents()
    scroll = model.currentWidget()
    live2d = dialog.live2d_model_group
    image = dialog.image_avatar_group
    assert jump.findText(live2d.title()) >= 0 and jump.findText(image.title()) < 0
    dialog.avatar_mode_combo.setCurrentIndex(dialog.avatar_mode_combo.findData("image"))
    index = jump.findText(image.title())
    assert index >= 0 and jump.findText(live2d.title()) < 0
    jump.activated.emit(index)
    assert scroll.verticalScrollBar().value() > 0
    model.setCurrentIndex(1)
    assert not jump.isVisibleTo(model)
    dialog.ui_language_combo.setCurrentIndex(dialog.ui_language_combo.findData("en"))
    assert model.tabText(0) == "Model & placement"
    model.setCurrentIndex(0)
    assert jump.findText(image.title()) >= 0
    assert jump.findText(live2d.title()) == -1
    dialog._set_section_index(5)
    behavior = dialog.findChild(QTabWidget, "behaviorSectionTabs")
    behavior.setCurrentIndex(3)
    groups = behavior.currentWidget().findChildren(QGroupBox)
    choices = behavior.findChild(QComboBox, "settingsGroupJump")
    assert [choices.itemText(i) for i in range(choices.count())] == [g.title() for g in groups]
