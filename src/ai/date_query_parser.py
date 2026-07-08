from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable


@dataclass(frozen=True)
class DateQueryMatch:
    """질문에서 추출한 날짜 또는 날짜 범위."""

    start: date
    end: date
    precision: str
    source_text: str
    has_year: bool


class DateQueryParser:
    """한/영/일 날짜 표현을 기억 검색용 날짜 범위로 변환한다."""

    ENGLISH_MONTHS = {
        "january": 1,
        "jan": 1,
        "february": 2,
        "feb": 2,
        "march": 3,
        "mar": 3,
        "april": 4,
        "apr": 4,
        "may": 5,
        "june": 6,
        "jun": 6,
        "july": 7,
        "jul": 7,
        "august": 8,
        "aug": 8,
        "september": 9,
        "sept": 9,
        "sep": 9,
        "october": 10,
        "oct": 10,
        "november": 11,
        "nov": 11,
        "december": 12,
        "dec": 12,
    }
    ENGLISH_MONTH_PATTERN = "|".join(
        re.escape(month_name)
        for month_name in sorted(ENGLISH_MONTHS, key=len, reverse=True)
    )
    SEASONS = {
        "봄": (3, 1, 5, 31),
        "春": (3, 1, 5, 31),
        "spring": (3, 1, 5, 31),
        "여름": (6, 1, 8, 31),
        "夏": (6, 1, 8, 31),
        "summer": (6, 1, 8, 31),
        "가을": (9, 1, 11, 30),
        "秋": (9, 1, 11, 30),
        "fall": (9, 1, 11, 30),
        "autumn": (9, 1, 11, 30),
        "겨울": (12, 1, 2, 28),
        "冬": (12, 1, 2, 28),
        "winter": (12, 1, 2, 28),
    }

    def parse(self, text: str, now: datetime | date | None = None) -> list[DateQueryMatch]:
        """질문 안의 날짜 표현을 검색 가능한 범위 목록으로 파싱한다."""
        source = str(text or "")
        base_date = self._coerce_now(now)
        matches: list[DateQueryMatch] = []
        occupied_spans: list[tuple[int, int]] = []

        occupied_spans.extend(self._parse_numeric_dates(source, matches))
        occupied_spans.extend(self._parse_korean_japanese_dates(source, base_date, matches))
        occupied_spans.extend(self._parse_english_dates(source, base_date, matches))
        self._parse_relative_dates(source, base_date, matches)
        occupied_spans.extend(self._parse_month_parts(source, base_date, matches))
        occupied_spans.extend(self._parse_seasons(source, matches))
        self._parse_month_ranges(source, base_date, matches, occupied_spans)

        return self._deduplicate(matches)

    def _parse_numeric_dates(self, source: str, matches: list[DateQueryMatch]) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        for match in re.finditer(r"(?<!\d)((?:19|20)\d{2})[-./](\d{1,2})[-./](\d{1,2})(?!\d)", source):
            if self._add_day(matches, match.group(1), match.group(2), match.group(3), match.group(0), True):
                spans.append(match.span())
        return spans

    def _parse_korean_japanese_dates(
        self,
        source: str,
        base_date: date,
        matches: list[DateQueryMatch],
    ) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        full_date_spans: list[tuple[int, int]] = []
        for match in re.finditer(
            r"((?:19|20)\d{2})\s*[년年]\s*(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]",
            source,
        ):
            if self._add_day(matches, match.group(1), match.group(2), match.group(3), match.group(0), True):
                full_date_spans.append(match.span())
        spans.extend(full_date_spans)

        for match in re.finditer(r"(?<!\d)(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]", source):
            if self._spans_overlap(match.span(), full_date_spans):
                continue
            if self._add_day(matches, base_date.year, match.group(1), match.group(2), match.group(0), False):
                spans.append(match.span())
        return spans

    def _parse_english_dates(
        self,
        source: str,
        base_date: date,
        matches: list[DateQueryMatch],
    ) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        month_day = (
            rf"\b({self.ENGLISH_MONTH_PATTERN})\.?\s+"
            r"(\d{1,2})(?:st|nd|rd|th)?"
            r"(?:,?\s+((?:19|20)\d{2}))?\b"
        )
        for match in re.finditer(month_day, source, flags=re.IGNORECASE):
            month = self.ENGLISH_MONTHS[match.group(1).lower()]
            year = int(match.group(3)) if match.group(3) else base_date.year
            if self._add_day(matches, year, month, match.group(2), match.group(0), bool(match.group(3))):
                spans.append(match.span())

        day_month = (
            r"\b(\d{1,2})(?:st|nd|rd|th)?\s+"
            rf"({self.ENGLISH_MONTH_PATTERN})\.?"
            r"(?:,?\s+((?:19|20)\d{2}))?\b"
        )
        for match in re.finditer(day_month, source, flags=re.IGNORECASE):
            month = self.ENGLISH_MONTHS[match.group(2).lower()]
            year = int(match.group(3)) if match.group(3) else base_date.year
            if self._add_day(matches, year, month, match.group(1), match.group(0), bool(match.group(3))):
                spans.append(match.span())
        return spans

    def _parse_relative_dates(self, source: str, base_date: date, matches: list[DateQueryMatch]) -> None:
        lower_source = source.lower()
        relative_days = [
            (r"(?<!\w)(today)(?!\w)|오늘|今日", 0),
            (r"(?<!\w)(yesterday)(?!\w)|어제|昨日", -1),
            (r"그제|그저께|一昨日", -2),
            (r"(?<!\w)(tomorrow)(?!\w)|내일|明日", 1),
        ]
        for pattern, offset in relative_days:
            for match in re.finditer(pattern, lower_source, flags=re.IGNORECASE):
                target = base_date + timedelta(days=offset)
                matches.append(DateQueryMatch(target, target, "day", match.group(0), True))

        relative_weeks = [
            (r"(?<!\w)(this week)(?!\w)|이번\s*주|이번주|今週", 0),
            (r"(?<!\w)(last week)(?!\w)|지난\s*주|지난주|先週", -1),
            (r"(?<!\w)(next week)(?!\w)|다음\s*주|다음주|来週", 1),
        ]
        for pattern, offset in relative_weeks:
            for match in re.finditer(pattern, lower_source, flags=re.IGNORECASE):
                start = base_date - timedelta(days=base_date.weekday()) + timedelta(days=offset * 7)
                matches.append(DateQueryMatch(start, start + timedelta(days=6), "week", match.group(0), True))

        relative_months = [
            (r"(?<!\w)(this month)(?!\w)|이번\s*달|이번달|今月", 0),
            (r"(?<!\w)(last month)(?!\w)|지난\s*달|지난달|先月", -1),
            (r"(?<!\w)(next month)(?!\w)|다음\s*달|다음달|来月", 1),
        ]
        for pattern, offset in relative_months:
            for match in re.finditer(pattern, lower_source, flags=re.IGNORECASE):
                year, month = self._shift_month(base_date.year, base_date.month, offset)
                start, end = self._month_range(year, month)
                matches.append(DateQueryMatch(start, end, "month", match.group(0), True))

    def _parse_month_parts(
        self,
        source: str,
        base_date: date,
        matches: list[DateQueryMatch],
    ) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        ko_ja_parts = {
            "초": (1, 10),
            "上旬": (1, 10),
            "중순": (11, 20),
            "中旬": (11, 20),
            "말": (21, None),
            "下旬": (21, None),
        }
        part_pattern = "|".join(re.escape(part) for part in sorted(ko_ja_parts, key=len, reverse=True))
        for match in re.finditer(
            rf"(?:(?P<year>(?:19|20)\d{{2}})\s*[년年]\s*)?(?P<month>\d{{1,2}})\s*[월月]\s*(?P<part>{part_pattern})",
            source,
        ):
            if self._add_month_part(
                matches,
                int(match.group("year")) if match.group("year") else base_date.year,
                int(match.group("month")),
                ko_ja_parts[match.group("part")],
                match.group(0),
                bool(match.group("year")),
            ):
                spans.append(match.span())

        english_parts = {"early": (1, 10), "mid": (11, 20), "late": (21, None)}
        for match in re.finditer(
            rf"\b(?P<part>early|mid|late)\s+(?P<month>{self.ENGLISH_MONTH_PATTERN})\.?(?:\s+(?P<year>(?:19|20)\d{{2}}))?\b",
            source,
            flags=re.IGNORECASE,
        ):
            if self._add_month_part(
                matches,
                int(match.group("year")) if match.group("year") else base_date.year,
                self.ENGLISH_MONTHS[match.group("month").lower()],
                english_parts[match.group("part").lower()],
                match.group(0),
                bool(match.group("year")),
            ):
                spans.append(match.span())
        return spans

    def _parse_seasons(self, source: str, matches: list[DateQueryMatch]) -> list[tuple[int, int]]:
        spans: list[tuple[int, int]] = []
        ko_ja_seasons = "봄|여름|가을|겨울|春|夏|秋|冬"
        for match in re.finditer(rf"((?:19|20)\d{{2}})\s*[년年]\s*({ko_ja_seasons})", source):
            if self._add_season(matches, int(match.group(1)), match.group(2), match.group(0)):
                spans.append(match.span())

        english_seasons = "spring|summer|fall|autumn|winter"
        for match in re.finditer(rf"\b({english_seasons})\s+((?:19|20)\d{{2}})\b", source, flags=re.IGNORECASE):
            if self._add_season(matches, int(match.group(2)), match.group(1).lower(), match.group(0)):
                spans.append(match.span())
        for match in re.finditer(rf"\b((?:19|20)\d{{2}})\s+({english_seasons})\b", source, flags=re.IGNORECASE):
            if self._add_season(matches, int(match.group(1)), match.group(2).lower(), match.group(0)):
                spans.append(match.span())
        return spans

    def _parse_month_ranges(
        self,
        source: str,
        base_date: date,
        matches: list[DateQueryMatch],
        occupied_spans: Iterable[tuple[int, int]],
    ) -> None:
        occupied = list(occupied_spans)
        for match in re.finditer(r"((?:19|20)\d{2})\s*[년年]\s*(\d{1,2})\s*[월月]", source):
            if self._spans_overlap(match.span(), occupied):
                continue
            self._add_month(matches, int(match.group(1)), int(match.group(2)), match.group(0), True)
            occupied.append(match.span())

        for match in re.finditer(r"(?<!\d)(\d{1,2})\s*[월月]", source):
            if self._spans_overlap(match.span(), occupied):
                continue
            self._add_month(matches, base_date.year, int(match.group(1)), match.group(0), False)

        english_month = self.ENGLISH_MONTH_PATTERN
        for match in re.finditer(rf"\b({english_month})\.?\s+((?:19|20)\d{{2}})\b", source, flags=re.IGNORECASE):
            if self._spans_overlap(match.span(), occupied):
                continue
            self._add_month(matches, int(match.group(2)), self.ENGLISH_MONTHS[match.group(1).lower()], match.group(0), True)
            occupied.append(match.span())
        for match in re.finditer(rf"\b((?:19|20)\d{{2}})\s+({english_month})\.?\b", source, flags=re.IGNORECASE):
            if self._spans_overlap(match.span(), occupied):
                continue
            self._add_month(matches, int(match.group(1)), self.ENGLISH_MONTHS[match.group(2).lower()], match.group(0), True)
            occupied.append(match.span())

    def _add_day(
        self,
        matches: list[DateQueryMatch],
        year: str | int,
        month: str | int,
        day: str | int,
        source_text: str,
        has_year: bool,
    ) -> bool:
        try:
            parsed = date(int(year), int(month), int(day))
        except (TypeError, ValueError):
            return False
        matches.append(DateQueryMatch(parsed, parsed, "day", source_text, has_year))
        return True

    def _add_month(
        self,
        matches: list[DateQueryMatch],
        year: int,
        month: int,
        source_text: str,
        has_year: bool,
    ) -> bool:
        try:
            start, end = self._month_range(year, month)
        except ValueError:
            return False
        matches.append(DateQueryMatch(start, end, "month", source_text, has_year))
        return True

    def _add_month_part(
        self,
        matches: list[DateQueryMatch],
        year: int,
        month: int,
        day_range: tuple[int, int | None],
        source_text: str,
        has_year: bool,
    ) -> bool:
        try:
            last_day = calendar.monthrange(year, month)[1]
            start = date(year, month, day_range[0])
            end = date(year, month, day_range[1] or last_day)
        except ValueError:
            return False
        matches.append(DateQueryMatch(start, end, "month_part", source_text, has_year))
        return True

    def _add_season(
        self,
        matches: list[DateQueryMatch],
        year: int,
        season: str,
        source_text: str,
    ) -> bool:
        season_range = self.SEASONS.get(season)
        if not season_range:
            return False
        start_month, start_day, end_month, end_day = season_range
        end_year = year + 1 if end_month < start_month else year
        try:
            start = date(year, start_month, start_day)
            end = date(end_year, end_month, end_day)
        except ValueError:
            return False
        matches.append(DateQueryMatch(start, end, "season", source_text, True))
        return True

    def _month_range(self, year: int, month: int) -> tuple[date, date]:
        last_day = calendar.monthrange(year, month)[1]
        return date(year, month, 1), date(year, month, last_day)

    def _shift_month(self, year: int, month: int, offset: int) -> tuple[int, int]:
        shifted = (year * 12) + (month - 1) + offset
        return shifted // 12, (shifted % 12) + 1

    def _coerce_now(self, now: datetime | date | None) -> date:
        if now is None:
            return datetime.now().astimezone().date()
        if isinstance(now, datetime):
            return now.date()
        return now

    def _deduplicate(self, matches: Iterable[DateQueryMatch]) -> list[DateQueryMatch]:
        deduped: list[DateQueryMatch] = []
        seen: set[tuple[date, date, str, bool]] = set()
        for match in matches:
            key = (match.start, match.end, match.precision, match.has_year)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(match)
        return deduped

    def _spans_overlap(self, span: tuple[int, int], occupied_spans: Iterable[tuple[int, int]]) -> bool:
        start, end = span
        return any(start < occupied_end and end > occupied_start for occupied_start, occupied_end in occupied_spans)
