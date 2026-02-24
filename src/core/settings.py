"""
ENE settings manager.
Loads and saves user settings to JSON.
"""
import json
from pathlib import Path


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
        "show_manual_summary_button": True,
        "model_scale": 1.0,
        "model_x_percent": 50,  # 0-100%
        "model_y_percent": 50,  # 0-100%
        "mouse_tracking_enabled": True,
        "enable_idle_motion": True,
        "idle_motion_strength": 1.0,  # 0.2 ~ 2.0
        "idle_motion_speed": 1.0,  # 0.5 ~ 2.0
        "idle_motion_dynamic_mode": False,
        "enable_head_pat": True,
        "head_pat_strength": 1.0,  # 0.5 ~ 2.5
        "head_pat_fade_in_ms": 180,
        "head_pat_fade_out_ms": 220,
        "head_pat_active_emotion_default": "eyeclose",
        "head_pat_active_emotion_custom": "",
        "head_pat_end_emotion_default": "shy",
        "head_pat_end_emotion_custom": "",
        "head_pat_end_emotion_duration_sec": 5,
        "gemini_api_key": "",
        "summarize_threshold": 10,
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
    }

    def __init__(self, config_path: str = "config.json"):
        self.config_path = Path(config_path)
        self.config = self.load()

    def load(self) -> dict:
        """Load settings. Return defaults on failure."""
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    loaded_config = json.load(f)
                return {**self.DEFAULT_CONFIG, **loaded_config}
            except Exception as e:
                print(f"Settings load failed: {e}")
                return self.DEFAULT_CONFIG.copy()
        return self.DEFAULT_CONFIG.copy()

    def save(self):
        """Persist current settings."""
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Settings save failed: {e}")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value

    def update(self, updates: dict):
        self.config.update(updates)
