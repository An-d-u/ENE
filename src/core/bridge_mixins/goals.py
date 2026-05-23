"""
WebBridge의 목표 UI 상태와 수동 목표 조작 로직.
"""
import json

from PyQt6.QtCore import pyqtSlot


class GoalBridgeMixin:
    def set_goal_manager(self, goal_manager):
        """에네 목표 매니저 설정"""
        self.goal_manager = goal_manager
        if self.llm_client and self.goal_manager:
            self.llm_client.goal_manager = self.goal_manager
        self._emit_goal_items_updated()

    def _emit_goal_items_updated(self, snapshot=None):
        """목표 목록을 JSON으로 UI에 안전하게 전달한다."""
        signal = getattr(self, "goal_items_updated", None)
        emit = getattr(signal, "emit", None)
        if not callable(emit):
            return
        try:
            goal_manager = getattr(self, "goal_manager", None)
            if snapshot is None and goal_manager and hasattr(goal_manager, "get_snapshot"):
                snapshot = goal_manager.get_snapshot()
            emit(json.dumps(snapshot or {}, ensure_ascii=False))
        except Exception as e:
            print(f"[Bridge] 목표 목록 갱신 신호 전송 실패: {e}")

    def _emit_goal_notice(self, message: str, level: str = "info"):
        """목표 UI 알림을 안전하게 전달한다."""
        signal = getattr(self, "goal_notice", None)
        emit = getattr(signal, "emit", None)
        if callable(emit):
            try:
                emit(str(message or ""), str(level or "info"))
                return
            except Exception as e:
                print(f"[Bridge] 목표 알림 신호 전송 실패: {e}")
        print(f"[Bridge] Goal notice({level}): {message}")

    def _apply_goal_update_payload(self, goal_update_payload: str):
        """LLM이 보낸 목표 업데이트를 적용하고 최신 목표 스냅샷을 UI로 보낸다."""
        goal_manager = getattr(self, "goal_manager", None)
        if not goal_manager or not goal_update_payload:
            return
        try:
            parsed = json.loads(goal_update_payload)
        except Exception as e:
            print(f"[Bridge] 목표 업데이트 JSON 파싱 실패: {e}")
            return
        if not isinstance(parsed, dict):
            return
        action = str(parsed.get("action") or "").strip().lower()
        if not parsed or not action or action == "none":
            return
        try:
            snapshot = goal_manager.apply_llm_update(parsed)
            GoalBridgeMixin._emit_goal_items_updated(self, snapshot)
        except Exception as e:
            print(f"[Bridge] 목표 업데이트 적용 실패: {e}")


    @pyqtSlot()
    def request_goal_items(self):
        """웹 UI에서 목표 목록 새로고침을 요청한다."""
        if not self.goal_manager:
            GoalBridgeMixin._emit_goal_notice(self, "목표 관리자가 아직 준비되지 않았어요.", "warning")
            return
        GoalBridgeMixin._emit_goal_items_updated(self)

    @pyqtSlot(str, str, str)
    def add_manual_goal(self, goal_type: str, title: str, reason: str):
        """웹 UI에서 수동 목표를 추가한다."""
        if not self.goal_manager:
            GoalBridgeMixin._emit_goal_notice(self, "목표를 추가할 수 없어요. 목표 관리자가 준비되지 않았어요.", "warning")
            return
        try:
            snapshot = self.goal_manager.add_manual_goal(goal_type, title, reason)
            GoalBridgeMixin._emit_goal_items_updated(self, snapshot)
        except Exception as e:
            print(f"[Bridge] 수동 목표 추가 실패: {e}")
            GoalBridgeMixin._emit_goal_notice(self, "목표 추가 중 오류가 발생했어요.", "error")

    @pyqtSlot(str, str, str)
    def update_goal_item(self, goal_id: str, title: str, reason: str):
        """웹 UI에서 수동 목표를 수정한다."""
        if not self.goal_manager:
            GoalBridgeMixin._emit_goal_notice(self, "목표를 수정할 수 없어요. 목표 관리자가 준비되지 않았어요.", "warning")
            return
        try:
            snapshot = self.goal_manager.update_goal(goal_id, {"title": title, "reason": reason})
            GoalBridgeMixin._emit_goal_items_updated(self, snapshot)
        except Exception as e:
            print(f"[Bridge] 목표 수정 실패: {e}")
            GoalBridgeMixin._emit_goal_notice(self, "목표 수정 중 오류가 발생했어요.", "error")

    @pyqtSlot(str, str)
    def complete_goal_item(self, goal_id: str, reason: str):
        """웹 UI에서 목표를 완료 처리한다."""
        if not self.goal_manager:
            GoalBridgeMixin._emit_goal_notice(self, "목표를 완료할 수 없어요. 목표 관리자가 준비되지 않았어요.", "warning")
            return
        try:
            snapshot = self.goal_manager.complete_goal(goal_id, reason)
            GoalBridgeMixin._emit_goal_items_updated(self, snapshot)
        except Exception as e:
            print(f"[Bridge] 목표 완료 실패: {e}")
            GoalBridgeMixin._emit_goal_notice(self, "목표 완료 중 오류가 발생했어요.", "error")

    @pyqtSlot(str, str)
    def cancel_goal_item(self, goal_id: str, reason: str):
        """웹 UI에서 목표를 취소 처리한다."""
        if not self.goal_manager:
            GoalBridgeMixin._emit_goal_notice(self, "목표를 취소할 수 없어요. 목표 관리자가 준비되지 않았어요.", "warning")
            return
        try:
            snapshot = self.goal_manager.cancel_goal(goal_id, reason)
            GoalBridgeMixin._emit_goal_items_updated(self, snapshot)
        except Exception as e:
            print(f"[Bridge] 목표 취소 실패: {e}")
            GoalBridgeMixin._emit_goal_notice(self, "목표 취소 중 오류가 발생했어요.", "error")
