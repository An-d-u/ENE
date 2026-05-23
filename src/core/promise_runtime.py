"""
대화 약속 실행 상태를 판단하는 순수 함수 모음.
"""
from datetime import datetime


def collect_promise_ids(items: list | None) -> list[str]:
    """저장 결과에서 유효한 약속 id만 추출한다."""
    collected: list[str] = []
    for item in items or []:
        reminder_id = ""
        if isinstance(item, dict):
            reminder_id = str(item.get("id", "") or "").strip()
        else:
            reminder_id = str(getattr(item, "id", "") or "").strip()
        if reminder_id:
            collected.append(reminder_id)
    return collected


def promise_fire_signature(payload: dict | None) -> str:
    """같은 예약 발화인지 판별할 간단한 서명을 만든다."""
    data = payload or {}
    title = str(data.get("title", "") or "").strip().lower()
    trigger_at = str(data.get("trigger_at", "") or "").strip()
    trigger_key = trigger_at[:16] if trigger_at else ""
    if not title or not trigger_key:
        return ""
    return f"{title}|{trigger_key}"


def prune_recent_promise_fire_signatures(
    recent_signatures: dict | None,
    now_dt: datetime,
    ttl_seconds: int = 600,
) -> dict:
    """최근 발화 서명 목록에서 만료된 항목을 제거한 사본을 반환한다."""
    kept = {}
    for signature, fired_at in (recent_signatures or {}).items():
        if not isinstance(fired_at, datetime):
            continue
        if (now_dt - fired_at).total_seconds() <= ttl_seconds:
            kept[str(signature)] = fired_at
    return kept


def should_suppress_duplicate_promise_fire(
    payload: dict | None,
    *,
    active_signature: str = "",
    queued_payloads: list | None = None,
    recent_signatures: dict | None = None,
    now_dt: datetime,
    ttl_seconds: int = 600,
) -> bool:
    """이미 진행/대기/최근 발화한 동일 예약이면 중복 발화를 막는다."""
    signature = promise_fire_signature(payload)
    if not signature:
        return False

    if signature == str(active_signature or "").strip():
        return True

    for queued in list(queued_payloads or []):
        if promise_fire_signature(queued) == signature:
            return True

    kept_recent = prune_recent_promise_fire_signatures(recent_signatures, now_dt, ttl_seconds)
    fired_at = kept_recent.get(signature)
    if isinstance(fired_at, datetime) and (now_dt - fired_at).total_seconds() <= ttl_seconds:
        return True
    return False


def build_promise_nudge_prompt(*, language: str, title: str, source_excerpt: str) -> str:
    """도래한 대화 약속을 ENE 응답용 프롬프트로 변환한다."""
    normalized_language = str(language or "ko").strip().lower()
    normalized_title = str(title or "").strip() or {
        "ko": "약속",
        "en": "promise",
        "ja": "約束",
    }.get(normalized_language, "약속")
    normalized_excerpt = str(source_excerpt or "").strip()

    if normalized_language == "en":
        return (
            f"Status notice: it is time for a conversation promise with Master. "
            f"The promise title is '{normalized_title}', and the original context is '{normalized_excerpt}'. "
            f"Give one short, natural line that continues the earlier conversation."
        )
    if normalized_language == "ja":
        return (
            f"状態通知: マスターとの会話の約束の時間になりました。"
            f"約束のタイトルは「{normalized_title}」、元の文脈は「{normalized_excerpt}」です。"
            f"前の会話につながる短く自然な一言を返してください。"
        )
    return (
        f"상태 알림: 마스터와의 대화 약속 시간이 되었어. "
        f"약속 제목은 '{normalized_title}'이고, 원래 맥락은 '{normalized_excerpt}' 이야. "
        f"이전 대화를 이어주는 짧고 자연스러운 한마디를 해줘."
    )
