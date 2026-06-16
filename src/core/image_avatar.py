"""
이미지 아바타 폴더를 해석하고 런타임 페이로드를 만드는 유틸리티.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .app_paths import get_bundle_root


SUPPORTED_IMAGE_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg")
DEFAULT_IMAGE_AVATAR_PLACEMENT = {"scale": 1.0, "xPercent": 50, "yPercent": 50}


def _resolve_settings_source(settings_source: Any | None = None) -> dict:
    if isinstance(settings_source, dict):
        return settings_source
    config = getattr(settings_source, "config", None)
    if isinstance(config, dict):
        return config
    return {}


def _normalize_emotion_name(text: str) -> str:
    return str(text or "").strip().lower()


def _resolve_base_path(base_path: str | Path | None = None) -> Path:
    return Path(base_path) if base_path is not None else get_bundle_root()


def _resolve_avatar_folder(settings_source: Any | None, base_path: str | Path | None) -> Path:
    source = _resolve_settings_source(settings_source)
    raw_folder = str(source.get("image_avatar_folder", "") or "").strip()
    if not raw_folder:
        return (_resolve_base_path(base_path) / "avatar_images").resolve()

    folder = Path(raw_folder).expanduser()
    if folder.is_absolute():
        return folder.resolve()
    return (_resolve_base_path(base_path) / folder).resolve()


def _extension_rank(path: Path) -> int:
    try:
        return SUPPORTED_IMAGE_EXTENSIONS.index(path.suffix.lower())
    except ValueError:
        return len(SUPPORTED_IMAGE_EXTENSIONS)


def _discover_image_paths(folder_path: str | Path) -> dict[str, Path]:
    folder = Path(folder_path)
    if not folder.exists() or not folder.is_dir():
        return {}

    discovered: dict[str, Path] = {}
    for path in folder.iterdir():
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            continue
        emotion = _normalize_emotion_name(path.stem)
        if not emotion:
            continue
        previous = discovered.get(emotion)
        if previous is None or _extension_rank(path) < _extension_rank(previous):
            discovered[emotion] = path
    return discovered


def _order_emotions(emotions: set[str]) -> list[str]:
    if "normal" not in emotions:
        return []
    return ["normal", *sorted(emotion for emotion in emotions if emotion != "normal")]


def discover_image_avatar_emotions(folder_path: str | Path) -> list[str]:
    """지원 이미지 파일명에서 사용 가능한 이미지 아바타 감정 목록을 반환한다."""
    discovered = _discover_image_paths(folder_path)
    return _order_emotions(set(discovered))


def _normalize_storage_key(raw_folder: str, image_path: Path, base_path: Path) -> str:
    if raw_folder:
        folder_key = str(Path(raw_folder)).replace("\\", "/").strip("/")
        if not Path(raw_folder).is_absolute():
            return f"{folder_key}/{image_path.name}" if folder_key else image_path.name

    try:
        return str(image_path.resolve().relative_to(base_path.resolve())).replace("\\", "/")
    except Exception:
        return str(image_path.resolve()).replace("\\", "/")


def _clamp_number(value: Any, default: float, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    if not math.isfinite(number):
        number = default
    return min(max(number, minimum), maximum)


def _whole_or_float(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


def _build_placement(raw_placement: Any) -> dict:
    if not isinstance(raw_placement, dict):
        return dict(DEFAULT_IMAGE_AVATAR_PLACEMENT)

    scale = _clamp_number(raw_placement.get("scale"), 1.0, 0.1, 2.0)
    x_percent = _clamp_number(raw_placement.get("x_percent"), 50, -100, 200)
    y_percent = _clamp_number(raw_placement.get("y_percent"), 50, -100, 200)
    return {
        "scale": _whole_or_float(scale),
        "xPercent": _whole_or_float(x_percent),
        "yPercent": _whole_or_float(y_percent),
    }


def build_image_avatar_payload(settings_source: Any | None, base_path: str | Path | None = None) -> dict:
    """현재 이미지 아바타 폴더 기준 런타임 페이로드를 만든다."""
    source = _resolve_settings_source(settings_source)
    resolved_base_path = _resolve_base_path(base_path)
    folder_path = _resolve_avatar_folder(source, resolved_base_path)
    raw_folder = str(source.get("image_avatar_folder", "") or "").strip()
    image_paths = _discover_image_paths(folder_path)
    available_emotions = _order_emotions(set(image_paths))

    folder_uri = folder_path.as_uri() if folder_path.exists() else ""
    if not available_emotions:
        return {
            "folderPath": folder_uri,
            "availableEmotions": ["normal"],
            "images": {},
            "error": "missing_normal",
        }

    placements = source.get("image_avatar_placements", {})
    if not isinstance(placements, dict):
        placements = {}

    images: dict[str, dict] = {}
    for emotion in available_emotions:
        image_path = image_paths[emotion].resolve()
        storage_key = _normalize_storage_key(raw_folder, image_path, resolved_base_path)
        images[emotion] = {
            "path": image_path.as_uri(),
            "storageKey": storage_key,
            "placement": _build_placement(placements.get(storage_key)),
        }

    return {
        "folderPath": folder_uri,
        "availableEmotions": available_emotions,
        "images": images,
        "error": "",
    }
