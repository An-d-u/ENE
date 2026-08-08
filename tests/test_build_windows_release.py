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


def test_release_mappings_include_life_ui_and_default_world_but_exclude_user_data(tmp_path):
    from scripts.build_windows_release import collect_data_mappings

    project_root = tmp_path / "ENE"
    default_world = project_root / "prompts" / "defaults" / "life_world.md"
    life_panel = project_root / "assets" / "web" / "runtime_life_record_panel.js"
    runtime_prompts = [
        project_root / "prompts" / name
        for name in (
            "life_world.md",
            "base_system_prompt.md",
            "sub_prompt_body.md",
            "analysis_system_appendix.md",
            "emotion_guides.md",
        )
    ]
    default_world.parent.mkdir(parents=True)
    default_world.write_text("# Synthetic village", encoding="utf-8")
    life_panel.parent.mkdir(parents=True)
    life_panel.write_text("// synthetic panel", encoding="utf-8")
    for runtime_prompt in runtime_prompts:
        runtime_prompt.write_text("# Runtime-only synthetic prompt", encoding="utf-8")
    mappings = collect_data_mappings(project_root)
    normalized = {
        (source.relative_to(project_root).as_posix(), target)
        for source, target in mappings
    }

    def is_collected(path):
        return any(path.is_relative_to(source) for source, _target in mappings)

    assert ("assets/web", "assets/web") in normalized
    assert ("prompts/defaults", "prompts/defaults") in normalized
    assert is_collected(default_world)
    assert is_collected(life_panel)
    assert not any(is_collected(runtime_prompt) for runtime_prompt in runtime_prompts)
    assert all(target != "prompts" for _source, target in normalized)
    assert {
        "life_records.json",
        "life_session_state.json",
        "life_session_state.lock",
        "config.json",
    }.isdisjoint(source for source, _target in normalized)


def test_release_command_collects_default_life_world_web_assets_and_tzdata(tmp_path):
    from scripts.build_windows_release import build_pyinstaller_command

    project_root = tmp_path / "ENE"
    command = build_pyinstaller_command(project_root)
    command_text = " ".join(str(part) for part in command).replace("\\", "/")

    assert "assets/web" in command_text
    assert "prompts/defaults" in command_text
    assert "--collect-all tzdata" in command_text
    assert "prompts/life_world.md" not in command_text
    assert "prompts/base_system_prompt.md" not in command_text
    assert "prompts/sub_prompt_body.md" not in command_text
    assert "life_records.json" not in command_text
    assert "life_session_state.json" not in command_text


def test_build_pyinstaller_command_collects_tzdata_for_windows_zone_database(tmp_path):
    from scripts.build_windows_release import build_pyinstaller_command

    project_root = tmp_path / "ENE"
    command = build_pyinstaller_command(project_root)
    collected_packages = [
        command[index + 1]
        for index, argument in enumerate(command[:-1])
        if argument == "--collect-all"
    ]

    assert "tzdata" in collected_packages
    assert collected_packages == [
        "faster_whisper",
        "ctranslate2",
        "av",
        "tokenizers",
        "tiktoken",
        "tiktoken_ext",
        "tzdata",
    ]
