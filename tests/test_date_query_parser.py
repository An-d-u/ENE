from datetime import date, datetime

from src.ai.date_query_parser import DateQueryParser


def _fixed_now() -> datetime:
    return datetime(2026, 7, 8, 12, 0, 0)


def _ranges(text: str):
    parser = DateQueryParser()
    return {
        (match.start, match.end, match.precision, match.has_year)
        for match in parser.parse(text, now=_fixed_now())
    }


def test_parse_exact_dates_in_korean_english_japanese():
    expected_full = (date(2026, 4, 14), date(2026, 4, 14), "day", True)
    expected_yearless = (date(2026, 4, 14), date(2026, 4, 14), "day", False)

    assert expected_full in _ranges("2026년 4월 14일에 무슨 일이 있었어?")
    assert expected_full in _ranges("2026年4月14日は何があった?")
    assert expected_full in _ranges("What happened on April 14, 2026?")
    assert expected_full in _ranges("What happened on 14 Apr 2026?")
    assert expected_full in _ranges("What happened on 2026-04-14?")

    assert expected_yearless in _ranges("4월 14일에는?")
    assert expected_yearless in _ranges("4月14日は?")
    assert expected_yearless in _ranges("What happened on Apr 14th?")


def test_parse_relative_day_week_month_in_korean_english_japanese():
    yesterday = (date(2026, 7, 7), date(2026, 7, 7), "day", True)
    last_week = (date(2026, 6, 29), date(2026, 7, 5), "week", True)
    next_month = (date(2026, 8, 1), date(2026, 8, 31), "month", True)

    assert yesterday in _ranges("어제 뭐 이야기했어?")
    assert yesterday in _ranges("What did we discuss yesterday?")
    assert yesterday in _ranges("昨日は何を話した?")

    assert last_week in _ranges("지난주에 정한 것 알려줘")
    assert last_week in _ranges("What happened last week?")
    assert last_week in _ranges("先週の話を教えて")

    assert next_month in _ranges("다음 달 일정 보여줘")
    assert next_month in _ranges("Show next month")
    assert next_month in _ranges("来月の予定を見せて")


def test_parse_month_parts_and_seasons_in_korean_english_japanese():
    assert (date(2026, 4, 1), date(2026, 4, 10), "month_part", False) in _ranges("4월 초에 이야기한 것")
    assert (date(2026, 4, 11), date(2026, 4, 20), "month_part", False) in _ranges("4月中旬の記録")
    assert (date(2026, 4, 21), date(2026, 4, 30), "month_part", True) in _ranges("late April 2026 notes")

    assert (date(2026, 3, 1), date(2026, 5, 31), "season", True) in _ranges("spring 2026")
    assert (date(2026, 9, 1), date(2026, 11, 30), "season", True) in _ranges("2026년 가을")
    assert (date(2026, 12, 1), date(2027, 2, 28), "season", True) in _ranges("2026年冬")


def test_parse_month_ranges_in_korean_english_japanese():
    assert (date(2026, 4, 1), date(2026, 4, 30), "month", True) in _ranges("2026년 4월")
    assert (date(2026, 4, 1), date(2026, 4, 30), "month", True) in _ranges("April 2026")
    assert (date(2026, 4, 1), date(2026, 4, 30), "month", True) in _ranges("2026 April")
    assert (date(2026, 4, 1), date(2026, 4, 30), "month", False) in _ranges("4月の話")


def test_parse_deduplicates_equivalent_dates():
    matches = DateQueryParser().parse("2026-04-14 그리고 2026년 4월 14일", now=_fixed_now())
    exact_days = [
        match
        for match in matches
        if match.start == date(2026, 4, 14)
        and match.end == date(2026, 4, 14)
        and match.precision == "day"
        and match.has_year
    ]

    assert len(exact_days) == 1
