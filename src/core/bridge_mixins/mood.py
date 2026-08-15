"""
WebBridge의 기분 UI 상태와 쓰다듬기 이벤트 로직.
"""
from collections.abc import Mapping
import json
import math

from PyQt6.QtCore import pyqtSlot


class MoodBridgeMixin:
    def set_mood_manager(self, mood_manager):
        """기분 매니저 설정"""
        self.mood_manager = mood_manager
        if self.llm_client and self.mood_manager:
            self.llm_client.mood_manager = self.mood_manager
        if self.mood_manager:
            snapshot = self.mood_manager.get_snapshot()
            self._emit_mood_changed(snapshot)

    def _emit_mood_changed(self, snapshot: dict):
        """기분 상태 변경 시 UI로 전달"""
        try:
            data = snapshot if isinstance(snapshot, Mapping) else {}
            background = data.get("background")
            background = background if isinstance(background, Mapping) else {}
            relationship = data.get("relationship")
            relationship = relationship if isinstance(relationship, Mapping) else {}

            def finite_number(*values: object) -> float:
                for value in values:
                    if isinstance(value, bool):
                        continue
                    try:
                        number = float(value)
                    except (TypeError, ValueError, OverflowError):
                        continue
                    if math.isfinite(number):
                        return number
                return 0.0

            current_mood = data.get("current_mood")
            temporary_state = data.get("temporary_state")
            self.mood_changed.emit(
                current_mood if isinstance(current_mood, str) and current_mood else "calm",
                finite_number(background.get("valence"), data.get("valence")),
                finite_number(
                    background.get("activity"),
                    background.get("energy"),
                    data.get("energy"),
                ),
                finite_number(relationship.get("affection"), data.get("bond")),
                finite_number(background.get("tension"), data.get("stress")),
                temporary_state
                if isinstance(temporary_state, str) and temporary_state
                else "steady",
            )
        except Exception as e:
            print(f"[Bridge] mood_changed emit 실패: {e}")

    @pyqtSlot()
    def increment_head_pat_count_from_js(self):
        """JavaScript에서 호출: 머리 쓰다듬기 횟수 증가."""
        if hasattr(self, "calendar_manager") and self.calendar_manager:
            self.calendar_manager.increment_head_pat_count()
            print("[Bridge] 쓰다듬기 횟수 증가")
        if self.mood_manager:
            snapshot = self.mood_manager.on_head_pat()
            self._emit_mood_changed(snapshot)

    @pyqtSlot(result=str)
    def get_mood_snapshot_json(self) -> str:
        """JavaScript에서 호출: 현재 기분 상태를 JSON 문자열로 반환."""
        if not self.mood_manager:
            return ""
        try:
            snapshot = self.mood_manager.get_snapshot()
            return json.dumps(snapshot, ensure_ascii=False)
        except Exception as e:
            print(f"[Bridge] 기분 스냅샷 반환 실패: {e}")
            return ""
