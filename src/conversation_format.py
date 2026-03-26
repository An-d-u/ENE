"""대화 컨텍스트 직렬화 공용 유틸리티."""


def prepend_message_time(content: str, timestamp: str | None = None) -> str:
    """모델에만 보이는 Message Time 프리픽스를 메시지 앞에 붙인다."""
    text = "" if content is None else str(content)
    ts = str(timestamp or "").strip()
    if not ts:
        return text
    return f"[Message Time: {ts}]\n{text}"


def role_label_for_context(role: str) -> str:
    """검색용 문맥에서 사용할 표시명을 반환한다."""
    normalized = str(role or "").strip().lower()
    if normalized == "user":
        return "마스터"
    if normalized in {"assistant", "model"}:
        return "에네"
    return normalized
