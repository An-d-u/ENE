"""
WebBridge의 기분 UI 상태와 쓰다듬기 이벤트 로직.
"""
import json

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
            self.mood_changed.emit(
                str(snapshot.get("current_mood", "calm")),
                float(snapshot.get("valence", 0.0)),
                float(snapshot.get("energy", 0.0)),
                float(snapshot.get("bond", 0.0)),
                float(snapshot.get("stress", 0.0)),
                str(snapshot.get("temporary_state", "steady")),
            )
        except Exception as e:
            print(f"[Bridge] mood_changed emit 실패: {e}")

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
