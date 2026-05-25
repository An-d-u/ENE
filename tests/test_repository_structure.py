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


def test_ci_coverage_threshold_is_80_percent():
    root = Path(__file__).resolve().parents[1]
    ci_config = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8-sig")

    assert "--fail-under=80" in ci_config
    assert "--cov-fail-under=4" not in ci_config


def test_ci_coverage_command_omits_ci_unstable_runtime_surfaces():
    root = Path(__file__).resolve().parents[1]
    ci_config = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8-sig")

    expected_omits = [
        "src/core/app.py",
        "src/core/audio_player.py",
        "src/core/global_ptt.py",
        "src/core/overlay_window.py",
        "src/core/bridge_workers.py",
        "src/core/bridge_mixins/attachments.py",
        "src/core/bridge_mixins/away.py",
        "src/core/bridge_mixins/memory_summary.py",
        "src/core/bridge_mixins/mood.py",
        "src/core/bridge_mixins/obsidian.py",
        "src/ui/drag_bar.py",
        "src/ui/settings_dialog_hotkeys.py",
        "src/ui/settings_dialog_profile.py",
        "src/ui/settings_dialog_prompt.py",
        "src/ui/settings_dialog_theme.py",
        "src/ui/settings_dialog_tts.py",
        "src/ui/settings_dialog_widgets.py",
        "src/ai/http_llm_clients.py",
        "src/ai/llm_client.py",
    ]

    for omitted_path in expected_omits:
        assert omitted_path in ci_config

    assert "coverage run --source=src --omit=" in ci_config
    assert "coverage report --show-missing --skip-empty --fail-under=80" in ci_config
