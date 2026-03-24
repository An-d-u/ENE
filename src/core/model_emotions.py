"""
현재 Live2D 모델의 표정 파일 목록을 해석하는 유틸리티.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .settings import Settings


DEFAULT_MODEL_JSON_PATH = "assets/live2d_models/jksalt/jksalt.model3.json"


def get_base_path() -> Path:
    """실행 환경에 맞는 프로젝트 기준 경로를 반환한다."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path.cwd()))
    return Path(__file__).resolve().parents[2]


def _resolve_settings_source(settings_source: dict | None = None) -> dict:
    if isinstance(settings_source, dict):
        return settings_source
    try:
        return dict(Settings().config)
    except Exception:
        return {}


def _normalize_emotion_name(text: str) -> str:
    return str(text or "").strip().lower()


def _normalize_fallback_emotions(fallback_emotions: list[str] | None = None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in fallback_emotions or []:
        emotion = _normalize_emotion_name(item)
        if emotion and emotion not in seen:
            seen.add(emotion)
            normalized.append(emotion)
    if not normalized:
        normalized = ["normal"]
    return normalized


def resolve_model_json_path(
    settings_source: dict | None = None,
    base_path: Path | None = None,
) -> Path:
    """설정에서 현재 모델 JSON 경로를 절대 경로로 해석한다."""
    source = _resolve_settings_source(settings_source)
    raw_model_path = str(source.get("model_json_path", DEFAULT_MODEL_JSON_PATH)).strip() or DEFAULT_MODEL_JSON_PATH

    model_path = Path(raw_model_path)
    resolved_base_path = Path(base_path) if base_path else get_base_path()
    if not model_path.is_absolute():
        model_path = resolved_base_path / model_path
    return model_path.resolve()


def discover_model_emotions(model_json_path: str | Path) -> list[str]:
    """모델과 같은 폴더의 emotions 디렉터리에서 실제 표정 파일 이름을 수집한다."""
    model_path = Path(model_json_path)
    emotions_dir = model_path.parent / "emotions"
    if not emotions_dir.exists() or not emotions_dir.is_dir():
        return []

    discovered: set[str] = set()
    for path in emotions_dir.glob("*.exp3.json"):
        emotion = _normalize_emotion_name(path.name[: -len(".exp3.json")])
        if emotion:
            discovered.add(emotion)

    if not discovered:
        return []

    ordered: list[str] = []
    if "normal" in discovered:
        ordered.append("normal")
        discovered.remove("normal")
    ordered.extend(sorted(discovered))
    return ordered


def get_available_model_emotions(
    settings_source: dict | None = None,
    base_path: Path | None = None,
    fallback_emotions: list[str] | None = None,
) -> list[str]:
    """현재 모델 기준 사용 가능한 감정 목록을 반환한다."""
    model_path = resolve_model_json_path(settings_source=settings_source, base_path=base_path)
    discovered = discover_model_emotions(model_path)
    if discovered:
        return discovered
    return _normalize_fallback_emotions(fallback_emotions)
