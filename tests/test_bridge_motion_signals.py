from src.core.bridge import WebBridge


def test_webbridge_exposes_motion_performance_signals():
    assert hasattr(WebBridge, "speech_state_changed")
    assert hasattr(WebBridge, "performance_state_changed")
