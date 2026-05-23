from src.core.bridge_state import (
    AwayBridgeState,
    BridgeStateAliasMixin,
    ChatBridgeState,
    ObsidianBridgeState,
    PromiseBridgeState,
    TTSBridgeState,
)


def test_bridge_state_aliases_preserve_legacy_attribute_access():
    class DummyBridge(BridgeStateAliasMixin):
        pass

    bridge = DummyBridge()
    bridge._init_bridge_states(checked_files=["daily.md"])

    bridge.conversation_buffer.append(("user", "안녕", "2026-05-24 10:00"))
    bridge._last_request_payload = {"message": "안녕"}
    bridge._cached_obs_tree_json = "{}"
    bridge.tts_streaming_enabled = True
    bridge.away_trigger_count_since_last_user_msg = 2
    bridge.promise_run_queue.append({"id": "p1"})

    assert isinstance(bridge.chat_state, ChatBridgeState)
    assert isinstance(bridge.obsidian_state, ObsidianBridgeState)
    assert isinstance(bridge.tts_state, TTSBridgeState)
    assert isinstance(bridge.promise_state, PromiseBridgeState)
    assert isinstance(bridge.away_state, AwayBridgeState)
    assert bridge.chat_state.conversation_buffer == [("user", "안녕", "2026-05-24 10:00")]
    assert bridge.chat_state.last_request_payload == {"message": "안녕"}
    assert bridge.obsidian_state.cached_obs_tree_json == "{}"
    assert bridge.tts_state.streaming_enabled is True
    assert bridge.away_state.trigger_count_since_last_user_msg == 2
    assert bridge.promise_state.run_queue == [{"id": "p1"}]


def test_obsidian_state_initial_tree_payload_contains_checked_files():
    state = ObsidianBridgeState.initial(checked_files=["a.md", "b.md"])

    assert '"checked_files": ["a.md", "b.md"]' in state.cached_obs_tree_json
