from pathlib import Path

from PyQt6.QtWidgets import QMessageBox


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")


def _sample_prompt_payload() -> dict:
    return {
        "base_system_prompt": "기본 베이스 프롬프트\n\n- 줄 단위 저장",
        "sub_prompt_body": "### [일본어 응답 규칙]\n- 일본어 번역을 붙이세요.",
        "emotions": ["normal", "smile"],
        "emotion_guides": {
            "normal": "기본 상태",
            "smile": "기분이 좋을 때",
        },
        "analysis_system_appendix": "### [분석 규칙]\n- 분석을 붙이세요.",
    }


def _write_prompt_markdown_files(directory: Path, payload: dict) -> None:
    _write_text(directory / "base_system_prompt.md", payload["base_system_prompt"])
    _write_text(directory / "sub_prompt_body.md", payload["sub_prompt_body"])
    _write_text(directory / "analysis_system_appendix.md", payload["analysis_system_appendix"])

    lines = ["### [감정 사용 가이드]"]
    for emotion in payload["emotions"]:
        lines.append(f"- {emotion}: {payload['emotion_guides'][emotion]}")
    _write_text(directory / "emotion_guides.md", "\n".join(lines) + "\n")


def test_load_prompt_config_creates_local_markdown_files_from_default(tmp_path, monkeypatch):
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    local_dir = tmp_path / "prompts"
    payload = _sample_prompt_payload()
    _write_prompt_markdown_files(default_dir, payload)

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", local_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", local_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", local_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", local_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", local_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH", default_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")

    loaded = prompt_config.load_prompt_config()

    assert loaded["base_system_prompt"] == payload["base_system_prompt"]
    assert loaded["sub_prompt_body"] == payload["sub_prompt_body"]
    assert loaded["analysis_system_appendix"] == payload["analysis_system_appendix"]
    assert loaded["emotions"] == payload["emotions"]
    assert loaded["emotion_guides"] == payload["emotion_guides"]
    assert (local_dir / "base_system_prompt.md").exists()
    assert (local_dir / "emotion_guides.md").exists()


def test_load_prompt_config_strips_generated_emotion_sections_in_both_languages(tmp_path, monkeypatch):
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    local_dir = tmp_path / "prompts"
    default_dir.mkdir(parents=True, exist_ok=True)

    _write_text(default_dir / "base_system_prompt.md", "베이스")
    _write_text(default_dir / "analysis_system_appendix.md", "부록")
    _write_text(
        default_dir / "emotion_guides.md",
        "### [감정 사용 가이드]\n- normal: 기본 상태\n- smile: 미소 지을 때\n",
    )
    _write_text(
        default_dir / "sub_prompt_body.md",
        "\n".join(
            [
                "### [Emotion Expression Rules]",
                "- Always add an emotion tag at the end of the response.",
                "- Format: `[emotion]`",
                "- Available emotions: ``",
                "",
                "### [Japanese Response Rules]",
                "- Keep this section.",
                "",
                "### [Emotion Usage Guide]",
                "- normal: Calm default state.",
            ]
        ),
    )

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", local_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", local_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", local_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", local_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", local_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH", default_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")

    loaded = prompt_config.load_prompt_config()

    assert loaded["sub_prompt_body"] == "### [Japanese Response Rules]\n- Keep this section."


def test_get_system_prompt_reads_from_markdown_files(tmp_path, monkeypatch):
    from src.ai import prompt as prompt_module
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    local_dir = tmp_path / "prompts"
    payload = _sample_prompt_payload()
    payload["base_system_prompt"] = "JSON이 아니라 MD 베이스"
    payload["sub_prompt_body"] = "### [응답 형식]\n- MD에서 읽은 규칙"
    payload["emotions"] = ["calm", "focus"]
    payload["emotion_guides"] = {
        "calm": "차분할 때",
        "focus": "집중할 때",
    }
    payload["analysis_system_appendix"] = "### [분석 부록]\n- MD 기반 부록"
    _write_prompt_markdown_files(default_dir, payload)

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", local_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", local_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", local_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", local_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", local_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH", default_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "get_runtime_emotions", lambda **kwargs: ["calm", "focus"])

    prompt_with_sub = prompt_module.get_system_prompt()
    prompt_without_sub = prompt_module.get_system_prompt(include_sub_prompt=False)
    runtime_prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
    )

    assert "MD 베이스" in prompt_with_sub
    assert "### [응답 형식]" in prompt_with_sub
    assert "### [감정 표현 규칙]" in prompt_with_sub
    assert "calm, focus" in prompt_with_sub
    assert "차분할 때" in prompt_with_sub
    assert prompt_without_sub == "JSON이 아니라 MD 베이스"
    assert "### [분석 부록]" in runtime_prompt
    assert prompt_module.get_available_emotions() == ["calm", "focus"]


def test_runtime_prompt_uses_model_emotions_instead_of_saved_emotion_list(tmp_path, monkeypatch):
    from src.ai import prompt as prompt_module
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    local_dir = tmp_path / "prompts"
    payload = _sample_prompt_payload()
    payload["sub_prompt_body"] = "### [응답 형식]\n- 모델 기준 감정을 사용하세요."
    payload["emotions"] = ["obsolete", "joy"]
    payload["emotion_guides"] = {
        "obsolete": "더 이상 없는 감정",
        "joy": "기쁠 때",
    }
    _write_prompt_markdown_files(default_dir, payload)

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", local_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", local_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", local_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", local_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", local_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH", default_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "get_runtime_emotions", lambda **kwargs: ["normal", "joy"])

    prompt_with_sub = prompt_module.get_system_prompt()

    assert prompt_module.get_available_emotions() == ["normal", "joy"]
    assert "normal, joy" in prompt_with_sub
    assert "obsolete" not in prompt_with_sub


def test_settings_dialog_saves_prompt_configuration_to_markdown_files(tmp_path, monkeypatch):
    from src.ai import prompt_config
    from src.ui.settings_dialog import SettingsDialog

    default_dir = tmp_path / "prompts" / "defaults"
    local_dir = tmp_path / "prompts"
    _write_prompt_markdown_files(default_dir, _sample_prompt_payload())

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", local_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", local_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", local_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", local_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", local_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH", default_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: QMessageBox.StandardButton.Ok)

    class DummyTextEdit:
        def __init__(self, text: str = ""):
            self._text = text

        def setPlainText(self, text: str) -> None:
            self._text = text

        def toPlainText(self) -> str:
            return self._text

    class DummyLabel:
        def __init__(self):
            self.text = ""

        def setText(self, text: str) -> None:
            self.text = text

    dialog = type("DummyDialog", (), {})()
    dialog.base_prompt_editor = DummyTextEdit()
    dialog.sub_prompt_editor = DummyTextEdit()
    dialog._prompt_status_label = DummyLabel()
    dialog._sync_emotion_combo_options = lambda: None
    dialog.base_prompt_editor.setPlainText("새 베이스 프롬프트")
    dialog.sub_prompt_editor.setPlainText("### [응답 형식]\n- 저장 테스트")
    dialog._emotion_items = [
        {"name": "calm", "guide": "차분할 때"},
        {"name": "spark", "guide": "아이디어가 번뜩일 때"},
    ]

    SettingsDialog._save_prompt_configuration(dialog)

    assert (local_dir / "base_system_prompt.md").read_text(encoding="utf-8-sig") == "새 베이스 프롬프트"
    assert (local_dir / "sub_prompt_body.md").read_text(encoding="utf-8-sig") == "### [응답 형식]\n- 저장 테스트"
    emotion_guides_text = (local_dir / "emotion_guides.md").read_text(encoding="utf-8-sig")
    assert "- spark: 아이디어가 번뜩일 때" in emotion_guides_text


def test_save_prompt_config_writes_readable_markdown_files(tmp_path, monkeypatch):
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    local_dir = tmp_path / "prompts"
    _write_prompt_markdown_files(default_dir, _sample_prompt_payload())

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", local_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", local_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", local_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", local_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", local_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH", default_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")

    prompt_config.save_prompt_config(
        {
            "base_system_prompt": "첫 줄\n\n둘째 줄",
            "sub_prompt_body": "가\n나",
            "analysis_system_appendix": "부록 한 줄",
            "emotions": ["normal"],
            "emotion_guides": {"normal": "기본 상태"},
        }
    )

    assert (local_dir / "base_system_prompt.md").read_text(encoding="utf-8-sig") == "첫 줄\n\n둘째 줄"
    assert (local_dir / "sub_prompt_body.md").read_text(encoding="utf-8-sig") == "가\n나"
    assert (local_dir / "analysis_system_appendix.md").read_text(encoding="utf-8-sig") == "부록 한 줄"
