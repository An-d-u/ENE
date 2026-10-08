"""유효 표시 설정만 전달하고 PC의 다른 상태는 건드리지 않는다."""

from types import SimpleNamespace

import pytest


def make_bridge(enabled=False):
    from src.core.companion.chat_display_bridge import CompanionChatDisplayBridge
    sent = []
    owner = SimpleNamespace(settings={"message_split_enabled": enabled},
                            _companion_adapter=SimpleNamespace(publish_extension=lambda *args: sent.append(args)))
    return CompanionChatDisplayBridge(owner), sent


def test_initial_current_value_and_only_changes_advance_revision():
    bridge, sent = make_bridge(True)
    assert bridge.snapshot() == {"display_revision": 0, "message_split_enabled": True}
    bridge.settings_changed(True)
    assert sent == []
    bridge.settings_changed(False)
    assert sent == [("chat_display_state", {"display_revision": 1, "message_split_enabled": False})]
    bridge.settings_changed(False)
    bridge.settings_changed(True)
    assert bridge.snapshot() == {"display_revision": 2, "message_split_enabled": True}
    assert len(sent) == 2


def test_preview_before_first_query_and_failed_notice_keep_effective_value():
    bridge, _ = make_bridge()
    bridge.owner._companion_adapter.publish_extension = lambda *_: (_ for _ in ()).throw(RuntimeError())
    bridge.settings_changed(True)
    assert bridge.snapshot()["message_split_enabled"] is True
    bridge.settings_changed(False)
    assert bridge.snapshot()["message_split_enabled"] is False


@pytest.mark.parametrize("loaded", [False, True])
def test_overlay_preview_and_restore_use_effective_value_before_web_loaded(loaded):
    from src.core.overlay_window import OverlayWindow

    display, sent = make_bridge()
    scripts = []
    overlay = SimpleNamespace(
        _page_loaded=loaded,
        settings=SimpleNamespace(config={"message_split_enabled": False}, get=lambda key, default=None: default),
        bridge=SimpleNamespace(_ensure_companion_chat_display=lambda: display),
        web_view=SimpleNamespace(page=lambda: SimpleNamespace(runJavaScript=scripts.append)),
        drag_bar=SimpleNamespace(setVisible=lambda *_: None),
        move=lambda *_: None, resize=lambda *_: None,
        _format_model_config_js_object=lambda *_: "{}", _resolve_model_config_payload=lambda *_, **kwargs: {},
    )
    for name in ("_apply_settings", "_apply_model_settings", "_apply_drag_bar_theme", "_sync_theme_to_js",
                 "_sync_ui_strings_to_js", "_sync_idle_motion_settings_to_js", "_sync_reroll_button_visibility_to_js",
                 "_sync_edit_button_visibility_to_js", "_sync_manual_summary_button_visibility_to_js",
                 "_sync_obsidian_note_button_visibility_to_js", "_sync_mood_toggle_button_visibility_to_js",
                 "_sync_proactive_conversation_button_visibility_to_js", "_sync_goal_button_visibility_to_js",
                 "_sync_token_usage_bubble_visibility_to_js", "_sync_typing_effect_settings_to_js",
                 "_sync_thought_feature_settings_to_js", "_sync_chat_panel_height_to_js"):
        setattr(overlay, name, lambda *_, **kwargs: None)
    overlay._resolve_message_split_payload = lambda override=None: OverlayWindow._resolve_message_split_payload(overlay, override)
    overlay._sync_message_split_settings_to_js = lambda override=None: OverlayWindow._sync_message_split_settings_to_js(overlay, override)
    OverlayWindow.preview_settings(overlay, {"message_split_enabled": True})
    assert display.snapshot()["message_split_enabled"] is True
    OverlayWindow.restore_settings(overlay)
    assert display.snapshot()["message_split_enabled"] is False
    assert [item[1]["display_revision"] for item in sent] == [1, 2]
    assert any("setMessageSplitConfig" in script for script in scripts) == loaded
