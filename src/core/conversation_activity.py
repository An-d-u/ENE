"""보관된 대화 원문과 현재 대화에서 확인할 수 있는 활동을 집계한다."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone, tzinfo

from ..ai.memory_types import MemoryMessage
from .local_time import resolve_local_time_context


@dataclass(frozen=True)
class SessionRecord:
    started_at: datetime
    minutes: int
    turns: int


@dataclass(frozen=True)
class ConversationActivity:
    as_of: date
    daily_turns: dict[date, int]
    hourly_turns: tuple[int, ...]
    total_turns: int
    characters: int
    first_day: date | None
    longest: SessionRecord | None
    streak_start: date | None
    streak_end: date | None
    streak_days: int


def _recorded_time(value: str, zone: tzinfo) -> datetime | None:
    # 구형 날짜 단독 기록에서 시각을 자정으로 꾸미지 않는다.
    if not isinstance(value, str) or len(value.strip()) <= 10:
        return None
    try:
        stamp = datetime.fromisoformat(value.strip())
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=zone)
        return stamp.astimezone(timezone.utc).astimezone(zone)
    except (ValueError, OverflowError):
        return None


def _message_groups(bridge, manager):
    """원래 대화와 발화 순번을 기준으로 중복 저장된 원문을 한 번만 읽는다."""
    groups = defaultdict(dict)
    retained_ids = set()
    for memory in getattr(manager, "memories", ()) or ():
        migration = getattr(memory, "migration_meta", {}) or {}
        inferred = migration.get("inferred_message_fields") or ()
        if migration.get("legacy_original_messages") or "role" in inferred or "timestamp" in inferred:
            continue
        for message in getattr(memory, "original_messages", ()):
            if not isinstance(message, MemoryMessage):
                continue
            retained_ids.add(memory.id)
            groups[message.conversation_id].setdefault(
                message.turn_index, (message.role, message.text, message.timestamp)
            )
    for group in groups.values():
        yield sorted(group.items())

    current = list(getattr(bridge, "conversation_buffer", ()) or ())
    review = getattr(bridge, "_pending_summary_review", None)
    if isinstance(review, dict) and getattr(review.get("saved_memory"), "id", None) in retained_ids:
        # 요약만 저장되고 후속 단계가 실패하면 같은 원문이 두 곳에 남는다.
        reviewed = review.get("messages") or []
        if current[:len(reviewed)] == reviewed:
            current = current[len(reviewed):]
    yield enumerate(current)


def _turns(group, zone, cutoff):
    previous = None
    for index, message in group:
        if not isinstance(message, (tuple, list)) or len(message) < 3:
            previous = None
            continue
        role, text, stamp = message[:3]
        when = _recorded_time(stamp, zone)
        if not when or not isinstance(text, str) or not text.strip():
            previous = None
            continue
        if role == "user":
            previous = (index, when, len(text.strip()))
            continue
        if role == "assistant" and previous is not None:
            user_index, start, user_chars = previous
            finish_utc = when.astimezone(timezone.utc)
            if index == user_index + 1 and start.astimezone(timezone.utc) <= finish_utc <= cutoff:
                yield start, finish_utc, user_chars + len(text.strip())
        previous = None


def conversation_activity(bridge=None, memory_manager=None, *, now: datetime | None = None) -> ConversationActivity:
    """현지 질문 시각을 기준으로 집계하며 입력한 현재 시각의 시간대를 따른다."""
    if now is None:
        now = datetime.now(resolve_local_time_context().view_timezone)
    if now.tzinfo is None:
        raise ValueError("집계 기준 시각에는 시간대가 필요합니다.")
    cutoff = now.astimezone(timezone.utc)
    if memory_manager is None:
        memory_manager = getattr(bridge, "memory_manager", None)

    days = Counter()
    hours = [0] * 24
    characters = 0
    longest = None
    longest_duration = timedelta(0)
    for group in _message_groups(bridge, memory_manager):
        first = last = None
        turns = 0
        for start, finish_utc, length in _turns(group, now.tzinfo, cutoff):
            days[start.date()] += 1
            hours[start.hour] += 1
            characters += length
            turns += 1
            start_utc = start.astimezone(timezone.utc)
            first = min(first, start_utc) if first else start_utc
            last = max(last, finish_utc) if last else finish_utc
        if not turns:
            continue
        duration = last - first
        if (
            longest is None
            or duration > longest_duration
            or (duration == longest_duration and first < longest.started_at.astimezone(timezone.utc))
        ):
            longest_duration = duration
            longest = SessionRecord(first.astimezone(now.tzinfo), duration // timedelta(minutes=1), turns)

    streak_days = run = 0
    streak_start = streak_end = previous_day = None
    for day in sorted(days):
        run = run + 1 if previous_day and (day - previous_day).days == 1 else 1
        if run > streak_days:
            streak_start = day - timedelta(days=run - 1)
            streak_end = day
            streak_days = run
        previous_day = day
    return ConversationActivity(
        as_of=now.date(),
        daily_turns=dict(days),
        hourly_turns=tuple(hours),
        total_turns=sum(hours),
        characters=characters,
        first_day=min(days, default=None),
        longest=longest,
        streak_start=streak_start,
        streak_end=streak_end,
        streak_days=streak_days,
    )
