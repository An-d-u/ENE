"""Live2D 파라미터 저장 브리지."""
from __future__ import annotations

import json

from PyQt6.QtCore import pyqtSlot

from ..live2d_parameter_overrides import (
    MAX_PARAMETER_PAYLOAD_BYTES,
    empty_live2d_parameter_payload,
    normalize_live2d_model_key,
    normalize_live2d_parameter_override_payload,
)


class Live2DParameterBridgeMixin:
    """JS에서 Live2D 파라미터 저장값을 읽고 저장하는 슬롯."""

    @pyqtSlot()
    def open_live2d_parameter_inspector(self) -> None:
        parent = self.parent()
        opener = getattr(parent, "open_live2d_parameter_inspector", None)
        if callable(opener):
            opener()

    @pyqtSlot(str, result=str)
    def get_live2d_parameter_overrides(self, model_key: str) -> str:
        key = normalize_live2d_model_key(model_key)
        if not key or not self.settings:
            return json.dumps(empty_live2d_parameter_payload(), ensure_ascii=False)
        overrides = self.settings.get("live2d_parameter_overrides", {})
        if not isinstance(overrides, dict):
            return json.dumps(empty_live2d_parameter_payload(), ensure_ascii=False)
        payload = (
            normalize_live2d_parameter_override_payload(overrides.get(key, {}))
            or empty_live2d_parameter_payload()
        )
        return json.dumps(payload, ensure_ascii=False)

    @pyqtSlot(str, str)
    def save_live2d_parameter_overrides(self, model_key: str, payload_json: str) -> None:
        key = normalize_live2d_model_key(model_key)
        if not key or not self.settings:
            return
        payload_text = str(payload_json or "{}")
        if len(payload_text.encode("utf-8")) > MAX_PARAMETER_PAYLOAD_BYTES:
            return
        try:
            raw_payload = json.loads(payload_text)
        except Exception:
            return
        payload = normalize_live2d_parameter_override_payload(raw_payload)
        if payload is None:
            return

        overrides = self.settings.get("live2d_parameter_overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
        else:
            overrides = dict(overrides)
        if payload == empty_live2d_parameter_payload():
            overrides.pop(key, None)
        else:
            overrides[key] = payload
        self.settings.set("live2d_parameter_overrides", overrides)
        self.settings.save()
