from src.core.bridge import WebBridge


def test_web_bridge_uses_feature_mixins_for_large_internal_domains():
    mro_names = [cls.__name__ for cls in WebBridge.__mro__]

    assert "PromiseBridgeMixin" in mro_names
    assert "ThoughtBridgeMixin" in mro_names
    assert "TTSBridgeMixin" in mro_names
    assert "ObsidianBridgeMixin" in mro_names
    assert "MemorySummaryBridgeMixin" in mro_names
    assert "AwayNudgeBridgeMixin" in mro_names
    assert "AttachmentBridgeMixin" in mro_names
    assert "GoalBridgeMixin" in mro_names
    assert "MoodBridgeMixin" in mro_names
    assert "ChatFlowBridgeMixin" in mro_names
