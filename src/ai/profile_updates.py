"""요약이 제안한 상태 변경의 시각과 사용자 발화 근거를 검증한다."""

from datetime import datetime, timezone
import re


def parse_memory_time(value):
    """시간대 없는 기존 시각은 로컬 시각으로 해석해 비교한다."""
    try:
        return datetime.fromisoformat(str(value)).astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def has_user_evidence(evidence, messages):
    """기억이나 조수의 말이 아닌 이번 사용자 원문에서 근거를 찾는다."""
    text = re.sub(r"\s+", " ", str(evidence or "")).strip()
    if len(text) < 4:
        return False
    for message in messages or []:
        role = message.get("role") if isinstance(message, dict) else getattr(message, "role", "")
        content = message.get("text", "") if isinstance(message, dict) else getattr(message, "text", "")
        if role == "user" and text in re.sub(r"\s+", " ", str(content)):
            return True
    return False


def is_current_update(update, messages):
    """확정된 현재 진술과 실제 사용자 근거를 모두 요구한다."""
    return (
        isinstance(update, dict)
        and update.get("assertion") == "current"
        and has_user_evidence(update.get("evidence"), messages)
    )
