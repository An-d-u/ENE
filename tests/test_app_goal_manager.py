from src.core import app as app_module


class _DummySettings:
    def __init__(self):
        self.config = {
            "ui_language": "ko",
            "interrupt_tts_on_ptt": True,
            "llm_provider": "openai",
            "llm_models": {"openai": "gpt-4o-mini"},
            "llm_model_params": {},
            "llm_api_keys": {"openai": ""},
            "ene_goal_state_file": "test_ene_goals.json",
            "show_drag_bar": True,
            "mouse_tracking_enabled": True,
        }
        self.secret_config = {}

    def get(self, key, default=None):
        return self.config.get(key, default)


class _DummyGoalManager:
    def __init__(self, state_file=None, settings=None):
        self.state_file = state_file
        self.settings = settings


class _DummyProactiveManager:
    def __init__(self, storage_file=None):
        self.storage_file = storage_file


class _DummyBridge:
    def __init__(self, obs_panel_visible=False):
        self.goal_manager = None
        self.proactive_manager = None
        self.llm_client = None
        self.obs_settings = type(
            "ObsSettings",
            (),
            {"get": lambda _self, key, default=None: obs_panel_visible if key == "panel_visible" else default},
        )()

    def set_goal_manager(self, goal_manager):
        self.goal_manager = goal_manager

    def set_llm_client(self, llm_client):
        self.llm_client = llm_client

    def set_obs_panel_window(self, window):
        self.obs_panel_window = window


class _DummyOverlayWindow:
    obs_panel_visible = False

    def __init__(self, settings):
        self.settings = settings
        self.bridge = _DummyBridge(obs_panel_visible=self.obs_panel_visible)

    def set_llm_client(self, llm_client):
        self.llm_client = llm_client

    def show(self):
        pass


class _DummyObsPanelWindow:
    def __init__(self, bridge=None, obs_settings=None):
        self.bridge = bridge
        self.obs_settings = obs_settings
        self.show_calls = 0

    def show(self):
        self.show_calls += 1


class _DummyTrayIcon:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_app_initializes_goal_manager_without_llm_api_key(monkeypatch):
    settings = _DummySettings()

    monkeypatch.setattr(app_module, "Settings", lambda: settings)
    monkeypatch.setattr(app_module, "configure_i18n", lambda language="auto": object())
    monkeypatch.setattr(app_module, "EneGoalManager", _DummyGoalManager)
    monkeypatch.setattr(app_module, "ProactiveConversationManager", _DummyProactiveManager)
    monkeypatch.setattr(app_module, "OverlayWindow", _DummyOverlayWindow)
    monkeypatch.setattr(app_module, "ObsidianPanelWindow", _DummyObsPanelWindow)
    monkeypatch.setattr(app_module, "TrayIcon", _DummyTrayIcon)
    monkeypatch.setattr(app_module.ENEApplication, "_apply_followed_system_theme", lambda self, save=False: False)
    monkeypatch.setattr(app_module.ENEApplication, "_init_calendar_manager", lambda self: setattr(self, "calendar_manager", None))
    monkeypatch.setattr(app_module.ENEApplication, "_init_promise_manager", lambda self: setattr(self, "promise_manager", None))
    monkeypatch.setattr(app_module.ENEApplication, "_connect_signals", lambda self: None)
    monkeypatch.setattr(app_module.ENEApplication, "_init_global_ptt", lambda self: None)
    monkeypatch.setattr(app_module.ENEApplication, "_init_system_theme_sync", lambda self: None)

    app = app_module.ENEApplication()

    assert app.llm_client is None
    assert isinstance(app.goal_manager, _DummyGoalManager)
    assert app.goal_manager.state_file == "test_ene_goals.json"
    assert app.overlay_window.bridge.goal_manager is app.goal_manager
    assert isinstance(app.proactive_manager, _DummyProactiveManager)
    assert app.overlay_window.bridge.proactive_manager is app.proactive_manager


def test_app_start_does_not_restore_obsidian_panel_visibility(monkeypatch):
    settings = _DummySettings()

    class _VisibleObsPanelOverlayWindow(_DummyOverlayWindow):
        obs_panel_visible = True

    monkeypatch.setattr(app_module, "Settings", lambda: settings)
    monkeypatch.setattr(app_module, "configure_i18n", lambda language="auto": object())
    monkeypatch.setattr(app_module, "EneGoalManager", _DummyGoalManager)
    monkeypatch.setattr(app_module, "ProactiveConversationManager", _DummyProactiveManager)
    monkeypatch.setattr(app_module, "OverlayWindow", _VisibleObsPanelOverlayWindow)
    monkeypatch.setattr(app_module, "ObsidianPanelWindow", _DummyObsPanelWindow)
    monkeypatch.setattr(app_module, "TrayIcon", _DummyTrayIcon)
    monkeypatch.setattr(app_module.ENEApplication, "_apply_followed_system_theme", lambda self, save=False: False)
    monkeypatch.setattr(app_module.ENEApplication, "_init_calendar_manager", lambda self: setattr(self, "calendar_manager", None))
    monkeypatch.setattr(app_module.ENEApplication, "_init_promise_manager", lambda self: setattr(self, "promise_manager", None))
    monkeypatch.setattr(app_module.ENEApplication, "_connect_signals", lambda self: None)
    monkeypatch.setattr(app_module.ENEApplication, "_init_global_ptt", lambda self: None)
    monkeypatch.setattr(app_module.ENEApplication, "_init_system_theme_sync", lambda self: None)

    app = app_module.ENEApplication()

    assert app.obsidian_panel_window.show_calls == 0
