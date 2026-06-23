from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
import uuid

from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data


PROACTIVE_TIMEZONE = timezone(timedelta(hours=9))
ALLOWED_COOLDOWN_KEYS = {
    "short-followup",
    "quiet-checkin",
    "topic-reopen",
    "task-momentum",
    "global-proactive",
}
COOLDOWN_KEY_ORDER = [
    "short-followup",
    "quiet-checkin",
    "topic-reopen",
    "task-momentum",
    "global-proactive",
]
DEFAULT_COOLDOWN_KEY = "global-proactive"
DEFAULT_COOLDOWN_MINUTES = 20
MIN_TRIGGER_SECONDS = 60
MAX_TRIGGER_SECONDS = 60 * 60
DUE_WINDOW_MINUTES = 10


def _coerce_datetime(value: str | datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = datetime.now(PROACTIVE_TIMEZONE)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=PROACTIVE_TIMEZONE)
    return parsed.astimezone(PROACTIVE_TIMEZONE)


def normalize_cooldown_key(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in ALLOWED_COOLDOWN_KEYS else DEFAULT_COOLDOWN_KEY


def _clean_text(value: str | None) -> str:
    return str(value or "").strip()


@dataclass
class ProactiveConversation:
    id: str
    trigger_at: str
    title: str
    generation_prompt: str
    source_excerpt: str
    reason: str
    cooldown_key: str
    status: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_public_dict(self) -> dict:
        return self.to_dict()

    @classmethod
    def from_dict(cls, payload: dict) -> "ProactiveConversation":
        return cls(**payload)


class ProactiveConversationManager:
    """선제 대화 예약 저장과 상태 전이를 관리한다."""

    def __init__(
        self,
        storage_file: str | Path | None = None,
        *,
        cooldown_minutes: int = DEFAULT_COOLDOWN_MINUTES,
    ):
        target = storage_file if storage_file is not None else "proactive_conversations.json"
        self.storage_file = resolve_user_storage_path(target)
        self.cooldown_minutes = max(1, int(cooldown_minutes or DEFAULT_COOLDOWN_MINUTES))
        self.items: List[ProactiveConversation] = []
        self.load()

    def load(self) -> None:
        try:
            data = load_json_data(self.storage_file)
        except Exception:
            self.items = []
            return

        raw_items = data.get("items", []) if isinstance(data, dict) else []
        self.items = [
            ProactiveConversation.from_dict(item)
            for item in raw_items
            if isinstance(item, dict)
        ]

    def save(self) -> None:
        save_json_data(
            self.storage_file,
            {"items": [item.to_dict() for item in self.items]},
        )

    def _is_key_on_cooldown(self, cooldown_key: str, now_dt: datetime) -> bool:
        cooldown_seconds = self.cooldown_minutes * 60
        for item in self.items:
            if item.status != "completed":
                continue
            try:
                updated_at = _coerce_datetime(item.updated_at or item.created_at)
            except Exception:
                continue
            elapsed = (now_dt - updated_at).total_seconds()
            if elapsed < 0 or elapsed >= cooldown_seconds:
                continue
            if item.cooldown_key == cooldown_key:
                return True
        return False

    def _has_recent_activity_for_key(self, cooldown_key: str, now_dt: datetime) -> bool:
        return self._is_key_on_cooldown(cooldown_key, now_dt)

    def available_cooldown_keys(self, now: str | datetime | None = None) -> list[str]:
        """현재 예약 생성에 사용할 수 있는 선제 발화 방식 키 목록을 반환한다."""
        now_dt = _coerce_datetime(now)
        return [
            key
            for key in COOLDOWN_KEY_ORDER
            if not self._is_key_on_cooldown(key, now_dt)
        ]

    def _is_valid_trigger(self, trigger_at: str, now_dt: datetime) -> bool:
        try:
            trigger_dt = _coerce_datetime(trigger_at)
        except Exception:
            return False
        delta_seconds = (trigger_dt - now_dt).total_seconds()
        return MIN_TRIGGER_SECONDS <= delta_seconds <= MAX_TRIGGER_SECONDS

    def add_proactive_conversation(
        self,
        *,
        trigger_at: str,
        title: str,
        generation_prompt: str,
        source_excerpt: str = "",
        reason: str = "",
        cooldown_key: str = DEFAULT_COOLDOWN_KEY,
        now: str | datetime | None = None,
    ) -> ProactiveConversation | None:
        now_dt = _coerce_datetime(now)
        normalized_key = normalize_cooldown_key(cooldown_key)
        normalized_title = _clean_text(title)
        normalized_prompt = _clean_text(generation_prompt)
        normalized_trigger = _clean_text(trigger_at)
        if not normalized_title or not normalized_prompt or not normalized_trigger:
            return None
        if not self._is_valid_trigger(normalized_trigger, now_dt):
            return None
        if self._has_recent_activity_for_key(normalized_key, now_dt):
            return None

        timestamp = now_dt.isoformat(timespec="seconds")
        created = ProactiveConversation(
            id=str(uuid.uuid4()),
            trigger_at=_coerce_datetime(normalized_trigger).isoformat(timespec="seconds"),
            title=normalized_title,
            generation_prompt=normalized_prompt,
            source_excerpt=_clean_text(source_excerpt),
            reason=_clean_text(reason),
            cooldown_key=normalized_key,
            status="scheduled",
            created_at=timestamp,
            updated_at=timestamp,
        )
        self.items.append(created)
        self.items.sort(key=lambda item: item.trigger_at)
        self.save()
        return created

    def list_items(self, include_statuses: tuple[str, ...] | list[str] | None = None) -> List[ProactiveConversation]:
        allowed = None
        if include_statuses:
            allowed = {str(status or "").strip() for status in include_statuses if str(status or "").strip()}
        return [
            item
            for item in sorted(self.items, key=lambda entry: entry.trigger_at)
            if allowed is None or item.status in allowed
        ]

    def list_dicts(self, include_statuses: tuple[str, ...] | list[str] | None = None) -> list[dict]:
        return [item.to_public_dict() for item in self.list_items(include_statuses=include_statuses)]

    def set_status(self, item_id: str, status: str, now: str | datetime | None = None) -> bool:
        normalized_id = _clean_text(item_id)
        normalized_status = _clean_text(status)
        if not normalized_id or not normalized_status:
            return False
        timestamp = _coerce_datetime(now).isoformat(timespec="seconds")
        for item in self.items:
            if item.id != normalized_id:
                continue
            item.status = normalized_status
            item.updated_at = timestamp
            self.save()
            return True
        return False

    def delete_item(self, item_id: str) -> bool:
        before = len(self.items)
        self.items = [item for item in self.items if item.id != item_id]
        changed = len(self.items) != before
        if changed:
            self.save()
        return changed

    def cancel_scheduled(self, now: str | datetime | None = None) -> list[ProactiveConversation]:
        timestamp = _coerce_datetime(now).isoformat(timespec="seconds")
        cancelled: list[ProactiveConversation] = []
        for item in self.items:
            if item.status not in {"scheduled", "queued"}:
                continue
            item.status = "cancelled"
            item.updated_at = timestamp
            cancelled.append(item)
        if cancelled:
            self.save()
        return cancelled

    def refresh_due_statuses(
        self,
        now: str | datetime | None = None,
    ) -> tuple[list[ProactiveConversation], list[ProactiveConversation]]:
        current = _coerce_datetime(now)
        due_items: list[ProactiveConversation] = []
        expired_items: list[ProactiveConversation] = []
        changed = False

        for item in self.items:
            if item.status not in {"scheduled", "queued"}:
                continue
            try:
                trigger_dt = _coerce_datetime(item.trigger_at)
            except Exception:
                item.status = "expired"
                item.updated_at = current.isoformat(timespec="seconds")
                expired_items.append(item)
                changed = True
                continue
            overdue_minutes = (current - trigger_dt).total_seconds() / 60.0
            if overdue_minutes < 0:
                continue
            if overdue_minutes < DUE_WINDOW_MINUTES:
                due_items.append(item)
                continue
            item.status = "expired"
            item.updated_at = current.isoformat(timespec="seconds")
            expired_items.append(item)
            changed = True

        if changed:
            self.save()
        return due_items, expired_items
