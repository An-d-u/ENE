"""ENE 프로세스 세션의 시작, 하트비트, 정상 종료 상태를 관리한다."""

from __future__ import annotations

import logging
import re
import socket
import sys
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
_SESSION_VERSION = 2
_SESSION_V1_KEYS = frozenset(
    {
        "version",
        "session_id",
        "started_at",
        "last_seen_at",
        "status",
        "stopped_at",
    }
)
_SESSION_V2_KEYS = _SESSION_V1_KEYS | frozenset(
    {
        "current_summary",
        "active_anchor",
        "generation_claim",
    }
)
_SUMMARY_KEYS = frozenset({"summary_id", "saved_at"})
_ANCHOR_KEYS = frozenset(
    {
        "summary_id",
        "saved_at",
        "activation_source",
        "origin_session_started_at",
        "origin_session_ended_at",
    }
)
_CLAIM_KEYS = frozenset({"summary_id", "returned_at", "expected_record_id"})
_RECORD_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_LOGGER = logging.getLogger(__name__)
_LOCK_FAILED_ERROR = QLockFile.LockError.LockFailedError
_LOCK_PERMISSION_ERROR = QLockFile.LockError.PermissionError
_LOCK_UNKNOWN_ERROR = QLockFile.LockError.UnknownError


@dataclass(frozen=True)
class InactiveStartCandidate:
    """이전 실행이 끝난 시각에서 시작할 비활성 기록 후보다."""

    started_at: datetime
    source: Literal[
        "graceful_exit",
        "heartbeat_recovery",
        "summary_graceful_exit",
        "summary_heartbeat_recovery",
    ]
    summary_id: str | None = None


@dataclass(frozen=True)
class ApprovedSummaryState:
    summary_id: str
    saved_at: datetime

    def to_payload(self) -> dict[str, object]:
        return {
            "summary_id": self.summary_id,
            "saved_at": self.saved_at.isoformat(),
        }


@dataclass(frozen=True)
class ActiveLifeAnchor:
    summary_id: str
    saved_at: datetime
    activation_source: Literal[
        "summary_graceful_exit",
        "summary_heartbeat_recovery",
    ]
    origin_session_started_at: datetime
    origin_session_ended_at: datetime

    def to_payload(self) -> dict[str, object]:
        return {
            "summary_id": self.summary_id,
            "saved_at": self.saved_at.isoformat(),
            "activation_source": self.activation_source,
            "origin_session_started_at": self.origin_session_started_at.isoformat(),
            "origin_session_ended_at": self.origin_session_ended_at.isoformat(),
        }


@dataclass(frozen=True)
class LifeGenerationClaim:
    summary_id: str
    returned_at: datetime
    expected_record_id: str

    def to_payload(self) -> dict[str, object]:
        return {
            "summary_id": self.summary_id,
            "returned_at": self.returned_at.isoformat(),
            "expected_record_id": self.expected_record_id,
        }


@dataclass(frozen=True)
class _SessionState:
    session_id: str
    started_at: datetime
    last_seen_at: datetime
    status: Literal["running", "stopped"]
    stopped_at: datetime | None
    current_summary: ApprovedSummaryState | None = None
    active_anchor: ActiveLifeAnchor | None = None
    generation_claim: LifeGenerationClaim | None = None

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
            "current_summary": (
                self.current_summary.to_payload()
                if self.current_summary is not None
                else None
            ),
            "active_anchor": (
                self.active_anchor.to_payload()
                if self.active_anchor is not None
                else None
            ),
            "generation_claim": (
                self.generation_claim.to_payload()
                if self.generation_claim is not None
                else None
            ),
        }


def _parse_aware_timestamp(
    value: object,
    *,
    require_integer_seconds: bool,
) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp_type")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp_naive")
    if require_integer_seconds and parsed.microsecond != 0:
        raise ValueError("timestamp_subsecond")
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


def _parse_summary_id(value: object) -> str:
    return _parse_uuid4(value)


def _parse_record_id(value: object) -> str:
    if not isinstance(value, str) or _RECORD_ID_PATTERN.fullmatch(value) is None:
        raise ValueError("record_id_invalid")
    return value


def _parse_approved_summary(value: object) -> ApprovedSummaryState:
    if not isinstance(value, dict) or set(value) != _SUMMARY_KEYS:
        raise ValueError("summary_envelope_invalid")
    return ApprovedSummaryState(
        summary_id=_parse_summary_id(value["summary_id"]),
        saved_at=_parse_aware_timestamp(
            value["saved_at"],
            require_integer_seconds=True,
        ),
    )


def _parse_active_anchor(value: object) -> ActiveLifeAnchor:
    if not isinstance(value, dict) or set(value) != _ANCHOR_KEYS:
        raise ValueError("anchor_envelope_invalid")
    source = value["activation_source"]
    if source not in {"summary_graceful_exit", "summary_heartbeat_recovery"}:
        raise ValueError("anchor_source_invalid")
    return ActiveLifeAnchor(
        summary_id=_parse_summary_id(value["summary_id"]),
        saved_at=_parse_aware_timestamp(
            value["saved_at"],
            require_integer_seconds=True,
        ),
        activation_source=source,
        origin_session_started_at=_parse_aware_timestamp(
            value["origin_session_started_at"],
            require_integer_seconds=True,
        ),
        origin_session_ended_at=_parse_aware_timestamp(
            value["origin_session_ended_at"],
            require_integer_seconds=True,
        ),
    )


def _parse_generation_claim(value: object) -> LifeGenerationClaim:
    if not isinstance(value, dict) or set(value) != _CLAIM_KEYS:
        raise ValueError("claim_envelope_invalid")
    return LifeGenerationClaim(
        summary_id=_parse_summary_id(value["summary_id"]),
        returned_at=_parse_aware_timestamp(
            value["returned_at"],
            require_integer_seconds=True,
        ),
        expected_record_id=_parse_record_id(value["expected_record_id"]),
    )


def _is_windows_platform() -> bool:
    return sys.platform == "win32"


def _local_hostname() -> str:
    return socket.gethostname()


def _known_lock_owner(lock_file: QLockFile) -> tuple[bool, str]:
    try:
        info = lock_file.getLockInfo()
    except Exception:
        return False, ""
    if not isinstance(info, tuple) or len(info) != 4:
        return False, ""
    available, process_id, host_name, app_name = info
    known = (
        available is True
        and type(process_id) is int
        and process_id > 0
        and isinstance(host_name, str)
        and bool(host_name)
        and isinstance(app_name, str)
    )
    return known, host_name if isinstance(host_name, str) else ""


def _lease_failure_diagnostic(lock_file: QLockFile) -> str:
    try:
        lock_error = lock_file.error()
    except Exception:
        lock_error = _LOCK_UNKNOWN_ERROR
    known_owner, owner_host = _known_lock_owner(lock_file)

    if lock_error == _LOCK_PERMISSION_ERROR:
        return "session_lease_permission_denied"
    if lock_error == _LOCK_FAILED_ERROR:
        try:
            local_host = _local_hostname()
        except Exception:
            local_host = ""
        nonascii_windows_host = (
            _is_windows_platform()
            and isinstance(local_host, str)
            and bool(local_host)
            and not local_host.isascii()
        )
        if nonascii_windows_host and (
            not known_owner or owner_host != local_host
        ):
            return "session_lease_manual_recovery_required"
        if known_owner:
            return "session_lease_locked"
        return "session_lease_owner_info_unavailable"
    return "session_lease_unknown_error"


def _parse_session_state(payload: object) -> _SessionState:
    if not isinstance(payload, dict):
        raise ValueError("session_envelope_invalid")
    version = payload.get("version")
    if type(version) is not int or version not in {1, _SESSION_VERSION}:
        raise ValueError("session_version_invalid")
    expected_keys = _SESSION_V1_KEYS if version == 1 else _SESSION_V2_KEYS
    if set(payload) != expected_keys:
        raise ValueError("session_envelope_invalid")

    session_id = _parse_uuid4(payload["session_id"])
    require_integer_seconds = version == _SESSION_VERSION
    started_at = _parse_aware_timestamp(
        payload["started_at"],
        require_integer_seconds=require_integer_seconds,
    )
    last_seen_at = _parse_aware_timestamp(
        payload["last_seen_at"],
        require_integer_seconds=require_integer_seconds,
    )
    status = payload["status"]
    if status not in ("running", "stopped"):
        raise ValueError("session_status_invalid")

    raw_stopped_at = payload["stopped_at"]
    if status == "running":
        if raw_stopped_at is not None:
            raise ValueError("running_stop_invalid")
        stopped_at = None
    else:
        stopped_at = _parse_aware_timestamp(
            raw_stopped_at,
            require_integer_seconds=require_integer_seconds,
        )

    if _as_utc(started_at) > _as_utc(last_seen_at):
        raise ValueError("session_order_invalid")
    if stopped_at is not None and _as_utc(last_seen_at) > _as_utc(stopped_at):
        raise ValueError("session_order_invalid")

    current_summary = None
    active_anchor = None
    generation_claim = None
    if version == _SESSION_VERSION:
        if payload["current_summary"] is not None:
            current_summary = _parse_approved_summary(payload["current_summary"])
            if not (
                _as_utc(started_at)
                <= _as_utc(current_summary.saved_at)
                <= _as_utc(last_seen_at)
            ):
                raise ValueError("summary_order_invalid")

        if payload["active_anchor"] is not None:
            active_anchor = _parse_active_anchor(payload["active_anchor"])
            if not (
                _as_utc(active_anchor.origin_session_started_at)
                <= _as_utc(active_anchor.saved_at)
                <= _as_utc(active_anchor.origin_session_ended_at)
            ):
                raise ValueError("anchor_order_invalid")

        if payload["generation_claim"] is not None:
            generation_claim = _parse_generation_claim(payload["generation_claim"])
            if active_anchor is None:
                raise ValueError("claim_anchor_missing")
            if generation_claim.summary_id != active_anchor.summary_id:
                raise ValueError("claim_summary_mismatch")
            lower_bound = max(
                _as_utc(active_anchor.saved_at),
                _as_utc(active_anchor.origin_session_ended_at),
                _as_utc(started_at),
            )
            if not (
                lower_bound
                <= _as_utc(generation_claim.returned_at)
                <= _as_utc(last_seen_at)
            ):
                raise ValueError("claim_order_invalid")
            from src.ai.life_record_types import stable_life_record_id

            expected_record_id = stable_life_record_id(
                active_anchor.saved_at,
                generation_claim.returned_at,
            )
            if generation_claim.expected_record_id != expected_record_id:
                raise ValueError("claim_record_id_mismatch")

    return _SessionState(
        session_id=session_id,
        started_at=started_at,
        last_seen_at=last_seen_at,
        status=status,
        stopped_at=stopped_at,
        current_summary=current_summary,
        active_anchor=active_anchor,
        generation_claim=generation_claim,
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
                _lease_failure_diagnostic(lock_file),
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
        if previous is None or previous.active_anchor is None:
            return None
        anchor = previous.active_anchor
        endpoint = anchor.saved_at

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
            source=anchor.activation_source,
            summary_id=anchor.summary_id,
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
            active_anchor=previous.active_anchor if previous is not None else None,
            generation_claim=(
                previous.generation_claim if previous is not None else None
            ),
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

    @staticmethod
    def _latest_endpoint(*values: datetime) -> datetime:
        if not values:
            raise ValueError("endpoint_missing")
        latest = values[0]
        for value in values[1:]:
            if _as_utc(value) > _as_utc(latest):
                latest = value
        return latest

    def register_approved_summary(
        self,
        summary_id: str,
    ) -> ApprovedSummaryState | None:
        """현재 running 세션에 실제 저장된 승인 요약을 원자 등록한다."""

        if (
            not self._lease_acquired
            or not self.life_records_writable
            or self._stopped
        ):
            return None
        try:
            canonical_summary_id = _parse_summary_id(summary_id)
        except (TypeError, ValueError):
            self._diagnose("summary_id_invalid")
            return None
        canonical_now = self._read_clock_endpoint()
        if canonical_now is None:
            return None
        authoritative = self._load_current_owner()
        if authoritative is None:
            return None
        endpoints = [
            canonical_now,
            authoritative.started_at,
            authoritative.last_seen_at,
        ]
        if authoritative.current_summary is not None:
            endpoints.append(authoritative.current_summary.saved_at)
        saved_at = self._latest_endpoint(*endpoints)
        registered = ApprovedSummaryState(
            summary_id=canonical_summary_id,
            saved_at=saved_at,
        )
        updated = _SessionState(
            session_id=authoritative.session_id,
            started_at=authoritative.started_at,
            last_seen_at=saved_at,
            status="running",
            stopped_at=None,
            current_summary=registered,
            active_anchor=authoritative.active_anchor,
            generation_claim=authoritative.generation_claim,
        )
        if not self._commit(updated):
            self._set_degraded(
                SESSION_TRACKER_DEGRADED,
                "session_summary_commit_failed",
            )
            return None
        self._current_state = updated
        return registered

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
            current_summary=authoritative.current_summary,
            active_anchor=authoritative.active_anchor,
            generation_claim=authoritative.generation_claim,
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
            current_summary=authoritative.current_summary,
            active_anchor=authoritative.active_anchor,
            generation_claim=authoritative.generation_claim,
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
        self.life_records_writable = False
        return True
