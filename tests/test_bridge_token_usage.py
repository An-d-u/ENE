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
