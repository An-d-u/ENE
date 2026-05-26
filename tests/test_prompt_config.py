import shutil
from pathlib import Path

from PyQt6.QtWidgets import QMessageBox


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8-sig")


def _sample_prompt_payload() -> dict:
    return {
        "base_system_prompt": "기본 베이스 프롬프트\n\n- 줄 단위 저장",
        "sub_prompt_body": "### [일본어 표기 규칙]\n- 일본어/한자 표기는 자연스럽게 유지하세요.",
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
                "### [Japanese Notation Rules]",
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

    assert loaded["sub_prompt_body"] == "### [일본어 표기 규칙]\n- Keep this section."


def test_parse_emotion_guides_accepts_backtick_wrapped_names():
    from src.ai import prompt_config

    emotions, guides = prompt_config._parse_emotion_guides(
        "\n".join(
            [
                "### [Emotion Usage Guide]",
                "- `normal`: default state",
                "- `smile`: when in a good mood",
            ]
        )
    )

    assert emotions == ["normal", "smile"]
    assert guides == {
        "normal": "default state",
        "smile": "when in a good mood",
    }


def test_default_prompt_templates_keep_output_format_in_runtime_contract(tmp_path, monkeypatch):
    from src.ai import prompt as prompt_module
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    local_dir = tmp_path / "prompts"
    default_dir.mkdir(parents=True, exist_ok=True)

    shutil.copyfile(prompt_config.DEFAULT_BASE_SYSTEM_PROMPT_PATH, default_dir / "base_system_prompt.md")
    shutil.copyfile(prompt_config.DEFAULT_SUB_PROMPT_BODY_PATH, default_dir / "sub_prompt_body.md")
    shutil.copyfile(
        prompt_config.DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH,
        default_dir / "analysis_system_appendix.md",
    )
    shutil.copyfile(prompt_config.DEFAULT_EMOTION_GUIDES_PATH, default_dir / "emotion_guides.md")

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", local_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", local_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", local_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", local_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", local_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(
        prompt_config,
        "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH",
        default_dir / "analysis_system_appendix.md",
    )
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "get_runtime_emotions", lambda **kwargs: ["normal", "smile"])

    prompt_with_sub = prompt_module.get_system_prompt()

    assert "[감정 표현 규칙]" in prompt_with_sub
    assert "Response Style Rules" in prompt_with_sub
    assert "[Japanese Response Rules]" not in prompt_with_sub
    assert "[Japanese Notation Rules]" not in prompt_with_sub
    assert "[Final Output Format]" not in prompt_with_sub
    assert "Japanese translation" not in prompt_with_sub
    assert "normal, smile" in prompt_with_sub


def test_default_sub_prompt_body_does_not_embed_thought_rules():
    from src.ai import prompt_config

    default_body = prompt_config.DEFAULT_SUB_PROMPT_BODY_PATH.read_text(encoding="utf-8-sig")

    assert "Japanese translation" not in default_body
    assert "Final Output Format" not in default_body
    assert "Original response [emotion]" not in default_body
    assert "[subconscious]" not in default_body
    assert "[/subconscious]" not in default_body
    assert "[ene_thought]" not in default_body
    assert "[/ene_thought]" not in default_body
    assert "[thought]" not in default_body
    assert "[/thought]" not in default_body
    assert "생각 출력 규칙" not in default_body


def test_runtime_prompt_adds_korean_response_contract_from_code_when_enabled(tmp_path, monkeypatch):
    from src.ai import prompt as prompt_module
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
    monkeypatch.setattr(prompt_config, "get_runtime_emotions", lambda **kwargs: ["normal", "smile"])

    runtime_prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
        settings_source={"ui_language": "ko", "enable_ene_goals": True, "enable_ene_thoughts": True},
    )

    assert "### [최종 응답 형식]" in runtime_prompt
    assert "[ene_goal_update]" in runtime_prompt
    assert "action=none" in runtime_prompt
    assert "short_term" in runtime_prompt
    assert "long_term" in runtime_prompt
    assert "[subconscious]" in runtime_prompt
    assert "[/subconscious]" in runtime_prompt
    assert "[ene_thought]" not in runtime_prompt
    assert "[/ene_thought]" not in runtime_prompt
    assert "[thought]" not in runtime_prompt
    assert "[/thought]" not in runtime_prompt
    assert "단계별 추론" in runtime_prompt
    assert "[proactive_conversation]" in runtime_prompt
    assert "[/subconscious]\n한국어 답변 [emotion]\n[tts]\n일본어 TTS 문장\n[/tts]" in runtime_prompt
    assert "본문을 subconscious 블록 안에 넣지 마세요" in runtime_prompt
    assert runtime_prompt.index("### [분석 규칙]") < runtime_prompt.index("### [최종 응답 형식]")


def test_runtime_prompt_omits_optional_response_contract_sections_when_settings_are_disabled(tmp_path, monkeypatch):
    from src.ai import prompt as prompt_module
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
    monkeypatch.setattr(prompt_config, "get_runtime_emotions", lambda **kwargs: ["normal", "smile"])

    runtime_prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
        settings_source={"ui_language": "ko", "enable_ene_goals": False, "enable_ene_thoughts": False},
    )

    assert "### [최종 응답 형식]" in runtime_prompt
    assert "[analysis]" in runtime_prompt
    assert "[ene_goal_update]" not in runtime_prompt
    assert "[subconscious]" not in runtime_prompt
    assert "[/subconscious]" not in runtime_prompt
    assert "[ene_thought]" not in runtime_prompt
    assert "[/ene_thought]" not in runtime_prompt
    assert "[thought]" not in runtime_prompt
    assert "[/thought]" not in runtime_prompt
    assert "한국어 답변 [emotion]\n[tts]\n일본어 TTS 문장\n[/tts]" in runtime_prompt


def test_runtime_thought_rules_are_localized(tmp_path, monkeypatch):
    from src.ai import prompt as prompt_module
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
    monkeypatch.setattr(prompt_config, "get_runtime_emotions", lambda **kwargs: ["normal", "smile"])

    english_prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
        settings_source={"ui_language": "en", "enable_ene_thoughts": True},
    )
    japanese_prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
        settings_source={"ui_language": "ja", "enable_ene_thoughts": True},
    )

    assert "### [Final Response Format]" in english_prompt
    assert "[subconscious]" in english_prompt
    assert "English reply [emotion]" in english_prompt
    assert "Japanese TTS text" in english_prompt
    assert "Korean reply [emotion]" not in english_prompt
    assert "step-by-step reasoning" in english_prompt
    assert "subconscious block in the same language as the visible reply" in english_prompt
    assert "do not mix it into the TTS block" in english_prompt
    assert "only in Korean" not in english_prompt
    assert "Japanese reply" not in english_prompt
    assert "### [最終応答形式]" in japanese_prompt
    assert "[subconscious]" in japanese_prompt
    assert "日本語返答 [emotion]" in japanese_prompt
    assert "韓国語返答 [emotion]" not in japanese_prompt
    assert "段階的な推論" in japanese_prompt
    assert "表示される返答と同じ言語" in japanese_prompt
    assert "TTSブロックには混ぜないでください" in japanese_prompt
    assert "韓国語だけ" not in japanese_prompt


def test_runtime_prompt_omits_tts_block_when_tts_language_matches_response_language(tmp_path, monkeypatch):
    from src.ai import prompt as prompt_module
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
    monkeypatch.setattr(prompt_config, "get_runtime_emotions", lambda **kwargs: ["normal", "smile"])

    runtime_prompt = prompt_module.build_runtime_system_prompt(
        include_sub_prompt=True,
        include_analysis_appendix=True,
        settings_source={"ui_language": "ja", "tts_language": "ja", "enable_ene_thoughts": False},
    )

    assert "日本語返答 [emotion]" in runtime_prompt
    assert "[tts]" not in runtime_prompt
    assert "[/tts]" not in runtime_prompt


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


def test_analysis_appendix_includes_conversation_promise_rules():
    from src.ai import prompt_config

    prompt_config.ensure_prompt_config_exists()
    repo_appendix = prompt_config.ANALYSIS_SYSTEM_APPENDIX_PATH.read_text(encoding="utf-8-sig")
    default_appendix = prompt_config.DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH.read_text(encoding="utf-8-sig")

    for appendix in (repo_appendix, default_appendix):
        assert "[약속:" in appendix
        assert ("상대 시간" in appendix) or ("relative time" in appendix)
        assert ("절대 시간" in appendix) or ("absolute time" in appendix)
        assert ("감정 태그보다 먼저" in appendix) or ("before the emotion tag" in appendix)
        assert ("assistant" in appendix) or ("에네가 응답에서 구체적인 시간을 새로 제안" in appendix)
        assert ("문장 일부를 그대로 복사하지 말고" in appendix) or ("Do not copy a long sentence fragment" in appendix)
    assert "plain mention of the current time" in default_appendix


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


def test_settings_dialog_tabs_use_external_builders(monkeypatch):
    from src.ui.settings_dialog import SettingsDialog
    from src.ui.settings_tabs import (
        behavior_tab,
        ene_profile_tab,
        llm_tab,
        memory_tab,
        model_tab,
        prompt_tab,
        theme_tab,
        tts_tab,
        user_profile_tab,
        window_tab,
    )

    builder_cases = [
        (window_tab, "build_window_tab", SettingsDialog._create_window_tab),
        (theme_tab, "build_theme_tab", SettingsDialog._create_theme_tab),
        (model_tab, "build_model_tab", SettingsDialog._create_model_tab),
        (llm_tab, "build_llm_tab", SettingsDialog._create_llm_tab),
        (tts_tab, "build_tts_tab", SettingsDialog._create_tts_tab),
        (behavior_tab, "build_behavior_tab", SettingsDialog._create_behavior_tab),
        (memory_tab, "build_memory_tab", SettingsDialog._create_memory_tab),
        (user_profile_tab, "build_user_profile_tab", SettingsDialog._create_user_profile_tab),
        (ene_profile_tab, "build_ene_profile_tab", SettingsDialog._create_ene_profile_tab),
        (prompt_tab, "build_prompt_tab", SettingsDialog._create_prompt_tab),
    ]

    dialog = object()

    for module, builder_name, method in builder_cases:
        sentinel = object()
        calls = []

        def fake_builder(received_dialog, *, _sentinel=sentinel, _calls=calls):
            _calls.append(received_dialog)
            return _sentinel

        monkeypatch.setattr(module, builder_name, fake_builder)

        result = method(dialog)

        assert result is sentinel
        assert calls == [dialog]


def test_settings_dialog_uses_extracted_widget_module():
    root = Path(__file__).resolve().parents[1]
    dialog_source = (root / "src" / "ui" / "settings_dialog.py").read_text(encoding="utf-8-sig")
    widget_source = (root / "src" / "ui" / "settings_dialog_widgets.py").read_text(encoding="utf-8-sig")

    assert "from .settings_dialog_widgets import (" in dialog_source
    for symbol in (
        "ClickableFrame",
        "ToggleSwitch",
        "ColorPlaneWidget",
        "HueSliderWidget",
        "ThemeColorPickerPopup",
        "apply_soft_shadow",
    ):
        assert f"class {symbol}" not in dialog_source
        assert symbol in widget_source


def test_settings_dialog_uses_extracted_theme_mixin():
    root = Path(__file__).resolve().parents[1]
    dialog_source = (root / "src" / "ui" / "settings_dialog.py").read_text(encoding="utf-8-sig")
    theme_source = (root / "src" / "ui" / "settings_dialog_theme.py").read_text(encoding="utf-8-sig")

    assert "from .settings_dialog_theme import SettingsDialogThemeMixin" in dialog_source
    settings_dialog_bases = dialog_source.split("class SettingsDialog(", 1)[1].split("):", 1)[0]
    assert "SettingsDialogThemeMixin" in settings_dialog_bases
    for method_name in (
        "_apply_theme_mode",
        "_build_theme_color_editor",
        "_build_theme_mode_preview",
        "_build_theme_variant_preview",
        "_refresh_theme_editor_state",
        "_flush_theme_live_update",
    ):
        assert f"def {method_name}" not in dialog_source
        assert f"def {method_name}" in theme_source


def test_settings_dialog_uses_extracted_prompt_mixin():
    root = Path(__file__).resolve().parents[1]
    dialog_source = (root / "src" / "ui" / "settings_dialog.py").read_text(encoding="utf-8-sig")
    prompt_source = (root / "src" / "ui" / "settings_dialog_prompt.py").read_text(encoding="utf-8-sig")

    assert "from .settings_dialog_prompt import SettingsDialogPromptMixin" in dialog_source
    assert "SettingsDialogPromptMixin" in dialog_source.split("class SettingsDialog(", 1)[1].split("):", 1)[0]
    for method_name in (
        "_count_prompt_tokens",
        "_refresh_prompt_token_counts",
        "_split_sub_prompt_content",
        "_build_sub_prompt_text",
        "_load_prompt_configuration",
        "_save_prompt_configuration",
    ):
        assert f"def {method_name}" not in dialog_source
        assert f"def {method_name}" in prompt_source


def test_settings_dialog_uses_extracted_tts_mixin():
    root = Path(__file__).resolve().parents[1]
    dialog_source = (root / "src" / "ui" / "settings_dialog.py").read_text(encoding="utf-8-sig")
    tts_source = (root / "src" / "ui" / "settings_dialog_tts.py").read_text(encoding="utf-8-sig")

    assert "from .settings_dialog_tts import SettingsDialogTtsMixin" in dialog_source
    assert "SettingsDialogTtsMixin" in dialog_source.split("class SettingsDialog(", 1)[1].split("):", 1)[0]
    for method_name in (
        "_browse_tts_audio_path_into",
        "_build_tts_output_device_items",
        "_refresh_tts_output_devices",
        "_request_browser_tts_voices",
        "_collect_tts_provider_configs",
        "_load_tts_values",
    ):
        assert f"def {method_name}" not in dialog_source
        assert f"def {method_name}" in tts_source


def test_settings_dialog_uses_remaining_extracted_mixins():
    root = Path(__file__).resolve().parents[1]
    dialog_source = (root / "src" / "ui" / "settings_dialog.py").read_text(encoding="utf-8-sig")
    mixin_cases = [
        (
            "settings_dialog_ui.py",
            "SettingsDialogUiMixin",
            (
                "_setup_ui",
                "_apply_stylesheet",
                "_add_section",
                "_ensure_lazy_tab_loaded",
                "_build_secret_row",
            ),
        ),
        (
            "settings_dialog_profile.py",
            "SettingsDialogProfileMixin",
            (
                "_refresh_basic_info_list",
                "_load_user_profile_data",
                "_save_user_profile_data",
            ),
        ),
        (
            "settings_dialog_goals.py",
            "SettingsDialogGoalsMixin",
            (
                "_create_ene_goals_group",
                "_connect_goal_bridge",
                "_render_goal_items",
                "_on_goal_add_clicked",
            ),
        ),
        (
            "settings_dialog_hotkeys.py",
            "SettingsDialogHotkeyMixin",
            (
                "_qt_key_to_hotkey_token",
                "_build_hotkey_from_event",
                "_start_ptt_hotkey_capture",
            ),
        ),
        (
            "settings_dialog_values.py",
            "SettingsDialogValuesMixin",
            (
                "_load_values",
                "_get_current_values",
                "_preview_settings",
                "_save_settings",
                "_cancel_settings",
            ),
        ),
    ]

    settings_dialog_bases = dialog_source.split("class SettingsDialog(", 1)[1].split("):", 1)[0]
    for filename, mixin_name, method_names in mixin_cases:
        mixin_source = (root / "src" / "ui" / filename).read_text(encoding="utf-8-sig")
        assert f"from .{filename.removesuffix('.py')} import {mixin_name}" in dialog_source
        assert mixin_name in settings_dialog_bases
        for method_name in method_names:
            assert f"def {method_name}" not in dialog_source
            assert f"def {method_name}" in mixin_source


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


def test_load_prompt_config_prefers_visible_roaming_prompts_under_store_python(tmp_path, monkeypatch):
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    runtime_dir = tmp_path / "virtualized" / "prompts"
    visible_dir = tmp_path / "visible" / "prompts"

    default_payload = _sample_prompt_payload()
    visible_payload = _sample_prompt_payload()
    visible_payload["base_system_prompt"] = "실제 Roaming 프롬프트"
    visible_payload["sub_prompt_body"] = "### [응답 형식]\n- 실제 Roaming 규칙"
    visible_payload["analysis_system_appendix"] = "### [분석 규칙]\n- 실제 Roaming 부록"
    visible_payload["emotion_guides"] = {
        "normal": "실제 기본 상태",
        "smile": "실제 미소 상태",
    }

    _write_prompt_markdown_files(default_dir, default_payload)
    _write_prompt_markdown_files(visible_dir, visible_payload)

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", runtime_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", runtime_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", runtime_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", runtime_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", runtime_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH", default_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "_is_windows_store_python_runtime", lambda: True, raising=False)
    monkeypatch.setattr(prompt_config, "_should_sync_store_python_prompt_dirs", lambda: True, raising=False)
    monkeypatch.setattr(prompt_config, "_get_visible_prompt_config_dir", lambda: visible_dir, raising=False)

    loaded = prompt_config.load_prompt_config()

    assert loaded["base_system_prompt"] == "실제 Roaming 프롬프트"
    assert loaded["sub_prompt_body"] == "### [응답 형식]\n- 실제 Roaming 규칙"
    assert loaded["analysis_system_appendix"] == "### [분석 규칙]\n- 실제 Roaming 부록"
    assert loaded["emotion_guides"] == visible_payload["emotion_guides"]


def test_save_prompt_config_mirrors_visible_roaming_prompts_under_store_python(tmp_path, monkeypatch):
    from src.ai import prompt_config

    default_dir = tmp_path / "prompts" / "defaults"
    runtime_dir = tmp_path / "virtualized" / "prompts"
    visible_dir = tmp_path / "visible" / "prompts"

    _write_prompt_markdown_files(default_dir, _sample_prompt_payload())

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", runtime_dir)
    monkeypatch.setattr(prompt_config, "DEFAULT_PROMPT_CONFIG_DIR", default_dir)
    monkeypatch.setattr(prompt_config, "BASE_SYSTEM_PROMPT_PATH", runtime_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "SUB_PROMPT_BODY_PATH", runtime_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "ANALYSIS_SYSTEM_APPENDIX_PATH", runtime_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "EMOTION_GUIDES_PATH", runtime_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_BASE_SYSTEM_PROMPT_PATH", default_dir / "base_system_prompt.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_SUB_PROMPT_BODY_PATH", default_dir / "sub_prompt_body.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH", default_dir / "analysis_system_appendix.md")
    monkeypatch.setattr(prompt_config, "DEFAULT_EMOTION_GUIDES_PATH", default_dir / "emotion_guides.md")
    monkeypatch.setattr(prompt_config, "_is_windows_store_python_runtime", lambda: True, raising=False)
    monkeypatch.setattr(prompt_config, "_should_sync_store_python_prompt_dirs", lambda: True, raising=False)
    monkeypatch.setattr(prompt_config, "_get_visible_prompt_config_dir", lambda: visible_dir, raising=False)

    prompt_config.save_prompt_config(
        {
            "base_system_prompt": "실제 Roaming으로도 나가야 하는 베이스",
            "sub_prompt_body": "### [응답 형식]\n- 저장 후 동기화",
            "analysis_system_appendix": "### [분석 규칙]\n- 저장 후 동기화",
            "emotions": ["normal"],
            "emotion_guides": {"normal": "실제 Roaming 동기화"},
        }
    )

    assert (visible_dir / "base_system_prompt.md").read_text(encoding="utf-8-sig") == "실제 Roaming으로도 나가야 하는 베이스"
    assert (visible_dir / "sub_prompt_body.md").read_text(encoding="utf-8-sig") == "### [응답 형식]\n- 저장 후 동기화"
    assert (visible_dir / "analysis_system_appendix.md").read_text(encoding="utf-8-sig") == "### [분석 규칙]\n- 저장 후 동기화"
    assert "실제 Roaming 동기화" in (visible_dir / "emotion_guides.md").read_text(encoding="utf-8-sig")


def test_store_python_sync_uses_visible_to_runtime_bridge_when_strings_match(monkeypatch):
    from src.ai import prompt_config

    same_dir = Path(r"C:\Users\umpad\AppData\Roaming\ENE\prompts")
    calls: list[tuple[Path, Path]] = []

    monkeypatch.setattr(prompt_config, "PROMPT_CONFIG_DIR", same_dir)
    monkeypatch.setattr(prompt_config, "_should_sync_store_python_prompt_dirs", lambda: True, raising=False)
    monkeypatch.setattr(prompt_config, "_get_visible_prompt_config_dir", lambda: same_dir, raising=False)
    monkeypatch.setattr(
        prompt_config,
        "_copy_prompt_files_from_visible_to_runtime_via_powershell",
        lambda source, target: calls.append((Path(source), Path(target))),
        raising=False,
    )

    prompt_config._sync_visible_roaming_prompt_files_to_runtime()

    assert calls == [(same_dir, same_dir)]
