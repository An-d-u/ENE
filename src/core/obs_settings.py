"""
Obsidian 전용 상태(obs_config.json) 관리
"""
from __future__ import annotations

from pathlib import Path

from .app_paths import load_json_data, resolve_user_storage_path, save_json_data


class ObsSettings:
    """Obsidian UI/선택 상태 전용 설정 관리자."""

    DEFAULT_CONFIG = {
        "checked_files": [],
        "expanded_dirs": [],
        "panel_visible": True,
        "floating_window_x": 40,
        "floating_window_y": 120,
        "floating_window_width": 360,
        "floating_window_height": 520,
    }

    def __init__(self, config_path: str | Path | None = None):
        target_path = config_path if config_path is not None else "obs_config.json"
        self.config_path = resolve_user_storage_path(target_path)
        self.config = self.load()

    def load(self) -> dict:
        try:
            loaded = load_json_data(self.config_path, encoding="utf-8")
            if isinstance(loaded, dict):
                merged = dict(self.DEFAULT_CONFIG)
                merged.update(loaded)
                if not isinstance(merged.get("checked_files"), list):
                    merged["checked_files"] = []
                if not isinstance(merged.get("expanded_dirs"), list):
                    merged["expanded_dirs"] = []
                return merged
        except Exception as e:
            if self.config_path.exists():
                print(f"[ObsSettings] load failed: {e}")
        return dict(self.DEFAULT_CONFIG)

    def save(self):
        try:
            save_json_data(
                self.config_path,
                self.config,
                encoding="utf-8",
                indent=2,
                ensure_ascii=False,
            )
        except Exception as e:
            print(f"[ObsSettings] save failed: {e}")

    def get(self, key: str, default=None):
        return self.config.get(key, default)

    def set(self, key: str, value):
        self.config[key] = value

    def get_checked_files(self) -> list[str]:
        raw = self.config.get("checked_files", [])
        if not isinstance(raw, list):
            return []
        return [str(x) for x in raw if str(x).strip()]

    def set_checked_files(self, files: list[str]):
        normalized = sorted(set(str(x).replace("\\", "/").strip() for x in files if str(x).strip()))
        self.config["checked_files"] = normalized
        self.save()

    def set_file_checked(self, rel_path: str, checked: bool):
        rel = str(rel_path or "").replace("\\", "/").strip()
        if not rel:
            return
        current = set(self.get_checked_files())
        if checked:
            current.add(rel)
        else:
            current.discard(rel)
        self.set_checked_files(list(current))
