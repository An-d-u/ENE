"""IANA 시간대와 timezone-aware 시각을 일관되게 다루는 서비스."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable
from zoneinfo import ZoneInfo

import tzlocal


TIMEZONE_UNAVAILABLE = "timezone_unavailable"
UTC_ZONE = ZoneInfo("UTC")


class NaiveDateTimeError(ValueError):
    """timezone 정보가 없는 datetime이 전달되었음을 나타낸다."""

    code = "naive_datetime"


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise NaiveDateTimeError("timezone-aware datetime이 필요합니다.")
    return value


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LocalTimeContext:
    """기록 생성과 조회에 사용할 단일 현지 시각 문맥."""

    timezone_name: str
    zone: ZoneInfo
    now_provider: Callable[[], datetime]

    def now(self) -> datetime:
        current = _require_aware(self.now_provider())
        return current.astimezone(self.zone)

    def canonicalize_endpoint(self, value: datetime) -> datetime:
        aware_value = _require_aware(value)
        return (
            aware_value.astimezone(timezone.utc)
            .astimezone(self.zone)
            .replace(microsecond=0)
        )

    def local_day_bounds(self, day: date) -> tuple[datetime, datetime]:
        start = datetime.combine(day, time.min, tzinfo=self.zone)
        end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=self.zone)
        return start, end

    def elapsed_between(self, start: datetime, end: datetime) -> timedelta:
        aware_start = _require_aware(start)
        aware_end = _require_aware(end)
        return aware_end.astimezone(timezone.utc) - aware_start.astimezone(timezone.utc)

    def same_instant(self, left: datetime, right: datetime) -> bool:
        aware_left = _require_aware(left)
        aware_right = _require_aware(right)
        return aware_left.astimezone(timezone.utc) == aware_right.astimezone(timezone.utc)

    def matches_zone_rules(self, value: datetime) -> bool:
        """표현된 wall time과 offset이 이 IANA zone의 해당 instant 규칙과 맞는지 확인한다."""

        aware_value = _require_aware(value)
        normalized = aware_value.astimezone(timezone.utc).astimezone(self.zone)
        return (
            normalized.replace(tzinfo=None) == aware_value.replace(tzinfo=None)
            and normalized.utcoffset() == aware_value.utcoffset()
        )


@dataclass(frozen=True)
class LocalTimeResolution:
    """쓰기 가능 문맥 또는 안전한 읽기 전용 UTC view를 담는 해석 결과."""

    context: LocalTimeContext | None
    view_timezone: ZoneInfo
    reason: str | None

    @property
    def is_read_only(self) -> bool:
        return self.context is None


def resolve_local_time_context(
    timezone_name: str | None = None,
    *,
    now_provider: Callable[[], datetime] = _utc_now,
) -> LocalTimeResolution:
    """현지 IANA 이름을 검증하고 실패 시 쓰기를 닫은 UTC view를 반환한다."""

    if timezone_name is None:
        try:
            resolved_name = tzlocal.get_localzone_name()
        except (LookupError, OSError):
            return LocalTimeResolution(
                context=None,
                view_timezone=UTC_ZONE,
                reason=TIMEZONE_UNAVAILABLE,
            )
    else:
        resolved_name = timezone_name

    try:
        if not isinstance(resolved_name, str) or not resolved_name.strip():
            raise ValueError("timezone 이름이 비어 있습니다.")
        zone = ZoneInfo(resolved_name)
    except (LookupError, OSError, TypeError, ValueError):
        return LocalTimeResolution(
            context=None,
            view_timezone=UTC_ZONE,
            reason=TIMEZONE_UNAVAILABLE,
        )

    return LocalTimeResolution(
        context=LocalTimeContext(
            timezone_name=resolved_name,
            zone=zone,
            now_provider=now_provider,
        ),
        view_timezone=zone,
        reason=None,
    )
