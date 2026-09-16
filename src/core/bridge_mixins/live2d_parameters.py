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

    @staticmethod
    def _parameter_json(value):
        if not isinstance(value, str) or len(value.encode("utf-8")) > MAX_PARAMETER_PAYLOAD_BYTES:
            raise ValueError("invalid_parameters")
        parsed = json.loads(value)
        if not isinstance(parsed, dict):
            raise ValueError("invalid_parameters")
        return parsed

    def _parameter_edit_baseline(self, key):
        character = self._ensure_companion_character()
        shared = character.settings_baseline()
        return {"model_key": key, "generation": shared["generation"],
                "settings_revision": shared["settings_revision"],
                "payload": json.loads(self.get_live2d_parameter_overrides(key))}

    @pyqtSlot(str, result=str)
    def get_live2d_parameter_edit_snapshot(self, model_key: str) -> str:
        key = normalize_live2d_model_key(model_key)
        current = self._ensure_companion_character().settings_baseline()
        if not key or key != current["model_key"]:
            return json.dumps({"status": "rejected", "reason": "model_changed"})
        return json.dumps(self._parameter_edit_baseline(key), ensure_ascii=False)

    @pyqtSlot(str, str, str, result=str)
    def commit_live2d_parameter_overrides(self, model_key, payload_json, baseline_json):
        try:
            answer = self._commit_parameter_edit(model_key, self._parameter_json(payload_json), self._parameter_json(baseline_json))
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            answer = {"status": "rejected", "reason": "invalid_parameters"}
        return json.dumps(answer, ensure_ascii=False)

    @pyqtSlot(str, str, result=str)
    def save_live2d_parameter_overrides(self, model_key: str, payload_json: str) -> str:
        """기존 로컬 호출은 유지하되 연결 중에는 명시적 편집 기준이 필요하다."""
        character = getattr(self, "_companion_character", None)
        if character is not None and character._active:
            return json.dumps({"status": "rejected", "reason": "snapshot_required"})
        try:
            key = normalize_live2d_model_key(model_key)
            answer = self._commit_parameter_edit(key, self._parameter_json(payload_json), self._parameter_edit_baseline(key), current_only=False)
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            answer = {"status": "rejected", "reason": "invalid_parameters"}
        return json.dumps(answer, ensure_ascii=False)

    def _commit_parameter_edit(self, model_key, raw, baseline, *, current_only=True):
        from ..companion.character_controls import normalize_parameters

        key = normalize_live2d_model_key(model_key)
        if not key or not self.settings:
            raise ValueError("invalid_parameters")
        character = self._ensure_companion_character()
        shared = character.settings_baseline()
        if current_only and (key != shared["model_key"] or baseline.get("model_key") != key or
                             baseline.get("generation") != shared["generation"]):
            return {"status": "conflict", "reason": "model_changed"}
        if current_only and character._active and character.state.status != "ready":
            return {"status": "rejected", "reason": "character_unavailable"}
        expected = baseline.get("settings_revision")
        if type(expected) is not int or not 0 <= expected <= shared["settings_revision"]:
            raise ValueError("invalid_baseline")
        desired = normalize_live2d_parameter_override_payload(raw)
        original = normalize_live2d_parameter_override_payload(baseline.get("payload"))
        if desired is None or original is None:
            raise ValueError("invalid_parameters")
        current = self._parameter_edit_baseline(key)
        saved = current["payload"]
        changes = {name: desired["values"].get(name) for name in original["values"].keys() | desired["values"].keys()
                   if original["values"].get(name) != desired["values"].get(name)}
        normalize_parameters(changes)
        if current_only and character.state.status == "ready":
            # 삭제는 현재 모델에서 없어진 옛 저장값도 정리할 수 있다.
            normalize_parameters({name: value for name, value in changes.items() if value is not None}, character.state.catalog)
        conflicts = {name: saved["values"].get(name) for name, value in changes.items()
                     if saved["values"].get(name) != original["values"].get(name) and saved["values"].get(name) != value}
        favorites_changed = desired["favorites"] != original["favorites"]
        if favorites_changed and saved["favorites"] != original["favorites"] and saved["favorites"] != desired["favorites"]:
            conflicts["__favorites__"] = saved["favorites"]
        if conflicts:
            return {"status": "conflict", "reason": "revision_conflict", "baseline": current, "conflicts": conflicts}
        merged = dict(saved["values"])
        for name, value in changes.items():
            if value is None:
                merged.pop(name, None)
            else:
                merged[name] = value
        payload = {"values": merged, "favorites": desired["favorites"] if favorites_changed else saved["favorites"]}
        try:
            self.settings.commit_live2d_parameter_overrides(key, payload)
        except Exception:
            return {"status": "rejected", "reason": "storage_failed"}
        if key == shared["model_key"] and changes:
            character.parameters_committed(payload["values"])
        return {"status": "accepted", "baseline": self._parameter_edit_baseline(key)}
