"""ENE 프로세스 세션의 시작, 하트비트, 정상 종료 상태를 관리한다."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from uuid import UUID, RFC_4122, uuid4

from PyQt6.QtCore import QLockFile

from .app_paths import load_json_data, save_json_data
from .local_time import (
    TIMEZONE_UNAVAILABLE,
    LocalTimeContext,
    UTC_ZONE,
    resolve_local_time_context,
)


SESSION_LEASE_UNAVAILABLE = "session_lease_unavailable"
SESSION_TRACKER_DEGRADED = "session_tracker_degraded"
_SESSION_VERSION = 1
_SESSION_KEYS = frozenset(
    {
        "version",
        "session_id",
        "started_at",
        "last_seen_at",
        "status",
        "stopped_at",
    }
)
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class InactiveStartCandidate:
    """이전 실행이 끝난 시각에서 시작할 비활성 기록 후보다."""

    started_at: datetime
    source: Literal["graceful_exit", "heartbeat_recovery"]


@dataclass(frozen=True)
class _SessionState:
    session_id: str
    started_at: datetime
    last_seen_at: datetime
    status: Literal["running", "stopped"]
    stopped_at: datetime | None

    def to_payload(self) -> dict[str, object]:
        return {
            "version": _SESSION_VERSION,
            "session_id": self.session_id,
            "started_at": self.started_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "status": self.status,
            "stopped_at": (
                self.stopped_at.isoformat() if self.stopped_at is not None else None
            ),
        }


def _parse_aware_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp_type")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_naive")
    return parsed


def _parse_uuid4(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("session_id_type")
    parsed = UUID(value)
    if parsed.version != 4 or parsed.variant != RFC_4122 or str(parsed) != value:
        raise ValueError("session_id_invalid")
    return value


def _as_utc(value: datetime) -> datetime:
    return value.astimezone(timezone.utc)


def _parse_session_state(payload: object) -> _SessionState:
    if not isinstance(payload, dict) or set(payload) != _SESSION_KEYS:
        raise ValueError("session_envelope_invalid")
    if type(payload["version"]) is not int or payload["version"] != _SESSION_VERSION:
        raise ValueError("session_version_invalid")

    session_id = _parse_uuid4(payload["session_id"])
    started_at = _parse_aware_timestamp(payload["started_at"])
    last_seen_at = _parse_aware_timestamp(payload["last_seen_at"])
    status = payload["status"]
    if status not in ("running", "stopped"):
        raise ValueError("session_status_invalid")

    raw_stopped_at = payload["stopped_at"]
    if status == "running":
        if raw_stopped_at is not None:
            raise ValueError("running_stop_invalid")
        stopped_at = None
    else:
        stopped_at = _parse_aware_timestamp(raw_stopped_at)

    if _as_utc(started_at) > _as_utc(last_seen_at):
        raise ValueError("session_order_invalid")
    if stopped_at is not None and _as_utc(last_seen_at) > _as_utc(stopped_at):
        raise ValueError("session_order_invalid")

    return _SessionState(
        session_id=session_id,
        started_at=started_at,
        last_seen_at=last_seen_at,
        status=status,
        stopped_at=stopped_at,
    )


class AppSessionTracker:
    """단일 ENE 프로세스가 소유하는 authoritative 세션 상태를 관리한다."""

    def __init__(
        self,
        state_path: str | Path,
        *,
        now: Callable[[], datetime] | None = None,
        time_context: LocalTimeContext | None = None,
    ) -> None:
        if now is not None and time_context is not None:
            raise ValueError("now와 time_context는 함께 지정할 수 없습니다.")

        self._state_path = Path(state_path)
        self._lock_path = self._state_path.with_suffix(".lock")
        self._time_context, self._time_context_reason = self._build_time_context(
            now,
            time_context,
        )
        self._lock_file: QLockFile | None = None
        self._lease_acquired = False
        self._start_attempted = False
        self._stopped = False
        self._current_state: _SessionState | None = None
        self._diagnostics: list[str] = []

        self.candidate: InactiveStartCandidate | None = None
        self.degraded = False
        self.life_records_writable = False
        self.reason: str | None = None

    @staticmethod
    def _build_time_context(
        now: Callable[[], datetime] | None,
        time_context: LocalTimeContext | None,
    ) -> tuple[LocalTimeContext | None, str | None]:
        if time_context is not None:
            return time_context, None
        if now is not None:
            return (
                LocalTimeContext(
                    timezone_name="UTC",
                    zone=UTC_ZONE,
                    now_provider=now,
                ),
                None,
            )

        resolution = resolve_local_time_context()
        if resolution.context is not None:
            return resolution.context, None
        return None, resolution.reason or TIMEZONE_UNAVAILABLE

    @property
    def session_id(self) -> str | None:
        if self._current_state is None:
            return None
        return self._current_state.session_id

    @property
    def diagnostics(self) -> tuple[str, ...]:
        return tuple(self._diagnostics)

    def _diagnose(self, code: str) -> None:
        self._diagnostics.append(code)
        _LOGGER.warning(
            "category=life_session_tracker code=%s path_kind=session_state",
            code,
        )

    def _set_degraded(self, reason: str, diagnostic_code: str) -> None:
        self.candidate = None
        self.degraded = True
        self.life_records_writable = False
        self.reason = reason
        self._diagnose(diagnostic_code)

    def _canonical_now(self) -> datetime:
        if self._time_context is None:
            raise RuntimeError("time_context_unavailable")
        return self._time_context.canonicalize_endpoint(self._time_context.now())

    def _acquire_lease(self) -> bool:
        lock_file = QLockFile(str(self._lock_path))
        lock_file.setStaleLockTime(0)
        try:
            acquired = lock_file.tryLock(0)
        except Exception:
            self._lock_file = lock_file
            self._set_degraded(
                SESSION_LEASE_UNAVAILABLE,
                "session_lease_error",
            )
            return False

        self._lock_file = lock_file
        if not acquired:
            self._set_degraded(
                SESSION_LEASE_UNAVAILABLE,
                SESSION_LEASE_UNAVAILABLE,
            )
            return False
        self._lease_acquired = True
        return True

    def _read_authoritative(self) -> _SessionState | None:
        try:
            payload = load_json_data(self._state_path)
        except FileNotFoundError:
            self._diagnose("session_state_missing")
            return None
        except Exception:
            self._diagnose("session_state_read_error")
            return None

        try:
            return _parse_session_state(payload)
        except (OverflowError, TypeError, ValueError):
            self._diagnose("session_state_invalid")
            return None

    def _commit(self, state: _SessionState) -> bool:
        payload = state.to_payload()
        try:
            _parse_session_state(payload)
            save_json_data(
                self._state_path,
                payload,
                encoding="utf-8",
            )
        except Exception:
            self._diagnose("session_state_write_error")
            return False
        return True

    def _candidate_from_previous(
        self,
        previous: _SessionState | None,
        canonical_now: datetime,
    ) -> InactiveStartCandidate | None:
        if previous is None:
            return None
        if previous.status == "stopped":
            assert previous.stopped_at is not None
            endpoint = previous.stopped_at
            source: Literal["graceful_exit", "heartbeat_recovery"] = "graceful_exit"
        else:
            endpoint = previous.last_seen_at
            source = "heartbeat_recovery"

        assert self._time_context is not None
        try:
            canonical_endpoint = self._time_context.canonicalize_endpoint(endpoint)
        except (OverflowError, ValueError):
            self._diagnose("session_candidate_invalid")
            return None
        if _as_utc(canonical_endpoint) > _as_utc(canonical_now):
            self._diagnose("session_candidate_in_future")
            return None
        return InactiveStartCandidate(
            started_at=canonical_endpoint,
            source=source,
        )

    def start_session(self) -> InactiveStartCandidate | None:
        """이전 종료 후보를 회복하고 현재 running 세션을 원자 저장한다."""

        if self._start_attempted:
            return None
        self._start_attempted = True
        if self._time_context is None:
            self._set_degraded(
                self._time_context_reason or TIMEZONE_UNAVAILABLE,
                "timezone_unavailable",
            )
            return None
        if not self._acquire_lease():
            return None

        try:
            canonical_now = self._canonical_now()
        except Exception:
            self._set_degraded(
                SESSION_TRACKER_DEGRADED,
                "session_clock_error",
            )
            return None

        previous = self._read_authoritative()
        candidate = self._candidate_from_previous(previous, canonical_now)
        current = _SessionState(
            session_id=str(uuid4()),
            started_at=canonical_now,
            last_seen_at=canonical_now,
            status="running",
            stopped_at=None,
        )
        if not self._commit(current):
            self._current_state = None
            self._set_degraded(
                SESSION_TRACKER_DEGRADED,
                "session_running_commit_failed",
            )
            return None

        self._current_state = current
        self.candidate = candidate
        self.degraded = False
        self.life_records_writable = True
        self.reason = None
        return candidate

    def _load_current_owner(self) -> _SessionState | None:
        authoritative = self._read_authoritative()
        expected_id = self.session_id
        if (
            authoritative is None
            or expected_id is None
            or authoritative.session_id != expected_id
            or authoritative.status != "running"
        ):
            self._set_degraded(
                SESSION_TRACKER_DEGRADED,
                "session_state_stale_owner",
            )
            return None
        return authoritative

    def _read_clock_endpoint(self) -> datetime | None:
        try:
            return self._canonical_now()
        except Exception:
            self._set_degraded(
                SESSION_TRACKER_DEGRADED,
                "session_clock_error",
            )
            return None

    @staticmethod
    def _next_endpoint(
        canonical_now: datetime,
        persisted_last_seen: datetime,
    ) -> datetime:
        if _as_utc(canonical_now) < _as_utc(persisted_last_seen):
            return persisted_last_seen
        return canonical_now

    def heartbeat(self) -> bool:
        """현재 세션의 마지막 생존 시각만 단조 증가하도록 갱신한다."""

        if (
            not self._lease_acquired
            or not self.life_records_writable
            or self._stopped
        ):
            return False
        canonical_now = self._read_clock_endpoint()
        if canonical_now is None:
            return False
        authoritative = self._load_current_owner()
        if authoritative is None:
            return False
        endpoint = self._next_endpoint(canonical_now, authoritative.last_seen_at)
        updated = _SessionState(
            session_id=authoritative.session_id,
            started_at=authoritative.started_at,
            last_seen_at=endpoint,
            status="running",
            stopped_at=None,
        )
        if not self._commit(updated):
            self._set_degraded(
                SESSION_TRACKER_DEGRADED,
                "session_heartbeat_commit_failed",
            )
            return False
        self._current_state = updated
        return True

    def stop_session(self) -> bool:
        """현재 세션을 한 번만 stopped 상태로 원자 저장한다."""

        if self._stopped:
            return True
        if not self._lease_acquired or not self.life_records_writable:
            return False
        canonical_now = self._read_clock_endpoint()
        if canonical_now is None:
            return False
        authoritative = self._load_current_owner()
        if authoritative is None:
            return False
        shutdown_at = self._next_endpoint(canonical_now, authoritative.last_seen_at)
        stopped = _SessionState(
            session_id=authoritative.session_id,
            started_at=authoritative.started_at,
            last_seen_at=shutdown_at,
            status="stopped",
            stopped_at=shutdown_at,
        )
        if not self._commit(stopped):
            self._set_degraded(
                SESSION_TRACKER_DEGRADED,
                "session_stop_commit_failed",
            )
            return False

        self._current_state = stopped
        self._stopped = True
        self.life_records_writable = False
        return True

    def release_lease(self) -> bool:
        """최종 앱 teardown에서 프로세스 수명 lease를 한 번 해제한다."""

        if not self._lease_acquired or self._lock_file is None:
            return False
        self._lock_file.unlock()
        self._lease_acquired = False
        return True
