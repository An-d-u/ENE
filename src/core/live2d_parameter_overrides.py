"""Live2D 파라미터 오버라이드 저장 payload 정규화."""
from __future__ import annotations

import math
from typing import Any


MAX_MODEL_KEY_LENGTH = 512
MAX_PARAMETER_ID_LENGTH = 128
MAX_PARAMETER_OVERRIDE_COUNT = 256
MAX_PARAMETER_PAYLOAD_BYTES = 64 * 1024


def empty_live2d_parameter_payload() -> dict[str, Any]:
    return {"values": {}, "favorites": []}


def normalize_live2d_model_key(model_key: str) -> str:
    key = str(model_key or "").strip().replace("\\", "/")
    return key if len(key) <= MAX_MODEL_KEY_LENGTH else ""


def normalize_live2d_parameter_override_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    raw_values = payload.get("values", {})
    raw_favorites = payload.get("favorites", payload.get("pinned", []))
    if not isinstance(raw_values, dict) or not isinstance(raw_favorites, list):
        return None
    if len(raw_values) > MAX_PARAMETER_OVERRIDE_COUNT or len(raw_favorites) > MAX_PARAMETER_OVERRIDE_COUNT:
        return None

    values: dict[str, float] = {}
    for key, value in raw_values.items():
        param_id = str(key or "").strip()
        if not param_id or len(param_id) > MAX_PARAMETER_ID_LENGTH:
            return None
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        numeric_value = float(value)
        if not math.isfinite(numeric_value):
            return None
        if not (-1.0e9 < numeric_value < 1.0e9):
            return None
        values[param_id] = numeric_value

    favorites: list[str] = []
    seen: set[str] = set()
    for item in raw_favorites:
        if not isinstance(item, str):
            return None
        param_id = item.strip()
        if not param_id or len(param_id) > MAX_PARAMETER_ID_LENGTH:
            return None
        if param_id in seen:
            continue
        seen.add(param_id)
        favorites.append(param_id)

    return {"values": values, "favorites": favorites}
