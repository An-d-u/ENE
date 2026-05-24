from pathlib import Path


def test_memory_settings_prototype_lives_outside_runtime_ui_package():
    root = Path(__file__).resolve().parents[1]

    assert not (root / "src" / "ui" / "settings_memory_prototype.py").exists()
    assert (root / "docs" / "prototypes" / "settings_memory_prototype.py").exists()
