from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import List
import uuid

from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data


@dataclass
class PromiseReminder:
    id: str
    title: str
    trigger_at: str
    source: str
    source_excerpt: str
    status: str
    created_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    def to_public_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "trigger_at": self.trigger_at,
            "source": self.source,
            "source_excerpt": self.source_excerpt,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "PromiseReminder":
        return cls(**payload)


class PromiseReminderManager:
    """대화 약속 저장/조회 전용 매니저."""

    def __init__(self, storage_file: str | Path | None = None):
        target = storage_file if storage_file is not None else "promise_reminders.json"
        self.storage_file = resolve_user_storage_path(target)
        self.items: List[PromiseReminder] = []
        self.load()

    def load(self) -> None:
        try:
            data = load_json_data(self.storage_file)
        except Exception:
            self.items = []
            return

        raw_items = data.get("items", []) if isinstance(data, dict) else []
        self.items = [
            PromiseReminder.from_dict(item)
            for item in raw_items
            if isinstance(item, dict)
        ]

    def save(self) -> None:
        save_json_data(
            self.storage_file,
            {"items": [item.to_dict() for item in self.items]},
        )

    def add_promise(
        self,
        *,
        title: str,
        trigger_at: str,
        source: str,
        source_excerpt: str = "",
    ) -> PromiseReminder:
        created = PromiseReminder(
            id=str(uuid.uuid4()),
            title=str(title or "").strip(),
            trigger_at=str(trigger_at or "").strip(),
            source=str(source or "").strip() or "user",
            source_excerpt=str(source_excerpt or "").strip(),
            status="scheduled",
            created_at=datetime.now().isoformat(),
        )
        self.items.append(created)
        self.items.sort(key=lambda item: item.trigger_at)
        self.save()
        return created

    def list_promises(self) -> List[PromiseReminder]:
        return list(sorted(self.items, key=lambda item: item.trigger_at))

    def list_promise_dicts(self, include_statuses: tuple[str, ...] | list[str] | None = None) -> list[dict]:
        allowed_statuses = None
        if include_statuses:
            allowed_statuses = {str(status or "").strip() for status in include_statuses if str(status or "").strip()}
        return [
            item.to_public_dict()
            for item in self.list_promises()
            if allowed_statuses is None or item.status in allowed_statuses
        ]

    def delete_promise(self, reminder_id: str) -> bool:
        before = len(self.items)
        self.items = [item for item in self.items if item.id != reminder_id]
        changed = len(self.items) != before
        if changed:
            self.save()
        return changed

    def set_status(self, reminder_id: str, status: str) -> bool:
        for item in self.items:
            if item.id == reminder_id:
                item.status = str(status or "").strip() or item.status
                self.save()
                return True
        return False

    def refresh_overdue_statuses(
        self,
        now: str | datetime | None = None,
    ) -> tuple[List[PromiseReminder], List[PromiseReminder], List[PromiseReminder]]:
        current = datetime.fromisoformat(now) if isinstance(now, str) else now
        if current is None:
            current = datetime.now().astimezone()

        due_items: List[PromiseReminder] = []
        missed_items: List[PromiseReminder] = []
        expired_items: List[PromiseReminder] = []
        changed = False

        for item in self.items:
            if item.status != "scheduled":
                continue

            trigger_at = datetime.fromisoformat(item.trigger_at)
            overdue_minutes = (current - trigger_at).total_seconds() / 60.0
            if overdue_minutes < 0:
                continue
            if overdue_minutes <= 10:
                due_items.append(item)
                continue
            if overdue_minutes <= 60:
                item.status = "missed"
                missed_items.append(item)
                changed = True
                continue
            item.status = "expired"
            expired_items.append(item)
            changed = True

        if changed:
            self.save()

        return due_items, missed_items, expired_items
