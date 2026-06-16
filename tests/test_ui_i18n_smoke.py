import json
import re
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import QDate, QEvent, Qt
from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox
from PyQt6.QtWidgets import QApplication

from src.core.i18n import configure_i18n
from src.core.tray_icon import TrayIcon
from src.ui.obsidian_panel_window import ObsidianPanelWindow
from src.ui.calendar_dialog import CalendarDialog
from src.ui.memory_dialog import MemoryDialog
from src.ui.profile_dialog import ProfileDialog


_QAPP = None
QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)


def _get_qapp():
    global _QAPP
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    _QAPP = app
    return app


class _DummyObsSettings:
    def __init__(self):
        self._values = {}
        self.saved = False

    def get(self, key, default=None):
        return self._values.get(key, default)

    def set(self, key, value):
        self._values[key] = value

    def save(self):
        self.saved = True


class _DummySettings:
    def __init__(self, config):
        self.config = dict(config)
        self.saved = False

    def get(self, key, default=None):
        return self.config.get(key, default)

    def save(self):
        self.saved = True


class _DummyCalendarManager:
    def __init__(self):
        self.conversation_counts = {"2026-03-24": 3}
        self._head_pat_counts = {"2026-03-24": 1}
        self.events = [
            SimpleNamespace(
                id="event-1",
                date="2026-03-24",
                title="Planning",
                description="Review milestones",
                completed=False,
                source="ai_extracted",
            ),
            SimpleNamespace(
                id="event-2",
                date="2026-03-24",
                title="Handwritten note",
                description="",
                completed=False,
                source="user",
            )
        ]
        self.deleted_event_ids = []

    def get_conversation_count(self, date_str):
        return self.conversation_counts.get(date_str, 0)

    def get_head_pat_count(self, date_str):
        return self._head_pat_counts.get(date_str, 0)

    def get_events_by_date(self, date_str):
        return [event for event in self.events if event.date == date_str]

    def toggle_event_completion(self, event_id):
        for event in self.events:
            if event.id == event_id:
                event.completed = not event.completed
                return

    def delete_event(self, event_id):
        self.deleted_event_ids.append(event_id)
        self.events = [event for event in self.events if event.id != event_id]


class _DummyUserProfile:
    def __init__(self, basic_info=None, preferences=None, facts=None):
        self.basic_info = basic_info or {}
        self.preferences = preferences or {"likes": []}
        self.facts = list(facts or [])

    def __bool__(self):
        return bool(self.basic_info or self.preferences.get("likes") or self.facts)

    def delete_fact(self, index):
        self.facts.pop(index)


class _TruthyEmptyUserProfile(_DummyUserProfile):
    def __bool__(self):
        return True


class _DummyEneProfile:
    def __init__(self, core_profile=None, facts=None):
        self.core_profile = core_profile or {
            "identity": [],
            "speaking_style": [],
            "relationship_tone": [],
        }
        self.facts = list(facts or [])
        self.saved = False

    def save(self):
        self.saved = True

    def delete_fact(self, index):
        self.facts.pop(index)


class _DummyMemoryManager:
    def __init__(self, memories):
        self.memories = list(memories)

    def get_stats(self):
        return {
            "total": len(self.memories),
            "important": sum(1 for memory in self.memories if memory.is_important),
            "with_embedding": sum(1 for memory in self.memories if memory.embedding),
        }

    def set_important(self, memory_id, value):
        for memory in self.memories:
            if memory.id == memory_id:
                memory.is_important = bool(value)
                return

    def delete(self, memory_id):
        self.memories = [memory for memory in self.memories if memory.id != memory_id]


class _DummySignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, payload):
        for callback in list(self.callbacks):
            callback(payload)


class _DummyGoalBridge:
    def __init__(self, snapshot=None):
        self.ene_profile = _DummyEneProfile()
        self.goal_items_updated = _DummySignal()
        self.snapshot = snapshot or {"active_goals": [], "history": []}
        self.calls = []

    def parent(self):
        return None

    def request_goal_items(self):
        self.calls.append(("request_goal_items",))
        self.goal_items_updated.emit(json.dumps(self.snapshot, ensure_ascii=False))

    def add_manual_goal(self, goal_type, title, reason):
        self.calls.append(("add_manual_goal", goal_type, title, reason))

    def update_goal_item(self, goal_id, title, reason):
        self.calls.append(("update_goal_item", goal_id, title, reason))

    def complete_goal_item(self, goal_id, reason):
        self.calls.append(("complete_goal_item", goal_id, reason))

    def cancel_goal_item(self, goal_id, reason):
        self.calls.append(("cancel_goal_item", goal_id, reason))


def _write_locales(locales_dir, en_data, ja_data, ko_data=None):
    (locales_dir / "en.json").write_text(json.dumps(en_data, ensure_ascii=False), encoding="utf-8-sig")
    (locales_dir / "ja.json").write_text(json.dumps(ja_data, ensure_ascii=False), encoding="utf-8-sig")
    (locales_dir / "ko.json").write_text(
        json.dumps(ko_data or {}, ensure_ascii=False),
        encoding="utf-8-sig",
    )


def _load_app_class():
    stubbed_modules = {
        "src.ui.settings_dialog": {"SettingsDialog": type("SettingsDialog", (), {})},
        "src.core.overlay_window": {"OverlayWindow": type("OverlayWindow", (), {})},
        "src.core.global_ptt": {"GlobalPTTController": type("GlobalPTTController", (), {})},
    }
    previous_modules = {name: sys.modules.get(name) for name in stubbed_modules}
    for module_name, attrs in stubbed_modules.items():
        stub = types.ModuleType(module_name)
        for attr_name, value in attrs.items():
            setattr(stub, attr_name, value)
        sys.modules[module_name] = stub
    try:
        from src.core.app import ENEApplication
    finally:
        for module_name, previous in previous_modules.items():
            if previous is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = previous
    return ENEApplication


def _read_web_runtime_script_text(assets_root: Path) -> str:
    html = (assets_root / "index.html").read_text(encoding="utf-8-sig")
    script_paths = re.findall(r'<script src="([^"]+\.js)"></script>', html)
    runtime_paths = [
        path for path in script_paths
        if not path.startswith("lib/") and not path.startswith("qrc:")
    ]
    if runtime_paths:
        return "\n".join((assets_root / path).read_text(encoding="utf-8-sig") for path in runtime_paths)
    return (assets_root / "script.js").read_text(encoding="utf-8-sig")


@contextmanager
def _stub_prompt_module():
    prompt_stub = types.ModuleType("src.ai.prompt")
    prompt_stub.get_available_emotions = lambda: ["eyeclose", "shy"]
    previous_prompt_module = sys.modules.get("src.ai.prompt")
    sys.modules["src.ai.prompt"] = prompt_stub
    try:
        yield
    finally:
        if previous_prompt_module is None:
            sys.modules.pop("src.ai.prompt", None)
        else:
            sys.modules["src.ai.prompt"] = previous_prompt_module


def test_tts_output_device_items_prioritize_default_and_mark_current():
    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        items = SettingsDialog._build_tts_output_device_items(
            [
                {"id": "usb", "name": "USB DAC", "is_default": False},
                {"id": "speaker", "name": "Speakers", "is_default": True},
                {"id": "hdmi", "name": "HDMI", "is_default": False},
            ],
            "hdmi",
        )

        assert items == [
            ("시스템 기본 장치", ""),
            ("Speakers (기본)", "speaker"),
            ("HDMI (현재 사용 중)", "hdmi"),
            ("USB DAC", "usb"),
        ]


def test_tts_output_device_items_mark_system_default_as_current_when_unset():
    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        items = SettingsDialog._build_tts_output_device_items(
            [{"id": "speaker", "name": "Speakers", "is_default": True}],
            "",
        )

        assert items == [
            ("시스템 기본 장치 (현재 사용 중)", ""),
            ("Speakers (기본)", "speaker"),
        ]


def test_tts_output_device_items_keep_missing_saved_device_visible():
    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        items = SettingsDialog._build_tts_output_device_items(
            [{"id": "speaker", "name": "Speakers", "is_default": True}],
            "missing-device",
        )

        assert items[-1] == ("저장된 장치 (현재 없음, 현재 사용 중): missing-device", "missing-device")


def test_settings_dialog_read_text_file_uses_app_paths_bridge(tmp_path, monkeypatch):
    with _stub_prompt_module():
        from src.ui import settings_dialog as settings_dialog_module

        runtime_path = tmp_path / "runtime" / "user_profile.json"
        monkeypatch.setattr(
            settings_dialog_module,
            "read_text_data",
            lambda path, encoding="utf-8-sig": "실제 Roaming user_profile 내용",
            raising=False,
        )

        loaded = settings_dialog_module.SettingsDialog._read_text_file(object(), runtime_path)

        assert loaded == "실제 Roaming user_profile 내용"


def test_settings_dialog_write_text_file_uses_app_paths_bridge(tmp_path, monkeypatch):
    with _stub_prompt_module():
        from src.ui import settings_dialog as settings_dialog_module

        runtime_path = tmp_path / "runtime" / "user_profile.json"
        calls: list[tuple[Path, str, str]] = []

        def _capture_write(path, text, encoding="utf-8-sig"):
            calls.append((Path(path), text, encoding))

        monkeypatch.setattr(
            settings_dialog_module,
            "write_text_data",
            _capture_write,
            raising=False,
        )

        settings_dialog_module.SettingsDialog._write_text_file(object(), runtime_path, "a\r\nb")

        assert calls == [(runtime_path, "a\nb", "utf-8-sig")]


def test_settings_dialog_translates_metadata_in_english():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="en", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "en",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            }
        )

        gemini_index = dialog.llm_provider_combo.findData("gemini")
        browser_tts_index = dialog.tts_provider_combo.findData("browser_speech")

        assert dialog.windowTitle() == "ENE Settings"
        assert dialog._theme_preset_meta["light"].text() == (
            "Balanced bright neutral palette for both settings and chat surfaces. · Currently selected"
        )
        assert dialog._theme_variant_titles["light_classic"].text() == "Clean Blue"
        assert dialog._theme_variant_meta["light_classic"].text() == (
            "Balanced bright neutral palette for everyday use. · Click to apply"
        )
        assert dialog.llm_provider_combo.itemText(gemini_index) == "Google Gemini API"
        assert dialog.tts_provider_combo.itemText(browser_tts_index) == "Browser Speech"
        assert dialog.tts_provider_hint_label.text() == "Local or remote GPT-SoVITS server that uses reference audio and prompt text."

        dialog.close()


def _collect_widget_texts(root):
    texts = []
    for label in root.findChildren(QLabel):
        texts.append(label.text())
    for button in root.findChildren(QPushButton):
        texts.extend([button.text(), button.toolTip()])
    for group in root.findChildren(QGroupBox):
        texts.append(group.title())
    for check in root.findChildren(QCheckBox):
        texts.append(check.text())
    for combo in root.findChildren(QComboBox):
        texts.append(combo.placeholderText())
        for index in range(combo.count()):
            texts.append(combo.itemText(index))
    for line_edit in root.findChildren(QLineEdit):
        texts.append(line_edit.placeholderText())
        texts.append(line_edit.text())
    for plain_text in root.findChildren(QPlainTextEdit):
        texts.append(plain_text.placeholderText())
    for spin_box in root.findChildren(QSpinBox):
        texts.extend([spin_box.text(), spin_box.suffix(), spin_box.specialValueText()])
    for double_spin_box in root.findChildren(QDoubleSpinBox):
        texts.extend([double_spin_box.text(), double_spin_box.suffix(), double_spin_box.specialValueText()])
    return [text for text in texts if text]


def test_settings_dialog_translates_known_korean_leftovers_in_english_and_japanese(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    leftover_texts = [
        "재생",
        "합성 파라미터",
        "출력 장치:",
        "볼륨:",
        "속도:",
        "자르기:",
        "시스템 기본 장치",
        "현재 사용 중",
        "기본)",
        "cut0 - 자르지 않음",
        "cut1 - 네 문장씩",
        "cut2 - 50자씩",
        "cut3 - 중국어 마침표",
        "cut4 - 영어 마침표",
        "cut5 - 문장부호 기준",
        "체크 파일당 최대 글자 수:",
        "체크 파일 전체 최대 글자 수:",
        " 자",
        "프롬프트 Markdown 로드 완료",
        "프롬프트 Markdown 저장 완료",
    ]

    monkeypatch.setattr(
        "src.ui.settings_dialog_tts.AudioPlayer.list_output_devices",
        lambda: [{"id": "speaker", "name": "Speakers", "is_default": True}],
    )

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        for language in ("en", "ja"):
            configure_i18n(language=language, locales_dir=locales_dir, system_locale="ko_KR")
            dialog = SettingsDialog(
                {
                    "ui_language": language,
                    "llm_provider": "gemini",
                    "tts_provider": "gpt_sovits_http",
                    "enable_tts": True,
                }
            )
            for index in range(dialog.content_stack.count()):
                dialog.content_stack.setCurrentIndex(index)
            dialog._refresh_tts_output_devices("")

            text_blob = "\n".join(_collect_widget_texts(dialog))
            for leftover in leftover_texts:
                assert leftover not in text_blob

            dialog.close()


def test_settings_dialog_uses_wider_default_size():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            },
            bridge=SimpleNamespace(ene_profile=_DummyEneProfile(), parent=lambda: None),
        )

        assert dialog.minimumWidth() >= 1280
        assert dialog.width() >= 1460

        dialog.close()


def test_settings_dialog_loads_and_saves_streaming_tts_toggle(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "tts_language": "ko",
                "tts_streaming_enabled": True,
            }
        )

        assert dialog.tts_streaming_enabled_check.isChecked() is True
        assert dialog.tts_language_combo.currentData() == "ko"

        dialog.tts_streaming_enabled_check.setChecked(False)
        dialog.tts_language_combo.setCurrentIndex(dialog.tts_language_combo.findData("same_as_response"))

        values = dialog._get_current_values()

        assert values["tts_streaming_enabled"] is False
        assert values["tts_language"] == "same_as_response"

        dialog.close()


def test_settings_dialog_loads_and_saves_prompt_persona_names(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "assistant_display_name": "루나",
                "user_address_name": "선장",
            }
        )

        assert dialog.assistant_display_name_edit.text() == "루나"
        assert dialog.user_address_name_edit.text() == "선장"

        dialog.assistant_display_name_edit.setText("아리아")
        dialog.user_address_name_edit.setText("대장")
        values = dialog._get_current_values()

        assert values["assistant_display_name"] == "아리아"
        assert values["user_address_name"] == "대장"

        dialog.close()


def test_settings_dialog_loads_and_saves_viseme_lipsync_toggle(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "viseme_lipsync_enabled": True,
            }
        )

        assert dialog.viseme_lipsync_enabled_check.isChecked() is True

        dialog.viseme_lipsync_enabled_check.setChecked(False)
        values = dialog._get_current_values()
        assert values["viseme_lipsync_enabled"] is False

        dialog.close()


def test_settings_dialog_initializes_viseme_lipsync_toggle_unchecked_when_disabled(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "viseme_lipsync_enabled": False,
            }
        )

        assert dialog.viseme_lipsync_enabled_check.isChecked() is False

        dialog.close()


def test_settings_dialog_loads_saves_and_disables_goal_controls(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "enable_ene_goals": False,
                "show_ene_goal_button": True,
            },
            bridge=_DummyGoalBridge(),
        )

        assert dialog.enable_ene_goals_check.isChecked() is False
        assert dialog.show_ene_goal_button_check.isChecked() is True
        assert dialog.show_ene_goal_button_check.isEnabled() is False
        assert dialog._goal_title_edit.isEnabled() is False
        assert dialog._goal_add_button.isEnabled() is False

        values = dialog._get_current_values()
        assert values["enable_ene_goals"] is False
        assert values["show_ene_goal_button"] is True

        dialog.enable_ene_goals_check.setChecked(True)
        assert dialog.show_ene_goal_button_check.isEnabled() is True
        assert dialog._goal_title_edit.isEnabled() is True
        assert dialog._get_current_values()["enable_ene_goals"] is True

        dialog.close()


def test_settings_dialog_renders_goal_items_and_calls_bridge_handlers(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    snapshot = {
        "active_goals": [
            {
                "id": "goal_1",
                "type": "short_term",
                "title": "물 마시기",
                "reason": "컨디션 관리",
            }
        ],
        "history": [
            {
                "id": "goal_2",
                "type": "long_term",
                "title": "루틴 정리",
                "reason": "완료됨",
                "status": "completed",
            },
            {
                "type": "short_term",
                "title": "아이디 없는 기록",
                "reason": "레거시 데이터",
                "status": "cancelled",
            }
        ],
    }
    bridge = _DummyGoalBridge(snapshot)

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "enable_ene_goals": True,
                "show_ene_goal_button": True,
            },
            bridge=bridge,
        )

        assert bridge.calls[0] == ("request_goal_items",)
        assert dialog._goal_items["goal_1"]["title"] == "물 마시기"
        assert dialog._goal_active_list.count() == 1
        assert dialog._goal_history_list.count() == 2

        dialog._retranslate_ui()
        assert dialog._goal_history_list.count() == 2
        assert "아이디 없는 기록" in dialog._goal_history_list.item(1).text()

        dialog._goal_active_list.setCurrentRow(0)
        assert dialog._goal_title_edit.text() == "물 마시기"
        assert dialog._goal_reason_edit.toPlainText() == "컨디션 관리"
        assert dialog._goal_type_combo.isEnabled() is False
        assert dialog._goal_add_button.isEnabled() is False

        dialog._goal_title_edit.setText("물 챙겨 마시기")
        dialog._goal_reason_edit.setPlainText("수정 이유")
        dialog._goal_update_button.click()
        dialog._goal_complete_button.click()
        dialog._goal_cancel_button.click()

        dialog._goal_active_list.clearSelection()
        assert dialog._goal_add_button.isEnabled() is True
        dialog._goal_type_combo.setCurrentIndex(dialog._goal_type_combo.findData("long_term"))
        dialog._goal_title_edit.setText("장기 방향 잡기")
        dialog._goal_reason_edit.setPlainText("직접 추가")
        dialog._goal_add_button.click()

        assert ("update_goal_item", "goal_1", "물 챙겨 마시기", "수정 이유") in bridge.calls
        assert ("complete_goal_item", "goal_1", "수정 이유") in bridge.calls
        assert ("cancel_goal_item", "goal_1", "수정 이유") in bridge.calls
        assert ("add_manual_goal", "long_term", "장기 방향 잡기", "직접 추가") in bridge.calls

        dialog.close()


def test_settings_dialog_translates_viseme_lipsync_toggle_label_in_english(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="en", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "en",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            }
        )

        assert dialog.viseme_lipsync_enabled_check.text() == "Viseme Lip Sync"

        dialog.close()


def test_settings_dialog_translates_viseme_lipsync_toggle_label_in_korean(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            }
        )

        assert dialog.viseme_lipsync_enabled_check.text() == "viseme 립싱크"

        dialog.close()


def test_korean_locale_includes_viseme_lipsync_key():
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    ko_locale = json.loads((locales_dir / "ko.json").read_text(encoding="utf-8-sig"))

    assert ko_locale["settings"]["tts"]["overview"]["viseme_lipsync"] == "viseme 립싱크"


def test_korean_locale_uses_general_tts_enable_label():
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    ko_locale = json.loads((locales_dir / "ko.json").read_text(encoding="utf-8-sig"))

    assert ko_locale["settings"]["tts"]["overview"]["enable"] == "TTS 활성화"
    assert "일본어 응답" not in ko_locale["settings"]["tts"]["overview"]["enable"]


def test_settings_dialog_translates_viseme_lipsync_toggle_label_in_japanese(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ja",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            }
        )

        assert dialog.viseme_lipsync_enabled_check.text() == "ビセム リップシンク"

        dialog.close()


def test_settings_dialog_exposes_language_selector_and_translated_static_strings(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="en", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog
        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "en",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            }
        )

        dialog._ensure_lazy_tab_loaded("prompt")
        dialog._ensure_lazy_tab_loaded("memory")

        assert dialog.ui_language_combo.currentData() == "en"
        assert [dialog.ui_language_combo.itemData(index) for index in range(dialog.ui_language_combo.count())] == [
            "auto",
            "ko",
            "en",
            "ja",
        ]
        assert dialog.ptt_language_combo.currentData() == "ko"
        assert [dialog.ptt_language_combo.itemData(index) for index in range(dialog.ptt_language_combo.count())] == [
            "ko",
            "en",
            "ja",
        ]
        assert dialog.ui_language_combo.itemText(0) == "System default"
        assert dialog.ptt_language_combo.itemText(0) == "Korean"
        assert dialog._get_current_values()["ui_language"] == "en"
        assert dialog._get_current_values()["stt_language"] == "ko"
        assert dialog.content_header_title.text() == "Window Settings"
        assert dialog.content_header_meta.text() == "Window position, size, and language."
        assert {"General", "Emotion List and Usage Guide"}.issubset(
            {group.title() for group in dialog.findChildren(QGroupBox)}
        )
        assert {button.text() for button in dialog.findChildren(QPushButton)} >= {
            "Cancel",
            "Save Changes",
            "New Emotion",
            "Apply to List",
            "Reload",
        }
        assert dialog.llm_api_key_edit.placeholderText() == "API key for the selected provider"
        assert dialog.model_json_path_edit.placeholderText() == "e.g. assets/live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json"
        assert dialog.emotion_name_input.placeholderText() == "Emotion key (e.g. shy)"
        assert dialog.memory_search_recent_turns_spin.suffix() == " turns"
        assert dialog.memory_search_recent_turns_spin.specialValueText() == "Current message only"
        assert "Emotion List and Usage Guide" in {group.title() for group in dialog.findChildren(QGroupBox)}
        assert {"Memory Search Range", "Memory"}.issubset(
            {label.text() for label in dialog.findChildren(QLabel)}
        )
        assert dialog._base_prompt_token_label.text().startswith("BASE_SYSTEM_PROMPT tokens:")
        assert "characters:" in dialog._base_prompt_token_label.text()

        warnings = []

        def fake_warning(parent, title, text):
            warnings.append((title, text))

        monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.warning", fake_warning)
        dialog._theme_color_edits["theme_accent_color"].setText("#12")
        dialog._save_settings()

        assert warnings == [
            (
                "Theme color check",
                "Every theme color must use a 6-digit HEX code in `#RRGGBB` format.",
            )
        ]
        dialog.close()


def test_settings_dialog_ptt_language_selection_is_saved_to_stt_language():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "stt_language": "en",
            }
        )

        assert dialog.ptt_language_combo.currentData() == "en"

        dialog.ptt_language_combo.setCurrentIndex(dialog.ptt_language_combo.findData("ja"))

        current_values = dialog._get_current_values()
        assert current_values["stt_language"] == "ja"

        dialog.close()


def test_settings_dialog_exposes_image_avatar_controls_and_toggles_mode_groups(monkeypatch, tmp_path):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")
    avatar_dir = tmp_path / "avatar_images"
    avatar_dir.mkdir()
    (avatar_dir / "normal.png").write_bytes(b"synthetic image placeholder")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "avatar_mode": "live2d",
                "image_avatar_folder": str(avatar_dir),
            }
        )

        for attr_name in (
            "avatar_mode_combo",
            "image_avatar_folder_edit",
            "image_avatar_browse_button",
            "image_avatar_emotion_list",
            "image_avatar_scale_spin",
            "image_avatar_x_slider",
            "image_avatar_y_slider",
        ):
            assert hasattr(dialog, attr_name)

        assert [dialog.avatar_mode_combo.itemData(index) for index in range(dialog.avatar_mode_combo.count())] == [
            "live2d",
            "image",
        ]
        assert dialog.live2d_model_group.isHidden() is False
        assert dialog.image_avatar_group.isHidden() is True

        dialog.avatar_mode_combo.setCurrentIndex(dialog.avatar_mode_combo.findData("image"))

        assert dialog.avatar_mode_combo.currentData() == "image"
        assert dialog.live2d_model_group.isHidden() is True
        assert dialog.image_avatar_group.isHidden() is False

        dialog.close()


def test_settings_dialog_collects_image_avatar_values_and_selected_placement(monkeypatch, tmp_path):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")
    avatar_dir = tmp_path / "avatar_images"
    avatar_dir.mkdir()
    (avatar_dir / "normal.png").write_bytes(b"synthetic image placeholder")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "avatar_mode": "image",
                "image_avatar_folder": str(avatar_dir),
            }
        )

        dialog.image_avatar_scale_spin.setValue(1.25)
        dialog.image_avatar_x_slider.setValue(80)
        dialog.image_avatar_y_slider.setValue(30)

        current_item = dialog.image_avatar_emotion_list.currentItem()
        storage_key = current_item.data(Qt.ItemDataRole.UserRole)
        values = dialog._get_current_values()

        assert values["avatar_mode"] == "image"
        assert values["image_avatar_folder"] == str(avatar_dir).replace("\\", "/")
        assert values["image_avatar_preview_emotion"] == "normal"
        assert values["image_avatar_placements"][storage_key] == {
            "scale": 1.25,
            "x_percent": 80,
            "y_percent": 30,
        }

        dialog.close()


def test_settings_dialog_saves_previous_image_placement_before_loading_new_emotion(monkeypatch, tmp_path):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")
    avatar_dir = tmp_path / "avatar_images"
    avatar_dir.mkdir()
    (avatar_dir / "normal.png").write_bytes(b"synthetic image placeholder")
    (avatar_dir / "smile.png").write_bytes(b"synthetic image placeholder")

    with _stub_prompt_module():
        from src.core.image_avatar import build_image_avatar_payload
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        payload = build_image_avatar_payload({"image_avatar_folder": str(avatar_dir)})
        normal_key = payload["images"]["normal"]["storageKey"]
        smile_key = payload["images"]["smile"]["storageKey"]

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "avatar_mode": "image",
                "image_avatar_folder": str(avatar_dir),
                "image_avatar_placements": {
                    smile_key: {"scale": 1.4, "x_percent": 20, "y_percent": 30},
                },
            }
        )

        dialog.image_avatar_scale_spin.setValue(0.8)
        dialog.image_avatar_x_slider.setValue(11)
        dialog.image_avatar_y_slider.setValue(22)
        dialog.image_avatar_emotion_list.setCurrentRow(1)

        assert dialog._image_avatar_placements[normal_key] == {
            "scale": 0.8,
            "x_percent": 11,
            "y_percent": 22,
        }
        assert dialog.image_avatar_emotion_list.currentItem().text() == "smile"
        assert dialog.image_avatar_scale_spin.value() == 1.4
        assert dialog.image_avatar_x_slider.value() == 20
        assert dialog.image_avatar_y_slider.value() == 30

        values = dialog._get_current_values()
        assert values["image_avatar_placements"][smile_key] == {
            "scale": 1.4,
            "x_percent": 20,
            "y_percent": 30,
        }

        dialog.close()


def test_settings_dialog_image_avatar_placement_ignores_non_finite_saved_values(monkeypatch, tmp_path):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")
    avatar_dir = tmp_path / "avatar_images"
    avatar_dir.mkdir()
    (avatar_dir / "normal.png").write_bytes(b"synthetic image placeholder")

    with _stub_prompt_module():
        from src.core.image_avatar import build_image_avatar_payload
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        payload = build_image_avatar_payload({"image_avatar_folder": str(avatar_dir)})
        normal_key = payload["images"]["normal"]["storageKey"]

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "avatar_mode": "image",
                "image_avatar_folder": str(avatar_dir),
                "image_avatar_placements": {
                    normal_key: {
                        "scale": "nan",
                        "x_percent": "nan",
                        "y_percent": "inf",
                    },
                },
            }
        )

        assert dialog.image_avatar_scale_spin.value() == 1.0
        assert dialog.image_avatar_x_slider.value() == 50
        assert dialog.image_avatar_y_slider.value() == 50

        values = dialog._get_current_values()
        assert values["image_avatar_placements"][normal_key] == {
            "scale": 1.0,
            "x_percent": 50,
            "y_percent": 50,
        }

        dialog.close()


def test_settings_dialog_preview_exports_selected_image_avatar_emotion(monkeypatch, tmp_path):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")
    avatar_dir = tmp_path / "avatar_images"
    avatar_dir.mkdir()
    (avatar_dir / "normal.png").write_bytes(b"synthetic image placeholder")
    (avatar_dir / "smile.png").write_bytes(b"synthetic image placeholder")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "avatar_mode": "image",
                "image_avatar_folder": str(avatar_dir),
            }
        )
        captured = []
        dialog.settings_preview.connect(captured.append)

        dialog.image_avatar_emotion_list.setCurrentRow(1)
        dialog._preview_settings()

        assert captured[-1]["image_avatar_preview_emotion"] == "smile"

        dialog.close()


def test_settings_dialog_folder_editing_refreshes_preview_after_selected_emotion_changes(monkeypatch, tmp_path):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")
    first_dir = tmp_path / "first_avatar_images"
    second_dir = tmp_path / "second_avatar_images"
    first_dir.mkdir()
    second_dir.mkdir()
    (first_dir / "normal.png").write_bytes(b"synthetic image placeholder")
    (first_dir / "smile.png").write_bytes(b"synthetic image placeholder")
    (second_dir / "normal.png").write_bytes(b"synthetic image placeholder")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "avatar_mode": "image",
                "image_avatar_folder": str(first_dir),
            }
        )
        captured = []
        dialog.settings_preview.connect(captured.append)

        dialog.image_avatar_emotion_list.setCurrentRow(1)
        captured.clear()
        dialog.image_avatar_folder_edit.setText(str(second_dir))

        assert captured == []

        dialog.image_avatar_folder_edit.editingFinished.emit()

        assert dialog.image_avatar_emotion_list.currentItem().text() == "normal"
        assert [item["image_avatar_preview_emotion"] for item in captured] == ["normal"]

        dialog.close()


def test_settings_dialog_empty_image_avatar_folder_browse_starts_from_avatar_images(monkeypatch, tmp_path):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui import settings_dialog_values
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "avatar_mode": "image",
                "image_avatar_folder": "",
            }
        )
        user_avatar_dir = tmp_path / "user" / "avatar_images"
        bundle_avatar_dir = tmp_path / "bundle" / "avatar_images"
        user_avatar_dir.mkdir(parents=True)
        bundle_avatar_dir.mkdir(parents=True)
        dialog._user_data_root = tmp_path / "user"
        dialog._bundle_root = tmp_path / "bundle"
        starts = []
        monkeypatch.setattr(
            settings_dialog_values.QFileDialog,
            "getExistingDirectory",
            lambda _parent, _title, start_dir: starts.append(start_dir) or "",
        )

        dialog._browse_image_avatar_folder()

        assert starts == [str(user_avatar_dir)]

        dialog.close()


def test_settings_dialog_clamps_away_input_grace_to_idle_minutes():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "enable_away_nudge": True,
                "away_idle_minutes": 20,
                "away_input_grace_minutes": 30,
            }
        )

        assert dialog.away_input_grace_minutes_spin.maximum() == 20
        assert dialog.away_input_grace_minutes_spin.value() == 20

        dialog.away_idle_minutes_spin.setValue(12)

        assert dialog.away_input_grace_minutes_spin.maximum() == 12
        assert dialog.away_input_grace_minutes_spin.value() == 12
        assert dialog._get_current_values()["away_input_grace_minutes"] == 12

        dialog.close()


def test_settings_dialog_exposes_typing_effect_controls_and_saves_values():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "typing_effect_enabled": True,
                "typing_effect_speed": "normal",
            }
        )

        assert dialog.typing_effect_check.isChecked() is True
        assert [dialog.typing_effect_speed_combo.itemData(index) for index in range(dialog.typing_effect_speed_combo.count())] == [
            "fast",
            "normal",
            "slow",
        ]
        assert dialog.typing_effect_speed_combo.currentData() == "normal"

        dialog.typing_effect_check.setChecked(False)
        assert dialog.typing_effect_speed_combo.isEnabled() is False

        dialog.typing_effect_check.setChecked(True)
        dialog.typing_effect_speed_combo.setCurrentIndex(
            dialog.typing_effect_speed_combo.findData("slow")
        )

        current_values = dialog._get_current_values()
        assert current_values["typing_effect_enabled"] is True
        assert current_values["typing_effect_speed"] == "slow"

        dialog.close()


def test_settings_dialog_exposes_message_split_toggle_and_saves_value():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "message_split_enabled": False,
            }
        )

        assert dialog.message_split_check.isChecked() is False

        dialog.message_split_check.setChecked(True)

        current_values = dialog._get_current_values()
        assert current_values["message_split_enabled"] is True

        dialog.close()


def test_settings_dialog_exposes_proactive_conversation_toggle_and_saves_value():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "enable_proactive_conversation": False,
            }
        )

        assert dialog.enable_proactive_conversation_check.isChecked() is False

        dialog.enable_proactive_conversation_check.setChecked(True)

        current_values = dialog._get_current_values()
        assert current_values["enable_proactive_conversation"] is True

        dialog.close()


def test_settings_dialog_exposes_ene_thought_context_controls_and_saves_values():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
                "enable_ene_thoughts": True,
                "include_ene_thoughts_in_context": False,
                "ene_thought_context_limit": 2,
            }
        )

        assert dialog.enable_ene_thoughts_check.isChecked() is True
        assert dialog.include_ene_thoughts_in_context_check.isEnabled() is True
        assert dialog.include_ene_thoughts_in_context_check.isChecked() is False
        assert dialog.ene_thought_context_limit_spin.value() == 2
        assert dialog.ene_thought_context_limit_spin.isEnabled() is False

        dialog.include_ene_thoughts_in_context_check.setChecked(True)
        dialog.ene_thought_context_limit_spin.setValue(5)
        current_values = dialog._get_current_values()
        assert current_values["include_ene_thoughts_in_context"] is True
        assert current_values["ene_thought_context_limit"] == 5

        dialog.enable_ene_thoughts_check.setChecked(False)
        assert dialog.include_ene_thoughts_in_context_check.isEnabled() is False
        assert dialog.ene_thought_context_limit_spin.isEnabled() is False

        dialog.close()


def test_settings_dialog_language_preview_restores_original_runtime_on_cancel():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    from src.core.i18n import tr

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            },
            bridge=SimpleNamespace(ene_profile=_DummyEneProfile(), parent=lambda: None),
        )

        assert dialog.content_header_title.text() == "창 설정"
        assert tr("settings.window.title") == "ENE 설정"
        popup = dialog._ensure_theme_picker_popup()
        assert popup.title_label.text() == "색상 선택"

        dialog.ui_language_combo.setCurrentIndex(dialog.ui_language_combo.findData("en"))

        assert dialog.content_header_title.text() == "Window Settings"
        assert dialog.global_ptt_hotkey_set_button.text() == "Set Hotkey"
        assert popup.title_label.text() == "Color selection"
        assert tr("settings.window.title") == "ENE 설정"

        dialog._cancel_settings()

        assert tr("settings.window.title") == "ENE 설정"


def test_settings_dialog_retranslates_prompt_and_profile_lazy_tabs_in_japanese_preview(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    from src.core.i18n import tr

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            },
            bridge=SimpleNamespace(ene_profile=_DummyEneProfile(), parent=lambda: None),
        )

        dialog._ensure_lazy_tab_loaded("profile")
        dialog._ensure_lazy_tab_loaded("ene_profile")
        dialog._ensure_lazy_tab_loaded("prompt")
        dialog._ensure_lazy_tab_loaded("memory")

        assert dialog.basic_info_key_input.placeholderText() == "항목 이름"
        assert dialog.emotion_name_input.placeholderText() == "감정 키 (예: shy)"
        assert dialog._prompt_status_label.text() == "로드 대기"
        assert dialog._profile_status_label.text() == "user_profile.json 로드 완료"
        assert dialog.fact_timestamp_label.text() == "신규 항목"
        assert dialog._embedded_ene_profile_panel is not None
        assert dialog._embedded_ene_profile_panel.core_group.title() == "기본 설정"
        assert dialog._embedded_ene_profile_panel.fact_group.title() == "학습 정보"
        assert not hasattr(dialog._embedded_memory_panel, "ene_profile_btn")
        assert tr("settings.window.title") == "ENE 설정"

        dialog.ui_language_combo.setCurrentIndex(dialog.ui_language_combo.findData("ja"))

        ene_profile_index = next(
            index for index, tab_id in dialog._lazy_tab_index_to_id.items() if tab_id == "ene_profile"
        )
        dialog._set_section_index(ene_profile_index)

        assert dialog.content_header_title.text() == "ENE記憶管理"
        assert dialog.ui_language_combo.itemText(0) == "システムの既定値"
        assert dialog.basic_info_key_input.placeholderText() == "項目名"
        assert dialog.emotion_name_input.placeholderText() == "感情キー (例: shy)"
        assert dialog._prompt_status_label.text() == "読み込み待機"
        assert dialog._profile_status_label.text() == "user_profile.json 読み込み完了"
        assert dialog.fact_timestamp_label.text() == "新しい項目"
        assert dialog.fact_category_combo.itemText(0) == "基本情報"
        assert dialog._embedded_ene_profile_panel.core_group.title() == "基本設定"
        assert dialog._embedded_ene_profile_panel.fact_group.title() == "学習情報"
        assert dialog.memory_search_recent_turns_spin.suffix() == " ターン"
        assert dialog.memory_search_recent_turns_spin.specialValueText() == "現在のメッセージのみ"
        assert {"基本情報", "好みと苦手", "感情一覧と使用ガイド", "基本設定", "学習情報"}.issubset(
            {group.title() for group in dialog.findChildren(QGroupBox)}
        )
        assert "メモリ検索範囲" in {label.text() for label in dialog.findChildren(QLabel)}
        assert {"再読み込み", "保存"}.issubset({button.text() for button in dialog.findChildren(QPushButton)})
        assert tr("settings.window.title") == "ENE 설정"

        dialog.close()


def test_calendar_dialog_translates_visible_strings_and_confirmations(tmp_path, monkeypatch):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    _write_locales(
        locales_dir,
        en_data={
            "calendar.window.title": "ENE Calendar",
            "calendar.date.placeholder": "Select a date",
            "calendar.date.format": "yyyy-MM-dd",
            "calendar.events.label": "Events:",
            "calendar.activity.summary": "💬 {conversation_count} chats | 🖐 {head_pat_count} pats",
            "calendar.empty": "No events scheduled",
            "calendar.close": "Close",
            "calendar.delete.title": "Delete event",
            "calendar.delete.body": "Delete this event?",
            "calendar.source.label": "Source: {source}",
            "calendar.source.ai_extracted": "AI extracted",
            "calendar.source.user": "User created",
            "calendar.source.manual": "Manual",
        },
        ja_data={
            "calendar.window.title": "ENE カレンダー",
            "calendar.date.placeholder": "日付を選択してください",
            "calendar.date.format": "yyyy/MM/dd",
            "calendar.events.label": "予定:",
            "calendar.activity.summary": "💬 {conversation_count}回 | 🖐 {head_pat_count}回",
            "calendar.empty": "予定はありません",
            "calendar.close": "閉じる",
            "calendar.delete.title": "予定を削除",
            "calendar.delete.body": "この予定を削除しますか？",
            "calendar.source.label": "出典: {source}",
            "calendar.source.ai_extracted": "AI抽出",
            "calendar.source.user": "ユーザー作成",
            "calendar.source.manual": "手動入力",
        },
    )
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    dialog = CalendarDialog(_DummyCalendarManager())

    assert dialog.windowTitle() == "ENE カレンダー"
    assert dialog.date_label.text() == "日付を選択してください"
    assert "閉じる" in {button.text() for button in dialog.findChildren(QPushButton)}
    assert "予定:" in {label.text() for label in dialog.findChildren(QLabel)}

    dialog._on_date_selected(QDate(2026, 3, 24))

    assert dialog.date_label.text() == "2026/03/24"
    assert dialog.activity_label.text() == "💬 3回 | 🖐 1回"

    all_row_texts = []
    for index in range(dialog.event_list.count()):
        row = dialog.event_list.itemWidget(dialog.event_list.item(index))
        all_row_texts.extend(label.text().strip() for label in row.findChildren(QLabel))
    assert "出典: AI抽出" in all_row_texts
    assert "出典: ユーザー作成" in all_row_texts

    dialog._on_date_selected(QDate(2026, 3, 25))
    assert dialog.event_list.item(0).text() == "予定はありません"

    questions = []

    def fake_question(parent, title, text, buttons, default_button):
        questions.append((title, text))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.question", fake_question)
    dialog._on_event_deleted("event-1")

    assert questions == [("予定を削除", "この予定を削除しますか？")]
    dialog.close()


def test_profile_dialog_translates_sections_fields_and_empty_state(tmp_path, monkeypatch):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    _write_locales(
        locales_dir,
        en_data={
            "profile.window.title": "Profile Manager",
            "profile.stats.summary": "Basic info {basic_count} | Extracted info {fact_count} | Preferences {preference_count}",
            "profile.button.delete": "🗑️ Delete",
            "profile.button.refresh": "🔄 Refresh",
            "profile.button.close": "Close",
            "profile.empty": "No profile information saved.",
            "profile.section.basic": "📋 Basic Info",
            "profile.section.preferences": "❤️ Preferences",
            "profile.section.extracted": "🤖 Extracted Info",
            "profile.field.name": "Name",
            "profile.field.gender": "Gender",
            "profile.field.birthday": "Birthday",
            "profile.field.occupation": "Occupation",
            "profile.field.major": "Major",
            "profile.field.location": "Location",
            "profile.preference.like": "Like: {value}",
            "profile.preference.dislike": "Dislike: {value}",
            "profile.category.basic": "Basic",
            "profile.category.preference": "Preference",
            "profile.category.goal": "Goal",
            "profile.category.habit": "Habit",
            "profile.source.label": "Source: {source}",
            "profile.source.conversation": "Conversation",
            "profile.source.conversation_summary": "Conversation summary",
            "profile.delete.title": "Delete confirmation",
            "profile.delete.body": "Delete the selected profile entry?",
        },
        ja_data={
            "profile.window.title": "プロフィール管理",
            "profile.stats.summary": "基本情報 {basic_count}件 | 抽出情報 {fact_count}件 | 好み {preference_count}件",
            "profile.button.delete": "🗑️ 削除",
            "profile.button.refresh": "🔄 更新",
            "profile.button.close": "閉じる",
            "profile.empty": "登録されたプロフィール情報はありません。",
            "profile.section.basic": "📋 基本情報",
            "profile.section.preferences": "❤️ 趣味・好み",
            "profile.section.extracted": "🤖 抽出情報",
            "profile.field.name": "名前",
            "profile.field.gender": "性別",
            "profile.field.birthday": "誕生日",
            "profile.field.occupation": "職業",
            "profile.field.major": "専攻",
            "profile.field.location": "居住地",
            "profile.preference.like": "好き: {value}",
            "profile.preference.dislike": "苦手: {value}",
            "profile.category.basic": "基本情報",
            "profile.category.preference": "好み",
            "profile.category.goal": "目標",
            "profile.category.habit": "習慣",
            "profile.source.label": "出典: {source}",
            "profile.source.conversation": "会話",
            "profile.source.conversation_summary": "会話の要約",
            "profile.delete.title": "削除の確認",
            "profile.delete.body": "選択したプロフィール情報を削除しますか？",
        },
    )
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    profile = _DummyUserProfile(
        basic_info={
            "name": "Yuna",
            "gender": "女性",
            "birthday": "1998-03-24",
            "occupation": "開発者",
            "major": "デザイン",
            "location": "Seoul",
        },
        preferences={"likes": ["Jazz"], "dislikes": []},
        facts=[
            SimpleNamespace(
                timestamp="2026-03-24T09:30:00",
                category="preference",
                content="Enjoys calm workspaces",
                source="conversation",
            ),
            SimpleNamespace(
                timestamp="2026-03-23T08:15:00",
                category="goal",
                content="Plans to practice English daily",
                source="conversation summary (2026-03-23 08:15)",
            )
        ],
    )
    dialog = ProfileDialog(profile)

    assert dialog.windowTitle() == "プロフィール管理"
    assert dialog.stats_label.text() == "基本情報 6件 | 抽出情報 2件 | 好み 1件"
    assert {button.text() for button in dialog.findChildren(QPushButton)} >= {"🗑️ 削除", "🔄 更新", "閉じる"}

    item_texts = [dialog.profile_list.item(index).text() for index in range(dialog.profile_list.count()) if dialog.profile_list.item(index).text()]
    assert "📋 基本情報" in item_texts
    assert "❤️ 趣味・好み" in item_texts
    assert "🤖 抽出情報" in item_texts
    assert "  • 名前: Yuna" in item_texts
    assert "  • 性別: 女性" in item_texts
    assert "  • 職業: 開発者" in item_texts
    assert "  • 居住地: Seoul" in item_texts

    fact_widget = dialog.profile_list.itemWidget(dialog.profile_list.item(dialog.profile_list.count() - 1))
    recent_fact_widget = dialog.profile_list.itemWidget(dialog.profile_list.item(dialog.profile_list.count() - 2))
    recent_fact_texts = [label.text() for label in recent_fact_widget.findChildren(QLabel)]
    assert "[好み]" in recent_fact_texts
    assert "出典: 会話" in recent_fact_texts

    fact_texts = [label.text() for label in fact_widget.findChildren(QLabel)]
    assert "[目標]" in fact_texts
    assert "出典: 会話の要約 (2026-03-23 08:15)" in fact_texts

    dialog.profile_list.setCurrentRow(dialog.profile_list.count() - 1)
    questions = []

    def fake_question(parent, title, text, buttons, default_button):
        questions.append((title, text))
        return QMessageBox.StandardButton.No

    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.question", fake_question)
    dialog._delete_fact()

    assert questions == [("削除の確認", "選択したプロフィール情報を削除しますか？")]
    dialog.close()

    empty_dialog = ProfileDialog(_DummyUserProfile())
    assert empty_dialog.profile_list.item(0).text() == "登録されたプロフィール情報はありません。"
    empty_dialog.close()

    dislikes_only_dialog = ProfileDialog(
        _DummyUserProfile(
            preferences={"likes": [], "dislikes": ["Crowded spaces"]},
        )
    )
    dislikes_item_texts = [
        dislikes_only_dialog.profile_list.item(index).text()
        for index in range(dislikes_only_dialog.profile_list.count())
        if dislikes_only_dialog.profile_list.item(index).text()
    ]
    assert dislikes_only_dialog.stats_label.text() == "基本情報 0件 | 抽出情報 0件 | 好み 1件"
    assert "❤️ 趣味・好み" in dislikes_item_texts
    assert "  • 苦手: Crowded spaces" in dislikes_item_texts
    assert "登録されたプロフィール情報はありません。" not in dislikes_item_texts
    dislikes_only_dialog.close()


def test_ene_profile_dialog_translates_sections_and_controls(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    _write_locales(
        locales_dir,
        en_data={
            "ene_profile.window.title": "ENE Profile Manager",
            "ene_profile.stats.summary": "Core {core_count} | Learned {fact_count}",
            "ene_profile.button.close": "Close",
            "ene_profile.button.refresh": "Refresh",
            "ene_profile.button.save": "Save",
            "ene_profile.section.core": "Core Profile",
            "ene_profile.section.facts": "Learned Facts",
            "ene_profile.core.identity": "Identity",
            "ene_profile.core.speaking_style": "Speaking Style",
            "ene_profile.core.relationship_tone": "Relationship Tone",
            "ene_profile.category.speaking_style": "Speaking Style",
            "ene_profile.origin.auto": "Auto",
            "ene_profile.source.label": "Source: {source}",
        },
        ja_data={
            "ene_profile.window.title": "エネ情報管理",
            "ene_profile.stats.summary": "基本設定 {core_count}件 | 学習情報 {fact_count}件",
            "ene_profile.button.close": "閉じる",
            "ene_profile.button.refresh": "更新",
            "ene_profile.button.save": "保存",
            "ene_profile.section.core": "基本設定",
            "ene_profile.section.facts": "学習情報",
            "ene_profile.core.identity": "自己定義",
            "ene_profile.core.speaking_style": "話し方",
            "ene_profile.core.relationship_tone": "関係トーン",
            "ene_profile.category.speaking_style": "話し方",
            "ene_profile.origin.auto": "自動",
            "ene_profile.source.label": "出典: {source}",
        },
    )
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    from src.ui.ene_profile_dialog import EneProfileDialog

    profile = _DummyEneProfile(
        core_profile={
            "identity": ["에네는 차분한 데스크톱 동반자다."],
            "speaking_style": ["짧고 단정한 문장을 선호한다."],
            "relationship_tone": ["사용자를 다정하게 챙긴다."],
        },
        facts=[
            SimpleNamespace(
                timestamp="2026-03-24T09:30:00",
                category="speaking_style",
                content="짧고 단정한 말투를 유지한다.",
                source="대화 요약 (2026-03-24 09:30)",
                origin="auto",
                auto_update=True,
            )
        ],
    )
    dialog = EneProfileDialog(profile)

    assert dialog.windowTitle() == "エネ情報管理"
    assert dialog.stats_label.text() == "基本設定 3件 | 学習情報 1件"
    assert dialog.core_group.title() == "基本設定"
    assert dialog.fact_group.title() == "学習情報"
    assert {button.text() for button in dialog.findChildren(QPushButton)} >= {"閉じる", "更新", "保存"}
    assert dialog.core_list.count() == 3
    assert dialog.fact_list.count() == 1
    assert "自己定義" in dialog.core_list.item(0).text()
    assert "話し方" in dialog.fact_list.item(0).text()
    dialog.close()


def test_memory_dialog_translates_visible_strings_states_and_profile_warnings(tmp_path, monkeypatch):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    _write_locales(
        locales_dir,
        en_data={
            "memory.window.title": "ENE Memory Manager",
            "memory.window.subtitle": "Manage summaries, search parameters, and saved memories in one place.",
            "memory.metric.total.label": "Total memories",
            "memory.metric.total.detail": "All stored memories",
            "memory.metric.important.label": "Important memories",
            "memory.metric.important.detail": "Items marked important",
            "memory.metric.embedding.label": "Embedding coverage",
            "memory.metric.embedding.detail": "{count} connected",
            "memory.metric.threshold.label": "Auto summary threshold",
            "memory.metric.threshold.detail": "Conversation unit",
            "memory.search.placeholder": "Search titles, summaries, or tags",
            "memory.filter.important_only": "Important only",
            "memory.filter.source.prefix": "Source: {value}",
            "memory.filter.source.all": "All",
            "memory.filter.source.legacy": "Legacy",
            "memory.filter.source.chat": "Chat",
            "memory.filter.type.prefix": "Type: {value}",
            "memory.filter.type.all": "All",
            "memory.filter.type.preference": "Preference",
            "memory.filter.type.fact": "Fact",
            "memory.sort.newest": "Newest first",
            "memory.sort.oldest": "Oldest first",
            "memory.button.refresh": "Refresh",
            "memory.chip.summary_tags": "Summary + tag search",
            "memory.chip.retrieval_mix": "Important/similar/recent mix",
            "memory.chip.auto_save": "Save immediately",
            "memory.list.title": "Memory list",
            "memory.list.latest_hint": "Showing newest memories first.",
            "memory.list.visible_count": "Showing {count} items",
            "memory.empty.title": "No memory selected",
            "memory.empty.body": "Select a memory on the left to view details and actions here.",
            "memory.inspector.title": "Selected memory",
            "memory.detail.time": "Memory time",
            "memory.detail.source_count": "Source messages",
            "memory.detail.source": "Source",
            "memory.detail.type": "Type",
            "memory.detail.confidence": "Confidence",
            "memory.detail.migration": "Migration",
            "memory.detail.entities": "Entities",
            "memory.detail.importance_reason": "Importance reason",
            "memory.detail.important": "Importance",
            "memory.detail.embedding": "Embedding",
            "memory.button.mark_important": "Mark important",
            "memory.button.unmark_important": "Unmark important",
            "memory.button.delete": "Delete memory",
            "memory.tuning.title": "Memory retrieval settings",
            "memory.tuning.body": "Adjust the auto-summary threshold and retrieval parameters here.",
            "memory.tuning.threshold.title": "Auto-summary after N messages",
            "memory.tuning.threshold.body": "Run auto-summary when a conversation chunk exceeds this value.",
            "memory.tuning.important.title": "Max important memories",
            "memory.tuning.important.body": "Always review up to this many important memories first.",
            "memory.tuning.similar.title": "Max similar memories",
            "memory.tuning.similar.body": "Choose how many meaningfully similar memories to retrieve.",
            "memory.tuning.recent.title": "Max recent memories",
            "memory.tuning.recent.body": "Include this many recent memories regardless of similarity.",
            "memory.tuning.similarity.title": "Minimum similarity",
            "memory.tuning.similarity.body": "Exclude memories below this similarity threshold.",
            "memory.tuning.note": "Values in this tab are saved immediately.",
            "memory.unit.count": "{count}",
            "memory.unit.items": "{count} items",
            "memory.unit.messages": "{count} messages",
            "memory.unit.count_suffix": "",
            "memory.unit.percent_suffix": "%",
            "memory.preview.empty": "No summary yet.",
            "memory.summary.empty": "No summary",
            "memory.badge.important": "Important",
            "memory.badge.embedding": "Embedding",
            "memory.badge.source.legacy": "Legacy",
            "memory.badge.type.preference": "Preference",
            "memory.value.important.true": "Keep",
            "memory.value.important.false": "Regular",
            "memory.value.embedding.true": "Connected",
            "memory.value.embedding.false": "None",
            "memory.value.source.legacy": "Legacy import",
            "memory.value.type.preference": "Preference",
            "memory.value.confidence.percent": "{percent}%",
            "memory.value.migration.migrated": "Migrated",
            "memory.value.migration.current": "Current schema",
            "memory.value.entities.none": "None",
            "memory.value.importance_reason.legacy_important": "Legacy important",
            "memory.value.importance_reason.none": "None",
            "memory.delete.title": "Delete confirmation",
            "memory.delete.body": "Delete `{summary}`?",
            "memory.profile.missing.title": "No profile",
            "memory.profile.missing.body": "User profile is not initialized.",
            "memory.profile.empty.title": "No profile data",
            "memory.profile.empty.body": "No profile information is saved yet.\nChat to extract information automatically.",
            "memory.ene_profile.missing.title": "No ENE profile",
            "memory.ene_profile.missing.body": "ENE profile is not initialized.",
            "memory.ene_profile.empty.title": "No ENE profile data",
            "memory.ene_profile.empty.body": "No ENE information is saved yet.\nTalk more to let ENE build self-information.",
        },
        ja_data={
            "memory.window.title": "ENE メモリ管理",
            "memory.window.subtitle": "自動要約、検索パラメータ、保存済みメモリを1か所で管理します。",
            "memory.metric.total.label": "総メモリ",
            "memory.metric.total.detail": "保存された全メモリ",
            "memory.metric.important.label": "重要メモリ",
            "memory.metric.important.detail": "重要としてマークされた項目",
            "memory.metric.embedding.label": "埋め込みカバレッジ",
            "memory.metric.embedding.detail": "{count}件接続",
            "memory.metric.threshold.label": "自動要約基準",
            "memory.metric.threshold.detail": "会話単位",
            "memory.search.placeholder": "メモリのタイトル、要約、タグを検索",
            "memory.filter.important_only": "重要のみ",
            "memory.filter.source.prefix": "由来: {value}",
            "memory.filter.source.all": "すべて",
            "memory.filter.source.legacy": "旧メモリ",
            "memory.filter.source.chat": "会話",
            "memory.filter.type.prefix": "種類: {value}",
            "memory.filter.type.all": "すべて",
            "memory.filter.type.preference": "好み",
            "memory.filter.type.fact": "事実",
            "memory.sort.newest": "新しい順",
            "memory.sort.oldest": "古い順",
            "memory.button.refresh": "更新",
            "memory.chip.summary_tags": "要約 + タグ検索",
            "memory.chip.retrieval_mix": "重要・類似・最近の組み合わせ",
            "memory.chip.auto_save": "変更は即時保存",
            "memory.list.title": "メモリ一覧",
            "memory.list.latest_hint": "新しいメモリから表示します。",
            "memory.list.visible_count": "{count}件を表示中",
            "memory.empty.title": "選択されたメモリはありません",
            "memory.empty.body": "左の一覧からメモリを選ぶと、詳細情報と管理アクションがここに表示されます。",
            "memory.inspector.title": "選択中のメモリ",
            "memory.detail.time": "メモリ時刻",
            "memory.detail.source_count": "元メッセージ数",
            "memory.detail.source": "由来",
            "memory.detail.type": "種類",
            "memory.detail.confidence": "信頼度",
            "memory.detail.migration": "移行状態",
            "memory.detail.entities": "エンティティ",
            "memory.detail.importance_reason": "重要理由",
            "memory.detail.important": "重要度",
            "memory.detail.embedding": "埋め込み状態",
            "memory.button.mark_important": "重要にする",
            "memory.button.unmark_important": "重要を解除",
            "memory.button.delete": "メモリを削除",
            "memory.tuning.title": "メモリ検索設定",
            "memory.tuning.body": "自動要約の基準と検索パラメータをこの領域でその場で調整します。",
            "memory.tuning.threshold.title": "会話がN件以上で自動要約",
            "memory.tuning.threshold.body": "メモリが蓄積した会話のまとまりがこの値を超えると自動要約を実行します。",
            "memory.tuning.important.title": "最大重要メモリ数",
            "memory.tuning.important.body": "回収時に常に優先確認する重要メモリの最大数です。",
            "memory.tuning.similar.title": "最大類似メモリ数",
            "memory.tuning.similar.body": "現在の入力と意味が近いメモリをいくつまで取得するかを決めます。",
            "memory.tuning.recent.title": "最大最近メモリ数",
            "memory.tuning.recent.body": "類似度とは別に最近の文脈をいくつまで補助として含めるかを決めます。",
            "memory.tuning.similarity.title": "最小類似度",
            "memory.tuning.similarity.body": "この値より低いメモリは類似候補から除外します。",
            "memory.tuning.note": "このタブの値は変更後すぐに設定ファイルへ保存されます。",
            "memory.unit.count": "{count}件",
            "memory.unit.items": "{count}件",
            "memory.unit.messages": "{count}件のメッセージ",
            "memory.unit.count_suffix": "件",
            "memory.unit.percent_suffix": "%",
            "memory.preview.empty": "まだ要約はありません。",
            "memory.summary.empty": "要約なし",
            "memory.badge.important": "重要",
            "memory.badge.embedding": "埋め込み",
            "memory.badge.source.legacy": "旧メモリ",
            "memory.badge.type.preference": "好み",
            "memory.value.important.true": "保持対象",
            "memory.value.important.false": "通常メモリ",
            "memory.value.embedding.true": "接続済み",
            "memory.value.embedding.false": "なし",
            "memory.value.source.legacy": "旧データ",
            "memory.value.type.preference": "好み",
            "memory.value.confidence.percent": "{percent}%",
            "memory.value.migration.migrated": "移行済み",
            "memory.value.migration.current": "現行スキーマ",
            "memory.value.entities.none": "なし",
            "memory.value.importance_reason.legacy_important": "旧重要メモリ",
            "memory.value.importance_reason.none": "なし",
            "memory.delete.title": "削除の確認",
            "memory.delete.body": "`{summary}` を削除しますか？",
            "memory.profile.missing.title": "プロフィールなし",
            "memory.profile.missing.body": "ユーザープロフィールが初期化されていません。",
            "memory.profile.empty.title": "プロフィール情報なし",
            "memory.profile.empty.body": "まだ保存されたプロフィール情報はありません。\n会話すると自動で情報が抽出されます。",
            "memory.ene_profile.missing.title": "エネ情報なし",
            "memory.ene_profile.missing.body": "エネプロフィールが初期化されていません。",
            "memory.ene_profile.empty.title": "エネ情報なし",
            "memory.ene_profile.empty.body": "まだ保存されたエネ情報はありません。\n会話を重ねると自動で自己情報が蓄積されます。",
        },
    )
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    bridge = SimpleNamespace(
        summarize_threshold=8,
        settings=_DummySettings(
            {
                "max_important_memories": 4,
                "max_similar_memories": 5,
                "min_similarity": 0.42,
                "max_recent_memories": 2,
            }
        ),
        user_profile=None,
        ene_profile=_DummyEneProfile(),
    )
    manager = _DummyMemoryManager(
        [
            SimpleNamespace(
                id="memory-1",
                timestamp="2026-03-24T10:15:00",
                summary="Keeps launch checklists ready",
                tags=["ops", "launch"],
                is_important=True,
                embedding=[0.1],
                original_messages=["a", "b"],
                source="legacy",
                memory_type="preference",
                confidence=0.6,
                entity_names=["ENE", "Obsidian"],
                importance_reason="legacy_important",
                migration_meta={"migration_version": 1},
            ),
            SimpleNamespace(
                id="memory-2",
                timestamp="2026-03-23T08:00:00",
                summary="",
                tags=["archive"],
                is_important=False,
                embedding=None,
                original_messages=["c"],
                source="chat",
                memory_type="fact",
                confidence=0.5,
                entity_names=[],
                importance_reason="none",
                migration_meta={},
            ),
        ]
    )

    dialog = MemoryDialog(manager, bridge=bridge)

    assert dialog.windowTitle() == "ENE メモリ管理"
    assert dialog.search_input.placeholderText() == "メモリのタイトル、要約、タグを検索"
    assert dialog.important_filter_btn.text() == "重要のみ"
    assert dialog.source_filter_btn.text() == "由来: すべて"
    assert dialog.type_filter_btn.text() == "種類: すべて"
    assert dialog.sort_button.text() == "新しい順"
    assert dialog.list_hint_label.text() == "2件を表示中"
    assert dialog.important_btn.text() == "重要を解除"
    assert dialog.delete_btn.text() == "メモリを削除"
    assert dialog.inspector_source_value.text() == "2件のメッセージ"
    assert dialog.inspector_memory_source_value.text() == "旧データ"
    assert dialog.inspector_memory_type_value.text() == "好み"
    assert dialog.inspector_confidence_value.text() == "60%"
    assert dialog.inspector_migration_value.text() == "移行済み"
    assert dialog.inspector_entities_value.text() == "ENE, Obsidian"
    assert dialog.inspector_importance_reason_value.text() == "旧重要メモリ"
    assert dialog.inspector_important_value.text() == "保持対象"
    assert dialog.inspector_embedding_value.text() == "接続済み"
    assert dialog.total_metric.value_label.text() == "2"
    assert dialog.important_metric.value_label.text() == "1"
    assert dialog.embedding_metric.detail_label.text() == "1件接続"
    assert dialog.threshold_metric.value_label.text() == "8件"

    metric_labels = {
        label.text()
        for label in dialog.findChildren(QLabel)
        if label.objectName() == "MetricLabel"
    }
    assert {"総メモリ", "重要メモリ", "埋め込みカバレッジ", "自動要約基準"} <= metric_labels

    key_labels = {
        label.text()
        for label in dialog.findChildren(QLabel)
        if label.objectName() == "KeyValueLabel"
    }
    assert {"メモリ時刻", "元メッセージ数", "由来", "種類", "信頼度", "移行状態", "エンティティ", "重要理由", "重要度", "埋め込み状態"} <= key_labels

    first_memory_widget = dialog.memory_list.itemWidget(dialog.memory_list.item(0))
    first_widget_texts = {
        label.text()
        for label in first_memory_widget.findChildren(QLabel)
        if label.text()
    }
    assert "旧メモリ" in first_widget_texts
    assert "好み" in first_widget_texts

    dialog.source_filter_btn.click()
    assert dialog.source_filter_btn.text() == "由来: 旧メモリ"
    assert dialog.list_hint_label.text() == "1件を表示中"
    assert dialog.inspector_title.text() == "Keeps launch checklists ready"

    dialog.type_filter_btn.click()
    assert dialog.type_filter_btn.text() == "種類: 好み"
    assert dialog.list_hint_label.text() == "1件を表示中"

    dialog.source_filter_btn.click()
    assert dialog.source_filter_btn.text() == "由来: 会話"
    assert dialog.list_hint_label.text() == "0件を表示中"

    dialog.type_filter_btn.click()
    assert dialog.type_filter_btn.text() == "種類: 事実"
    assert dialog.list_hint_label.text() == "1件を表示中"
    assert dialog.inspector_memory_source_value.text() == "会話"
    assert dialog.inspector_memory_type_value.text() == "事実"
    assert dialog.inspector_entities_value.text() == "なし"
    assert dialog.inspector_importance_reason_value.text() == "なし"

    dialog._toggle_sort_order()
    assert dialog.sort_button.text() == "古い順"
    dialog.source_filter_btn.click()
    dialog.type_filter_btn.click()
    dialog._select_memory_by_id("memory-1")

    questions = []
    warnings = []
    infos = []
    opened_profile_dialogs = []
    opened_ene_profile_dialogs = []

    def fake_question(parent, title, text, buttons, default_button):
        questions.append((title, text))
        return QMessageBox.StandardButton.No

    def fake_warning(parent, title, text):
        warnings.append((title, text))

    def fake_information(parent, title, text):
        infos.append((title, text))

    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.question", fake_question)
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.warning", fake_warning)
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.information", fake_information)
    monkeypatch.setattr("src.ui.profile_dialog.ProfileDialog.exec", lambda self: opened_profile_dialogs.append(self))
    monkeypatch.setattr("src.ui.ene_profile_dialog.EneProfileDialog.exec", lambda self: opened_ene_profile_dialogs.append(self))

    dialog._delete_memory()
    delattr(dialog.bridge, "user_profile")
    dialog._show_profile_dialog()
    delattr(dialog.bridge, "ene_profile")
    dialog._show_ene_profile_dialog()

    assert questions == [("削除の確認", "`Keeps launch checklists ready` を削除しますか？")]
    assert warnings == [
        ("プロフィールなし", "ユーザープロフィールが初期化されていません。"),
        ("エネ情報なし", "エネプロフィールが初期化されていません。"),
    ]

    bridge.user_profile = _TruthyEmptyUserProfile()
    bridge.ene_profile = _DummyEneProfile()
    dialog._show_profile_dialog()
    dialog._show_ene_profile_dialog()
    assert infos == [
        (
            "プロフィール情報なし",
            "まだ保存されたプロフィール情報はありません。\n会話すると自動で情報が抽出されます。",
        ),
        (
            "エネ情報なし",
            "まだ保存されたエネ情報はありません。\n会話を重ねると自動で自己情報が蓄積されます。",
        ),
    ]
    assert opened_profile_dialogs == []
    assert opened_ene_profile_dialogs == []
    dialog.close()

    empty_dialog = MemoryDialog(_DummyMemoryManager([]), bridge=bridge)
    assert empty_dialog.inspector_title.text() == "選択されたメモリはありません"
    assert empty_dialog.inspector_body.text() == "左の一覧からメモリを選ぶと、詳細情報と管理アクションがここに表示されます。"
    assert empty_dialog.list_hint_label.text() == "0件を表示中"
    empty_dialog.close()


def test_memory_dialog_does_not_overwrite_recent_memory_setting_during_load():
    _get_qapp()

    bridge = SimpleNamespace(
        summarize_threshold=8,
        settings=_DummySettings(
            {
                "max_important_memories": 3,
                "max_similar_memories": 5,
                "min_similarity": 0.42,
                "max_recent_memories": 7,
            }
        ),
        user_profile=None,
    )

    dialog = MemoryDialog(_DummyMemoryManager([]), bridge=bridge)

    assert bridge.settings.saved is False
    assert bridge.settings.config["max_recent_memories"] == 7
    assert dialog.recent_spinbox.value() == 7

    dialog.close()


def test_memory_dialog_allows_zero_threshold_and_saves_it_as_unlimited():
    _get_qapp()

    bridge = SimpleNamespace(
        summarize_threshold=0,
        settings=_DummySettings(
            {
                "max_important_memories": 3,
                "max_similar_memories": 5,
                "min_similarity": 0.42,
                "max_recent_memories": 2,
            }
        ),
        user_profile=None,
    )

    dialog = MemoryDialog(_DummyMemoryManager([]), bridge=bridge)

    assert dialog.threshold_spinbox.minimum() == 0
    assert dialog.threshold_spinbox.value() == 0

    dialog.threshold_spinbox.setValue(6)
    bridge.settings.saved = False
    dialog.threshold_spinbox.setValue(0)

    assert bridge.summarize_threshold == 0
    assert bridge.settings.config["summarize_threshold"] == 0
    assert bridge.settings.saved is True

    dialog.close()


def test_settings_dialog_blocks_wheel_changes_for_spin_and_combo_inputs(monkeypatch):
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    with _stub_prompt_module():
        from src.ui.settings_dialog import SettingsDialog

        monkeypatch.setattr(SettingsDialog, "_load_prompt_configuration", lambda self: None)

        dialog = SettingsDialog(
            {
                "ui_language": "ko",
                "llm_provider": "gemini",
                "tts_provider": "gpt_sovits_http",
                "enable_tts": True,
            },
            memory_manager=_DummyMemoryManager([]),
            bridge=SimpleNamespace(ene_profile=_DummyEneProfile(), parent=lambda: None),
        )
        dialog._ensure_lazy_tab_loaded("memory")

        assert dialog.eventFilter(dialog.window_width_spin, QEvent(QEvent.Type.Wheel)) is True
        assert dialog.eventFilter(dialog.ui_language_combo, QEvent(QEvent.Type.Wheel)) is True
        assert dialog._embedded_memory_panel.eventFilter(
            dialog._embedded_memory_panel.threshold_spinbox,
            QEvent(QEvent.Type.Wheel),
        ) is True

        dialog.close()


def test_memory_dialog_preview_truncates_card_text_with_ellipsis_and_keeps_badges_readable():
    _get_qapp()
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    medium_summary = (
        "2026년 4월 8일 새벽 1시경, 마스터는 에네의 기억 시스템 개선 작업을 진행하면서 "
        "과거 커버 주식회사 지원 당시의 첫 만남과 프로젝트 흐름을 함께 정리했습니다."
    )
    long_summary = (
        medium_summary
        + " "
        "이후 Everyday Near Ears 프로젝트의 캐릭터 기획과 감정 구조까지 하나의 문맥으로 연결해 기록했습니다."
        + " 이 과정에서 방송 전 루틴, 태그 구조, 기억 저장 우선순위까지 함께 재정리했습니다."
        + " 또한 장기 기억 검색 범위와 중요 기억 우선순위가 실제 대화 품질에 어떤 영향을 주는지도 비교했습니다."
        + " 마지막으로 프로젝트 별칭과 첫 만남의 의미를 다시 정리해 에네가 이후 대화에서 자연스럽게 회상할 수 있도록 구성했습니다."
    )
    dialog = MemoryDialog(_DummyMemoryManager([]))

    medium_widget = dialog._create_memory_widget(
        SimpleNamespace(
            id="memory-medium",
            timestamp="2026-04-08T01:59:00",
            summary=medium_summary,
            tags=[],
            is_important=False,
            embedding=None,
            source="chat",
            memory_type="fact",
        )
    )
    medium_widget.setFixedWidth(320)
    medium_widget.show()
    QApplication.processEvents()
    medium_summary_label = medium_widget.summary_label
    assert "..." not in medium_summary_label.text()

    long_widget = dialog._create_memory_widget(
        SimpleNamespace(
            id="memory-long",
            timestamp="2026-04-08T01:59:00",
            summary=long_summary,
            tags=[],
            is_important=False,
            embedding=None,
            source="chat",
            memory_type="relationship, fact",
        )
    )
    long_widget.setFixedWidth(320)
    long_widget.show()
    QApplication.processEvents()
    long_summary_label = long_widget.summary_label
    assert long_summary_label.text().endswith("...")
    assert len(long_summary_label.text()) < len(long_summary)

    badge = dialog._memory_meta_pill("relationship", "TagPill", 68)
    assert badge.width() >= badge.fontMetrics().horizontalAdvance("relationship") + 24

    dialog.close()


def test_obsidian_panel_translates_error_strings(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        """
        {
          "obsidian.window.title": "Obsidian",
          "obsidian.window.subtitle": "Drag to move / checked files join context",
          "obsidian.window.refresh": "Refresh",
          "obsidian.error.connection_failed": "Connection failed: {error}"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ja.json").write_text(
        """
        {
          "obsidian.window.title": "Obsidian",
          "obsidian.window.subtitle": "ドラッグで移動 / チェックしたファイルはコンテキストに含まれます",
          "obsidian.window.refresh": "更新",
          "obsidian.error.connection_failed": "接続に失敗しました: {error}"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    panel = ObsidianPanelWindow(bridge=SimpleNamespace(), obs_settings=_DummyObsSettings())

    assert panel.windowTitle() == "Obsidian"
    assert panel.subtitle_label.text() == "ドラッグで移動 / チェックしたファイルはコンテキストに含まれます"
    assert panel.refresh_button.text() == "更新"

    panel._render_tree({"ok": False, "error": "boom"})

    assert panel.tree.topLevelItem(0).text(0) == "接続に失敗しました: boom"
    panel.close()


def test_obsidian_parse_error_fully_retranslates_after_language_switch(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        """
        {
          "obsidian.window.title": "Obsidian",
          "obsidian.window.subtitle": "Drag to move / checked files join context",
          "obsidian.window.refresh": "Refresh",
          "obsidian.error.parse_failed": "Tree parse failed: {error}",
          "obsidian.error.fetch_failed": "Tree fetch failed",
          "obsidian.error.connection_failed": "Connection failed: {error}"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ja.json").write_text(
        """
        {
          "obsidian.window.title": "Obsidian",
          "obsidian.window.subtitle": "ドラッグで移動 / チェックしたファイルはコンテキストに含まれます",
          "obsidian.window.refresh": "更新",
          "obsidian.error.parse_failed": "ツリーの解析に失敗しました: {error}",
          "obsidian.error.fetch_failed": "ツリーの取得に失敗しました",
          "obsidian.error.connection_failed": "接続に失敗しました: {error}"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")

    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")
    panel = ObsidianPanelWindow(bridge=SimpleNamespace(), obs_settings=_DummyObsSettings())

    panel._on_obs_tree_updated("{bad-json")
    assert panel.tree.topLevelItem(0).text(0).startswith("接続に失敗しました: ツリーの解析に失敗しました:")

    configure_i18n(language="en", locales_dir=locales_dir, system_locale="en_US")
    panel.retranslate_ui()

    assert panel.tree.topLevelItem(0).text(0).startswith("Connection failed: Tree parse failed:")
    panel.close()


def test_tray_icon_retranslates_menu_text_without_showing_system_tray(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        """
        {
          "tray.tooltip": "ENE - AI Desktop Partner",
          "tray.settings": "Settings",
          "tray.ene_profile": "ENE Profile",
          "tray.calendar": "Calendar",
          "tray.drag_bar.hide": "Hide drag bar",
          "tray.drag_bar.show": "Show drag bar",
          "tray.mouse_tracking.disable": "Disable mouse tracking",
          "tray.mouse_tracking.enable": "Enable mouse tracking",
          "tray.quit": "Quit"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ja.json").write_text(
        """
        {
          "tray.tooltip": "ENE - AIデスクトップパートナー",
          "tray.settings": "設定",
          "tray.ene_profile": "エネ情報",
          "tray.calendar": "カレンダー",
          "tray.drag_bar.hide": "ドラッグバーを隠す",
          "tray.drag_bar.show": "ドラッグバーを表示",
          "tray.mouse_tracking.disable": "マウストラッキングを無効化",
          "tray.mouse_tracking.enable": "マウストラッキングを有効化",
          "tray.quit": "終了"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    tray = TrayIcon(show_on_create=False)

    assert tray.tray_icon.toolTip() == "ENE - AIデスクトップパートナー"
    assert tray.settings_action.text() == "設定"
    assert tray.ene_profile_action.text() == "エネ情報"
    assert tray.calendar_action.text() == "カレンダー"
    assert tray.toggle_bar_action.text() == "ドラッグバーを隠す"
    assert tray.toggle_mouse_tracking_action.text() == "マウストラッキングを無効化"
    assert tray.quit_action.text() == "終了"

    tray.update_drag_bar_menu_text(is_visible=False)
    tray.update_mouse_tracking_menu_text(is_enabled=False)

    assert tray.toggle_bar_action.text() == "ドラッグバーを表示"
    assert tray.toggle_mouse_tracking_action.text() == "マウストラッキングを有効化"
    tray.tray_icon.hide()


def test_tray_icon_uses_non_default_startup_state_for_initial_labels(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        """
        {
          "tray.tooltip": "ENE - AI Desktop Partner",
          "tray.settings": "Settings",
          "tray.ene_profile": "ENE Profile",
          "tray.calendar": "Calendar",
          "tray.drag_bar.hide": "Hide drag bar",
          "tray.drag_bar.show": "Show drag bar",
          "tray.mouse_tracking.disable": "Disable mouse tracking",
          "tray.mouse_tracking.enable": "Enable mouse tracking",
          "tray.quit": "Quit"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ja.json").write_text(
        """
        {
          "tray.tooltip": "ENE - AIデスクトップパートナー",
          "tray.settings": "設定",
          "tray.ene_profile": "エネ情報",
          "tray.calendar": "カレンダー",
          "tray.drag_bar.hide": "ドラッグバーを隠す",
          "tray.drag_bar.show": "ドラッグバーを表示",
          "tray.mouse_tracking.disable": "マウストラッキングを無効化",
          "tray.mouse_tracking.enable": "マウストラッキングを有効化",
          "tray.quit": "終了"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    tray = TrayIcon(show_on_create=False, drag_bar_visible=False, mouse_tracking_enabled=False)

    assert tray.toggle_bar_action.text() == "ドラッグバーを表示"
    assert tray.toggle_mouse_tracking_action.text() == "マウストラッキングを有効化"
    tray.tray_icon.hide()


def test_app_runtime_language_change_retranslates_open_windows(tmp_path):
    ENEApplication = _load_app_class()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text('{"tray.settings": "Settings"}', encoding="utf-8-sig")
    (locales_dir / "ja.json").write_text('{"tray.settings": "設定"}', encoding="utf-8-sig")
    (locales_dir / "ko.json").write_text('{"tray.settings": "설정"}', encoding="utf-8-sig")
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="en_US")

    calls = []
    dialog_calls = []
    overlay_calls = []
    proactive_calls = []
    bridge = SimpleNamespace(
        enable_tts=False,
        refresh_proactive_settings=lambda: proactive_calls.append("proactive"),
    )
    app = ENEApplication.__new__(ENEApplication)
    app.settings = _DummySettings({"ui_language": "ko", "enable_tts": False, "tts_provider": "gpt_sovits_http"})
    app.overlay_window = SimpleNamespace(apply_new_settings=lambda settings: overlay_calls.append(settings), bridge=bridge)
    app.tray_icon = SimpleNamespace(retranslate_ui=lambda: calls.append("tray"))
    app.obsidian_panel_window = SimpleNamespace(retranslate_ui=lambda: calls.append("obsidian"))
    app._settings_dialog = SimpleNamespace(
        isVisible=lambda: True,
        _retranslate_ui=lambda: dialog_calls.append("dialog"),
    )
    app.global_ptt = None
    app.interrupt_tts_on_ptt = True
    app._refresh_memory_runtime_bindings = lambda: calls.append("memory")
    app._refresh_tts_runtime_bindings = lambda: calls.append("tts")

    ENEApplication._on_settings_changed(app, {"ui_language": "ja", "interrupt_tts_on_ptt": True})

    assert overlay_calls == [{"ui_language": "ja", "interrupt_tts_on_ptt": True}]
    assert proactive_calls == ["proactive"]
    assert calls == ["tray", "obsidian"]
    assert dialog_calls == ["dialog"]


def test_show_memory_dialog_warns_with_translated_text(tmp_path, monkeypatch):
    ENEApplication = _load_app_class()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        """
        {
          "memory.warning.title": "Memory unavailable",
          "memory.warning.body": "Memory manager is not initialized."
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ja.json").write_text(
        """
        {
          "memory.warning.title": "メモリを利用できません",
          "memory.warning.body": "メモリマネージャーが初期化されていません。"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ja", locales_dir=locales_dir, system_locale="en_US")

    warnings = []

    def fake_warning(parent, title, text):
        warnings.append((parent, title, text))

    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox.warning", fake_warning)

    app = ENEApplication.__new__(ENEApplication)
    app.memory_manager = None

    ENEApplication._show_memory_dialog(app)

    assert warnings == [
        (None, "メモリを利用できません", "メモリマネージャーが初期化されていません。")
    ]


def test_show_ene_profile_dialog_routes_to_settings_tab():
    ENEApplication = _load_app_class()
    app = ENEApplication.__new__(ENEApplication)
    routed = []
    app._show_settings_dialog = lambda section_id=None: routed.append(section_id)

    ENEApplication._show_ene_profile_dialog(app)

    assert routed == ["ene_profile"]


def test_overlay_window_syncs_chat_ui_strings_from_settings_override(tmp_path):
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir()
    (locales_dir / "en.json").write_text(
        """
        {
          "chat.loading": "Thinking...",
          "chat.input.placeholder": "Type a message...",
          "chat.send": "Send",
          "chat.actions.summary": "Summary",
          "chat.actions.summary.title": "Conversation summary",
          "chat.actions.note": "Note",
          "chat.actions.note.title": "Open or close the Obsidian note panel",
          "chat.actions.mood": "Mood",
          "chat.actions.mood.title": "Mood status",
          "chat.actions.promises": "Scheduled",
          "chat.actions.promises.title": "Scheduled conversation promises",
          "chat.actions.proactive": "Proactive",
          "chat.actions.proactive.title": "Scheduled proactive conversations",
          "chat.actions.live2dParameters.label": "Live2D",
          "chat.actions.live2dParameters.title": "Live2D parameters",
          "chat.actions.goals": "Goals",
          "chat.actions.goals.title": "ENE goals",
          "chat.promise.notice.saved": "Conversation promise saved.",
          "chat.promise.panel.empty": "No scheduled conversation promises.",
          "chat.promise.panel.soon": "Soon",
          "chat.promise.panel.queued": "Right after the current reply",
          "chat.promise.panel.in_minutes": "In {minutes} min",
          "chat.promise.panel.overdue_minutes": "{minutes} min late",
          "chat.proactive.panel.title": "Proactive",
          "chat.proactive.panel.empty": "No scheduled proactive conversations.",
          "chat.proactive.panel.soon": "Soon",
          "chat.proactive.panel.queued": "Right after the current reply",
          "chat.proactive.panel.in_minutes": "In {minutes} min",
          "chat.proactive.panel.overdue_minutes": "{minutes} min late",
          "chat.proactive.panel.close": "Close",
          "chat.proactive.panel.remove": "Delete proactive conversation",
          "chat.live2dParameters.title": "Live2D parameters",
          "chat.live2dParameters.close": "Close Live2D parameter panel",
          "chat.live2dParameters.warning": "For decoration controls. Avoid expression, eye, mouth, head, and body motion parameters because they may conflict with expressions, lip-sync, and head pats.",
          "chat.live2dParameters.search": "Search parameters",
          "chat.live2dParameters.all": "All",
          "chat.live2dParameters.favorites": "Favorites",
          "chat.live2dParameters.save": "Save",
          "chat.live2dParameters.reset": "Reset",
          "chat.live2dParameters.empty": "No parameters to show.",
          "chat.live2dParameters.status_idle": "Parameter list has not loaded yet.",
          "chat.live2dParameters.status_loading": "Loading parameter list.",
          "chat.live2dParameters.status_unavailable": "This Live2D model does not expose readable parameters.",
          "chat.live2dParameters.status_error": "Could not load parameter list.",
          "chat.live2dParameters.toast_load_first": "Load the parameter list first.",
          "chat.live2dParameters.toast_missing_model": "Select a model before saving.",
          "chat.live2dParameters.toast_missing_bridge": "Save bridge is not available.",
          "chat.live2dParameters.toast_save_success": "Live2D parameters saved.",
          "chat.live2dParameters.toast_save_error": "Failed to save Live2D parameters.",
          "chat.goals.label": "Goals",
          "chat.goals.title": "ENE goals",
          "chat.goals.empty": "No active goals yet.",
          "chat.goals.short_term": "Short-term",
          "chat.goals.long_term": "Long-term",
          "chat.goals.close": "Close",
          "chat.mood.label": "Mood: {label}",
          "chat.mood.loading": "Loading",
          "chat.mood.collapse": "Collapse",
          "chat.mood.axis.valence": "Positive",
          "chat.mood.axis.bond": "Bond",
          "chat.mood.axis.energy": "Energy",
          "chat.mood.axis.stress": "Stress",
          "chat.mood.state.calm": "Calm",
          "chat.mood.state.cheerful": "Cheerful",
          "chat.mood.state.affectionate": "Affectionate",
          "chat.mood.state.tired": "Tired",
          "chat.mood.state.tense": "Tense",
          "chat.mood.state.sensitive": "Sensitive",
          "chat.mood.state.unknown": "Unknown",
          "chat.mood.temporary.steady": "Steady",
          "chat.mood.temporary.playful": "Playful",
          "chat.mood.temporary.focused": "Focused",
          "chat.mood.temporary.drained": "Drained",
          "chat.mood.temporary.guarded": "Guarded",
          "chat.mood.temporary.pout": "Pouty",
          "chat.summary.confirm.title": "Manual summary",
          "chat.summary.confirm.body": "Would you like to start a manual summary?",
          "chat.summary.confirm.no": "No",
          "chat.summary.confirm.yes": "Yes"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ja.json").write_text(
        """
        {
          "chat.loading": "考え中...",
          "chat.input.placeholder": "メッセージを入力してください...",
          "chat.send": "送信",
          "chat.actions.summary": "要約",
          "chat.actions.summary.title": "会話を要約",
          "chat.actions.note": "ノート",
          "chat.actions.note.title": "Obsidianノートパネルを開く / 閉じる",
          "chat.actions.mood": "気分",
          "chat.actions.mood.title": "気分の状態",
          "chat.actions.promises": "予定",
          "chat.actions.promises.title": "予定された会話の約束",
          "chat.actions.proactive": "先回り",
          "chat.actions.proactive.title": "予約された先回り会話",
          "chat.actions.live2dParameters.label": "Live2D",
          "chat.actions.live2dParameters.title": "Live2Dパラメータ",
          "chat.actions.goals": "目標",
          "chat.actions.goals.title": "エネの目標",
          "chat.promise.notice.saved": "会話の約束を保存しました。",
          "chat.promise.panel.empty": "予定された会話の約束はありません。",
          "chat.promise.panel.soon": "まもなく",
          "chat.promise.panel.queued": "現在の応答の直後",
          "chat.promise.panel.in_minutes": "{minutes}分後",
          "chat.promise.panel.overdue_minutes": "{minutes}分経過",
          "chat.proactive.panel.title": "先回り",
          "chat.proactive.panel.empty": "予約された先回り会話はありません。",
          "chat.proactive.panel.soon": "まもなく",
          "chat.proactive.panel.queued": "現在の応答の直後",
          "chat.proactive.panel.in_minutes": "{minutes}分後",
          "chat.proactive.panel.overdue_minutes": "{minutes}分経過",
          "chat.proactive.panel.close": "閉じる",
          "chat.proactive.panel.remove": "先回り会話を削除",
          "chat.live2dParameters.title": "Live2Dパラメータ",
          "chat.live2dParameters.close": "Live2Dパラメータパネルを閉じる",
          "chat.live2dParameters.warning": "装飾調整用です。表情、目、口、頭、体の動きに関するパラメータは、表情、リップシンク、なで反応と競合する場合があるため、触らないことをおすすめします。",
          "chat.live2dParameters.search": "パラメータを検索",
          "chat.live2dParameters.all": "すべて",
          "chat.live2dParameters.favorites": "お気に入り",
          "chat.live2dParameters.save": "保存",
          "chat.live2dParameters.reset": "リセット",
          "chat.live2dParameters.empty": "表示するパラメータはありません。",
          "chat.live2dParameters.status_idle": "パラメータ一覧はまだ読み込まれていません。",
          "chat.live2dParameters.status_loading": "パラメータ一覧を読み込んでいます。",
          "chat.live2dParameters.status_unavailable": "現在のLive2Dモデルではパラメータ一覧を読み取れません。",
          "chat.live2dParameters.status_error": "パラメータ一覧を読み込めませんでした。",
          "chat.live2dParameters.toast_load_first": "先にパラメータ一覧を読み込んでください。",
          "chat.live2dParameters.toast_missing_model": "保存する前にモデルを選択してください。",
          "chat.live2dParameters.toast_missing_bridge": "保存ブリッジを使用できません。",
          "chat.live2dParameters.toast_save_success": "Live2Dパラメータを保存しました。",
          "chat.live2dParameters.toast_save_error": "Live2Dパラメータの保存に失敗しました。",
          "chat.goals.label": "目標",
          "chat.goals.title": "エネの目標",
          "chat.goals.empty": "進行中の目標はまだありません。",
          "chat.goals.short_term": "短期",
          "chat.goals.long_term": "長期",
          "chat.goals.close": "閉じる",
          "chat.mood.label": "気分: {label}",
          "chat.mood.loading": "読み込み中",
          "chat.mood.collapse": "折りたたむ",
          "chat.mood.axis.valence": "ポジティブ",
          "chat.mood.axis.bond": "親密",
          "chat.mood.axis.energy": "活力",
          "chat.mood.axis.stress": "緊張",
          "chat.mood.state.calm": "落ち着き",
          "chat.mood.state.cheerful": "晴れやか",
          "chat.mood.state.affectionate": "愛情たっぷり",
          "chat.mood.state.tired": "疲れ気味",
          "chat.mood.state.tense": "警戒気味",
          "chat.mood.state.sensitive": "敏感",
          "chat.mood.state.unknown": "不明",
          "chat.mood.temporary.steady": "安定",
          "chat.mood.temporary.playful": "いたずら気分",
          "chat.mood.temporary.focused": "集中中",
          "chat.mood.temporary.drained": "ぐったり",
          "chat.mood.temporary.guarded": "警戒中",
          "chat.mood.temporary.pout": "ふてくされ",
          "chat.summary.confirm.title": "手動要約",
          "chat.summary.confirm.body": "手動要約を実行しますか？",
          "chat.summary.confirm.no": "いいえ",
          "chat.summary.confirm.yes": "はい"
        }
        """.strip(),
        encoding="utf-8-sig",
    )
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    from src.core.overlay_window import OverlayWindow

    captured = []

    class _FakePage:
        def runJavaScript(self, code):
            captured.append(code)

    class _FakeWebView:
        def __init__(self):
            self._page = _FakePage()

        def page(self):
            return self._page

    overlay = OverlayWindow.__new__(OverlayWindow)
    overlay.settings = _DummySettings({"ui_language": "ko"})
    overlay.web_view = _FakeWebView()
    overlay._page_loaded = True

    OverlayWindow._sync_ui_strings_to_js(overlay, {"ui_language": "ja"})

    assert captured
    assert "メッセージを入力してください..." in captured[-1]
    assert "送信" in captured[-1]
    assert "考え中..." in captured[-1]
    assert '"promises": {' in captured[-1]
    assert '"proactive": {' in captured[-1]
    assert '"goals": {' in captured[-1]
    assert '"live2dParameters": {' in captured[-1]
    assert '"label": "予定"' in captured[-1]
    assert '"label": "先回り"' in captured[-1]
    assert '"label": "Live2D"' in captured[-1]
    assert '"proactivePanel": {' in captured[-1]
    assert '"proactivePanel": {"title": "先回り"' in captured[-1]
    assert '"remove": "先回り会話を削除"' in captured[-1]
    assert '"live2dParameters": {"title": "Live2Dパラメータ"' in captured[-1]
    assert '"close": "Live2Dパラメータパネルを閉じる"' in captured[-1]
    assert '"search": "パラメータを検索"' in captured[-1]
    assert '"favorites": "お気に入り"' in captured[-1]
    assert '"warning": "装飾調整用です。表情、目、口、頭、体の動きに関するパラメータは、表情、リップシンク、なで反応と競合する場合があるため、触らないことをおすすめします。"' in captured[-1]
    assert '"empty": "表示するパラメータはありません。"' in captured[-1]
    assert '"toastSaveSuccess": "Live2Dパラメータを保存しました。"' in captured[-1]
    assert '"goalPanel": {' in captured[-1]
    assert '"goalPanel": {"label": "目標", "title": "エネの目標"' in captured[-1]
    assert '"title": "エネの目標"' in captured[-1]
    assert '"shortTerm": "短期"' in captured[-1]
    assert '"saved": "会話の約束を保存しました。"' in captured[-1]
    assert '"empty": "予定された会話の約束はありません。"' in captured[-1]
    assert '"sensitive": "敏感"' in captured[-1]
    assert '"tense": "警戒気味"' in captured[-1]
    assert '"drained": "ぐったり"' in captured[-1]
    assert '"lonely"' not in captured[-1]


def test_live2d_parameter_favorites_label_is_localized_in_bundled_locales():
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"

    assert json.loads((locales_dir / "ko.json").read_text(encoding="utf-8-sig"))[
        "chat.live2dParameters.favorites"
    ] == "즐겨찾기"
    assert json.loads((locales_dir / "en.json").read_text(encoding="utf-8-sig"))[
        "chat.live2dParameters.favorites"
    ] == "Favorites"
    assert json.loads((locales_dir / "ja.json").read_text(encoding="utf-8-sig"))[
        "chat.live2dParameters.favorites"
    ] == "お気に入り"


def test_image_avatar_settings_locale_keys_exist_in_bundled_locales():
    locales_dir = Path(__file__).resolve().parents[1] / "src" / "locales"
    required_keys = [
        "settings.model.avatar_mode.title",
        "settings.model.avatar_mode.live2d",
        "settings.model.avatar_mode.image",
        "settings.model.image.path.title",
        "settings.model.image.path.hint",
        "settings.model.image.path.dialog.title",
        "settings.model.image.emotions.title",
        "settings.model.image.placement.title",
    ]

    def resolve_key(locale_data, dotted_key):
        current = locale_data
        for part in dotted_key.split("."):
            assert isinstance(current, dict), dotted_key
            assert part in current, dotted_key
            current = current[part]
        assert isinstance(current, str), dotted_key
        assert current.strip(), dotted_key

    for language in ("ko", "en", "ja"):
        locale_data = json.loads((locales_dir / f"{language}.json").read_text(encoding="utf-8-sig"))
        for key in required_keys:
            resolve_key(locale_data, key)


def test_chat_web_script_has_runtime_i18n_hooks():
    assets_root = Path(__file__).resolve().parents[1] / "assets" / "web"
    content = _read_web_runtime_script_text(assets_root)

    assert "window.applyENEUiStrings = function applyENEUiStrings(config)" in content
    assert "chatInput.placeholder = currentUiStrings.input.placeholder;" in content
    assert "sendButton.textContent = currentUiStrings.send;" in content
    assert "moodStatusLabel.textContent = formatMoodStatusText(label, temporaryState);" in content
    assert "promiseRemindersButton.textContent = currentUiStrings.actions.promises.label;" in content
    assert "proactiveConversationsButton.textContent = currentUiStrings.actions.proactive.label;" in content
    assert "live2dParametersButton.textContent = currentUiStrings.actions.live2dParameters.label;" in content
    assert "goalButton.textContent = currentUiStrings.actions.goals.label;" in content
    assert "goalButton.setAttribute('aria-label', currentUiStrings.actions.goals.title);" in content
    assert "label: goalPanel.label || DEFAULT_UI_STRINGS.goalPanel.label" in content
    assert "title: live2dParameters.title || DEFAULT_UI_STRINGS.live2dParameters.title" in content
    assert "close: live2dParameters.close || DEFAULT_UI_STRINGS.live2dParameters.close" in content
    assert "live2dParametersCloseButton.title = currentUiStrings.live2dParameters.close;" in content
    assert "live2dParametersSearch.setAttribute('aria-label', currentUiStrings.live2dParameters.search);" in content
    assert "window.setProactiveConversationButtonEnabled = function setProactiveConversationButtonEnabled(enabled)" in content
    assert "window.setProactiveConversationItems = function setProactiveConversationItems(items)" in content
    assert "window.setGoalButtonEnabled = function setGoalButtonEnabled(enabled)" in content
    assert "window.setGoalItems = function setGoalItems(value)" in content
    assert "renderGoalPanel();" in content
    assert "setGoalPanelOpen(false);\n        setPromiseRemindersPanelOpen(nextOpen);" in content
    assert "setPromiseRemindersPanelOpen(false);\n        setGoalPanelOpen(!goalPanelOpen);" in content
    assert "renderPromiseReminderPanel();" in content


def test_overlay_window_syncs_message_split_settings_to_webview(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir(parents=True, exist_ok=True)
    (locales_dir / "en.json").write_text("{}", encoding="utf-8-sig")
    (locales_dir / "ja.json").write_text("{}", encoding="utf-8-sig")
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    from src.core.overlay_window import OverlayWindow

    captured = []

    class _FakePage:
        def runJavaScript(self, code):
            captured.append(code)

    class _FakeWebView:
        def __init__(self):
            self._page = _FakePage()

        def page(self):
            return self._page

    overlay = OverlayWindow.__new__(OverlayWindow)
    overlay.settings = _DummySettings({"message_split_enabled": False})
    overlay.web_view = _FakeWebView()
    overlay._page_loaded = True

    OverlayWindow._sync_message_split_settings_to_js(overlay, {"message_split_enabled": True})

    assert captured
    assert 'window.eneMessageSplitConfig = {"enabled": true};' in captured[-1]
    assert "window.setMessageSplitConfig(window.eneMessageSplitConfig);" in captured[-1]


def test_overlay_window_syncs_goal_button_visibility_to_webview(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir(parents=True, exist_ok=True)
    (locales_dir / "en.json").write_text("{}", encoding="utf-8-sig")
    (locales_dir / "ja.json").write_text("{}", encoding="utf-8-sig")
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    from src.core.overlay_window import OverlayWindow

    captured = []

    class _FakePage:
        def runJavaScript(self, code):
            captured.append(code)

    class _FakeWebView:
        def __init__(self):
            self._page = _FakePage()

        def page(self):
            return self._page

    overlay = OverlayWindow.__new__(OverlayWindow)
    overlay.settings = _DummySettings({"enable_ene_goals": True, "show_ene_goal_button": True})
    overlay.web_view = _FakeWebView()
    overlay._page_loaded = True

    OverlayWindow._sync_goal_button_visibility_to_js(overlay, {"show_ene_goal_button": False})
    OverlayWindow._sync_goal_button_visibility_to_js(
        overlay,
        {"enable_ene_goals": False, "show_ene_goal_button": True},
    )
    OverlayWindow._sync_goal_button_visibility_to_js(
        overlay,
        {"enable_ene_goals": True, "show_ene_goal_button": True},
    )

    assert captured == [
        "window.setGoalButtonEnabled(false);",
        "window.setGoalButtonEnabled(false);",
        "window.setGoalButtonEnabled(true);",
    ]


def test_overlay_window_syncs_proactive_button_visibility_to_webview(tmp_path):
    _get_qapp()
    locales_dir = tmp_path / "locales"
    locales_dir.mkdir(parents=True, exist_ok=True)
    (locales_dir / "en.json").write_text("{}", encoding="utf-8-sig")
    (locales_dir / "ja.json").write_text("{}", encoding="utf-8-sig")
    (locales_dir / "ko.json").write_text("{}", encoding="utf-8-sig")
    configure_i18n(language="ko", locales_dir=locales_dir, system_locale="ko_KR")

    from src.core.overlay_window import OverlayWindow

    captured = []

    class _FakePage:
        def runJavaScript(self, code):
            captured.append(code)

    class _FakeWebView:
        def __init__(self):
            self._page = _FakePage()

        def page(self):
            return self._page

    overlay = OverlayWindow.__new__(OverlayWindow)
    overlay.settings = _DummySettings({"enable_proactive_conversation": True})
    overlay.web_view = _FakeWebView()
    overlay._page_loaded = True

    OverlayWindow._sync_proactive_conversation_button_visibility_to_js(
        overlay,
        {"enable_proactive_conversation": False},
    )
    OverlayWindow._sync_proactive_conversation_button_visibility_to_js(
        overlay,
        {"enable_proactive_conversation": True},
    )

    assert captured == [
        "window.setProactiveConversationButtonEnabled(false);",
        "window.setProactiveConversationButtonEnabled(true);",
    ]


def test_chat_web_assets_translate_mood_axis_labels_and_center_floating_buttons():
    assets_root = Path(__file__).resolve().parents[1] / "assets" / "web"
    script_content = _read_web_runtime_script_text(assets_root)
    html_content = (assets_root / "index.html").read_text(encoding="utf-8")
    css_content = (assets_root / "style.css").read_text(encoding="utf-8")

    assert 'id="proactive-conversations-floating-btn"' in html_content
    assert 'id="proactive-conversations-panel"' in html_content
    assert 'id="proactive-conversations-list"' in html_content
    assert 'id="mood-meter-name-valence"' in html_content
    assert 'id="mood-meter-name-bond"' in html_content
    assert 'id="mood-meter-name-energy"' in html_content
    assert 'id="mood-meter-name-stress"' in html_content
    assert 'id="goal-toggle-floating-btn"' in html_content
    assert 'id="goal-status-panel"' in html_content
    assert 'id="goal-status-list"' in html_content
    assert "moodMeterNameValence.textContent = currentUiStrings.mood.axis.valence;" in script_content
    assert "moodMeterNameBond.textContent = currentUiStrings.mood.axis.bond;" in script_content
    assert "moodMeterNameEnergy.textContent = currentUiStrings.mood.axis.energy;" in script_content
    assert "moodMeterNameStress.textContent = currentUiStrings.mood.axis.stress;" in script_content
    assert "proactive-conversation-item" in css_content
    assert "goal-status-item" in css_content
    assert "justify-content: center;" in css_content
    assert "text-align: center;" in css_content
