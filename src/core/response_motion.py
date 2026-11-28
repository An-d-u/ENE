"""대화 동작 설정을 UI와 Live2D에 같은 범위로 전달한다."""

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from .app_paths import get_bundle_root, relativize_for_storage

DEFAULT_EMOTION_OVERLAP_PERCENT = 28
RESPONSE_MOTION_DEFAULTS = {
    "response_motion_mode": "classic",
    "enable_emotion_motion": True,
    "emotion_motion_preset": "standard",
    "emotion_motion_overrides": {},
    "emotion_motion_overlap_percentages": {},
    "emotion_motion_head_strength": 1.0,
    "emotion_motion_body_strength": 1.0,
    "response_gesture_head_strength": 1.0,
    "response_gesture_body_strength": 1.0,
    "response_gesture_repeat_limits": {},
}


@lru_cache(maxsize=4)
def _motion_catalog(bundle_root: Path) -> tuple[dict[str, str], tuple[str, ...]]:
    """재생기와 같은 모션 파일에서 자동 연결표와 선택 가능한 동작만 보관한다."""
    path = bundle_root / "assets/web/motions/response-accent.json"
    try:
        bank = json.loads(path.read_text(encoding="utf-8"))
        ids = tuple(key.removesuffix(".standard") for key in bank["emotions"] if key.endswith(".standard"))
        return bank["aliases"], ids
    except (OSError, ValueError, KeyError):
        return {}, ()


def automatic_emotion_motion(expression: str) -> str | None:
    aliases, _ = _motion_catalog(get_bundle_root())
    key = re.sub(r"[\s_-]+", "", unicodedata.normalize("NFKC", expression).lower())
    return aliases.get(key)


def emotion_motion_ids() -> tuple[str, ...]:
    return _motion_catalog(get_bundle_root())[1]


def normalize_response_motion_mode(value):
    return "accent" if value in ("accent", "follow") else "classic"


def response_motion_model_key(path: str | None) -> str:
    from .model_emotions import DEFAULT_MODEL_JSON_PATH

    value = path.strip() if isinstance(path, str) else ""
    try:
        return relativize_for_storage(value or DEFAULT_MODEL_JSON_PATH)
    except (OSError, RuntimeError, ValueError):
        return value.replace("\\", "/")


def normalize_response_repeat_limits(values) -> dict[str, int]:
    if not isinstance(values, dict):
        return {}
    return {
        response_motion_model_key(path): count
        for path, count in values.items()
        if isinstance(path, str) and path.strip() and type(count) is int and 1 <= count <= 3
    }


def normalize_emotion_overlap_percentages(values) -> dict[str, int]:
    if not isinstance(values, dict):
        return {}
    return {
        response_motion_model_key(path): percent
        for path, percent in values.items()
        if isinstance(path, str) and path.strip() and type(percent) is int and 0 <= percent <= 100
    }


def normalize_emotion_motion_overrides(values) -> dict[str, dict[str, str]]:
    if not isinstance(values, dict) or not values:
        return {}
    motion_ids = emotion_motion_ids()
    result = {}
    for path, choices in values.items():
        if not isinstance(path, str) or not path.strip() or not isinstance(choices, dict):
            continue
        # 파일명 구분자를 보존해 soft-smile과 soft_smile을 따로 지정할 수 있다.
        selected = {
            name.strip().lower(): motion for name, motion in choices.items()
            if isinstance(name, str) and name.strip() and isinstance(motion, str)
            and motion and (motion == "none" or motion in motion_ids or not motion_ids)
        }
        if selected:
            result.setdefault(response_motion_model_key(path), {}).update(selected)
    return result


def response_motion_config(settings):
    def strength(key):
        value = settings.get(key, 1.0)
        if type(value) not in (int, float) or not 0 <= value <= 2:
            return 1.0
        return value

    repeats = normalize_response_repeat_limits(settings.get("response_gesture_repeat_limits"))
    overrides = normalize_emotion_motion_overrides(settings.get("emotion_motion_overrides"))
    overlaps = normalize_emotion_overlap_percentages(settings.get("emotion_motion_overlap_percentages"))
    model_key = response_motion_model_key(settings.get("model_json_path"))
    preset = settings.get("emotion_motion_preset")
    return {
        "mode": normalize_response_motion_mode(settings.get("response_motion_mode")),
        "enabled": settings.get("enable_emotion_motion", True) is True,
        "preset": preset if preset in ("restrained", "lively", "gentle") else "standard",
        "head": strength("emotion_motion_head_strength"),
        "body": strength("emotion_motion_body_strength"),
        "gestureHead": strength("response_gesture_head_strength"),
        "gestureBody": strength("response_gesture_body_strength"),
        "repeatLimit": repeats.get(model_key, 0),
        "overlapPercent": overlaps.get(model_key, DEFAULT_EMOTION_OVERLAP_PERCENT),
        "emotionOverrides": overrides.get(model_key, {}),
    }
