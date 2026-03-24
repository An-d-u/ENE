import sys
import types
from types import SimpleNamespace

from PyQt6.QtWidgets import QApplication

from src.core.i18n import configure_i18n
from src.core.tray_icon import TrayIcon
from src.ui.obsidian_panel_window import ObsidianPanelWindow


_QAPP = None


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

    def get(self, key, default=None):
        return self.config.get(key, default)


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
