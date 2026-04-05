import json

from PyQt6.QtCore import QCoreApplication

from src.core.bridge import WebBridge


def _ensure_qt_app():
    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication([])
    return app


def test_bridge_response_ready_emits_token_usage_payload():
    _ensure_qt_app()

    bridge = WebBridge()

    class DummyLLMClient:
        def get_last_token_usage(self):
            return {
                "input_tokens": 111,
                "output_tokens": 222,
                "total_tokens": 333,
            }

    bridge.llm_client = DummyLLMClient()

    payloads = []
    bridge.token_usage_ready.connect(lambda payload: payloads.append(json.loads(payload)))

    bridge._on_response_ready("응답", "normal", "", [])

    assert payloads == [
        {
            "input_tokens": 111,
            "output_tokens": 222,
            "total_tokens": 333,
        }
    ]


def test_open_settings_dialog_slot_calls_registered_callback():
    _ensure_qt_app()

    bridge = WebBridge()
    calls = []

    bridge.set_settings_dialog_opener(lambda: calls.append("opened"))

    bridge.open_settings_dialog()

    assert calls == ["opened"]


def test_save_chat_panel_height_slot_updates_settings_and_persists():
    _ensure_qt_app()

    class DummySettings:
        def __init__(self):
            self.values = {}
            self.saved = False

        def set(self, key, value):
            self.values[key] = value

        def save(self):
            self.saved = True

    settings = DummySettings()
    bridge = WebBridge(settings=settings)

    bridge.save_chat_panel_height("388")

    assert settings.values["chat_panel_height"] == 388
    assert settings.saved is True
