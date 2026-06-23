from src.core.bridge import WebBridge


JS_CALLABLE_BRIDGE_METHODS = {
    "delete_message_attachment",
    "delete_promise_reminder",
    "edit_last_user_message",
    "get_live2d_parameter_overrides",
    "get_mood_snapshot_json",
    "get_obs_tree_json",
    "increment_head_pat_count_from_js",
    "open_settings_dialog",
    "preview_attachments",
    "refresh_obs_tree",
    "request_goal_items",
    "request_promise_items",
    "reroll_last_response",
    "save_chat_panel_height",
    "save_live2d_parameter_overrides",
    "send_to_ai",
    "send_to_ai_with_attachments",
    "set_obs_file_checked",
    "summarize_now",
    "toggle_obs_panel",
}


def _qwebchannel_method_names(bridge: WebBridge) -> set[str]:
    meta = bridge.metaObject()
    return {
        bytes(meta.method(index).name()).decode("utf-8")
        for index in range(meta.methodCount())
    }


def test_attachment_send_slot_is_exposed_to_qwebchannel():
    bridge = WebBridge()
    meta = bridge.metaObject()

    assert meta.indexOfMethod(b"send_to_ai_with_attachments(QString,QString)") >= 0


def test_manual_summary_slot_is_exposed_to_qwebchannel():
    bridge = WebBridge()
    meta = bridge.metaObject()

    assert meta.indexOfMethod(b"summarize_now()") >= 0


def test_live2d_parameter_slots_are_exposed_with_exact_qwebchannel_signatures():
    bridge = WebBridge()
    meta = bridge.metaObject()

    assert meta.indexOfMethod(b"get_live2d_parameter_overrides(QString)") >= 0
    assert meta.indexOfMethod(b"save_live2d_parameter_overrides(QString,QString)") >= 0


def test_js_callable_bridge_methods_are_exposed_to_qwebchannel():
    bridge = WebBridge()
    exposed_methods = _qwebchannel_method_names(bridge)

    assert sorted(JS_CALLABLE_BRIDGE_METHODS - exposed_methods) == []
