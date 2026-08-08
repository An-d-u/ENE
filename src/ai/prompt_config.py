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
import tempfile
from pathlib import Path

from ..core.model_emotions import get_available_avatar_emotions
from ..core.app_paths import get_bundle_prompts_defaults_dir, get_bundle_root, get_user_prompts_dir
from .prompt_language import resolve_prompt_language


VALID_RESPONSE_STYLES = frozenset({"plain", "structured_fields", "legacy_tags"})


def normalize_response_style(response_style: str) -> str:
    """공개 프롬프트 빌더가 공유하는 응답 스타일을 검증한다."""
    if not isinstance(response_style, str) or response_style not in VALID_RESPONSE_STYLES:
        raise ValueError(f"invalid response style: {response_style!r}")
    return response_style


PROJECT_ROOT = get_bundle_root()
PROMPT_CONFIG_DIR = get_user_prompts_dir()
DEFAULT_PROMPT_CONFIG_DIR = get_bundle_prompts_defaults_dir()

BASE_SYSTEM_PROMPT_PATH = PROMPT_CONFIG_DIR / "base_system_prompt.md"
SUB_PROMPT_BODY_PATH = PROMPT_CONFIG_DIR / "sub_prompt_body.md"
EMOTION_GUIDES_PATH = PROMPT_CONFIG_DIR / "emotion_guides.md"
LIFE_WORLD_PROMPT_FILENAME = "life_world.md"
LIFE_WORLD_PROMPT_PATH = PROMPT_CONFIG_DIR / LIFE_WORLD_PROMPT_FILENAME

DEFAULT_BASE_SYSTEM_PROMPT_PATH = DEFAULT_PROMPT_CONFIG_DIR / "base_system_prompt.md"
DEFAULT_SUB_PROMPT_BODY_PATH = DEFAULT_PROMPT_CONFIG_DIR / "sub_prompt_body.md"
DEFAULT_EMOTION_GUIDES_PATH = DEFAULT_PROMPT_CONFIG_DIR / "emotion_guides.md"
DEFAULT_LIFE_WORLD_PROMPT_PATH = DEFAULT_PROMPT_CONFIG_DIR / LIFE_WORLD_PROMPT_FILENAME

PROMPT_MARKDOWN_FILENAMES = (
    "base_system_prompt.md",
    "sub_prompt_body.md",
    "emotion_guides.md",
    LIFE_WORLD_PROMPT_FILENAME,
)
PROMPT_FILE_PRESENT_MARKER = "P:"

GENERATED_SUB_PROMPT_SECTION_TITLES = {
    "감정 표현 규칙",
    "Emotion Expression Rules",
    "感情表現ルール",
    "감정 사용 가이드",
    "Emotion Usage Guide",
    "感情使用ガイド",
}

# 예전 사용자 프롬프트 파일을 읽을 수 있도록 과거 섹션명을 현재 명칭으로 정규화한다.
SUB_PROMPT_SECTION_TITLE_ALIASES = {
    "Emotion Expression Rules": "감정 표현 규칙",
    "Japanese Response Rules": "일본어 표기 규칙",
    "Japanese Notation Rules": "일본어 표기 규칙",
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
    path.write_text(normalized, encoding="utf-8")


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
        target.write_text("", encoding="utf-8")


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
        encoding="utf-8",
        errors="replace",
    )


def _read_prompt_file_via_powershell(path: Path) -> bytes | None:
    file_text = str(path).replace("'", "''")
    result = _run_powershell_command(
        "\n".join(
            [
                f"$path = '{file_text}'",
                "if (-not (Test-Path -LiteralPath $path)) { exit 0 }",
                f"[Console]::Write('{PROMPT_FILE_PRESENT_MARKER}' + "
                "[Convert]::ToBase64String([IO.File]::ReadAllBytes($path)))",
            ]
        )
    )
    payload = str(result.stdout or "").strip()
    if not payload:
        return None
    if not payload.startswith(PROMPT_FILE_PRESENT_MARKER):
        raise ValueError("unexpected prompt file bridge response")
    return base64.b64decode(payload.removeprefix(PROMPT_FILE_PRESENT_MARKER))


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


def _delete_prompt_file_via_powershell(path: Path) -> None:
    file_text = str(path).replace("'", "''")
    _run_powershell_command(
        "\n".join(
            [
                f"$path = '{file_text}'",
                "if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }",
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


def _sync_runtime_life_world_prompt_to_visible_roaming() -> None:
    if not _should_sync_store_python_prompt_dirs() or not LIFE_WORLD_PROMPT_PATH.exists():
        return
    try:
        visible_path = _get_visible_prompt_config_dir() / LIFE_WORLD_PROMPT_FILENAME
        if _get_visible_prompt_config_dir() == Path(PROMPT_CONFIG_DIR):
            _write_prompt_file_via_powershell(visible_path, LIFE_WORLD_PROMPT_PATH.read_bytes())
            return
        visible_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(LIFE_WORLD_PROMPT_PATH, visible_path)
    except Exception:
        pass


def ensure_prompt_config_exists() -> Path:
    _sync_visible_roaming_prompt_files_to_runtime()
    _copy_default_if_missing(BASE_SYSTEM_PROMPT_PATH, DEFAULT_BASE_SYSTEM_PROMPT_PATH)
    _copy_default_if_missing(SUB_PROMPT_BODY_PATH, DEFAULT_SUB_PROMPT_BODY_PATH)
    _copy_default_if_missing(EMOTION_GUIDES_PATH, DEFAULT_EMOTION_GUIDES_PATH)
    _copy_default_if_missing(LIFE_WORLD_PROMPT_PATH, DEFAULT_LIFE_WORLD_PROMPT_PATH)
    return PROMPT_CONFIG_DIR


def load_life_world_prompt() -> str:
    """현재 생활 환경 프롬프트를 읽는다."""
    _sync_visible_roaming_prompt_files_to_runtime()
    _copy_default_if_missing(LIFE_WORLD_PROMPT_PATH, DEFAULT_LIFE_WORLD_PROMPT_PATH)
    return _read_text_file(LIFE_WORLD_PROMPT_PATH)


def save_life_world_prompt(text: str) -> str:
    """생활 환경 프롬프트를 UTF-8로 저장한다."""
    normalized = str(text or "").replace("\r\n", "\n").strip("\n")
    _write_text_file(LIFE_WORLD_PROMPT_PATH, normalized)
    _sync_runtime_life_world_prompt_to_visible_roaming()
    return normalized


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
    }


def get_runtime_emotions(
    settings_source: dict | None = None,
    base_path: Path | None = None,
) -> list[str]:
    """현재 모델 기준 실제 사용 가능한 감정 목록을 반환한다."""
    config = load_prompt_config()
    return get_available_avatar_emotions(
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
    }


def save_prompt_config(config: dict) -> dict:
    normalized = _normalize_prompt_config_payload(config)

    _write_text_file(BASE_SYSTEM_PROMPT_PATH, normalized["base_system_prompt"])
    _write_text_file(SUB_PROMPT_BODY_PATH, normalized["sub_prompt_body"])
    _write_text_file(
        EMOTION_GUIDES_PATH,
        _serialize_emotion_guides(normalized["emotions"], normalized["emotion_guides"]),
    )
    _sync_runtime_prompt_files_to_visible_roaming()
    return normalized


def _normalize_prompt_config_payload(config: dict) -> dict:
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
    }

    return normalized


def _stage_prompt_bundle_file(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def _replace_prompt_bundle_file(source: Path, target: Path) -> None:
    os.replace(source, target)


def _restore_prompt_bundle_snapshots(snapshots: dict[Path, bytes | None]) -> bool:
    rollback_failed = False
    for path, payload in snapshots.items():
        try:
            if payload is None:
                path.unlink(missing_ok=True)
                continue
            staged = _stage_prompt_bundle_file(path, payload)
            try:
                os.replace(staged, path)
            finally:
                staged.unlink(missing_ok=True)
        except Exception:
            rollback_failed = True
    return not rollback_failed


def _sync_prompt_bundle_to_visible_roaming(payloads: dict[Path, bytes]) -> None:
    if not _should_sync_store_python_prompt_dirs():
        return
    visible_dir = _get_visible_prompt_config_dir()
    visible_payloads = {
        visible_dir / path.name: payload
        for path, payload in payloads.items()
    }
    snapshots = {
        path: _read_prompt_file_via_powershell(path)
        for path in visible_payloads
    }
    try:
        for path, payload in visible_payloads.items():
            _write_prompt_file_via_powershell(path, payload)
    except Exception:
        rollback_failed = False
        for path, payload in snapshots.items():
            try:
                if payload is None:
                    _delete_prompt_file_via_powershell(path)
                else:
                    _write_prompt_file_via_powershell(path, payload)
            except Exception:
                rollback_failed = True
        code = "prompt_bundle_visible_save_failed"
        if rollback_failed:
            code = "prompt_bundle_visible_rollback_failed"
        raise RuntimeError(code) from None


def save_prompt_bundle(config: dict, life_world: str) -> dict:
    """프롬프트 네 파일을 하나의 복구 가능한 저장 단위로 교체한다."""
    normalized = _normalize_prompt_config_payload(config)
    normalized_life_world = str(life_world or "").replace("\r\n", "\n").strip("\n")
    payloads = {
        BASE_SYSTEM_PROMPT_PATH: normalized["base_system_prompt"].encode("utf-8"),
        SUB_PROMPT_BODY_PATH: normalized["sub_prompt_body"].encode("utf-8"),
        EMOTION_GUIDES_PATH: _serialize_emotion_guides(
            normalized["emotions"], normalized["emotion_guides"]
        ).encode("utf-8"),
        LIFE_WORLD_PROMPT_PATH: normalized_life_world.encode("utf-8"),
    }
    snapshots = {
        path: path.read_bytes() if path.exists() else None
        for path in payloads
    }
    staged_files: list[tuple[Path, Path]] = []
    try:
        for path, payload in payloads.items():
            staged_files.append((_stage_prompt_bundle_file(path, payload), path))
        for staged, target in staged_files:
            _replace_prompt_bundle_file(staged, target)
    except Exception:
        restored = _restore_prompt_bundle_snapshots(snapshots)
        code = "prompt_bundle_save_failed" if restored else "prompt_bundle_rollback_failed"
        raise RuntimeError(code) from None
    finally:
        for staged, _target in staged_files:
            staged.unlink(missing_ok=True)

    try:
        _sync_prompt_bundle_to_visible_roaming(payloads)
    except Exception as error:
        restored = _restore_prompt_bundle_snapshots(snapshots)
        code = str(error) if restored else "prompt_bundle_rollback_failed"
        raise RuntimeError(code) from None
    return {**normalized, "life_world": normalized_life_world}


def build_sub_prompt_text(
    body_text: str,
    emotions: list[str],
    emotion_guides: dict[str, str],
    language: str | None = None,
    response_style: str = "legacy_tags",
) -> str:
    response_style = normalize_response_style(response_style)
    resolved_language = resolve_prompt_language(language)
    emotion_names = ", ".join(emotions)
    text = {
        "ko": {
            "rules": "감정 표현 규칙",
            "tag": "- 답변 말 마지막에 반드시 감정 태그를 추가하세요.",
            "format": "- 형식: `[emotion]`",
            "available": "- 사용 가능한 감정",
            "guide": "감정 사용 가이드",
            "fallback": "이 감정을 어떤 상황에서 쓰는지 설명하세요.",
            "field": "- 최상위 `emotion` 필드에는 사용 가능한 감정 중 하나만 넣으세요.",
        },
        "en": {
            "rules": "Emotion Expression Rules",
            "tag": "- Always add an emotion tag at the end of the reply.",
            "format": "- Format: `[emotion]`",
            "available": "- Available emotions",
            "guide": "Emotion Usage Guide",
            "fallback": "Describe when to use this emotion.",
            "field": "- Put exactly one available emotion in the top-level `emotion` field.",
        },
        "ja": {
            "rules": "感情表現ルール",
            "tag": "- 返答の最後に必ず感情タグを追加してください。",
            "format": "- 形式: `[emotion]`",
            "available": "- 使用可能な感情",
            "guide": "感情使用ガイド",
            "fallback": "この感情をどのような状況で使うか説明してください。",
            "field": "- 最上位の `emotion` フィールドには、使用可能な感情を一つだけ入れてください。",
        },
    }[resolved_language]
    if response_style == "legacy_tags":
        rules_section = "\n".join(
            [
                f"### [{text['rules']}]",
                text["tag"],
                text["format"],
                f"{text['available']}: `{emotion_names}`",
            ]
        )
    elif response_style == "structured_fields":
        rules_section = "\n".join(
            [
                f"### [{text['rules']}]",
                text["field"],
                f"{text['available']}: `{emotion_names}`",
            ]
        )
    elif response_style == "plain":
        rules_section = ""
    else:
        raise ValueError(f"지원하지 않는 응답 스타일입니다: {response_style}")

    guide_lines = [f"### [{text['guide']}]"]
    for emotion in emotions:
        guide = str(emotion_guides.get(emotion, "") or "").strip()
        if not guide:
            guide = text["fallback"]
        guide_lines.append(f"- {emotion}: {guide}")

    parts = []
    if rules_section:
        parts.append(rules_section)
    cleaned_body = str(body_text or "").strip()
    if cleaned_body:
        parts.append(cleaned_body)
    parts.append("\n".join(guide_lines))
    return "\n\n".join(parts).strip()


def get_sub_prompt_text(
    settings_source: dict | None = None,
    base_path: Path | None = None,
    response_style: str = "legacy_tags",
) -> str:
    response_style = normalize_response_style(response_style)
    config = load_runtime_prompt_config(settings_source=settings_source, base_path=base_path)
    return build_sub_prompt_text(
        config.get("sub_prompt_body", ""),
        list(config.get("emotions", [])),
        dict(config.get("emotion_guides", {})),
        language=resolve_prompt_language(settings_source=settings_source),
        response_style=response_style,
    )
