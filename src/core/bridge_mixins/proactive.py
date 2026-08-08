"""
WebBridge의 선제 대화 예약과 실행 흐름을 담당한다.
"""
import json
from datetime import datetime

from PyQt6.QtCore import pyqtSlot

from ...ai.persona_names import resolve_prompt_persona_names
from ...ai.response_contract import is_proactive_conversation_enabled
from ..proactive_conversation_runtime import (
    build_proactive_conversation_prompt,
    proactive_fire_signature,
    prune_recent_proactive_fire_signatures,
    should_suppress_duplicate_proactive_fire,
)


def _collect_proactive_ids(items: list | None) -> list[str]:
    collected: list[str] = []
    for item in items or []:
        proactive_id = ""
        if isinstance(item, dict):
            proactive_id = str(item.get("id", "") or "").strip()
        else:
            proactive_id = str(getattr(item, "id", "") or "").strip()
        if proactive_id:
            collected.append(proactive_id)
    return collected


class ProactiveBridgeMixin:
    def _is_proactive_conversation_enabled(self) -> bool:
        """현재 설정에서 선제 대화 기능이 켜져 있는지 확인한다."""
        return is_proactive_conversation_enabled(getattr(self, "settings", None))

    def refresh_proactive_settings(self) -> None:
        """선제 대화 설정이 꺼져 있으면 대기 중인 예약을 즉시 정리한다."""
        if self._is_proactive_conversation_enabled():
            return
        if not self.proactive_manager:
            self.proactive_run_queue = []
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
            return
        self._cancel_pending_proactive_conversations_for_user_message()

    def _emit_proactive_items_updated(self) -> None:
        """웹 UI가 표시할 선제 대화 예약 목록을 전송한다."""
        signal = getattr(self, "proactive_items_updated", None)
        emit = getattr(signal, "emit", None)
        if not callable(emit):
            return
        manager = getattr(self, "proactive_manager", None)
        if not manager or not self._is_proactive_conversation_enabled():
            emit("[]")
            return
        payload = manager.list_dicts(include_statuses=("scheduled", "queued"))
        emit(json.dumps(payload, ensure_ascii=False))

    def _store_proactive_conversations(self, candidates: list | None, *, suppress: bool = False) -> list:
        """LLM 응답 메타에 포함된 선제 대화 예약을 저장한다."""
        if suppress or not candidates or not self.proactive_manager or not self._is_proactive_conversation_enabled():
            return []

        stored = []
        for item in candidates:
            if not isinstance(item, dict):
                continue
            trigger_at = str(item.get("trigger_at", "") or "").strip()
            title = str(item.get("title", "") or "").strip()
            generation_prompt = str(item.get("generation_prompt", "") or "").strip()
            if not trigger_at or not title or not generation_prompt:
                continue
            created = self.proactive_manager.add_proactive_conversation(
                trigger_at=trigger_at,
                title=title,
                generation_prompt=generation_prompt,
                source_excerpt=str(item.get("source_excerpt", "") or "").strip(),
                reason=str(item.get("reason", "") or "").strip(),
                cooldown_key=str(item.get("cooldown_key", "") or "").strip(),
            )
            if created:
                stored.append(created)
        if stored:
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
        return stored

    def _remember_tracked_proactive_ids(self, proactive_ids: list[str] | None) -> None:
        """최근 요청 턴에서 생성된 선제 대화 id 목록을 payload에 기록한다."""
        if not isinstance(self._last_request_payload, dict):
            return
        unique_ids: list[str] = []
        for proactive_id in proactive_ids or []:
            normalized = str(proactive_id or "").strip()
            if normalized and normalized not in unique_ids:
                unique_ids.append(normalized)
        self._last_request_payload["proactive_ids"] = unique_ids

    def _delete_tracked_proactive_for_retry(self) -> list[str]:
        """리롤/수정 전에 직전 턴에서 생성한 선제 대화 예약만 제거한다."""
        payload = self._last_request_payload if isinstance(self._last_request_payload, dict) else None
        if payload is None:
            return []

        tracked_ids = payload.get("proactive_ids") or []
        if not isinstance(tracked_ids, list):
            tracked_ids = []
        payload["proactive_ids"] = []

        if not tracked_ids or not self.proactive_manager:
            return []

        removed_ids: list[str] = []
        for proactive_id in tracked_ids:
            normalized = str(proactive_id or "").strip()
            if normalized and self.proactive_manager.delete_item(normalized):
                removed_ids.append(normalized)
        if removed_ids:
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
        return removed_ids

    def _cancel_pending_proactive_conversations_for_user_message(self) -> list:
        """사용자가 새 메시지를 보내면 아직 실행되지 않은 선제 대화를 취소한다."""
        if not self.proactive_manager:
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
            return []
        queued_payloads = list(getattr(self, "proactive_run_queue", []) or [])
        self.proactive_run_queue = []
        cancelled = self.proactive_manager.cancel_scheduled()
        for payload in queued_payloads:
            proactive_id = str((payload or {}).get("id", "") or "").strip()
            if proactive_id:
                self.proactive_manager.set_status(proactive_id, "cancelled")
        if cancelled or queued_payloads:
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
        return cancelled

    def _current_proactive_fire_time(self) -> datetime:
        """중복 발화 억제 계산에 사용할 현재 시각을 반환한다."""
        return datetime.now()

    def _proactive_fire_signature(self, payload: dict | None) -> str:
        """같은 선제 대화 실행인지 판별할 간단한 서명을 만든다."""
        return proactive_fire_signature(payload)

    def _prune_recent_proactive_fire_signatures(self, now_dt: datetime | None = None) -> None:
        """최근 선제 대화 실행 서명 목록에서 만료된 항목을 정리한다."""
        current = now_dt or self._current_proactive_fire_time()
        source = getattr(self, "_recent_proactive_fire_signatures", None)
        self._recent_proactive_fire_signatures = prune_recent_proactive_fire_signatures(source, current)

    def _should_suppress_duplicate_proactive_fire(self, payload: dict | None) -> bool:
        """이미 진행/대기/최근 실행한 동일 예약이면 중복 실행을 막는다."""
        now_dt = self._current_proactive_fire_time()
        self._prune_recent_proactive_fire_signatures(now_dt)
        return should_suppress_duplicate_proactive_fire(
            payload,
            active_signature=str(getattr(self, "_active_proactive_signature", "") or "").strip(),
            queued_payloads=list(getattr(self, "proactive_run_queue", []) or []),
            recent_signatures=getattr(self, "_recent_proactive_fire_signatures", None),
            now_dt=now_dt,
        )

    def _mark_proactive_fire_started(self, payload: dict | None) -> None:
        """실제로 선제 대화 실행을 시작한 서명을 기억한다."""
        signature = self._proactive_fire_signature(payload)
        self._active_proactive_signature = signature or None
        if not signature:
            return
        self._prune_recent_proactive_fire_signatures()
        self._recent_proactive_fire_signatures[signature] = self._current_proactive_fire_time()

    def _enqueue_due_proactive_conversation(self, payload: dict) -> None:
        """현재 생성 중이면 선제 대화를 큐에 넣고, 아니면 즉시 시작한다."""
        proactive_id = str((payload or {}).get("id", "") or "").strip()
        if proactive_id:
            for queued in list(getattr(self, "proactive_run_queue", []) or []):
                queued_id = str((queued or {}).get("id", "") or "").strip()
                if queued_id == proactive_id:
                    return
        if self._should_suppress_duplicate_proactive_fire(payload):
            if self.proactive_manager and proactive_id:
                self.proactive_manager.set_status(proactive_id, "cancelled")
                ProactiveBridgeMixin._emit_proactive_items_updated(self)
            return
        if self.worker and self.worker.isRunning():
            self.proactive_run_queue.append(payload)
            if self.proactive_manager and proactive_id:
                self.proactive_manager.set_status(proactive_id, "queued")
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
            return
        self._start_proactive_ai_worker(payload)

    def _drain_proactive_queue_if_idle(self) -> None:
        """유휴 상태가 되면 대기 중인 선제 대화를 하나 실행한다."""
        if not self._is_proactive_conversation_enabled():
            self.refresh_proactive_settings()
            return
        if self.worker and self.worker.isRunning():
            return
        if not self.proactive_run_queue:
            return
        payload = self.proactive_run_queue.pop(0)
        self._start_proactive_ai_worker(payload)

    def _start_proactive_ai_worker(self, payload: dict) -> None:
        """선제 대화 생성 프롬프트로 응답 생성을 시작한다."""
        proactive_id = str((payload or {}).get("id", "") or "").strip()
        if not self._is_proactive_conversation_enabled():
            if self.proactive_manager and proactive_id:
                self.proactive_manager.set_status(proactive_id, "cancelled")
                ProactiveBridgeMixin._emit_proactive_items_updated(self)
            return
        if self.proactive_manager and proactive_id:
            self.proactive_manager.set_status(proactive_id, "triggered")
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
        self._mark_proactive_fire_started(payload)
        self._active_proactive_id = proactive_id or None
        language = self._prompt_language()
        prompt = build_proactive_conversation_prompt(
            language=language,
            title=str((payload or {}).get("title", "") or "").strip(),
            generation_prompt=str((payload or {}).get("generation_prompt", "") or "").strip(),
            reason=str((payload or {}).get("reason", "") or "").strip(),
            user_name=resolve_prompt_persona_names(
                settings_source=getattr(self, "settings", None),
                language=language,
            ).user,
        )
        timestamp = self._now_timestamp()
        message_with_time = self._with_prompt_time(timestamp, prompt)
        self._last_request_payload = {
            "type": "proactive",
            "message": prompt,
            "message_with_time": message_with_time,
            "images": [],
            "proactive_id": proactive_id,
            "include_life_record_context": False,
        }
        self._start_ai_worker(message_with_time)

    def _poll_proactive_conversations(self) -> None:
        """도래한 선제 대화 예약을 찾아 즉시 실행하거나 큐에 넣는다."""
        if not self.proactive_manager:
            return
        if not self._is_proactive_conversation_enabled():
            self.refresh_proactive_settings()
            return

        due_items, expired_items = self.proactive_manager.refresh_due_statuses()
        if expired_items:
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
        for item in due_items:
            if isinstance(item, dict):
                payload = item
            else:
                payload = item.to_public_dict()
            self._enqueue_due_proactive_conversation(payload)

    def _collect_proactive_ids(self, items: list | None) -> list[str]:
        """저장 결과에서 유효한 선제 대화 id만 추출한다."""
        return _collect_proactive_ids(items)

    @pyqtSlot()
    def request_proactive_conversation_items(self):
        """웹 UI에서 현재 선제 대화 예약 목록을 요청한다."""
        ProactiveBridgeMixin._emit_proactive_items_updated(self)

    @pyqtSlot(str)
    def delete_proactive_conversation(self, proactive_id: str):
        """웹 UI에서 선택한 선제 대화 예약을 삭제한다."""
        normalized = str(proactive_id or "").strip()
        if not normalized or not self.proactive_manager:
            return
        if self.proactive_manager.delete_item(normalized):
            ProactiveBridgeMixin._emit_proactive_items_updated(self)
