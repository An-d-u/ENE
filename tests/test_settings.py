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


def test_save_and_reload_roundtrip(tmp_path):
    config_path = tmp_path / "config.json"
    secret_path = tmp_path / "api_keys.json"
    settings = Settings(config_path=str(config_path), secret_path=str(secret_path))
    settings.set("window_width", 777)
    settings.set("zoom_level", 1.25)
    settings.set("ui_language", "ja")
    settings.save()

    reloaded = Settings(config_path=str(config_path), secret_path=str(secret_path))
    assert reloaded.get("window_width") == 777
    assert reloaded.get("zoom_level") == 1.25
    assert reloaded.get("ui_language") == "ja"


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
