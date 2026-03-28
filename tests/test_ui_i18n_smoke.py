import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from PyQt6.QtCore import QDate, Qt
from PyQt6.QtWidgets import QGroupBox, QLabel, QMessageBox, QPushButton
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
        assert dialog.model_json_path_edit.placeholderText() == "e.g. assets/live2d_models/jksalt/jksalt.model3.json"
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
            }
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
            }
        )

        dialog._ensure_lazy_tab_loaded("profile")
        dialog._ensure_lazy_tab_loaded("prompt")
        dialog._ensure_lazy_tab_loaded("memory")

        assert dialog.basic_info_key_input.placeholderText() == "항목 이름"
        assert dialog.emotion_name_input.placeholderText() == "감정 키 (예: shy)"
        assert dialog._prompt_status_label.text() == "로드 대기"
        assert dialog._profile_status_label.text() == "user_profile.json 로드 완료"
        assert dialog.fact_timestamp_label.text() == "신규 항목"
        assert tr("settings.window.title") == "ENE 설정"

        dialog.ui_language_combo.setCurrentIndex(dialog.ui_language_combo.findData("ja"))

        assert dialog.content_header_title.text() == "ウィンドウ設定"
        assert dialog.ui_language_combo.itemText(0) == "システムの既定値"
        assert dialog.basic_info_key_input.placeholderText() == "項目名"
        assert dialog.emotion_name_input.placeholderText() == "感情キー (例: shy)"
        assert dialog._prompt_status_label.text() == "読み込み待機"
        assert dialog._profile_status_label.text() == "user_profile.json 読み込み完了"
        assert dialog.fact_timestamp_label.text() == "新しい項目"
        assert dialog.fact_category_combo.itemText(0) == "基本情報"
        assert dialog.memory_search_recent_turns_spin.suffix() == " ターン"
        assert dialog.memory_search_recent_turns_spin.specialValueText() == "現在のメッセージのみ"
        assert {"基本情報", "好みと苦手", "感情一覧と使用ガイド"}.issubset(
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
            "memory.value.important.true": "Keep",
            "memory.value.important.false": "Regular",
            "memory.value.embedding.true": "Connected",
            "memory.value.embedding.false": "None",
            "memory.delete.title": "Delete confirmation",
            "memory.delete.body": "Delete `{summary}`?",
            "memory.profile.missing.title": "No profile",
            "memory.profile.missing.body": "User profile is not initialized.",
            "memory.profile.empty.title": "No profile data",
            "memory.profile.empty.body": "No profile information is saved yet.\nChat to extract information automatically.",
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
            "memory.value.important.true": "保持対象",
            "memory.value.important.false": "通常メモリ",
            "memory.value.embedding.true": "接続済み",
            "memory.value.embedding.false": "なし",
            "memory.delete.title": "削除の確認",
            "memory.delete.body": "`{summary}` を削除しますか？",
            "memory.profile.missing.title": "プロフィールなし",
            "memory.profile.missing.body": "ユーザープロフィールが初期化されていません。",
            "memory.profile.empty.title": "プロフィール情報なし",
            "memory.profile.empty.body": "まだ保存されたプロフィール情報はありません。\n会話すると自動で情報が抽出されます。",
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
            ),
            SimpleNamespace(
                id="memory-2",
                timestamp="2026-03-23T08:00:00",
                summary="",
                tags=["archive"],
                is_important=False,
                embedding=None,
                original_messages=["c"],
            ),
        ]
    )

    dialog = MemoryDialog(manager, bridge=bridge)

    assert dialog.windowTitle() == "ENE メモリ管理"
    assert dialog.search_input.placeholderText() == "メモリのタイトル、要約、タグを検索"
    assert dialog.important_filter_btn.text() == "重要のみ"
    assert dialog.sort_button.text() == "新しい順"
    assert dialog.list_hint_label.text() == "2件を表示中"
    assert dialog.important_btn.text() == "重要を解除"
    assert dialog.delete_btn.text() == "メモリを削除"
    assert dialog.inspector_source_value.text() == "2件のメッセージ"
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
    assert {"メモリ時刻", "元メッセージ数", "重要度", "埋め込み状態"} <= key_labels

    dialog._toggle_sort_order()
    assert dialog.sort_button.text() == "古い順"

    questions = []
    warnings = []
    infos = []
    opened_profile_dialogs = []

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

    dialog._delete_memory()
    delattr(dialog.bridge, "user_profile")
    dialog._show_profile_dialog()

    assert questions == [("削除の確認", "`Keeps launch checklists ready` を削除しますか？")]
    assert warnings == [("プロフィールなし", "ユーザープロフィールが初期化されていません。")]

    bridge.user_profile = _TruthyEmptyUserProfile()
    dialog._show_profile_dialog()
    assert infos == [
        (
            "プロフィール情報なし",
            "まだ保存されたプロフィール情報はありません。\n会話すると自動で情報が抽出されます。",
        )
    ]
    assert opened_profile_dialogs == []
    dialog.close()

    empty_dialog = MemoryDialog(_DummyMemoryManager([]), bridge=bridge)
    assert empty_dialog.inspector_title.text() == "選択されたメモリはありません"
    assert empty_dialog.inspector_body.text() == "左の一覧からメモリを選ぶと、詳細情報と管理アクションがここに表示されます。"
    assert empty_dialog.list_hint_label.text() == "0件を表示中"
    empty_dialog.close()


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
    bridge = SimpleNamespace(enable_tts=False)
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
          "chat.mood.state.lonely": "Lonely",
          "chat.mood.state.unknown": "Unknown",
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
          "chat.mood.state.tense": "緊張気味",
          "chat.mood.state.lonely": "さみしい",
          "chat.mood.state.unknown": "不明",
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


def test_chat_web_script_has_runtime_i18n_hooks():
    script_path = Path(__file__).resolve().parents[1] / "assets" / "web" / "script.js"
    content = script_path.read_text(encoding="utf-8")

    assert "window.applyENEUiStrings = function applyENEUiStrings(config)" in content
    assert "chatInput.placeholder = currentUiStrings.input.placeholder;" in content
    assert "sendButton.textContent = currentUiStrings.send;" in content
    assert "moodStatusLabel.textContent = formatMoodStatusText(label);" in content


def test_chat_web_assets_translate_mood_axis_labels_and_center_floating_buttons():
    assets_root = Path(__file__).resolve().parents[1] / "assets" / "web"
    script_content = (assets_root / "script.js").read_text(encoding="utf-8")
    html_content = (assets_root / "index.html").read_text(encoding="utf-8")
    css_content = (assets_root / "style.css").read_text(encoding="utf-8")

    assert 'id="mood-meter-name-valence"' in html_content
    assert 'id="mood-meter-name-bond"' in html_content
    assert 'id="mood-meter-name-energy"' in html_content
    assert 'id="mood-meter-name-stress"' in html_content
    assert "moodMeterNameValence.textContent = currentUiStrings.mood.axis.valence;" in script_content
    assert "moodMeterNameBond.textContent = currentUiStrings.mood.axis.bond;" in script_content
    assert "moodMeterNameEnergy.textContent = currentUiStrings.mood.axis.energy;" in script_content
    assert "moodMeterNameStress.textContent = currentUiStrings.mood.axis.stress;" in script_content
    assert "justify-content: center;" in css_content
    assert "text-align: center;" in css_content
