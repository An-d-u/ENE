from pathlib import Path


def test_memory_settings_prototype_lives_outside_runtime_ui_package():
    root = Path(__file__).resolve().parents[1]

    assert not (root / "src" / "ui" / "settings_memory_prototype.py").exists()
    assert (root / "docs" / "prototypes" / "settings_memory_prototype.py").exists()


def test_web_library_setup_script_lives_under_scripts():
    root = Path(__file__).resolve().parents[1]

    assert not (root / "setup.py").exists()
    assert (root / "scripts" / "setup_web_libs.py").exists()


def test_web_library_setup_script_resolves_project_root():
    from scripts import setup_web_libs

    root = Path(__file__).resolve().parents[1]

    assert setup_web_libs.get_project_root() == root
