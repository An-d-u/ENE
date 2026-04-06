"""
ENE settings manager.
Loads and saves user settings to JSON.
"""
import json
from pathlib import Path

from .app_paths import (
    get_user_file,
    load_json_data,
    resolve_user_storage_path,
    save_json_data,
    sync_visible_store_python_file_to_runtime,
)


class Settings:
    """Application settings manager."""

    DEFAULT_CONFIG = {
        "window_x": 100,
        "window_y": 100,
        "window_width": 400,
        "window_height": 600,
        "zoom_level": 1.0,
        "show_drag_bar": True,
        "show_recent_reroll_button": True,
        "show_recent_edit_button": True,
        "show_manual_summary_button": True,
        "show_obsidian_note_button": True,
        "show_mood_toggle_button": True,
        "show_token_usage_bubble": False,
        "typing_effect_enabled": True,
        "typing_effect_speed": "normal",
        "message_split_enabled": False,
        "enable_global_ptt": True,
        "global_ptt_hotkey": "alt",
        "interrupt_tts_on_ptt": True,
        "embedding_provider": "voyage",
        "embedding_model": "voyage-3",
        "stt_model_size": "small",
        "stt_language": "ko",
        "stt_device": "auto",
        "stt_compute_type": "int8",
        "stt_min_record_sec": 0.25,
        "model_scale": 1.0,
        "model_x_percent": 50,  # 0-100%
        "model_y_percent": 50,  # 0-100%
        "model_json_path": "assets/live2d_models/jksalt/jksalt.model3.json",
        "theme_accent_color": "#0071E3",
        "settings_window_bg_color": "#EEF1F5",
        "settings_card_bg_color": "#FFFFFF",
        "settings_input_bg_color": "#F8FAFC",
        "chat_panel_bg_color": "#111214",
        "chat_input_bg_color": "#1B1D22",
        "chat_assistant_bubble_color": "#FFFFFF",
        "chat_user_bubble_color": "#0071E3",
        "theme_mode": "light",
        "ui_language": "auto",
        "follow_system_theme": False,
        "mouse_tracking_enabled": True,
        "enable_idle_motion": True,
        "idle_motion_strength": 1.0,  # 0.2 ~ 2.0
        "idle_motion_speed": 1.0,  # 0.5 ~ 2.0
        "idle_motion_dynamic_mode": False,
        "performance_engine_enabled": True,
        "performance_intensity": 1.0,
        "speech_reactivity": 1.0,
        "idle_micro_motion": 0.35,
        "show_motion_debug_overlay": False,
        "enable_head_pat": True,
        "head_pat_strength": 1.0,  # 0.5 ~ 2.5
        "head_pat_fade_in_ms": 180,
        "head_pat_fade_out_ms": 220,
        "head_pat_active_emotion_default": "eyeclose",
        "head_pat_active_emotion_custom": "",
        "head_pat_end_emotion_default": "shy",
        "head_pat_end_emotion_custom": "",
        "head_pat_end_emotion_duration_sec": 5,
        "llm_provider": "gemini",
        "llm_model": "gemini-3-flash-preview",
        "llm_models": {
            "gemini": "gemini-3-flash-preview",
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-5-sonnet-latest",
            "openrouter": "openai/gpt-4o-mini",
            "deepseek": "deepseek-chat",
            "ollama": "llama3.1",
            "custom_api": "",
        },
        "llm_model_params": {
            "gemini": {
                "gemini-3-flash-preview": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
                "__default__": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
            },
            "openai": {
                "gpt-4o-mini": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
                "__default__": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
            },
            "anthropic": {
                "claude-3-5-sonnet-latest": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
                "__default__": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
            },
            "openrouter": {
                "openai/gpt-4o-mini": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
                "__default__": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
            },
            "deepseek": {
                "deepseek-chat": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
                "__default__": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
            },
            "ollama": {
                "llama3.1": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
                "__default__": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
            },
            "custom_api": {
                "__default__": {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048},
            },
        },
        "custom_api_url": "",
        "custom_api_request_model": "",
        "custom_api_format": "openai_compatible",
        "gemini_api_key": "",
        "summarize_threshold": 10,
        "enable_tts": True,
        "tts_output_device_id": "",
        "tts_output_volume": 0.8,
        "tts_provider": "gpt_sovits_http",
        "tts_api_url": "http://127.0.0.1:9880",
        "tts_ref_audio_path": "assets/ref_audio/refvoice.wav",
        "tts_ref_text": "人間さんはどんな色が一番好き？ ん？ なんで聞いたかって？ ふふん～ 内緒",
        "tts_ref_language": "ja",
        "tts_target_language": "ja",
        "tts_provider_configs": {
            "gpt_sovits_http": {
                "api_url": "http://127.0.0.1:9880",
                "ref_audio_path": "assets/ref_audio/refvoice.wav",
                "ref_text": "人間さんはどんな色が一番好き？ ん？ なんで聞いたかって？ ふふん～ 内緒",
                "ref_language": "ja",
                "target_language": "ja",
                "speed_factor": 1.0,
                "top_k": 15,
                "top_p": 1.0,
                "temperature": 1.0,
                "text_split_method": "cut5",
            },
            "openai_audio_speech": {
                "api_url": "https://api.openai.com/v1",
                "model": "gpt-4o-mini-tts",
                "voice": "alloy",
                "speed": 1.0,
                "response_format": "wav",
            },
            "openai_compatible_audio_speech": {
                "api_url": "http://127.0.0.1:8000/v1",
                "model": "tts-1",
                "voice": "alloy",
                "speed": 1.0,
                "response_format": "wav",
            },
            "elevenlabs": {
                "api_url": "https://api.elevenlabs.io/v1",
                "model": "eleven_multilingual_v2",
                "voice": "EXAVITQu4vr4xnSDxMaL",
                "speed": 1.0,
                "stability": 0.5,
                "similarity_boost": 0.75,
                "style": 0.0,
                "use_speaker_boost": True,
                "output_format": "pcm_44100",
            },
            "browser_speech": {
                "lang": "ja-JP",
                "voice": "",
                "rate": 1.0,
                "pitch": 1.0,
                "volume": 1.0,
            },
        },
        "enable_away_nudge": True,
        "away_idle_minutes": 60,
        "away_compare_delay_seconds": 30,
        "away_diff_threshold_percent": 3.0,
        "away_additional_retry_limit": 0,
        "enable_mood_system": True,
        "mood_update_speed": "normal",
        "mood_personality_profile": "affectionate",
        "mood_decay_per_hour": 0.08,
        "mood_state_file": "mood_state.json",
        "obsidian_cli_enabled": False,
        "obsidian_cli_bin": "obsidian",
        "obsidian_cli_command": "",
        "obsidian_cli_timeout_sec": 20,
        "obsidian_cli_retry_count": 2,
        "obsidian_cli_retry_delay_ms": 500,
        "obsidian_cli_primary_for_diary": True,
        "obsidian_checked_max_chars_per_file": 3000,
        "obsidian_checked_total_max_chars": 12000,
        "diary_keep_local_copy_on_cli_success": False,
        "note_include_recent_context": False,
        "note_recent_context_turns": 4,
        "memory_search_recent_turns": 2,
        "max_profile_facts_in_context": 10,
    }

    DEFAULT_SECRET_CONFIG = {
        "llm_api_keys": {
            "gemini": "",
            "openai": "",
            "anthropic": "",
            "openrouter": "",
            "deepseek": "",
            "ollama": "",
            "custom_api": "",
        },
        "embedding_api_keys": {
            "voyage": "",
        },
        "tts_api_keys": {
            "openai_audio_speech": "",
            "openai_compatible_audio_speech": "",
            "elevenlabs": "",
        },
        "custom_api_key_or_password": "",
    }

    SECRET_KEYS = set(DEFAULT_SECRET_CONFIG.keys())

    def __init__(self, config_path: str | None = None, secret_path: str | None = None):
        self.config_path = (
            resolve_user_storage_path(config_path)
            if config_path is not None
            else get_user_file("config.json").resolve()
        )
        self.secret_path = (
            resolve_user_storage_path(secret_path)
            if secret_path is not None
            else get_user_file("api_keys.json").resolve()
        )
        self.config = self.load()
        self.secret_config = self.load_secret()
        self._migrate_secrets_from_legacy_config()
        self._migrate_legacy_embedding_key_file()
        self._migrate_legacy_tts_config()

    def load(self) -> dict:
        """Load settings. Return defaults on failure."""
        try:
            loaded_config = load_json_data(self.config_path, encoding="utf-8-sig")
            if not isinstance(loaded_config, dict):
                loaded_config = {}
            # 비밀값은 api_keys.json으로 분리 관리한다.
            loaded_config = {
                k: v for k, v in loaded_config.items()
                if k not in self.SECRET_KEYS
            }
            merged = {**self.DEFAULT_CONFIG, **loaded_config}

            base_models = dict(self.DEFAULT_CONFIG["llm_models"])
            loaded_models = loaded_config.get("llm_models", {})
            if isinstance(loaded_models, dict):
                base_models.update(loaded_models)
            merged["llm_models"] = base_models

            base_params = json.loads(json.dumps(self.DEFAULT_CONFIG["llm_model_params"]))
            loaded_params = loaded_config.get("llm_model_params", {})
            if isinstance(loaded_params, dict):
                for provider, provider_params in loaded_params.items():
                    if not isinstance(provider_params, dict):
                        continue
                    store = base_params.setdefault(provider, {})
                    for model_name, params in provider_params.items():
                        if isinstance(params, dict):
                            store[model_name] = params
            merged["llm_model_params"] = base_params

            base_tts_configs = json.loads(json.dumps(self.DEFAULT_CONFIG["tts_provider_configs"]))
            loaded_tts_configs = loaded_config.get("tts_provider_configs", {})
            if isinstance(loaded_tts_configs, dict):
                for provider, provider_config in loaded_tts_configs.items():
                    if not isinstance(provider_config, dict):
                        continue
                    store = base_tts_configs.setdefault(provider, {})
                    store.update(provider_config)
            merged["tts_provider_configs"] = base_tts_configs

            return merged
        except Exception as e:
            if self.config_path.exists():
                print(f"Settings load failed: {e}")
        return self.DEFAULT_CONFIG.copy()

    def load_secret(self) -> dict:
        """Load secret settings. Return defaults on failure."""
        try:
            loaded_secret = load_json_data(self.secret_path, encoding="utf-8-sig")
            if not isinstance(loaded_secret, dict):
                loaded_secret = {}
            merged = {**self.DEFAULT_SECRET_CONFIG, **loaded_secret}
            # 중첩 딕셔너리는 안전하게 병합한다.
            base_api_keys = dict(self.DEFAULT_SECRET_CONFIG["llm_api_keys"])
            loaded_api_keys = merged.get("llm_api_keys", {})
            if isinstance(loaded_api_keys, dict):
                base_api_keys.update(loaded_api_keys)
            merged["llm_api_keys"] = base_api_keys

            base_embedding_keys = dict(self.DEFAULT_SECRET_CONFIG["embedding_api_keys"])
            loaded_embedding_keys = merged.get("embedding_api_keys", {})
            if isinstance(loaded_embedding_keys, dict):
                base_embedding_keys.update(loaded_embedding_keys)
            merged["embedding_api_keys"] = base_embedding_keys

            base_tts_keys = dict(self.DEFAULT_SECRET_CONFIG["tts_api_keys"])
            loaded_tts_keys = merged.get("tts_api_keys", {})
            if isinstance(loaded_tts_keys, dict):
                base_tts_keys.update(loaded_tts_keys)
            merged["tts_api_keys"] = base_tts_keys
            return merged
        except Exception as e:
            if self.secret_path.exists():
                print(f"Secret settings load failed: {e}")
        return self.DEFAULT_SECRET_CONFIG.copy()

    def _migrate_secrets_from_legacy_config(self):
        """
        과거 config.json에 저장된 비밀값을 api_keys.json으로 1회 이전한다.
        """
        sync_visible_store_python_file_to_runtime(self.config_path)
        if not self.config_path.exists():
            return

        try:
            raw_config = load_json_data(self.config_path, encoding="utf-8-sig")
            if not isinstance(raw_config, dict):
                return
        except Exception:
            return

        moved = False
        for key in list(self.SECRET_KEYS):
            if key in raw_config:
                value = raw_config.get(key)
                if key == "llm_api_keys" and isinstance(value, dict):
                    merged_keys = dict(self.secret_config.get("llm_api_keys", {}))
                    for provider, provider_key in value.items():
                        if provider_key:
                            merged_keys[provider] = provider_key
                    self.secret_config["llm_api_keys"] = merged_keys
                elif value:
                    self.secret_config[key] = value
                # 현재 메모리 config에는 이미 secret key가 없지만,
                # 혹시 포함되어 있으면 안전하게 제거한다.
                self.config.pop(key, None)
                moved = True
        if moved:
            self.save()

    def _migrate_legacy_embedding_key_file(self):
        """
        과거 voyage_api_key.txt를 api_keys.json의 embedding_api_keys.voyage로 1회 이전한다.
        이전 후 레거시 파일은 제거한다.
        """
        legacy_path = resolve_user_storage_path("voyage_api_key.txt")
        sync_visible_store_python_file_to_runtime(legacy_path)
        if not legacy_path.exists():
            legacy_path = Path("voyage_api_key.txt")
        if not legacy_path.exists():
            return

        try:
            raw_value = legacy_path.read_text(encoding="utf-8-sig").strip()
        except Exception as e:
            print(f"Legacy embedding key load failed: {e}")
            return

        existing_keys = self.secret_config.get("embedding_api_keys", {})
        if not isinstance(existing_keys, dict):
            existing_keys = {}

        current_value = str(existing_keys.get("voyage", "")).strip()
        migrated = False
        if raw_value and raw_value != "your-voyage-api-key-here" and not current_value:
            existing_keys["voyage"] = raw_value
            self.secret_config["embedding_api_keys"] = existing_keys
            migrated = True

        if migrated:
            self.save()

        try:
            legacy_path.unlink()
        except Exception as e:
            print(f"Legacy embedding key cleanup failed: {e}")

    def _migrate_legacy_tts_config(self):
        """
        과거 평면 TTS 설정을 공급자별 구조(tts_provider_configs / tts_api_keys)로 1회 이전한다.
        기존 키는 하위 호환을 위해 유지한다.
        """
        defaults = json.loads(json.dumps(self.DEFAULT_CONFIG["tts_provider_configs"]))
        existing = self.config.get("tts_provider_configs", {})
        if not isinstance(existing, dict):
            existing = {}

        merged = defaults
        for provider, provider_config in existing.items():
            if isinstance(provider_config, dict):
                merged.setdefault(provider, {}).update(provider_config)

        gpt_sovits_config = merged.setdefault("gpt_sovits_http", {})
        gpt_sovits_config["api_url"] = str(self.config.get("tts_api_url", defaults["gpt_sovits_http"]["api_url"]))
        gpt_sovits_config["ref_audio_path"] = str(self.config.get("tts_ref_audio_path", defaults["gpt_sovits_http"]["ref_audio_path"]))
        gpt_sovits_config["ref_text"] = str(self.config.get("tts_ref_text", defaults["gpt_sovits_http"]["ref_text"]))
        gpt_sovits_config["ref_language"] = str(self.config.get("tts_ref_language", defaults["gpt_sovits_http"]["ref_language"]))
        gpt_sovits_config["target_language"] = str(self.config.get("tts_target_language", defaults["gpt_sovits_http"]["target_language"]))
        gpt_sovits_config["speed_factor"] = float(gpt_sovits_config.get("speed_factor", defaults["gpt_sovits_http"]["speed_factor"]) or defaults["gpt_sovits_http"]["speed_factor"])
        gpt_sovits_config["top_k"] = int(gpt_sovits_config.get("top_k", defaults["gpt_sovits_http"]["top_k"]) or defaults["gpt_sovits_http"]["top_k"])
        gpt_sovits_config["top_p"] = float(gpt_sovits_config.get("top_p", defaults["gpt_sovits_http"]["top_p"]) or defaults["gpt_sovits_http"]["top_p"])
        gpt_sovits_config["temperature"] = float(gpt_sovits_config.get("temperature", defaults["gpt_sovits_http"]["temperature"]) or defaults["gpt_sovits_http"]["temperature"])
        gpt_sovits_config["text_split_method"] = str(gpt_sovits_config.get("text_split_method", defaults["gpt_sovits_http"]["text_split_method"]) or defaults["gpt_sovits_http"]["text_split_method"])

        self.config["tts_provider_configs"] = merged

        secret_defaults = dict(self.DEFAULT_SECRET_CONFIG["tts_api_keys"])
        existing_keys = self.secret_config.get("tts_api_keys", {})
        if not isinstance(existing_keys, dict):
            existing_keys = {}
        secret_defaults.update(existing_keys)
        self.secret_config["tts_api_keys"] = secret_defaults

    def save(self):
        """Persist current settings and secret settings."""
        try:
            save_json_data(
                self.config_path,
                self.config,
                encoding="utf-8-sig",
                indent=2,
                ensure_ascii=False,
            )
        except Exception as e:
            print(f"Settings save failed: {e}")
        try:
            save_json_data(
                self.secret_path,
                self.secret_config,
                encoding="utf-8-sig",
                indent=2,
                ensure_ascii=False,
            )
        except Exception as e:
            print(f"Secret settings save failed: {e}")

    def get(self, key: str, default=None):
        if key in self.SECRET_KEYS:
            return self.secret_config.get(key, default)
        return self.config.get(key, default)

    def set(self, key: str, value):
        if key in self.SECRET_KEYS:
            self.secret_config[key] = value
            return
        self.config[key] = value

    def update(self, updates: dict):
        for key, value in updates.items():
            if key in self.SECRET_KEYS:
                self.secret_config[key] = value
            else:
                self.config[key] = value
