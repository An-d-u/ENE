"""
ENE 프롬프트 설정 Markdown 로더
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from ..core.model_emotions import get_available_model_emotions
from ..core.app_paths import get_bundle_prompts_defaults_dir, get_bundle_root, get_user_prompts_dir


PROJECT_ROOT = get_bundle_root()
PROMPT_CONFIG_DIR = get_user_prompts_dir()
DEFAULT_PROMPT_CONFIG_DIR = get_bundle_prompts_defaults_dir()

BASE_SYSTEM_PROMPT_PATH = PROMPT_CONFIG_DIR / "base_system_prompt.md"
SUB_PROMPT_BODY_PATH = PROMPT_CONFIG_DIR / "sub_prompt_body.md"
ANALYSIS_SYSTEM_APPENDIX_PATH = PROMPT_CONFIG_DIR / "analysis_system_appendix.md"
EMOTION_GUIDES_PATH = PROMPT_CONFIG_DIR / "emotion_guides.md"

DEFAULT_BASE_SYSTEM_PROMPT_PATH = DEFAULT_PROMPT_CONFIG_DIR / "base_system_prompt.md"
DEFAULT_SUB_PROMPT_BODY_PATH = DEFAULT_PROMPT_CONFIG_DIR / "sub_prompt_body.md"
DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH = DEFAULT_PROMPT_CONFIG_DIR / "analysis_system_appendix.md"
DEFAULT_EMOTION_GUIDES_PATH = DEFAULT_PROMPT_CONFIG_DIR / "emotion_guides.md"

PROMPT_MARKDOWN_FILENAMES = (
    "base_system_prompt.md",
    "sub_prompt_body.md",
    "analysis_system_appendix.md",
    "emotion_guides.md",
)

GENERATED_SUB_PROMPT_SECTION_TITLES = {
    "감정 표현 규칙",
    "Emotion Expression Rules",
    "감정 사용 가이드",
    "Emotion Usage Guide",
}

SUB_PROMPT_SECTION_TITLE_ALIASES = {
    "Emotion Expression Rules": "감정 표현 규칙",
    "Japanese Response Rules": "일본어 응답 규칙",
    "Response Format Examples": "응답 형식 예시",
    "Emotion Usage Guide": "감정 사용 가이드",
}


def _normalize_emotion_name(text: str) -> str:
    normalized = str(text or "").strip()
    if normalized.startswith("`") and normalized.endswith("`") and len(normalized) >= 2:
        normalized = normalized[1:-1].strip()
    return normalized.lower()


def _read_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8-sig").strip("\n")


def _write_text_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = str(text or "").replace("\r\n", "\n").strip("\n")
    path.write_text(normalized, encoding="utf-8-sig")


def _strip_generated_sub_prompt_sections(text: str) -> str:
    content = str(text or "").strip()
    if not content:
        return ""

    pattern = re.compile(r"^### \[(.+?)\]\s*$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return content

    remaining_sections: list[str] = []
    preamble = content[: matches[0].start()].strip()
    if preamble:
        remaining_sections.append(preamble)

    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        section_text = content[start:end].strip()
        if title in GENERATED_SUB_PROMPT_SECTION_TITLES:
            continue
        remaining_sections.append(section_text)

    return "\n\n".join(remaining_sections).strip()


def _localize_sub_prompt_section_titles(text: str) -> str:
    content = str(text or "").strip()
    if not content:
        return ""

    for source, target in SUB_PROMPT_SECTION_TITLE_ALIASES.items():
        content = content.replace(f"### [{source}]", f"### [{target}]")
    return content


def _parse_emotion_guides(text: str) -> tuple[list[str], dict[str, str]]:
    content = str(text or "").strip()
    if not content:
        return ["normal"], {"normal": "기본 상태"}

    emotions: list[str] = []
    guides: dict[str, str] = {}
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        name, separator, guide = stripped[2:].partition(":")
        emotion = _normalize_emotion_name(name)
        if not separator or not emotion:
            continue
        if emotion not in guides:
            emotions.append(emotion)
        guides[emotion] = guide.strip()

    if not emotions:
        return ["normal"], {"normal": "기본 상태"}
    return emotions, guides


def _serialize_emotion_guides(emotions: list[str], emotion_guides: dict[str, str]) -> str:
    lines = ["### [감정 사용 가이드]"]
    for emotion in emotions:
        guide = str(emotion_guides.get(emotion, "") or "").strip()
        if not guide:
            guide = "이 감정을 어떤 상황에서 쓰는지 설명하세요."
        lines.append(f"- {emotion}: {guide}")
    return "\n".join(lines)


def _copy_default_if_missing(target: Path, default: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    if default.exists():
        shutil.copyfile(default, target)
    else:
        target.write_text("", encoding="utf-8-sig")


def _is_windows_store_python_runtime() -> bool:
    executable = str(getattr(sys, "executable", "") or "").lower()
    return os.name == "nt" and "\\windowsapps\\pythonsoftwarefoundation.python." in executable


def _get_visible_prompt_config_dir() -> Path:
    return Path.home() / "AppData" / "Roaming" / "ENE" / "prompts"


def _should_sync_store_python_prompt_dirs() -> bool:
    if not _is_windows_store_python_runtime():
        return False
    try:
        return Path(PROMPT_CONFIG_DIR).resolve() == get_user_prompts_dir().resolve()
    except Exception:
        return False


def _copy_prompt_files_locally(source_dir: Path, target_dir: Path) -> None:
    source = Path(source_dir)
    target = Path(target_dir)
    if not source.exists():
        return

    target.mkdir(parents=True, exist_ok=True)
    for filename in PROMPT_MARKDOWN_FILENAMES:
        source_file = source / filename
        if not source_file.exists():
            continue
        shutil.copyfile(source_file, target / filename)


def _run_powershell_command(command: str) -> subprocess.CompletedProcess[str]:
    command = "\n".join(
        [command]
    )
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        check=True,
        capture_output=True,
        text=True,
    )


def _read_prompt_file_via_powershell(path: Path) -> bytes | None:
    file_text = str(path).replace("'", "''")
    result = _run_powershell_command(
        "\n".join(
            [
                f"$path = '{file_text}'",
                "if (-not (Test-Path -LiteralPath $path)) { exit 0 }",
                "[Console]::Write([Convert]::ToBase64String([IO.File]::ReadAllBytes($path)))",
            ]
        )
    )
    payload = str(result.stdout or "").strip()
    if not payload:
        return None
    return base64.b64decode(payload)


def _write_prompt_file_via_powershell(path: Path, payload: bytes) -> None:
    file_text = str(path).replace("'", "''")
    encoded = base64.b64encode(payload).decode("ascii")
    _run_powershell_command(
        "\n".join(
            [
                f"$path = '{file_text}'",
                f"$payload = '{encoded}'",
                "$parent = Split-Path -Parent $path",
                "New-Item -ItemType Directory -Path $parent -Force | Out-Null",
                "[IO.File]::WriteAllBytes($path, [Convert]::FromBase64String($payload))",
            ]
        )
    )


def _copy_prompt_files_from_visible_to_runtime_via_powershell(source_dir: Path, target_dir: Path) -> None:
    source = Path(source_dir)
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    for filename in PROMPT_MARKDOWN_FILENAMES:
        payload = _read_prompt_file_via_powershell(source / filename)
        if payload is None:
            continue
        (target / filename).write_bytes(payload)


def _copy_prompt_files_from_runtime_to_visible_via_powershell(source_dir: Path, target_dir: Path) -> None:
    source = Path(source_dir)
    target = Path(target_dir)
    for filename in PROMPT_MARKDOWN_FILENAMES:
        source_file = source / filename
        if not source_file.exists():
            continue
        _write_prompt_file_via_powershell(target / filename, source_file.read_bytes())


def _sync_visible_roaming_prompt_files_to_runtime() -> None:
    if not _should_sync_store_python_prompt_dirs():
        return
    try:
        visible_dir = _get_visible_prompt_config_dir()
        runtime_dir = Path(PROMPT_CONFIG_DIR)
        if visible_dir == runtime_dir:
            _copy_prompt_files_from_visible_to_runtime_via_powershell(visible_dir, runtime_dir)
            return
        _copy_prompt_files_locally(visible_dir, runtime_dir)
    except Exception:
        pass


def _sync_runtime_prompt_files_to_visible_roaming() -> None:
    if not _should_sync_store_python_prompt_dirs():
        return
    try:
        runtime_dir = Path(PROMPT_CONFIG_DIR)
        visible_dir = _get_visible_prompt_config_dir()
        if visible_dir == runtime_dir:
            _copy_prompt_files_from_runtime_to_visible_via_powershell(runtime_dir, visible_dir)
            return
        _copy_prompt_files_locally(runtime_dir, visible_dir)
    except Exception:
        pass


def ensure_prompt_config_exists() -> Path:
    _sync_visible_roaming_prompt_files_to_runtime()
    _copy_default_if_missing(BASE_SYSTEM_PROMPT_PATH, DEFAULT_BASE_SYSTEM_PROMPT_PATH)
    _copy_default_if_missing(SUB_PROMPT_BODY_PATH, DEFAULT_SUB_PROMPT_BODY_PATH)
    _copy_default_if_missing(ANALYSIS_SYSTEM_APPENDIX_PATH, DEFAULT_ANALYSIS_SYSTEM_APPENDIX_PATH)
    _copy_default_if_missing(EMOTION_GUIDES_PATH, DEFAULT_EMOTION_GUIDES_PATH)
    return PROMPT_CONFIG_DIR


def load_prompt_config() -> dict:
    ensure_prompt_config_exists()
    emotions, emotion_guides = _parse_emotion_guides(_read_text_file(EMOTION_GUIDES_PATH))
    return {
        "base_system_prompt": _read_text_file(BASE_SYSTEM_PROMPT_PATH),
        "sub_prompt_body": _localize_sub_prompt_section_titles(
            _strip_generated_sub_prompt_sections(_read_text_file(SUB_PROMPT_BODY_PATH))
        ),
        "emotions": emotions,
        "emotion_guides": emotion_guides,
        "analysis_system_appendix": _read_text_file(ANALYSIS_SYSTEM_APPENDIX_PATH),
    }


def get_runtime_emotions(
    settings_source: dict | None = None,
    base_path: Path | None = None,
) -> list[str]:
    """현재 모델 기준 실제 사용 가능한 감정 목록을 반환한다."""
    config = load_prompt_config()
    return get_available_model_emotions(
        settings_source=settings_source,
        base_path=base_path,
        fallback_emotions=list(config.get("emotions", [])),
    )


def load_runtime_prompt_config(
    settings_source: dict | None = None,
    base_path: Path | None = None,
) -> dict:
    """실행 시점에 사용할 프롬프트 설정을 반환한다."""
    config = load_prompt_config()
    runtime_emotions = get_runtime_emotions(settings_source=settings_source, base_path=base_path)
    saved_guides = dict(config.get("emotion_guides", {}))
    runtime_guides: dict[str, str] = {}
    for emotion in runtime_emotions:
        guide = str(saved_guides.get(emotion, "") or "").strip()
        if not guide and emotion == "normal":
            guide = "기본 상태"
        runtime_guides[emotion] = guide

    return {
        "base_system_prompt": config.get("base_system_prompt", ""),
        "sub_prompt_body": config.get("sub_prompt_body", ""),
        "emotions": runtime_emotions,
        "emotion_guides": runtime_guides,
        "analysis_system_appendix": config.get("analysis_system_appendix", ""),
    }


def save_prompt_config(config: dict) -> dict:
    existing = load_prompt_config()
    merged = dict(existing)
    if isinstance(config, dict):
        merged.update(config)

    emotions_input = merged.get("emotions", [])
    emotions: list[str] = []
    seen: set[str] = set()
    if isinstance(emotions_input, list):
        for item in emotions_input:
            emotion = _normalize_emotion_name(item)
            if emotion and emotion not in seen:
                seen.add(emotion)
                emotions.append(emotion)
    if not emotions:
        emotions = ["normal"]

    guides_input = merged.get("emotion_guides", {})
    emotion_guides: dict[str, str] = {}
    if isinstance(guides_input, dict):
        for emotion in emotions:
            emotion_guides[emotion] = str(guides_input.get(emotion, "") or "").strip()

    normalized = {
        "base_system_prompt": str(merged.get("base_system_prompt", "") or "").strip("\n"),
        "sub_prompt_body": _localize_sub_prompt_section_titles(
            _strip_generated_sub_prompt_sections(merged.get("sub_prompt_body", ""))
        ),
        "emotions": emotions,
        "emotion_guides": emotion_guides,
        "analysis_system_appendix": str(merged.get("analysis_system_appendix", "") or "").strip("\n"),
    }

    _write_text_file(BASE_SYSTEM_PROMPT_PATH, normalized["base_system_prompt"])
    _write_text_file(SUB_PROMPT_BODY_PATH, normalized["sub_prompt_body"])
    _write_text_file(ANALYSIS_SYSTEM_APPENDIX_PATH, normalized["analysis_system_appendix"])
    _write_text_file(
        EMOTION_GUIDES_PATH,
        _serialize_emotion_guides(normalized["emotions"], normalized["emotion_guides"]),
    )
    _sync_runtime_prompt_files_to_visible_roaming()
    return normalized


def build_sub_prompt_text(body_text: str, emotions: list[str], emotion_guides: dict[str, str]) -> str:
    emotion_names = ", ".join(emotions)
    rules_section = "\n".join(
        [
            "### [감정 표현 규칙]",
            "- 답변 말 마지막에 반드시 감정 태그를 추가하세요.",
            "- 형식: `[emotion]`",
            f"- 사용 가능한 감정: `{emotion_names}`",
        ]
    )

    guide_lines = ["### [감정 사용 가이드]"]
    for emotion in emotions:
        guide = str(emotion_guides.get(emotion, "") or "").strip()
        if not guide:
            guide = "이 감정을 어떤 상황에서 쓰는지 설명하세요."
        guide_lines.append(f"- {emotion}: {guide}")

    parts = [rules_section]
    cleaned_body = str(body_text or "").strip()
    if cleaned_body:
        parts.append(cleaned_body)
    parts.append("\n".join(guide_lines))
    return "\n\n".join(parts).strip()


def get_sub_prompt_text(
    settings_source: dict | None = None,
    base_path: Path | None = None,
) -> str:
    config = load_runtime_prompt_config(settings_source=settings_source, base_path=base_path)
    return build_sub_prompt_text(
        config.get("sub_prompt_body", ""),
        list(config.get("emotions", [])),
        dict(config.get("emotion_guides", {})),
    )
