from pathlib import Path


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")


def _write_default_prompt_files(directory: Path) -> None:
    _write_text(directory / "base_system_prompt.md", "기본 프롬프트")
    _write_text(directory / "sub_prompt_body.md", "### [응답 형식]\n- 기본 응답")
    _write_text(directory / "emotion_guides.md", "### [감정 사용 가이드]\n- normal: 기본 상태\n")


def test_save_prompt_config_writes_utf8_without_bom(tmp_path, monkeypatch):
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    local_dir = tmp_path / "prompts"
    _write_default_prompt_files(default_dir)

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", local_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", local_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", local_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", local_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")

    prompt_config.save_prompt_config(
        {
            "base_system_prompt": "첫 줄\n\n둘째 줄",
            "sub_prompt_body": "가\n나",
            "emotions": ["normal"],
            "emotion_guides": {"normal": "기본 상태"},
        }
    )

    saved_files = [
        local_dir / "base_system_prompt.md",
        local_dir / "sub_prompt_body.md",
        local_dir / "emotion_guides.md",
    ]
    assert all(not path.read_bytes().startswith(b"\xef\xbb\xbf") for path in saved_files)
    assert (local_dir / "base_system_prompt.md").read_text(encoding="utf-8-sig") == "첫 줄\n\n둘째 줄"
    assert not (local_dir / "analysis_system_appendix.md").exists()
