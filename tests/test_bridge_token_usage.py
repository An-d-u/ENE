import json

from PyQt6.QtCore import QCoreApplication

from src.core.bridge import WebBridge
from src.core.bridge_workers import AIWorker


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


def test_bridge_response_ready_preserves_partial_null_token_usage():
    _ensure_qt_app()

    bridge = WebBridge()

    class DummyLLMClient:
        def get_last_token_usage(self):
            return {
                "input_tokens": 111,
                "output_tokens": None,
                "total_tokens": None,
            }

    bridge.llm_client = DummyLLMClient()
    payloads = []
    bridge.token_usage_ready.connect(lambda payload: payloads.append(json.loads(payload)))

    bridge._on_response_ready("합성 응답", "normal", "", [])

    assert payloads == [
        {
            "input_tokens": 111,
            "output_tokens": None,
            "total_tokens": None,
        }
    ]


def test_answer_worker_accumulates_prior_life_record_usage():
    class DummyLLMClient:
        def get_last_token_usage(self):
            return {
                "input_tokens": 11,
                "output_tokens": 7,
                "total_tokens": 18,
            }

    worker = AIWorker(
        DummyLLMClient(),
        "합성 요청",
        prior_token_usage={
            "input_tokens": 8,
            "output_tokens": 5,
            "total_tokens": 13,
        },
    )

    assert json.loads(worker._build_token_usage_payload()) == {
        "input_tokens": 19,
        "output_tokens": 12,
        "total_tokens": 31,
    }


def test_open_settings_dialog_slot_calls_registered_callback():
    _ensure_qt_app()

    bridge = WebBridge()
    calls = []

    bridge.set_settings_dialog_opener(lambda: calls.append("opened"))

    bridge.open_settings_dialog()

    assert calls == ["opened"]


def test_open_settings_dialog_section_slot_calls_registered_callback_with_safe_destination():
    _ensure_qt_app()
    bridge = WebBridge()
    calls = []
    bridge.set_settings_dialog_opener(lambda section=None: calls.append(section))

    bridge.open_settings_dialog_section("life_world")
    bridge.open_settings_dialog_section("private-unknown-section")

    assert calls == ["life_world"]


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
