import json

from src.core.obs_settings import ObsSettings


def test_load_reads_existing_utf8_bom_obs_config(tmp_path):
    config_path = tmp_path / "obs_config.json"
    payload = {
        "checked_files": ["notes/샘플.md"],
        "expanded_dirs": ["notes"],
        "panel_visible": True,
    }
    config_path.write_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8-sig"))

    settings = ObsSettings(config_path=str(config_path))

    assert settings.get_checked_files() == ["notes/샘플.md"]
    assert settings.get("panel_visible") is True
