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
        "src/ai/http_llm_common.py",
        "src/ai/http_llm_openai.py",
        "src/ai/http_llm_custom_providers.py",
        "src/ai/http_llm_anthropic.py",
        "src/ai/http_llm_ollama.py",
        "src/ai/llm_client.py",
    ]

    for omitted_path in expected_omits:
        assert omitted_path in ci_config

    assert "coverage run --source=src --omit=" in ci_config
    assert "coverage report --show-missing --skip-empty --fail-under=80" in ci_config


def test_ci_coverage_steps_keep_linux_and_windows_commands_in_sync():
    root = Path(__file__).resolve().parents[1]
    ci_config = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8-sig")
    linux_step = _extract_ci_step(ci_config, "Run tests with coverage (Linux)")
    windows_step = _extract_ci_step(ci_config, "Run tests with coverage (Windows)")

    expected_fragments = [
        "coverage run --source=src --omit=",
        "coverage report --show-missing --skip-empty --fail-under=80",
        "src/core/app.py",
        "src/ai/http_llm_clients.py",
        "src/ai/http_llm_openai.py",
        "src/ai/http_llm_ollama.py",
    ]

    for fragment in expected_fragments:
        assert fragment in linux_step
        assert fragment in windows_step


def test_http_llm_clients_is_compatibility_facade():
    root = Path(__file__).resolve().parents[1]
    facade = root / "src" / "ai" / "http_llm_clients.py"
    facade_text = facade.read_text(encoding="utf-8-sig")

    assert len(facade_text.splitlines()) <= 90
    assert "from .http_llm_common import" in facade_text
    assert "from .http_llm_openai import" in facade_text
    assert "from .http_llm_custom_providers import" in facade_text
    assert "from .http_llm_anthropic import" in facade_text
    assert "from .http_llm_ollama import" in facade_text

    for module_name in [
        "http_llm_common.py",
        "http_llm_openai.py",
        "http_llm_custom_providers.py",
        "http_llm_anthropic.py",
        "http_llm_ollama.py",
    ]:
        assert (root / "src" / "ai" / module_name).exists()


def test_http_llm_clients_facade_preserves_legacy_helper_exports():
    from src.ai import http_llm_clients

    for name in [
        "build_runtime_system_prompt",
        "build_summary_prompt",
        "build_summary_prompt_from_text",
        "parse_summary_response",
        "parse_summary_memory_meta",
        "resolve_prompt_language",
        "get_available_emotions",
        "extract_analysis_block",
        "extract_legacy_japanese_tts_lines",
        "extract_tts_text",
        "is_japanese",
        "parse_analysis_lines",
        "parse_llm_response",
        "extract_goal_update_metadata",
        "extract_thought_metadata",
        "build_markdown_document_prompt",
        "prepend_message_time",
        "build_common_memory_context",
        "resolve_prompt_persona_names",
    ]:
        assert hasattr(http_llm_clients, name)


def test_prompt_and_command_helpers_live_in_focused_modules():
    root = Path(__file__).resolve().parents[1]
    summary_prompt_text = (root / "src" / "ai" / "summary_prompt.py").read_text(encoding="utf-8-sig")
    diary_service_text = (root / "src" / "ai" / "diary_service.py").read_text(encoding="utf-8-sig")

    assert (root / "src" / "ai" / "markdown_document_prompt.py").exists()
    assert (root / "src" / "ai" / "chat_commands.py").exists()
    assert "def build_markdown_document_prompt" not in summary_prompt_text
    assert "def parse_diary_command" not in diary_service_text
    assert "def parse_obs_command" not in diary_service_text
    assert "def parse_note_command" not in diary_service_text


def test_app_runtime_initializers_live_outside_app_module():
    root = Path(__file__).resolve().parents[1]
    app_text = (root / "src" / "core" / "app.py").read_text(encoding="utf-8-sig")

    assert "from src.ai.embedding import EmbeddingGenerator" not in app_text
    assert "from src.ai.memory import MemoryManager" not in app_text
    assert "from src.ai.user_profile import UserProfile" not in app_text
    assert "from src.ai.ene_profile import EneProfile" not in app_text
    assert "from src.ai.tts_client import create_tts_client" not in app_text
    assert "from src.core.audio_player import AudioPlayer" not in app_text
    assert (root / "src" / "core" / "app_memory_bootstrap.py").exists()
    assert (root / "src" / "core" / "app_tts_bootstrap.py").exists()


def test_main_configures_qt_webengine_gl_before_app_import():
    root = Path(__file__).resolve().parents[1]
    main_text = (root / "main.py").read_text(encoding="utf-8-sig")

    assert "AA_ShareOpenGLContexts" in main_text
    assert main_text.index("QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)") < main_text.index("from src.core.app import ENEApplication")
def _extract_ci_step(ci_config: str, step_name: str) -> str:
    start_marker = f"      - name: {step_name}"
    start = ci_config.index(start_marker)
    next_step = ci_config.find("\n      - name:", start + len(start_marker))
    if next_step == -1:
        return ci_config[start:]
    return ci_config[start:next_step]
