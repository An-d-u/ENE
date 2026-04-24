"""
대화 요약 및 장기기억 추출 프롬프트 생성기.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class SummaryPrompt:
    prompt: str
    time_range: str


def _format_now(now: datetime | None = None) -> tuple[datetime, str]:
    current = now or datetime.now()
    return current, current.strftime("%Y년 %m월 %d일 %H시 %M분")


def _build_conversation_text(messages: list) -> tuple[str, str | None, str | None]:
    conv_lines: list[str] = []
    first_time: str | None = None
    last_time: str | None = None

    for item in messages or []:
        if isinstance(item, (list, tuple)) and len(item) == 3:
            role, content, timestamp = item
            timestamp_text = str(timestamp or "").strip()
            if timestamp_text:
                if first_time is None:
                    first_time = timestamp_text
                last_time = timestamp_text
                conv_lines.append(f"[{timestamp_text}] {role}: {content}")
            else:
                conv_lines.append(f"{role}: {content}")
            continue

        if isinstance(item, (list, tuple)) and len(item) >= 2:
            role, content = item[0], item[1]
            conv_lines.append(f"{role}: {content}")
            continue

        conv_lines.append(str(item))

    return "\n".join(conv_lines), first_time, last_time


def _build_elapsed_hint(first_time: str | None, last_time: str | None) -> str:
    if not first_time or not last_time:
        return ""
    try:
        start_dt = datetime.strptime(first_time, "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(last_time, "%Y-%m-%d %H:%M")
    except Exception:
        return ""

    total_minutes = int((end_dt - start_dt).total_seconds() // 60)
    if total_minutes < 0:
        total_minutes = 0
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0 and minutes > 0:
        return f"{hours}시간 {minutes}분"
    if hours > 0:
        return f"{hours}시간"
    return f"{minutes}분"


def build_current_profile_snapshot(user_profile) -> str:
    if not user_profile:
        return ""

    profile_lines = ["현재 user_profile 스냅샷 (중복 금지 기준):"]

    if hasattr(user_profile, "basic_info"):
        basic = user_profile.basic_info or {}
        basic_lines: list[str] = []
        if basic.get("name"):
            basic_lines.append(f"- 이름: {basic['name']}")
        if basic.get("gender"):
            basic_lines.append(f"- 성별: {basic['gender']}")
        if basic.get("birthday"):
            basic_lines.append(f"- 생일: {basic['birthday']}")
        if basic.get("occupation"):
            basic_lines.append(f"- 직업: {basic['occupation']}")
        if basic.get("major"):
            basic_lines.append(f"- 전공: {basic['major']}")
        if basic_lines:
            profile_lines.append("[basic_info]")
            profile_lines.extend(basic_lines)

    if hasattr(user_profile, "preferences"):
        prefs = user_profile.preferences or {}
        likes = prefs.get("likes", [])
        dislikes = prefs.get("dislikes", [])
        if likes or dislikes:
            profile_lines.append("[preferences]")
            if likes:
                profile_lines.append(f"- likes: {', '.join(likes)}")
            if dislikes:
                profile_lines.append(f"- dislikes: {', '.join(dislikes)}")

    if hasattr(user_profile, "get_all_facts"):
        facts = user_profile.get_all_facts()
        sorted_facts = sorted(facts, key=lambda x: x.timestamp, reverse=True)[:20]
        if sorted_facts:
            profile_lines.append("[facts]")
            profile_lines.extend([f"- [{f.category}] {f.content}" for f in sorted_facts])

    if len(profile_lines) <= 1:
        return ""
    return "\n".join(profile_lines)


def build_summary_prompt(messages: list, user_profile=None, now: datetime | None = None) -> SummaryPrompt:
    _, time_str = _format_now(now)
    conversation_text, first_time, last_time = _build_conversation_text(messages)
    time_range = f"{first_time} ~ {last_time}" if first_time and last_time else time_str
    elapsed_hint = _build_elapsed_hint(first_time, last_time)
    current_profile = build_current_profile_snapshot(user_profile)
    return build_summary_prompt_from_text(
        conversation_text,
        current_profile=current_profile,
        time_range=time_range,
        elapsed_hint=elapsed_hint,
        time_str=time_str,
    )


def build_summary_prompt_from_text(
    conversation_text: str,
    *,
    current_profile: str = "",
    time_range: str = "",
    elapsed_hint: str = "",
    time_str: str = "",
    now: datetime | None = None,
) -> SummaryPrompt:
    if not time_str:
        _, time_str = _format_now(now)
    resolved_time_range = time_range or time_str

    prompt = f"""아래 대화를 요약하고, 마스터 정보와 에네 정보를 추출하세요.
[CURRENT_PROFILE]
{current_profile}

[TIME_RANGE]
{resolved_time_range}

[ELAPSED_HINT]
{elapsed_hint}

[CONVERSATION]
{conversation_text}

[OUTPUT_FORMAT]
[SUMMARY]
- {time_str}에 이루어진 대화 요약
- [CONVERSATION]의 타임스탬프를 우선 기준으로 각 시간 흐름을 요약하세요.
- 문장 수를 기계적으로 고정하지 말고, 자연스럽고 읽기 좋은 길이(보통 1~3문장)로 작성하세요.
- [TIME_RANGE]와 [ELAPSED_HINT]는 참고용이며, 그대로 복붙하지 말고 맥락에 맞게 표현하세요.
- 같은 사건을 반복하지 말고, 핵심 행동만 요약하세요.
- 예 : "2026년 2월 9일 오후 5시경, 사용자가 생굴을 먹고 노로바이러스 증상을 걱정하며 에네와 증상 및 식단에 대해 대화를 나눴습니다. 오후 6시 30분 무렵에는 직접 찍은 도트 이미지를 공유하며 무료함을 달랬고, 오후 9시 20분경부터는 게임을 플레이하며 등장인물에 대한 감상을 이야기했습니다."

[MASTER_INFO]
- 없으면: none
- 있으면 아래 형식으로만 작성:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...

[ENE_INFO]
- 없으면: none
- 있으면 아래 형식으로만 작성:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
- [speaking_style] ...
- [relationship_tone] ...

[MEMORY_META]
- 없으면: none
- 있으면 아래 형식으로만 작성:
- memory_type: fact | preference | promise | event | relationship | task | general
- importance_reason: user_marked | promise | repeated_topic | long_term_preference | none
- confidence: 0.0~1.0 사이 숫자
- entity_names: 이름1, 이름2

[ALLOW]
- basic: 신상/직업/학력/환경/관계 같은 정적 정보
- preference: 선호하는 방식이나 취향/스타일
- goal: 달성하려는 목표
- habit: 반복되는 행동/루틴 성향
- speaking_style: 에네가 유지하는 말투, 설명 방식, 반응 스타일
- relationship_tone: 사용자와의 지속적인 거리감, 태도, 챙김 방식

[DISALLOW]
- 감정/기분/피곤함/흥분 등 일시적 상태
- 단순 인사/추임새
- 이미 basic 정보와 중복되는 취업/전공 진술
- 사용자에 대한 정보를 에네 정보처럼 옮겨 적는 것
- 근거 없는 추측성 정보

[DEDUP]
- 기존 정보와 의미가 같으면 새로 쓰지 마세요.
- 같은 의미의 문장은 더 구체적인 1개만 남기세요.
- 사용자 정보와 에네 정보가 겹치면 에네 정보에는 쓰지 마세요.

[STYLE]
- 너무 길지 않게 간결하게 작성하세요.
- 출력 형식을 정확히 지키세요.
- "**"와 같은 강조표시의 사용은 금지합니다.
"""
    return SummaryPrompt(prompt=prompt, time_range=resolved_time_range)
