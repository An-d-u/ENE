"""
선제 대화 실행 상태를 판단하는 순수 함수 모음.
"""
from datetime import datetime

def proactive_fire_signature(payload: dict | None) -> str:
    """같은 선제 대화 실행인지 판별할 간단한 서명을 만든다."""
    data = payload or {}
    cooldown_key = str(data.get("cooldown_key", "") or "").strip().lower()
    title = str(data.get("title", "") or "").strip().lower()
    trigger_at = str(data.get("trigger_at", "") or "").strip()
    trigger_key = trigger_at[:16] if trigger_at else ""
    if not cooldown_key or not title or not trigger_key:
        return ""
    return f"{cooldown_key}|{title}|{trigger_key}"


def prune_recent_proactive_fire_signatures(
    recent_signatures: dict | None,
    now_dt: datetime,
    ttl_seconds: int = 600,
) -> dict:
    """최근 선제 대화 실행 서명 목록에서 만료된 항목을 제거한 사본을 반환한다."""
    kept = {}
    for signature, fired_at in (recent_signatures or {}).items():
        if not isinstance(fired_at, datetime):
            continue
        if (now_dt - fired_at).total_seconds() <= ttl_seconds:
            kept[str(signature)] = fired_at
    return kept


def should_suppress_duplicate_proactive_fire(
    payload: dict | None,
    *,
    active_signature: str = "",
    queued_payloads: list | None = None,
    recent_signatures: dict | None = None,
    now_dt: datetime,
    ttl_seconds: int = 600,
) -> bool:
    """이미 진행/대기/최근 실행한 동일 선제 대화면 중복 실행을 막는다."""
    signature = proactive_fire_signature(payload)
    if not signature:
        return False

    if signature == str(active_signature or "").strip():
        return True

    for queued in list(queued_payloads or []):
        if proactive_fire_signature(queued) == signature:
            return True

    kept_recent = prune_recent_proactive_fire_signatures(recent_signatures, now_dt, ttl_seconds)
    fired_at = kept_recent.get(signature)
    if isinstance(fired_at, datetime) and (now_dt - fired_at).total_seconds() <= ttl_seconds:
        return True
    return False


def build_proactive_conversation_prompt(
    *,
    language: str,
    generation_prompt: str,
    title: str = "",
    reason: str = "",
    user_name: str | None = None,
) -> str:
    """저장된 선제 대화 예약을 ENE 응답 생성용 프롬프트로 변환한다."""
    normalized_language = str(language or "ko").strip().lower()
    prompt_user_name = str(user_name or "").strip() or {
        "ko": "마스터",
        "en": "Master",
        "ja": "マスター",
    }.get(normalized_language, "마스터")
    normalized_title = str(title or "").strip() or {
        "ko": "선제 대화",
        "en": "proactive conversation",
        "ja": "先回り会話",
    }.get(normalized_language, "선제 대화")
    normalized_prompt = str(generation_prompt or "").strip()
    normalized_reason = str(reason or "").strip()

    if normalized_language == "en":
        return (
            f"Status notice: this is a good moment to proactively message {prompt_user_name}. "
            f"The internal title is '{normalized_title}'. "
            f"Reason: '{normalized_reason}'. "
            f"Instruction: {normalized_prompt} "
            "Reply with one or two short, natural sentences. Do not explain this notice. "
            "Do not create a new proactive conversation reservation."
        )
    if normalized_language == "ja":
        return (
            f"状態通知: {prompt_user_name}にこちらから短く話しかけるタイミングです。"
            f"内部タイトルは「{normalized_title}」です。"
            f"理由:「{normalized_reason}」。"
            f"指示: {normalized_prompt} "
            "一、二文で自然に返してください。この通知自体は説明しないでください。"
            "新しい先回り会話の予約は作らないでください。"
        )
    return (
        f"상태 알림: {prompt_user_name}에게 먼저 말을 걸 타이밍이야. "
        f"내부 제목은 '{normalized_title}'이고, 이유는 '{normalized_reason}'이야. "
        f"실행 지시: {normalized_prompt} "
        "이 알림 자체는 설명하지 말고, 자연스러운 한두 문장으로만 답해줘. "
        "새 선제 대화 예약은 만들지 마."
    )
