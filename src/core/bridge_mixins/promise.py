"""
WebBridge? ?? ?? ??/?? ??.
"""
import json
import re
from datetime import datetime

from PyQt6.QtCore import pyqtSlot

from ...ai.prompt_language import resolve_prompt_language
from ...ai.promise_reminder_manager import GENERIC_PROMISE_TITLE, extract_promise_candidates
from ..i18n import I18n, get_i18n
from ..promise_runtime import (
    build_promise_nudge_prompt,
    collect_promise_ids,
    promise_fire_signature,
    prune_recent_promise_fire_signatures,
    should_suppress_duplicate_promise_fire,
)


class PromiseBridgeMixin:
    def _promise_notice_text(self, key: str) -> str:
        """현재 UI 언어에 맞는 promise 알림 문구를 읽는다."""
        language = resolve_prompt_language(settings_source=getattr(self, "settings", None))
        runtime_i18n = get_i18n()
        if runtime_i18n.language == language:
            return runtime_i18n.t(key)
        return I18n(language=language, locales_dir=runtime_i18n.locales_dir).t(key)

    def _emit_promise_saved_notice(self) -> None:
        """대화 약속 저장 완료 알림을 현재 UI 언어로 보낸다."""
        self.promise_notice.emit(PromiseBridgeMixin._promise_notice_text(self, "chat.promise.notice.saved"), "success")

    def _store_scheduled_promises(self, scheduled_promises: list | None) -> list:
        """응답 메타에 포함된 대화 약속을 저장하고 알림을 보낸다."""
        if not scheduled_promises or not self.promise_manager:
            return []

        stored = []
        for item in scheduled_promises:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "") or "").strip()
            trigger_at = str(item.get("trigger_at", "") or "").strip()
            source_excerpt = str(item.get("source_excerpt", "") or "").strip()
            if not title or not trigger_at:
                continue
            existing = self.promise_manager.find_similar_promise(
                title=title,
                trigger_at=trigger_at,
                source_excerpt=source_excerpt,
                include_statuses=("scheduled", "queued", "missed", "triggered"),
            )
            if existing:
                existing_id = ""
                existing_title = ""
                if isinstance(existing, dict):
                    existing_id = str(existing.get("id", "") or "").strip()
                    existing_title = str(existing.get("title", "") or "").strip()
                else:
                    existing_id = str(getattr(existing, "id", "") or "").strip()
                    existing_title = str(getattr(existing, "title", "") or "").strip()
                updater = getattr(self.promise_manager, "update_promise_title", None)
                if (
                    existing_id
                    and existing_title == GENERIC_PROMISE_TITLE
                    and title
                    and title != GENERIC_PROMISE_TITLE
                    and callable(updater)
                ):
                    updater(existing_id, title)
                    emit_items = getattr(self, "_emit_promise_items_updated", None)
                    if callable(emit_items):
                        emit_items()
                continue
            stored.append(
                self.promise_manager.add_promise(
                    title=title,
                    trigger_at=trigger_at,
                    source=str(item.get("source", "") or "user"),
                    source_excerpt=source_excerpt,
                )
            )

        if stored:
            PromiseBridgeMixin._emit_promise_saved_notice(self)
            emit_items = getattr(self, "_emit_promise_items_updated", None)
            if callable(emit_items):
                emit_items()
        return stored

    def _store_local_promise_candidates(
        self,
        source_text: str,
        timestamp: str,
        source: str = "user",
    ) -> list:
        """LLM 태그가 없어도 사용자 원문에서 약속을 보수적으로 추출해 저장한다."""
        if not self.promise_manager:
            return []

        candidates = extract_promise_candidates(source_text, now=timestamp, source=source)
        if not candidates:
            return []

        stored = []
        for item in candidates:
            existing = self.promise_manager.find_similar_promise(
                title=str(item.get("title", "") or "").strip(),
                trigger_at=str(item.get("trigger_at", "") or "").strip(),
                source_excerpt=str(item.get("source_excerpt", "") or "").strip(),
                include_statuses=("scheduled", "queued", "missed", "triggered"),
            )
            if existing:
                continue
            stored.append(
                self.promise_manager.add_promise(
                    title=str(item.get("title", "") or "").strip(),
                    trigger_at=str(item.get("trigger_at", "") or "").strip(),
                    source=str(item.get("source", "") or source).strip() or source,
                    source_excerpt=str(item.get("source_excerpt", "") or "").strip(),
                )
            )

        if stored:
            PromiseBridgeMixin._emit_promise_saved_notice(self)
            self._emit_promise_items_updated()
        return stored

    def _maybe_store_user_promise_candidates(self, scheduled_promises: list | None = None) -> list:
        """LLM이 약속 태그를 놓쳤을 때만 최근 사용자 원문을 fallback으로 보완한다."""
        if scheduled_promises or not self.promise_manager:
            return []

        entries = list(getattr(self, "conversation_buffer", []) or [])
        latest_user_text = ""
        latest_user_timestamp = ""
        for index in range(len(entries) - 1, -1, -1):
            item = entries[index]
            if not item or len(item) < 2:
                continue
            role = str(item[0] or "").strip().lower()
            if role != "user":
                continue
            latest_user_text = str(item[1] or "").strip()
            latest_user_timestamp = str(item[2] or "").strip() if len(item) >= 3 and item[2] else ""
            break

        if not latest_user_text:
            return []
        return self._store_local_promise_candidates(
            latest_user_text,
            latest_user_timestamp or self._now_timestamp(),
            source="user",
        )

    def _maybe_store_assistant_promise_candidates(self, source_text: str) -> list:
        """LLM이 약속 태그를 놓쳤을 때만 assistant 응답에서 제한적으로 fallback을 시도한다."""
        if not self.promise_manager:
            return []

        entries = list(getattr(self, "conversation_buffer", []) or [])
        latest_user_index = -1
        latest_user_text = ""
        latest_user_timestamp = ""
        previous_assistant_text = ""
        previous_assistant_timestamp = ""
        for index in range(len(entries) - 1, -1, -1):
            item = entries[index]
            if not item or len(item) < 2:
                continue
            role = str(item[0] or "").strip().lower()
            if role != "user":
                continue
            latest_user_index = index
            latest_user_text = str(item[1] or "").strip()
            latest_user_timestamp = str(item[2] or "").strip() if len(item) >= 3 and item[2] else ""
            break

        if latest_user_index > 0:
            for index in range(latest_user_index - 1, -1, -1):
                item = entries[index]
                if not item or len(item) < 2:
                    continue
                role = str(item[0] or "").strip().lower()
                if role != "assistant":
                    continue
                previous_assistant_text = str(item[1] or "").strip()
                previous_assistant_timestamp = str(item[2] or "").strip() if len(item) >= 3 and item[2] else ""
                break

        if not latest_user_text:
            return []

        normalized = re.sub(r"\s+", " ", latest_user_text).strip().lower()
        explicit_schedule_request = (
            (
                ("예정" in normalized)
                or ("약속" in normalized)
                or ("리마인드" in normalized)
                or ("예약" in normalized)
                or ("일정" in normalized)
            )
            and (
                ("잡아" in normalized)
                or ("등록" in normalized)
                or ("저장" in normalized)
                or ("추가" in normalized)
                or ("만들" in normalized)
            )
        )
        if not explicit_schedule_request:
            negative_tokens = ("아니", "싫", "말고", "안 할", "안할", "못 하", "못할")
            acceptance_tokens = (
                "응",
                "그래",
                "좋아",
                "그럴래",
                "알겠",
                "오케이",
                "ㅇㅋ",
                "콜",
                "하자",
                "딱 하자",
            )
            user_acceptance = (
                not any(token in latest_user_text for token in negative_tokens)
                and any(token in latest_user_text for token in acceptance_tokens)
            )
            user_defined_time = bool(
                extract_promise_candidates(
                    latest_user_text,
                    now=latest_user_timestamp or self._now_timestamp(),
                    source="user",
                )
            )
            current_assistant_candidates = extract_promise_candidates(
                source_text,
                now=latest_user_timestamp or self._now_timestamp(),
                source="assistant",
            )
            previous_assistant_candidates = extract_promise_candidates(
                previous_assistant_text,
                now=previous_assistant_timestamp or latest_user_timestamp or self._now_timestamp(),
                source="assistant",
            ) if previous_assistant_text else []
            assistant_confirmation = any(
                token in source_text
                for token in (
                    "알겠",
                    "불러드릴게",
                    "알려드릴게",
                    "시간 되면",
                    "약속",
                    "그때",
                    "이따",
                )
            )
            if user_defined_time:
                return []
            if user_acceptance and (current_assistant_candidates or (assistant_confirmation and previous_assistant_candidates)):
                if current_assistant_candidates:
                    return self._store_local_promise_candidates(
                        source_text,
                        latest_user_timestamp or self._now_timestamp(),
                        source="assistant",
                    )
                return self._store_local_promise_candidates(
                    previous_assistant_text,
                    previous_assistant_timestamp or latest_user_timestamp or self._now_timestamp(),
                    source="assistant",
                )
            return []

        base_timestamp = latest_user_timestamp or self._now_timestamp()
        return self._store_local_promise_candidates(source_text, base_timestamp, source="assistant")

    def _collect_promise_ids(self, items: list | None) -> list[str]:
        """저장 결과에서 유효한 약속 id만 추출한다."""
        return collect_promise_ids(items)

    def _remember_tracked_promise_ids(self, reminder_ids: list[str] | None) -> None:
        """최근 요청 턴에서 생성된 약속 id 목록을 payload에 기록한다."""
        if not isinstance(self._last_request_payload, dict):
            return
        unique_ids: list[str] = []
        for reminder_id in reminder_ids or []:
            normalized = str(reminder_id or "").strip()
            if normalized and normalized not in unique_ids:
                unique_ids.append(normalized)
        self._last_request_payload["promise_ids"] = unique_ids

    def _delete_tracked_promises_for_retry(self) -> list[str]:
        """리롤/수정 전에 직전 턴에서 생성한 약속만 제거한다."""
        payload = self._last_request_payload if isinstance(self._last_request_payload, dict) else None
        if payload is None:
            return []

        tracked_ids = payload.get("promise_ids") or []
        if not isinstance(tracked_ids, list):
            tracked_ids = []
        payload["promise_ids"] = []

        if not tracked_ids or not self.promise_manager:
            return []

        removed_ids: list[str] = []
        for reminder_id in tracked_ids:
            normalized = str(reminder_id or "").strip()
            if not normalized:
                continue
            if self.promise_manager.delete_promise(normalized):
                removed_ids.append(normalized)

        if removed_ids:
            emit_items = getattr(self, "_emit_promise_items_updated", None)
            if callable(emit_items):
                emit_items()
        return removed_ids

    def _current_promise_fire_time(self) -> datetime:
        """중복 발화 억제 계산에 사용할 현재 시각을 반환한다."""
        return datetime.now()

    def _promise_fire_signature(self, payload: dict | None) -> str:
        """같은 예약 발화인지 판별할 간단한 서명을 만든다."""
        return promise_fire_signature(payload)

    def _prune_recent_promise_fire_signatures(self, now_dt: datetime | None = None) -> None:
        """최근 발화 서명 목록에서 만료된 항목을 정리한다."""
        current = now_dt or self._current_promise_fire_time()
        source = getattr(self, "_recent_promise_fire_signatures", None)
        self._recent_promise_fire_signatures = prune_recent_promise_fire_signatures(source, current)

    def _should_suppress_duplicate_promise_fire(self, payload: dict | None) -> bool:
        """이미 진행/대기/최근 발화한 동일 예약이면 중복 발화를 막는다."""
        now_dt = self._current_promise_fire_time()
        self._prune_recent_promise_fire_signatures(now_dt)
        return should_suppress_duplicate_promise_fire(
            payload,
            active_signature=str(getattr(self, "_active_promise_signature", "") or "").strip(),
            queued_payloads=list(getattr(self, "promise_run_queue", []) or []),
            recent_signatures=getattr(self, "_recent_promise_fire_signatures", None),
            now_dt=now_dt,
        )

    def _dismiss_duplicate_promise_payload(self, payload: dict | None) -> bool:
        """중복으로 판단된 예약은 예정 목록에서 제거하고 건너뛴다."""
        reminder_id = str((payload or {}).get("id", "") or "").strip()
        if not reminder_id or not self.promise_manager:
            return False
        removed = bool(self.promise_manager.delete_promise(reminder_id))
        if removed:
            emit_items = getattr(self, "_emit_promise_items_updated", None)
            if callable(emit_items):
                emit_items()
        return removed

    def _mark_promise_fire_started(self, payload: dict | None) -> None:
        """실제로 발화를 시작한 예약 서명을 기억한다."""
        signature = self._promise_fire_signature(payload)
        self._active_promise_signature = signature or None
        if not signature:
            return
        self._prune_recent_promise_fire_signatures()
        self._recent_promise_fire_signatures[signature] = self._current_promise_fire_time()

    def _enqueue_due_promise(self, payload: dict) -> None:
        """현재 생성 중이면 약속 발화를 큐에 넣고, 아니면 즉시 시작한다."""
        if self._should_suppress_duplicate_promise_fire(payload):
            self._dismiss_duplicate_promise_payload(payload)
            return
        reminder_id = str((payload or {}).get("id", "") or "").strip()
        if self.worker and self.worker.isRunning():
            promise_manager = getattr(self, "promise_manager", None)
            if promise_manager and reminder_id:
                promise_manager.set_status(reminder_id, "queued")
            self.promise_run_queue.append(payload)
            emit_items = getattr(self, "_emit_promise_items_updated", None)
            if callable(emit_items):
                emit_items()
            return
        self._start_promise_ai_worker(payload)

    def _drain_promise_queue_if_idle(self) -> None:
        """유휴 상태가 되면 대기 중인 약속 발화를 하나 실행한다."""
        if self.worker and self.worker.isRunning():
            return
        if not self.promise_run_queue:
            return
        payload = self.promise_run_queue.pop(0)
        self._start_promise_ai_worker(payload)

    def _start_promise_ai_worker(self, payload: dict) -> None:
        """대화 약속 기반 프롬프트로 응답 생성을 시작한다."""
        reminder_id = str((payload or {}).get("id", "") or "").strip()
        if self.promise_manager and reminder_id:
            self.promise_manager.set_status(reminder_id, "triggered")
        self._mark_promise_fire_started(payload)
        self._active_promise_id = reminder_id or None
        self._emit_promise_items_updated()
        language = self._prompt_language()
        title = str((payload or {}).get("title", "") or "").strip() or {
            "ko": "약속",
            "en": "promise",
            "ja": "約束",
        }.get(language, "약속")
        source_excerpt = str((payload or {}).get("source_excerpt", "") or "").strip()
        prompt = build_promise_nudge_prompt(
            language=language,
            title=title,
            source_excerpt=source_excerpt,
        )
        timestamp = self._now_timestamp()
        self._start_ai_worker(self._with_prompt_time(timestamp, prompt))

    def _emit_promise_items_updated(self) -> None:
        """현재 예정 목록을 JSON으로 UI에 전달한다."""
        if not self.promise_manager:
            self.promise_items_updated.emit("[]")
            return
        self.promise_items_updated.emit(
            json.dumps(
                self.promise_manager.list_promise_dicts(
                    include_statuses=("scheduled", "queued", "missed"),
                ),
                ensure_ascii=False,
            )
        )

    def _poll_promise_reminders(self) -> None:
        """도래한 대화 약속을 찾아 즉시 실행하거나 큐에 넣는다."""
        if not self.promise_manager:
            return

        due_items, _, _ = self.promise_manager.refresh_overdue_statuses()
        if not due_items:
            self._emit_promise_items_updated()
            return

        for item in due_items:
            self._enqueue_due_promise(item.to_public_dict())

    @pyqtSlot()
    def request_promise_items(self):
        """웹 UI에서 예정 목록 새로고침을 요청한다."""
        self._emit_promise_items_updated()

    @pyqtSlot(str)
    def delete_promise_reminder(self, reminder_id: str):
        """웹 UI에서 지정한 대화 약속을 삭제한다."""
        if not self.promise_manager:
            return
        removed = self.promise_manager.delete_promise(reminder_id)
        if removed:
            self._emit_promise_items_updated()
