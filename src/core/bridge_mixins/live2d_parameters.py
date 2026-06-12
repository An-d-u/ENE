"""Live2D 파라미터 저장 브리지."""
from __future__ import annotations

import json
import math
from typing import Any

from PyQt6.QtCore import pyqtSlot


MAX_MODEL_KEY_LENGTH = 512
MAX_PARAMETER_ID_LENGTH = 128
MAX_PARAMETER_OVERRIDE_COUNT = 256
MAX_PARAMETER_PAYLOAD_BYTES = 64 * 1024


def _empty_payload() -> dict[str, Any]:
    return {"values": {}, "pinned": []}


def _normalize_model_key(model_key: str) -> str:
    key = str(model_key or "").strip().replace("\\", "/")
    return key if len(key) <= MAX_MODEL_KEY_LENGTH else ""


def _normalize_override_payload(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    raw_values = payload.get("values", {})
    raw_pinned = payload.get("pinned", [])
    if not isinstance(raw_values, dict) or not isinstance(raw_pinned, list):
        return None
    if len(raw_values) > MAX_PARAMETER_OVERRIDE_COUNT or len(raw_pinned) > MAX_PARAMETER_OVERRIDE_COUNT:
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

    pinned: list[str] = []
    seen: set[str] = set()
    for item in raw_pinned:
        if not isinstance(item, str):
            return None
        param_id = item.strip()
        if not param_id or len(param_id) > MAX_PARAMETER_ID_LENGTH:
            return None
        if param_id in seen:
            continue
        seen.add(param_id)
        pinned.append(param_id)

    return {"values": values, "pinned": pinned}


class Live2DParameterBridgeMixin:
    """JS에서 Live2D 파라미터 저장값을 읽고 저장하는 슬롯."""

    @pyqtSlot(str, result=str)
    def get_live2d_parameter_overrides(self, model_key: str) -> str:
        key = _normalize_model_key(model_key)
        if not key or not self.settings:
            return json.dumps(_empty_payload(), ensure_ascii=False)
        overrides = self.settings.get("live2d_parameter_overrides", {})
        if not isinstance(overrides, dict):
            return json.dumps(_empty_payload(), ensure_ascii=False)
        payload = _normalize_override_payload(overrides.get(key, {})) or _empty_payload()
        return json.dumps(payload, ensure_ascii=False)

    @pyqtSlot(str, str)
    def save_live2d_parameter_overrides(self, model_key: str, payload_json: str) -> None:
        key = _normalize_model_key(model_key)
        if not key or not self.settings:
            return
        payload_text = str(payload_json or "{}")
        if len(payload_text.encode("utf-8")) > MAX_PARAMETER_PAYLOAD_BYTES:
            return
        try:
            raw_payload = json.loads(payload_text)
        except Exception:
            return
        payload = _normalize_override_payload(raw_payload)
        if payload is None:
            return

        overrides = self.settings.get("live2d_parameter_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        else:
            overrides = dict(overrides)
        if payload == _empty_payload():
            overrides.pop(key, None)
        else:
            overrides[key] = payload
        self.settings.set("live2d_parameter_overrides", overrides)
        self.settings.save()
