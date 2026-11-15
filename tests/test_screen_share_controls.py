import json
from types import SimpleNamespace
from unittest.mock import Mock

from src.core.bridge import WebBridge


def test_bridge_has_two_independent_screen_modes():
    assert hasattr(WebBridge, "configure_screen_share")
    assert hasattr(WebBridge, "stop_screen_share")
    assert hasattr(WebBridge, "get_screen_share_state")


def test_controls_show_receiving_model_before_start():
    from src.core.bridge_mixins.screen import ScreenBridgeMixin

    class Controls(ScreenBridgeMixin):
        pass

    bridge = Controls()
    bridge.llm_client = SimpleNamespace(model_name="demo", endpoint="http://127.0.0.1:11434/api/chat",
        supports_image_input=True, send_screen_question=Mock(), observe_screen_once=Mock())
    state = json.loads(bridge.get_screen_share_state())
    assert state["model"] == "demo" and not state["remote"]
    assert not state["question"] and not state["observe"]
