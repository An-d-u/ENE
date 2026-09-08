"""동반 앱 시험은 가상 시각·식별자·문장만 사용한다."""

from datetime import datetime, timedelta, timezone
from itertools import count


def sample_id(number):
    return f"00000000-0000-4000-8000-{number:012d}"


def id_factory(start=100):
    numbers = count(start)
    return lambda: sample_id(next(numbers))


class FakeClock:
    def __init__(self):
        self.seconds = 0.0

    def monotonic(self):
        return self.seconds

    def utcnow(self):
        return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(
            seconds=self.seconds
        )

    def advance(self, seconds):
        self.seconds += seconds
