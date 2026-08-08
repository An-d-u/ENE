"""생활 기록의 검증된 영속화, 정렬, 날짜 조회를 담당한다."""

from __future__ import annotations

from contextlib import contextmanager
import json
from datetime import date, datetime, timezone
from pathlib import Path
from threading import Lock, RLock
from typing import Iterable

from PyQt6.QtCore import QLockFile

from src.core import app_paths
from src.core.local_time import LocalTimeContext, resolve_local_time_context

from .life_record_types import (
    LifeRecord,
    LifeRecordOutput,
    create_life_record,
    life_record_store_to_dict,
    parse_life_record_store,
)


class LifeRecordStoreError(RuntimeError):
    """호출자가 안전한 상태 코드만 처리할 수 있는 저장소 오류."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_STORE_LOCKS_GUARD = Lock()
_STORE_LOCKS: dict[str, RLock] = {}


def _process_store_lock(path: Path) -> RLock:
    key = str(path.resolve()).casefold()
    with _STORE_LOCKS_GUARD:
        lock = _STORE_LOCKS.get(key)
        if lock is None:
            lock = RLock()
            _STORE_LOCKS[key] = lock
        return lock


@contextmanager
def _exclusive_store_write(path: Path):
    """프로세스·파일 경계를 함께 잠가 read-check-write를 직렬화한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    process_lock = _process_store_lock(path)
    with process_lock:
        lock_file = QLockFile(str(path.with_name(f"{path.name}.write.lock")))
        if not lock_file.tryLock(5_000):
            raise LifeRecordStoreError("store_busy")
        try:
            yield
        finally:
            lock_file.unlock()


def _utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _sorted_records(records: Iterable[LifeRecord]) -> tuple[LifeRecord, ...]:
    ordered = sorted(records, key=lambda record: record.id)
    ordered.sort(key=lambda record: _utc(record.created_at), reverse=True)
    ordered.sort(key=lambda record: _utc(record.returned_at), reverse=True)
    return tuple(ordered)


def _localized_iso(value: datetime, zone) -> str:
    return value.astimezone(zone).isoformat(timespec="seconds")


def to_public_dict(
    record: LifeRecord,
    view_timezone: str,
    locale: str,
    *,
    time_context: LocalTimeContext | None = None,
) -> dict[str, object]:
    """브리지에서 자유롭게 복사·수정할 수 있는 현재 timezone 기준 표현을 만든다."""

    if time_context is not None and time_context.timezone_name == view_timezone:
        zone = time_context.zone
    else:
        resolution = resolve_local_time_context(view_timezone)
        if resolution.context is None:
            raise LifeRecordStoreError("invalid_view_timezone")
        zone = resolution.view_timezone
    resolved_locale = locale if locale in {"ko", "en", "ja"} else "en"
    return {
        "id": record.id,
        "inactive_started_at": _localized_iso(record.inactive_started_at, zone),
        "returned_at": _localized_iso(record.returned_at, zone),
        "created_at": _localized_iso(record.created_at, zone),
        "updated_at": _localized_iso(record.updated_at, zone),
        "revision": record.revision,
        "timezone": record.timezone,
        "view_timezone": view_timezone,
        "locale": resolved_locale,
        "inactive_start_source": record.inactive_start_source,
        "mood_snapshot": dict(record.mood_snapshot),
        "entries": [
            {
                "started_at": _localized_iso(entry.started_at, zone),
                "ended_at": _localized_iso(entry.ended_at, zone),
                "place": entry.place,
                "activity": entry.activity,
            }
            for entry in record.entries
        ],
        "ending_state": dict(record.ending_state),
    }


class LifeRecordManager:
    """단일 권위 파일에 저장된 완전 검증 생활 기록만 메모리에 유지한다."""

    def __init__(
        self,
        store_file: str | Path | None = None,
        *,
        time_context: LocalTimeContext | None = None,
    ) -> None:
        target = store_file if store_file is not None else "life_records.json"
        self.store_path = app_paths.resolve_user_storage_path(target)
        self.time_context = time_context
        self._records: tuple[LifeRecord, ...] = ()
        self.store_status = "missing"
        self._load()

    @property
    def records(self) -> tuple[LifeRecord, ...]:
        return self._records

    def _load(self) -> None:
        try:
            decoded = app_paths.load_json_data(
                self.store_path,
                encoding="utf-8-sig",
            )
        except FileNotFoundError:
            self._records = ()
            self.store_status = "missing"
            return
        except Exception:
            self._records = ()
            self.store_status = "read_error"
            return

        try:
            raw = json.dumps(decoded, ensure_ascii=False, allow_nan=False)
            records = parse_life_record_store(raw)
        except Exception:
            self._records = ()
            self.store_status = "read_error"
            return
        self._records = _sorted_records(records)
        self.store_status = "ready"

    def _require_healthy_store(self) -> None:
        if self.store_status == "read_error":
            raise LifeRecordStoreError("read_error")

    def _commit(self, records: Iterable[LifeRecord]) -> tuple[LifeRecord, ...]:
        self._require_healthy_store()
        unvalidated_payload = life_record_store_to_dict(_sorted_records(records))
        candidate = _sorted_records(
            parse_life_record_store(
                json.dumps(unvalidated_payload, ensure_ascii=False, allow_nan=False)
            )
        )
        payload = life_record_store_to_dict(candidate)
        app_paths.save_json_data(
            self.store_path,
            payload,
            encoding="utf-8",
            indent=2,
            ensure_ascii=False,
        )
        self._records = candidate
        self.store_status = "ready"
        return candidate

    def latest(self) -> LifeRecord | None:
        return self._records[0] if self._records else None

    def add(self, record: LifeRecord) -> bool:
        with _exclusive_store_write(self.store_path):
            authoritative = LifeRecordManager(
                self.store_path,
                time_context=self.time_context,
            )
            authoritative._require_healthy_store()
            if any(existing.id == record.id for existing in authoritative.records):
                return False
            validated = parse_life_record_store(
                json.dumps(life_record_store_to_dict([record]), ensure_ascii=False)
            )[0]
            self._commit((*authoritative.records, validated))
            return True

    def records_overlapping_date(
        self,
        local_date: date,
        view_timezone: str,
    ) -> list[LifeRecord]:
        self._require_healthy_store()
        context = self._view_time_context(view_timezone)
        start, end = context.local_day_bounds(local_date)
        start_utc = _utc(start)
        end_utc = _utc(end)
        return [
            record
            for record in self._records
            if _utc(record.inactive_started_at) < end_utc
            and _utc(record.returned_at) > start_utc
        ]

    def _view_time_context(self, view_timezone: str) -> LocalTimeContext:
        if (
            self.time_context is not None
            and self.time_context.timezone_name == view_timezone
        ):
            return self.time_context
        resolution = resolve_local_time_context(view_timezone)
        if resolution.context is None:
            raise LifeRecordStoreError("invalid_view_timezone")
        return resolution.context

    def previous_before(self, record_id: str) -> LifeRecord | None:
        for index, record in enumerate(self._records):
            if record.id == record_id:
                next_index = index + 1
                return self._records[next_index] if next_index < len(self._records) else None
        return None

    def replace_latest(
        self,
        record_id: str,
        generated: LifeRecordOutput,
        updated_at: datetime,
    ) -> LifeRecord:
        self._require_healthy_store()
        current = self.latest()
        if current is None or current.id != record_id:
            raise LifeRecordStoreError("not_latest")
        return self.replace_latest_if_unchanged(current, generated, updated_at)

    def replace_latest_if_unchanged(
        self,
        expected: LifeRecord,
        generated: LifeRecordOutput,
        updated_at: datetime,
    ) -> LifeRecord:
        """권위 파일의 최신값이 예상 사본과 같을 때만 원자 교체한다."""
        if not isinstance(expected, LifeRecord):
            raise LifeRecordStoreError("invalid_expected_record")
        with _exclusive_store_write(self.store_path):
            self._load()
            self._require_healthy_store()
            current = self.latest()
            if current != expected:
                raise LifeRecordStoreError("stale_record")
            replacement = self._replacement_record(current, generated, updated_at)
            committed = self._commit((replacement, *self._records[1:]))
            authoritative = committed[0] if committed else None
            if authoritative != replacement:
                raise LifeRecordStoreError("commit_verification_failed")
            return authoritative

    @staticmethod
    def _replacement_record(
        current: LifeRecord,
        generated: LifeRecordOutput,
        updated_at: datetime,
    ) -> LifeRecord:
        replacement = create_life_record(
            id=current.id,
            inactive_started_at=current.inactive_started_at,
            returned_at=current.returned_at,
            created_at=current.created_at,
            updated_at=updated_at,
            revision=current.revision + 1,
            timezone=current.timezone,
            inactive_start_source=current.inactive_start_source,
            mood_snapshot=dict(current.mood_snapshot),
            entries=[
                {
                    "started_at": entry.started_at,
                    "ended_at": entry.ended_at,
                    "place": entry.place,
                    "activity": entry.activity,
                }
                for entry in generated.entries
            ],
            ending_state={
                "place": generated.ending_state.place,
                "summary": generated.ending_state.summary,
            },
        )
        return replacement

    def to_public_dict(
        self,
        record: LifeRecord,
        view_timezone: str,
        locale: str,
    ) -> dict[str, object]:
        return to_public_dict(
            record,
            view_timezone,
            locale,
            time_context=self._view_time_context(view_timezone),
        )
