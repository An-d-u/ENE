from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import TZPATH, ZoneInfo, reset_tzpath

import pytest


def _fixed_clock(value: datetime):
    return lambda: value


def test_runtime_requirements_include_local_timezone_database():
    project_root = Path(__file__).resolve().parents[1]
    requirements = (project_root / "requirements.txt").read_text(encoding="utf-8").splitlines()

    assert any(line.startswith("tzlocal>=") for line in requirements)
    assert any(line.startswith("tzdata>=") for line in requirements)


@pytest.mark.parametrize("timezone_name", ["Asia/Seoul", "America/New_York"])
def test_tzdata_resolves_required_zones_without_system_database(timezone_name):
    original_tzpath = TZPATH
    try:
        reset_tzpath([])
        ZoneInfo.clear_cache()

        assert ZoneInfo(timezone_name).key == timezone_name
    finally:
        reset_tzpath(original_tzpath)
        ZoneInfo.clear_cache()


def test_resolver_validates_tzlocal_name_with_zoneinfo(monkeypatch):
    from src.core import local_time

    monkeypatch.setattr(local_time.tzlocal, "get_localzone_name", lambda: "Asia/Seoul")

    resolution = local_time.resolve_local_time_context(
        now_provider=_fixed_clock(datetime(2099, 1, 2, 3, 4, tzinfo=timezone.utc))
    )

    assert resolution.reason is None
    assert resolution.context is not None
    assert resolution.context.timezone_name == "Asia/Seoul"
    assert resolution.context.zone.key == "Asia/Seoul"
    assert resolution.view_timezone.key == "Asia/Seoul"


def test_resolver_fails_closed_when_tzlocal_returns_invalid_name(monkeypatch):
    from src.core import local_time

    monkeypatch.setattr(local_time.tzlocal, "get_localzone_name", lambda: "Invalid/Local")

    resolution = local_time.resolve_local_time_context()

    assert resolution.context is None
    assert resolution.reason == "timezone_unavailable"
    assert resolution.view_timezone.key == "UTC"
    assert resolution.is_read_only is True


@pytest.mark.parametrize("timezone_name", ["Invalid/Zone", ""])
def test_invalid_timezone_is_fail_closed_with_read_only_utc_view(timezone_name):
    from src.core.local_time import resolve_local_time_context

    resolution = resolve_local_time_context(timezone_name)

    assert resolution.context is None
    assert resolution.reason == "timezone_unavailable"
    assert resolution.view_timezone.key == "UTC"
    assert resolution.is_read_only is True


def test_valid_explicit_timezone_is_preserved_without_utc_fallback():
    from src.core.local_time import resolve_local_time_context

    resolution = resolve_local_time_context("America/New_York")

    assert resolution.reason is None
    assert resolution.context is not None
    assert resolution.view_timezone.key == "America/New_York"
    assert resolution.is_read_only is False


def test_now_returns_timezone_aware_datetime_in_context_zone():
    from src.core.local_time import LocalTimeContext

    context = LocalTimeContext(
        timezone_name="Asia/Seoul",
        zone=ZoneInfo("Asia/Seoul"),
        now_provider=_fixed_clock(datetime(2099, 1, 2, 3, 4, 5, 678901, tzinfo=timezone.utc)),
    )

    current = context.now()

    assert current.tzinfo is not None
    assert current.utcoffset() == timedelta(hours=9)
    assert current == datetime(2099, 1, 2, 12, 4, 5, 678901, tzinfo=ZoneInfo("Asia/Seoul"))


def test_clock_provider_rejects_naive_datetime():
    from src.core.local_time import LocalTimeContext, NaiveDateTimeError

    context = LocalTimeContext(
        timezone_name="Asia/Seoul",
        zone=ZoneInfo("Asia/Seoul"),
        now_provider=_fixed_clock(datetime(2099, 1, 2, 3, 4, 5)),
    )

    with pytest.raises(NaiveDateTimeError):
        context.now()


def test_canonicalize_endpoint_preserves_integer_second_instant_in_context_zone():
    from src.core.local_time import LocalTimeContext

    context = LocalTimeContext(
        timezone_name="Asia/Seoul",
        zone=ZoneInfo("Asia/Seoul"),
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )
    value = datetime(2099, 6, 7, 1, 2, 3, 987654, tzinfo=timezone.utc)

    canonical = context.canonicalize_endpoint(value)

    assert canonical == datetime(2099, 6, 7, 10, 2, 3, tzinfo=ZoneInfo("Asia/Seoul"))
    assert canonical.microsecond == 0
    assert canonical.timestamp() == value.replace(microsecond=0).timestamp()


def test_canonicalize_endpoint_rejects_naive_datetime():
    from src.core.local_time import LocalTimeContext, NaiveDateTimeError

    context = LocalTimeContext(
        timezone_name="Asia/Seoul",
        zone=ZoneInfo("Asia/Seoul"),
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )

    with pytest.raises(NaiveDateTimeError):
        context.canonicalize_endpoint(datetime(2099, 6, 7, 1, 2, 3))


def test_canonicalize_endpoint_normalizes_nonexistent_wall_time_through_utc():
    from src.core.local_time import LocalTimeContext

    zone = ZoneInfo("America/New_York")
    context = LocalTimeContext(
        timezone_name=zone.key,
        zone=zone,
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )
    nonexistent = datetime(2099, 3, 8, 2, 30, tzinfo=zone)

    canonical = context.canonicalize_endpoint(nonexistent)

    assert canonical == datetime(2099, 3, 8, 3, 30, tzinfo=zone)
    assert context.same_instant(canonical, nonexistent) is True


def test_elapsed_and_equality_use_utc_instants():
    from src.core.local_time import LocalTimeContext

    context = LocalTimeContext(
        timezone_name="America/New_York",
        zone=ZoneInfo("America/New_York"),
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )
    first = datetime(2099, 1, 2, 3, 4, tzinfo=timezone.utc)
    same = datetime(2099, 1, 1, 22, 4, tzinfo=ZoneInfo("America/New_York"))
    later = datetime(2099, 1, 1, 23, 34, tzinfo=ZoneInfo("America/New_York"))

    assert context.same_instant(first, same) is True
    assert context.elapsed_between(first, later) == timedelta(hours=1, minutes=30)


@pytest.mark.parametrize(
    ("day", "expected_hours"),
    [
        (date(2099, 3, 8), 23),
        (date(2099, 11, 1), 25),
    ],
)
def test_new_york_dst_day_bounds_have_correct_utc_duration(day, expected_hours):
    from src.core.local_time import LocalTimeContext

    context = LocalTimeContext(
        timezone_name="America/New_York",
        zone=ZoneInfo("America/New_York"),
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )

    start, end = context.local_day_bounds(day)

    assert start.hour == 0
    assert end.hour == 0
    assert start.date() == day
    assert end.date() == day + timedelta(days=1)
    assert start.tzinfo == context.zone
    assert end.tzinfo == context.zone
    assert context.elapsed_between(start, end) == timedelta(hours=expected_hours)


def test_fall_dst_fold_values_are_distinct_instants():
    from src.core.local_time import LocalTimeContext

    zone = ZoneInfo("America/New_York")
    context = LocalTimeContext(
        timezone_name=zone.key,
        zone=zone,
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )
    first = datetime(2099, 11, 1, 1, 30, tzinfo=zone, fold=0)
    second = datetime(2099, 11, 1, 1, 30, tzinfo=zone, fold=1)

    assert context.same_instant(first, second) is False
    assert context.elapsed_between(first, second) == timedelta(hours=1)


def test_zone_rule_match_rejects_nonexistent_spring_wall_time():
    from src.core.local_time import LocalTimeContext

    zone = ZoneInfo("America/New_York")
    context = LocalTimeContext(
        timezone_name=zone.key,
        zone=zone,
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )
    nonexistent = datetime(2099, 3, 8, 2, 30, tzinfo=zone)

    assert context.matches_zone_rules(nonexistent) is False


def test_zone_rule_match_rejects_offset_that_does_not_match_instant():
    from src.core.local_time import LocalTimeContext

    zone = ZoneInfo("America/New_York")
    context = LocalTimeContext(
        timezone_name=zone.key,
        zone=zone,
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )
    mismatched = datetime(2099, 1, 2, 12, 0, tzinfo=timezone(timedelta(hours=-4)))

    assert context.matches_zone_rules(mismatched) is False


def test_zone_rule_match_accepts_both_valid_fall_fold_instants():
    from src.core.local_time import LocalTimeContext

    zone = ZoneInfo("America/New_York")
    context = LocalTimeContext(
        timezone_name=zone.key,
        zone=zone,
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )

    assert context.matches_zone_rules(datetime(2099, 11, 1, 1, 30, tzinfo=zone, fold=0)) is True
    assert context.matches_zone_rules(datetime(2099, 11, 1, 1, 30, tzinfo=zone, fold=1)) is True


def test_zone_rule_match_rejects_naive_datetime():
    from src.core.local_time import LocalTimeContext, NaiveDateTimeError

    context = LocalTimeContext(
        timezone_name="Asia/Seoul",
        zone=ZoneInfo("Asia/Seoul"),
        now_provider=_fixed_clock(datetime(2099, 1, 1, tzinfo=timezone.utc)),
    )

    with pytest.raises(NaiveDateTimeError):
        context.matches_zone_rules(datetime(2099, 1, 2, 3, 4))
