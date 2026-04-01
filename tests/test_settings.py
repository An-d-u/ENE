import json

from src.core.settings import Settings


def test_load_missing_file_uses_default_config(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert settings.get("window_width") == Settings.DEFAULT_CONFIG["window_width"]
    assert settings.get("ui_language") == "auto"
    assert settings.get("enable_away_nudge") is True
    assert settings.get("show_obsidian_note_button") is True
    assert settings.get("show_token_usage_bubble") is False
    assert settings.get("note_include_recent_context") is False
    assert settings.get("note_recent_context_turns") == 4
    assert settings.get("memory_search_recent_turns") == 2
    assert settings.get("obsidian_checked_max_chars_per_file") == 3000
    assert settings.get("obsidian_checked_total_max_chars") == 12000
    assert settings.get("tts_output_device_id") == ""
    assert settings.get("tts_output_volume") == 0.8
    assert settings.get("typing_effect_enabled") is True
    assert settings.get("typing_effect_speed") == "normal"
    assert settings.get("message_split_enabled") is False
    gpt_sovits = settings.get("tts_provider_configs")["gpt_sovits_http"]
    assert gpt_sovits["speed_factor"] == 1.0
    assert gpt_sovits["top_k"] == 15
    assert gpt_sovits["top_p"] == 1.0
    assert gpt_sovits["temperature"] == 1.0
    assert gpt_sovits["text_split_method"] == "cut5"


def test_save_and_reload_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.set("window_width", 777)
    settings.set("zoom_level", 1.25)
    settings.set("ui_language", "ja")
    settings.set("typing_effect_enabled", False)
    settings.set("typing_effect_speed", "slow")
    settings.set("message_split_enabled", True)
    settings.save()

    reloaded = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert reloaded.get("window_width") == 777
    assert reloaded.get("zoom_level") == 1.25
    assert reloaded.get("ui_language") == "ja"
    assert reloaded.get("typing_effect_enabled") is False
    assert reloaded.get("typing_effect_speed") == "slow"
    assert reloaded.get("message_split_enabled") is True


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
