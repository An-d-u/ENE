import json

import pytest

from src.core.settings import Settings


def test_image_avatar_defaults_are_present():
    assert Settings.DEFAULT_CONFIG["avatar_mode"] == "live2d"
    assert Settings.DEFAULT_CONFIG["image_avatar_folder"] == ""
    assert Settings.DEFAULT_CONFIG["image_avatar_placements"] == {}
    assert Settings.DEFAULT_CONFIG["image_avatar_preview_emotion"] == "normal"


def test_load_missing_file_uses_default_config(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert settings.get("window_width") == Settings.DEFAULT_CONFIG["window_width"]
    assert settings.get("ui_language") == "auto"
    assert settings.get("enable_away_nudge") is True
    assert settings.get("away_input_grace_minutes") == 5
    assert settings.get("show_obsidian_note_button") is True
    assert settings.get("show_token_usage_bubble") is False
    assert settings.get("note_include_recent_context") is False
    assert settings.get("note_recent_context_turns") == 4
    assert settings.get("memory_search_recent_turns") == 2
    assert settings.get("obsidian_checked_max_chars_per_file") == 3000
    assert settings.get("obsidian_checked_total_max_chars") == 12000
    assert settings.get("tts_output_device_id") == ""
    assert settings.get("tts_output_volume") == 0.8
    assert settings.get("tts_language") == "ja"
    assert settings.get("typing_effect_enabled") is True
    assert settings.get("typing_effect_speed") == "normal"
    assert settings.get("message_split_enabled") is False
    assert settings.get("enable_ene_thoughts") is True
    assert settings.get("enable_response_analysis") is True
    assert settings.get("enable_schedule_recognition") is True
    assert settings.get("enable_conversation_promises") is True
    assert settings.get("include_ene_thoughts_in_context") is False
    assert settings.get("ene_thought_context_limit") == 2
    assert settings.get("enable_ene_goals") is True
    assert settings.get("enable_synthetic_gestures") is True
    assert settings.get("synthetic_gesture_scale") == 1.0
    assert settings.get("enable_idle_synthetic_gestures") is False
    assert settings.get("idle_synthetic_gesture_frequency") == "normal"
    assert settings.get("enable_expressive_pose_transitions") is False
    assert settings.get("show_ene_goal_button") is True
    assert settings.get("ene_goal_state_file") == "ene_goals.json"
    assert settings.get("live2d_parameter_overrides") == {}
    assert settings.get("model_json_path") == "assets/live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json"
    assert settings.get("head_pat_active_emotion_default") == "normal"
    assert settings.get("head_pat_end_emotion_default") == "normal"
    assert settings.get("chat_panel_height") == Settings.DEFAULT_CONFIG["chat_panel_height"]
    assert settings.get("max_raw_chunks_in_context") == 2
    assert settings.get("raw_chunk_turns") == 6
    assert settings.get("memory_activation_enabled") is True
    assert settings.get("max_activated_memories") is None
    assert settings.get("memory_activation_expand_hops") == 1
    gpt_sovits = settings.get("tts_provider_configs")["gpt_sovits_http"]
    assert gpt_sovits["speed_factor"] == 1.0
    assert gpt_sovits["top_k"] == 15
    assert gpt_sovits["top_p"] == 1.0
    assert gpt_sovits["temperature"] == 1.0
    assert gpt_sovits["text_split_method"] == "cut5"


def test_load_missing_file_uses_web_search_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("web_search_enabled") is False
    assert settings.get("web_search_auto_enabled") is True
    assert settings.get("web_search_provider") == "tavily"
    assert settings.get("web_search_max_results") == 5
    assert settings.get("web_search_timeout_sec") == 12
    assert settings.get("web_search_api_keys") == {"tavily": ""}


def test_load_missing_file_includes_genie_tts_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    genie = settings.get("tts_provider_configs")["genie_tts_http"]
    assert genie["api_url"] == "http://127.0.0.1:7860"
    assert genie["character_name"] == ""
    assert genie["onnx_model_dir"] == ""
    assert genie["model_language"] == "ja"
    assert genie["ref_audio_path"] == "assets/ref_audio/refvoice.wav"
    assert genie["ref_text"] == ""
    assert genie["ref_language"] == "ja"
    assert genie["split_sentence"] is True


def test_load_missing_file_includes_streaming_tts_defaults(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert "tts_streaming_enabled" in Settings.DEFAULT_CONFIG
    assert "tts_streaming_emit_message_on_first_chunk" in Settings.DEFAULT_CONFIG
    assert "tts_streaming_enabled" in settings.config
    assert "tts_streaming_emit_message_on_first_chunk" in settings.config
    assert settings.get("tts_streaming_enabled", False) is False
    assert settings.get("tts_streaming_emit_message_on_first_chunk", True) is True


def test_load_missing_file_uses_builtin_idle_motion_default(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("enable_builtin_idle_motion") is True


def test_load_missing_file_uses_viseme_lipsync_default(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("viseme_lipsync_enabled") is True


def test_load_legacy_config_without_viseme_lipsync_uses_default(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    config_path.write_text(
        json.dumps(
            {
                "window_width": 1280,
                "ui_language": "ko",
                "enable_builtin_idle_motion": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("window_width") == 1280
    assert settings.get("ui_language") == "ko"
    assert settings.get("enable_builtin_idle_motion") is False
    assert settings.get("viseme_lipsync_enabled") is True


def test_load_preserves_saved_legacy_model_path(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    legacy_path = "assets/live2d_models/jksalt/jksalt.model3.json"
    config_path.write_text(
        json.dumps(
            {
                "model_json_path": legacy_path,
                "head_pat_active_emotion_default": "eyeclose",
                "head_pat_end_emotion_default": "shy",
                "window_width": 1280,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("model_json_path") == legacy_path
    assert settings.get("head_pat_active_emotion_default") == "eyeclose"
    assert settings.get("head_pat_end_emotion_default") == "shy"
    assert settings.get("window_width") == 1280

    saved_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    assert saved_config["model_json_path"] == legacy_path


def test_load_preserves_custom_model_path(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    custom_path = "assets/live2d_models/custom/custom.model3.json"
    config_path.write_text(
        json.dumps({"model_json_path": custom_path}, ensure_ascii=False),
        encoding="utf-8-sig",
    )

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("model_json_path") == custom_path


def test_save_upgrades_legacy_config_with_viseme_lipsync_default(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    config_path.write_text(
        json.dumps(
            {
                "window_width": 1280,
                "ui_language": "ko",
                "enable_builtin_idle_motion": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.save()

    saved_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    assert saved_config["window_width"] == 1280
    assert saved_config["ui_language"] == "ko"
    assert saved_config["enable_builtin_idle_motion"] is False
    assert saved_config["viseme_lipsync_enabled"] is True


def test_load_missing_file_uses_auto_eye_blink_default(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("enable_auto_eye_blink") is True


def test_load_missing_file_keeps_idle_motion_dynamic_mode_as_legacy_default(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("idle_motion_dynamic_mode") is False


def test_settings_roundtrip_preserves_genie_tts_config(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    provider_configs = settings.get("tts_provider_configs")
    provider_configs["genie_tts_http"] = {
        "api_url": "http://127.0.0.1:7860",
        "character_name": "ene",
        "onnx_model_dir": "models/ene",
        "model_language": "ja",
        "ref_audio_path": "assets/ref_audio/refvoice.wav",
        "ref_text": "테스트 참조 문장",
        "ref_language": "ja",
        "split_sentence": False,
    }
    settings.set("tts_provider_configs", provider_configs)
    settings.save()

    reloaded = Settings(config_path=str(config_path), secret_path=str(secret_path))
    genie = reloaded.get("tts_provider_configs")["genie_tts_http"]
    assert genie["character_name"] == "ene"
    assert genie["onnx_model_dir"] == "models/ene"
    assert genie["model_language"] == "ja"
    assert genie["ref_text"] == "테스트 참조 문장"
    assert genie["split_sentence"] is False


def test_save_and_reload_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.set("window_width", 777)
    settings.set("zoom_level", 1.25)
    settings.set("ui_language", "ja")
    settings.set("tts_language", "same_as_response")
    settings.set("typing_effect_enabled", False)
    settings.set("typing_effect_speed", "slow")
    settings.set("message_split_enabled", True)
    settings.set("enable_ene_thoughts", False)
    settings.set("enable_proactive_conversation", False)
    settings.set("enable_response_analysis", False)
    settings.set("enable_schedule_recognition", False)
    settings.set("enable_conversation_promises", False)
    settings.set("include_ene_thoughts_in_context", True)
    settings.set("ene_thought_context_limit", 4)
    settings.set("chat_panel_height", 388)
    settings.set("max_raw_chunks_in_context", 4)
    settings.set("raw_chunk_turns", 8)
    settings.set("memory_activation_enabled", False)
    settings.set("max_activated_memories", 5)
    settings.set("memory_activation_expand_hops", 0)
    settings.save()

    reloaded = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert reloaded.get("window_width") == 777
    assert reloaded.get("zoom_level") == 1.25
    assert reloaded.get("ui_language") == "ja"
    assert reloaded.get("tts_language") == "same_as_response"
    assert reloaded.get("typing_effect_enabled") is False
    assert reloaded.get("typing_effect_speed") == "slow"
    assert reloaded.get("message_split_enabled") is True
    assert reloaded.get("enable_ene_thoughts") is False
    assert reloaded.get("enable_proactive_conversation") is False
    assert reloaded.get("enable_response_analysis") is False
    assert reloaded.get("enable_schedule_recognition") is False
    assert reloaded.get("enable_conversation_promises") is False
    assert reloaded.get("include_ene_thoughts_in_context") is True
    assert reloaded.get("ene_thought_context_limit") == 4
    assert reloaded.get("chat_panel_height") == 388
    assert reloaded.get("max_raw_chunks_in_context") == 4
    assert reloaded.get("raw_chunk_turns") == 8
    assert reloaded.get("memory_activation_enabled") is False
    assert reloaded.get("max_activated_memories") == 5
    assert reloaded.get("memory_activation_expand_hops") == 0


def test_save_and_reload_roundtrip_preserves_builtin_idle_motion(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.set("enable_builtin_idle_motion", False)
    settings.save()

    reloaded = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert reloaded.get("enable_builtin_idle_motion") is False


def test_default_config_enables_proactive_conversation():
    assert Settings.DEFAULT_CONFIG["enable_proactive_conversation"] is True


def test_save_and_reload_roundtrip_preserves_auto_eye_blink(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.set("enable_auto_eye_blink", False)
    settings.save()

    reloaded = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert reloaded.get("enable_auto_eye_blink") is False


def test_save_and_reload_roundtrip_preserves_viseme_lipsync_enabled(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.set("viseme_lipsync_enabled", False)
    settings.save()

    reloaded = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert reloaded.get("viseme_lipsync_enabled") is False


def test_load_invalid_json_falls_back_to_default(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    config_path.write_text("{invalid-json", encoding="utf-8")

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert settings.get("window_height") == Settings.DEFAULT_CONFIG["window_height"]


def test_update_merges_multiple_values(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.update({"window_x": 10, "window_y": 20})
    settings.save()

    assert not config_path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert not secret_path.read_bytes().startswith(b"\xef\xbb\xbf")
    loaded_data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    assert loaded_data["window_x"] == 10
    assert loaded_data["window_y"] == 20


def test_secret_values_are_saved_to_api_keys_file(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    settings.set("llm_api_keys", {"gemini": "gem-key"})
    settings.set("custom_api_key_or_password", "custom-secret")
    settings.save()

    config_data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    secret_data = json.loads(secret_path.read_text(encoding="utf-8-sig"))
    assert "llm_api_keys" not in config_data
    assert "custom_api_key_or_password" not in config_data
    assert secret_data["llm_api_keys"]["gemini"] == "gem-key"
    assert secret_data["custom_api_key_or_password"] == "custom-secret"


def test_web_search_api_keys_are_saved_to_secret_file(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    settings.set("web_search_api_keys", {"tavily": "synthetic-tavily-key"})
    settings.save()

    config_data = json.loads(config_path.read_text(encoding="utf-8-sig"))
    secret_data = json.loads(secret_path.read_text(encoding="utf-8-sig"))
    assert "web_search_api_keys" not in config_data
    assert secret_data["web_search_api_keys"]["tavily"] == "synthetic-tavily-key"


def test_save_creates_missing_parent_directories(tmp_path):
    config_path = tmp_path / "nested" / "config.json"
    secret_path = tmp_path / "nested" / "api_keys.json"

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.set("window_width", 640)
    settings.save()

    assert config_path.exists()
    assert secret_path.exists()


def test_migrates_legacy_secret_values_from_config(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    config_path.write_text(
        json.dumps(
            {
                "window_x": 55,
                "llm_api_keys": {"openai": "old-openai-key"},
                "custom_api_key_or_password": "old-custom-secret",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert settings.get("window_x") == 55
    assert settings.get("llm_api_keys")["openai"] == "old-openai-key"
    assert settings.get("custom_api_key_or_password") == "old-custom-secret"

    saved_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    saved_secret = json.loads(secret_path.read_text(encoding="utf-8-sig"))
    assert "llm_api_keys" not in saved_config
    assert "custom_api_key_or_password" not in saved_config
    assert saved_secret["llm_api_keys"]["openai"] == "old-openai-key"


def test_migrates_legacy_web_search_keys_without_overwriting_current_secret(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    config_path.write_text(
        json.dumps(
            {
                "web_search_api_keys": {
                    "tavily": "stale-legacy-tavily-key",
                    "future_provider": "legacy-future-provider-key",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    secret_path.write_text(
        json.dumps(
            {
                "web_search_api_keys": {
                    "tavily": "current-tavily-key",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("web_search_api_keys")["tavily"] == "current-tavily-key"
    assert settings.get("web_search_api_keys")["future_provider"] == "legacy-future-provider-key"

    saved_config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    saved_secret = json.loads(secret_path.read_text(encoding="utf-8-sig"))
    assert "web_search_api_keys" not in saved_config
    assert saved_secret["web_search_api_keys"]["tavily"] == "current-tavily-key"
    assert saved_secret["web_search_api_keys"]["future_provider"] == "legacy-future-provider-key"


def test_store_python_settings_loads_visible_roaming_files_when_runtime_copy_is_missing(tmp_path, monkeypatch):
    from src.core import app_paths

    runtime_root = tmp_path / "runtime" / "ENE"
    visible_root = tmp_path / "visible" / "ENE"
    config_path = runtime_root / "config.json"
    secret_path = runtime_root / "api_keys.json"
    visible_config_path = visible_root / "config.json"
    visible_secret_path = visible_root / "api_keys.json"

    visible_config = {
        "ui_language": "ko",
        "embedding_provider": "voyage",
        "llm_provider": "openai",
        "stt_device": "cuda",
    }
    visible_secret = {
        "llm_api_keys": {"openai": "real-openai-key"},
        "embedding_api_keys": {"voyage": "real-voyage-key"},
        "tts_api_keys": {},
        "custom_api_key_or_password": "",
    }

    monkeypatch.delenv("ENE_USER_DATA_DIR", raising=False)
    monkeypatch.setattr(app_paths, "is_windows_store_python_runtime", lambda: True)
    monkeypatch.setattr(app_paths, "get_user_data_dir", lambda app_name=app_paths.APP_NAME: runtime_root)
    monkeypatch.setattr(app_paths, "get_visible_user_data_dir", lambda app_name=app_paths.APP_NAME: visible_root)

    def _read_visible_bytes(path):
        if path == visible_config_path:
            return json.dumps(visible_config, ensure_ascii=False).encode("utf-8-sig")
        if path == visible_secret_path:
            return json.dumps(visible_secret, ensure_ascii=False).encode("utf-8-sig")
        return None

    monkeypatch.setattr(app_paths, "_read_file_bytes_via_powershell", _read_visible_bytes)

    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))

    assert settings.get("ui_language") == "ko"
    assert settings.get("stt_device") == "cuda"
    assert settings.get("llm_provider") == "openai"
    assert settings.get("llm_api_keys")["openai"] == "real-openai-key"
    assert settings.get("embedding_api_keys")["voyage"] == "real-voyage-key"


def test_structured_response_mode_defaults_to_auto(tmp_path):
    settings = Settings(
        config_path=str(tmp_path / "config.json"),
        secret_path=str(tmp_path / "api_keys.json"),
    )

    assert settings.get("structured_response_mode") == "auto"


@pytest.mark.parametrize("saved_value", [None, 42, "AUTO"])
def test_structured_response_mode_normalizes_unknown_saved_values_to_auto(
    tmp_path, saved_value
):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"structured_response_mode": saved_value}),
        encoding="utf-8",
    )

    settings = Settings(
        config_path=str(config_path),
        secret_path=str(tmp_path / "api_keys.json"),
    )

    assert settings.get("structured_response_mode") == "auto"


def test_structured_response_mode_preserves_legacy_saved_value(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"structured_response_mode": "legacy"}),
        encoding="utf-8",
    )

    settings = Settings(
        config_path=str(config_path),
        secret_path=str(tmp_path / "api_keys.json"),
    )

    assert settings.get("structured_response_mode") == "legacy"


def test_structured_response_mode_preserves_auto_saved_value(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"structured_response_mode": "auto"}),
        encoding="utf-8",
    )

    settings = Settings(
        config_path=str(config_path),
        secret_path=str(tmp_path / "api_keys.json"),
    )

    assert settings.get("structured_response_mode") == "auto"
