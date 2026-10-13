"""저장 데이터를 바꾸지 않고 목적별 프로필 입력을 선별한다."""

import re

from .profile_review import normalize_subject
from .profile_updates import parse_memory_time


_GENERIC = {"상태", "현재", "정보", "목표", "계획", "기억", "알려줘", "말해줘", "어떻게", "어떤", "무엇", "the", "is", "was", "what", "goal", "state", "현재는"}
_PARTICLES = re.compile(r"(.{2,}?)(?:에서는|으로|에서|에게|은|는|이|가|을|를|의|도|에|과|와)$")


def _tokens(text):
    values = set()
    for word in re.findall(r"[^\W_]+", normalize_subject(text)):
        match = _PARTICLES.fullmatch(word)
        word = match.group(1) if match else word
        if len(word) >= 2 and word not in _GENERIC:
            values.add(word)
    return values


def _score(fact, query, query_tokens):
    subject = normalize_subject(getattr(fact, "subject", ""))
    exact = bool(subject and re.search(r"(?<![\w])" + re.escape(subject) + r"(?=$|\W|[은는이가을를의도에과와])", query))
    subject_overlap = len(query_tokens & _tokens(subject))
    content_overlap = len(query_tokens & _tokens(getattr(fact, "content", "")))
    return int(exact), subject_overlap, content_overlap


def _time(value):
    parsed = parse_memory_time(value)
    return parsed.timestamp() if parsed else float("-inf")


def _select(facts, text, limit):
    query = normalize_subject(text)
    query_tokens = _tokens(text)
    unique = []
    seen = set()
    for fact in facts:
        identifier = getattr(fact, "id", None)
        if identifier and identifier in seen:
            continue
        if identifier:
            seen.add(identifier)
        unique.append(fact)
    selected = sorted(unique, key=lambda fact: (
        *_score(fact, query, query_tokens),
        _time(getattr(fact, "effective_at", "") or getattr(fact, "timestamp", "")),
        _time(getattr(fact, "timestamp", "")),
    ), reverse=True)
    return selected[:limit] if limit > 0 else selected


def select_response_facts(facts, query, limit):
    """답변 관련 사실을 우선하고 남는 자리는 최근 사실로 채운다."""
    return _select(facts, query, max(0, limit))


def select_summary_facts(facts, user_text, limit=20):
    """이번 사용자 원문과 비교할 기존 사실의 ID를 보존한다."""
    return _select(facts, user_text, max(0, limit))
