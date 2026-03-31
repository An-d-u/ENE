def test_build_archive_name_uses_tag_and_platform_suffix():
    from scripts.build_windows_release import build_archive_name

    assert build_archive_name("v1.2.3") == "ENE-v1.2.3-win64.zip"


def test_build_pyinstaller_command_includes_required_resource_directories(tmp_path):
    from scripts.build_windows_release import build_pyinstaller_command

    project_root = tmp_path / "ENE"
    (project_root / "assets" / "icons").mkdir(parents=True, exist_ok=True)
    (project_root / "assets" / "icons" / "ene_app.ico").write_bytes(b"ico")
    (project_root / "assets" / "web").mkdir(parents=True, exist_ok=True)
    (project_root / "assets" / "live2d_models" / "hiyori").mkdir(parents=True, exist_ok=True)
    (project_root / "assets" / "live2d_models" / "jksalt").mkdir(parents=True, exist_ok=True)
    (project_root / "assets" / "ref_audio").mkdir(parents=True, exist_ok=True)
    (project_root / "src" / "locales").mkdir(parents=True, exist_ok=True)
    (project_root / "prompts" / "defaults").mkdir(parents=True, exist_ok=True)
    (project_root / "main.py").write_text("print('ok')", encoding="utf-8-sig")

    command = build_pyinstaller_command(project_root)
    command_text = " ".join(str(part) for part in command)

    assert "--windowed" in command
    assert "--name" in command
    assert "ENE" in command
    assert "assets/icons" in command_text.replace("\\", "/")
    assert "assets/web" in command_text.replace("\\", "/")
    assert "assets/live2d_models/hiyori" in command_text.replace("\\", "/")
    assert "assets/live2d_models/jksalt" not in command_text.replace("\\", "/")
    assert "assets/ref_audio" not in command_text.replace("\\", "/")
    assert "src/locales" in command_text.replace("\\", "/")
    assert "prompts/defaults" in command_text.replace("\\", "/")
    assert "tiktoken_ext" in command_text
    assert str(project_root / "main.py") in command


def test_collect_data_mappings_returns_only_release_safe_bundle_targets(tmp_path):
    from scripts.build_windows_release import collect_data_mappings

    project_root = tmp_path / "ENE"
    mappings = collect_data_mappings(project_root)

    assert (project_root / "assets" / "icons", "assets/icons") in mappings
    assert (project_root / "assets" / "web", "assets/web") in mappings
    assert (project_root / "assets" / "live2d_models" / "hiyori", "assets/live2d_models/hiyori") in mappings
    assert (project_root / "src" / "locales", "src/locales") in mappings
    assert (project_root / "prompts" / "defaults", "prompts/defaults") in mappings
    assert (project_root / "assets", "assets") not in mappings
    assert (project_root / "assets" / "live2d_models" / "jksalt", "assets/live2d_models/jksalt") not in mappings
    assert (project_root / "assets" / "ref_audio", "assets/ref_audio") not in mappings
