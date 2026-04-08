from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
import re
import uuid

from ..core.app_paths import load_json_data, resolve_user_storage_path, save_json_data


PROMISE_TIMEZONE = timezone(timedelta(hours=9))
GENERIC_PROMISE_TITLE = "대화 약속"
RELATIVE_PROMISE_PATTERNS = (
    re.compile(r"(?P<amount>\d+)\s*(?P<unit>분|시간|일)\s*(?:뒤|후)"),
    re.compile(r"(?P<amount>\d+)\s*(?P<unit>분|시간)\s*만"),
)
ABSOLUTE_PROMISE_PATTERN = re.compile(
    r"(?:(?P<day>오늘|내일|모레)\s*)?"
    r"(?:(?P<ampm>오전|오후)\s*)?"
    r"(?P<hour>\d{1,2})\s*시"
    r"(?:\s*(?P<minute>\d{1,2})\s*분?)?"
)


def _coerce_base_datetime(now: str | datetime | None = None) -> datetime:
    if isinstance(now, datetime):
        base = now
    elif isinstance(now, str):
        parsed = None
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(now, fmt)
                break
            except ValueError:
                continue
        base = parsed or datetime.fromisoformat(now)
    else:
        base = datetime.now(PROMISE_TIMEZONE)

    if base.tzinfo is None:
        return base.replace(tzinfo=PROMISE_TIMEZONE)
    return base.astimezone(PROMISE_TIMEZONE)


def _normalize_promise_text(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "").strip())
    cleaned = cleaned.strip(" .,!?:;\"'`~")
    return cleaned


def _infer_promise_title(text: str) -> str:
    _ = text
    return GENERIC_PROMISE_TITLE


def _has_promise_intent(text: str, source: str = "user") -> bool:
    normalized = _normalize_promise_text(text)
    if not normalized:
        return False

    negative_markers = (
        "안됐",
        "안 됐",
        "도 안",
        "밖에 안",
        "아직",
        "벌써",
        "잖아",
        "인데",
        "였는데",
    )
    if any(marker in normalized for marker in negative_markers):
        return False

    positive_markers = (
        "하자",
        "할게",
        "하겠다",
        "해야",
        "할래",
        "다시",
        "쉬고",
        "쉬자",
        "쓸게",
        "써야",
        "시작",
        "깨워",
        "불러",
        "알려",
        "맞춰",
        "그때",
        "있다가",
        "어때요",
        "하죠",
        "거예요",
        "드릴게",
    )
    if any(marker in normalized for marker in positive_markers):
        return True

    if source == "assistant" and ("?" in text or "?" in normalized):
        return True
    return False


def _parse_relative_trigger(text: str, base_dt: datetime) -> datetime | None:
    earliest: tuple[int, datetime] | None = None
    for pattern in RELATIVE_PROMISE_PATTERNS:
        for match in pattern.finditer(text):
            amount = int(match.group("amount"))
            unit = match.group("unit")
            if amount <= 0:
                continue
            if unit == "분":
                trigger_at = base_dt + timedelta(minutes=amount)
            elif unit == "시간":
                trigger_at = base_dt + timedelta(hours=amount)
            else:
                trigger_at = base_dt + timedelta(days=amount)
            if earliest is None or match.start() < earliest[0]:
                earliest = (match.start(), trigger_at)
    return earliest[1] if earliest else None


def _parse_absolute_trigger(text: str, base_dt: datetime) -> datetime | None:
    match = ABSOLUTE_PROMISE_PATTERN.search(text)
    if not match:
        return None

    hour = int(match.group("hour"))
    minute = int(match.group("minute") or 0)
    ampm = str(match.group("ampm") or "").strip()
    day_token = str(match.group("day") or "").strip()

    if ampm == "오후" and hour < 12:
        hour += 12
    elif ampm == "오전" and hour == 12:
        hour = 0

    day_offset = {"": 0, "오늘": 0, "내일": 1, "모레": 2}.get(day_token, 0)
    if day_token:
        candidate = base_dt.replace(hour=hour % 24, minute=minute, second=0, microsecond=0) + timedelta(days=day_offset)
        return candidate

    interpreted_hours = {hour % 24}
    if not ampm:
        if 1 <= hour <= 11:
            interpreted_hours.add((hour % 12) + 12)
        elif hour == 12:
            interpreted_hours.update({0, 12})

    candidates: list[datetime] = []
    for interpreted_hour in interpreted_hours:
        candidate = base_dt.replace(hour=interpreted_hour % 24, minute=minute, second=0, microsecond=0)
        if candidate <= base_dt:
            candidate += timedelta(days=1)
        candidates.append(candidate)

    if not candidates:
        return None
    return min(candidates)


def extract_promise_candidates(text: str, now: str | datetime | None = None, source: str = "user") -> list[dict]:
    normalized = _normalize_promise_text(text)
    if not normalized:
        return []
    if not _has_promise_intent(normalized, source=source):
        return []

    base_dt = _coerce_base_datetime(now)
    trigger_at = _parse_relative_trigger(normalized, base_dt) or _parse_absolute_trigger(normalized, base_dt)
    if trigger_at is None or trigger_at <= base_dt:
        return []

    return [
        {
            "title": _infer_promise_title(normalized),
            "trigger_at": trigger_at.isoformat(timespec="seconds"),
            "source": str(source or "user").strip() or "user",
            "source_excerpt": normalized,
        }
    ]


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

    def update_promise_title(self, reminder_id: str, title: str) -> bool:
        normalized_title = str(title or "").strip()
        if not reminder_id or not normalized_title:
            return False
        for item in self.items:
            if item.id != reminder_id:
                continue
            if item.title == normalized_title:
                return False
            item.title = normalized_title
            self.save()
            return True
        return False

    def find_similar_promise(
        self,
        *,
        title: str,
        trigger_at: str,
        source_excerpt: str = "",
        include_statuses: tuple[str, ...] | list[str] | None = None,
        tolerance_seconds: int = 120,
    ) -> PromiseReminder | None:
        allowed_statuses = None
        if include_statuses:
            allowed_statuses = {str(status or "").strip() for status in include_statuses if str(status or "").strip()}

        normalized_title = _normalize_promise_text(title)
        normalized_excerpt = _normalize_promise_text(source_excerpt)
        generic_title = _normalize_promise_text(GENERIC_PROMISE_TITLE)
        try:
            target_dt = datetime.fromisoformat(str(trigger_at or "").strip())
        except Exception:
            return None

        for item in self.items:
            if allowed_statuses is not None and item.status not in allowed_statuses:
                continue
            try:
                item_dt = datetime.fromisoformat(item.trigger_at)
            except Exception:
                continue
            if abs((item_dt - target_dt).total_seconds()) > max(0, tolerance_seconds):
                continue

            item_title = _normalize_promise_text(item.title)
            item_excerpt = _normalize_promise_text(item.source_excerpt)
            same_title = normalized_title != generic_title and bool(normalized_title) and (
                item_title == normalized_title
                or (len(normalized_title) >= 2 and normalized_title in item_title)
                or (len(item_title) >= 2 and item_title in normalized_title)
            )
            same_generic_time = normalized_title == generic_title and item_title == generic_title
            same_excerpt = bool(normalized_excerpt) and (
                item_excerpt == normalized_excerpt
                or (len(normalized_excerpt) >= 4 and normalized_excerpt in item_excerpt)
                or (len(item_excerpt) >= 4 and item_excerpt in normalized_excerpt)
            )
            if same_title or same_excerpt or same_generic_time:
                return item
        return None

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
