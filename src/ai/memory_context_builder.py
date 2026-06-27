"""
LLM 클라이언트 공통 메모리 컨텍스트 빌더.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .persona_names import resolve_prompt_persona_names
from .prompt_language import resolve_prompt_language


ENGLISH_MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _english_month_name(value: datetime) -> str:
    month = int(getattr(value, "month", 0) or 0)
    if 1 <= month <= 12:
        return ENGLISH_MONTH_NAMES[month]
    return f"{month:02d}"


def _format_context_full_date(value: datetime, language: str = "ko") -> str:
    """로케일 인코딩에 의존하지 않고 컨텍스트용 전체 날짜를 만든다."""
    if language == "en":
        return f"{_english_month_name(value)} {value.day:02d}, {value.year:04d}"
    if language == "ja":
        return f"{value.year:04d}年{value.month:02d}月{value.day:02d}日"
    return f"{value.year:04d}년 {value.month:02d}월 {value.day:02d}일"


def _format_context_month_day(value: datetime, language: str = "ko") -> str:
    """로케일 인코딩에 의존하지 않고 컨텍스트용 월/일 라벨을 만든다."""
    if language == "en":
        return f"{_english_month_name(value)} {value.day:02d}"
    if language == "ja":
        return f"{value.month:02d}月{value.day:02d}日"
    return f"{value.month:02d}월 {value.day:02d}일"


def _format_context_month_day_time(value: datetime, language: str = "ko") -> str:
    """로케일 인코딩에 의존하지 않고 컨텍스트용 월/일/시각 라벨을 만든다."""
    if language == "en":
        return f"{_english_month_name(value)} {value.day:02d}, {value.hour:02d}:{value.minute:02d}"
    if language == "ja":
        return f"{value.month:02d}月{value.day:02d}日 {value.hour:02d}:{value.minute:02d}"
    return f"{value.month:02d}월 {value.day:02d}일 {value.hour:02d}:{value.minute:02d}"


def _settings_config(client) -> dict:
    settings = getattr(client, "settings", None)
    if isinstance(settings, dict):
        return settings
    config = getattr(settings, "config", None)
    return config if isinstance(config, dict) else {}


def memory_context_labels(client) -> dict[str, str]:
    language = resolve_prompt_language(settings_source=getattr(client, "settings", None))
    names = resolve_prompt_persona_names(settings_source=getattr(client, "settings", None), language=language)
    return {
        "ko": {
            "master_basic": f"{names.user} 기본 정보",
            "master_facts": f"{names.user}에 대한 정보",
            "ene_basic": f"{names.assistant} 기본 설정",
            "ene_facts": f"{names.assistant}에 대한 누적 정보",
            "important": "중요한 기억",
            "related": "관련된 과거 기억",
            "raw_chunks": "회상된 원문 조각",
            "chunk": "조각",
            "recent": "최근 대화 기록",
            "upcoming": "다가오는 일정",
            "past_due_events": "지나간 일정",
            "activity": "최근 대화 활동",
            "interaction": "오늘 상호작용",
            "overdue_promises": "지나간 대화 약속",
            "name": "이름",
            "gender": "성별",
            "birthday": "생일",
            "occupation": "직업",
            "major": "전공",
            "likes": "좋아하는 것",
            "done": "완료",
            "times": "회",
            "head_pat_today": "오늘 쓰다듬은 횟수",
            "head_pat_before": "지금 쓰다듬은 횟수",
            "missed": "놓침",
            "expired": "만료",
            "incomplete": "미완료",
        },
        "en": {
            "master_basic": f"{names.user} Basic Information",
            "master_facts": f"Information About {names.user}",
            "ene_basic": f"{names.assistant} Basic Settings",
            "ene_facts": f"Accumulated Information About {names.assistant}",
            "important": "Important Memories",
            "related": "Related Past Memories",
            "raw_chunks": "Recalled Raw Text Chunks",
            "chunk": "Chunk",
            "recent": "Recent Conversation Records",
            "upcoming": "Upcoming Schedule",
            "past_due_events": "Past Due Schedule",
            "activity": "Recent Conversation Activity",
            "interaction": "Today's Interaction",
            "overdue_promises": "Overdue Conversation Promises",
            "name": "Name",
            "gender": "Gender",
            "birthday": "Birthday",
            "occupation": "Occupation",
            "major": "Major",
            "likes": "Likes",
            "done": "done",
            "times": "times",
            "head_pat_today": "Head pats today",
            "head_pat_before": "Current head pats",
            "missed": "Missed",
            "expired": "Expired",
            "incomplete": "Incomplete",
        },
        "ja": {
            "master_basic": f"{names.user}基本情報",
            "master_facts": f"{names.user}に関する情報",
            "ene_basic": f"{names.assistant}基本設定",
            "ene_facts": f"{names.assistant}に関する蓄積情報",
            "important": "重要な記憶",
            "related": "関連する過去の記憶",
            "raw_chunks": "思い出した原文断片",
            "chunk": "断片",
            "recent": "最近の会話記録",
            "upcoming": "今後の予定",
            "past_due_events": "過ぎた予定",
            "activity": "最近の会話活動",
            "interaction": "今日のやり取り",
            "overdue_promises": "過ぎた会話の約束",
            "name": "名前",
            "gender": "性別",
            "birthday": "誕生日",
            "occupation": "職業",
            "major": "専攻",
            "likes": "好きなもの",
            "done": "完了",
            "times": "回",
            "head_pat_today": "今日なでた回数",
            "head_pat_before": "今なでた回数",
            "missed": "見逃し",
            "expired": "期限切れ",
            "incomplete": "未完了",
        },
    }[language]


def now_for_context(client) -> datetime:
    provider = getattr(client, "_now_for_context", None)
    if callable(provider):
        return provider()
    return datetime.now().astimezone()


def build_goal_context_block(client, prompt_language: str | None = None) -> str:
    """메모리 매니저와 독립적으로 활성 목표 컨텍스트를 만든다."""
    goal_manager = getattr(client, "goal_manager", None)
    if not goal_manager or not hasattr(goal_manager, "build_context_block"):
        return ""
    try:
        return str(goal_manager.build_context_block(language=prompt_language) or "").strip()
    except Exception as e:
        print(f"[LLM] Goal context append failed: {e}")
        return ""


def build_overdue_promise_context(client, labels: dict[str, str], language: str = "ko") -> str:
    promise_manager = getattr(client, "promise_manager", None)
    if not promise_manager or not hasattr(promise_manager, "list_promises"):
        return ""

    now_dt = now_for_context(client)
    recent_expired_cutoff = now_dt - timedelta(hours=24)
    selected: list[tuple[datetime, str, str]] = []

    for item in list(promise_manager.list_promises() or []):
        try:
            trigger_at = datetime.fromisoformat(str(getattr(item, "trigger_at", "") or "").strip())
        except Exception:
            continue

        overdue_minutes = (now_dt - trigger_at).total_seconds() / 60.0
        if overdue_minutes <= 10:
            continue

        if overdue_minutes <= 60:
            status = "missed"
        elif trigger_at >= recent_expired_cutoff:
            status = "expired"
        else:
            continue

        title = str(getattr(item, "title", "") or "").strip()
        if not title:
            continue
        selected.append((trigger_at, status, title))

    if not selected:
        return ""

    selected.sort(key=lambda item: item[0], reverse=True)
    lines = [f"[{labels['overdue_promises']}]"]
    for trigger_at, status, title in selected[:3]:
        time_label = _format_context_month_day_time(trigger_at, language)
        status_label = labels.get(status, status)
        lines.append(f"- [{status_label}] {time_label}: {title}")
    return "\n".join(lines)


def build_recent_incomplete_past_event_context(client, labels: dict[str, str], language: str = "ko") -> str:
    calendar_manager = getattr(client, "calendar_manager", None)
    if not calendar_manager or not hasattr(calendar_manager, "get_all_events"):
        return ""

    now_dt = now_for_context(client)
    today = now_dt.date()
    recent_cutoff = today - timedelta(days=7)
    selected: list[tuple[datetime, str, str]] = []

    for event in list(calendar_manager.get_all_events() or []):
        if bool(getattr(event, "completed", False)):
            continue
        try:
            event_date = datetime.fromisoformat(str(getattr(event, "date", "") or "").strip())
        except Exception:
            continue

        event_day = event_date.date()
        if not (recent_cutoff <= event_day < today):
            continue

        title = str(getattr(event, "title", "") or "").strip()
        if not title:
            continue
        description = str(getattr(event, "description", "") or "").strip()
        selected.append((event_date, title, description))

    if not selected:
        return ""

    selected.sort(key=lambda item: item[0], reverse=True)
    lines = [f"[{labels['past_due_events']}]"]
    for event_date, title, description in selected[:3]:
        date_label = _format_context_month_day(event_date, language)
        line = f"- [{labels['incomplete']}] {date_label}: {title}"
        if description:
            line += f" ({description})"
        lines.append(line)
    return "\n".join(lines)


def normalize_int_setting(value, *, default: int, min_value: int, max_value: int) -> int:
    """정수 설정값을 안전하게 정규화한다."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def normalize_bool_setting(value, *, default: bool) -> bool:
    """불리언 설정값을 안전하게 정규화한다."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


async def build_memory_context(
    client,
    query: str,
    recent_context: str = "",
    head_pat_count_before_message: int | None = None,
) -> str:
    """클라이언트 상태에서 LLM에 붙일 메모리 컨텍스트를 구성한다."""
    prompt_language_getter = getattr(client, "_prompt_language", None)
    prompt_language = (
        prompt_language_getter()
        if callable(prompt_language_getter)
        else resolve_prompt_language(settings_source=getattr(client, "settings", None))
    )
    goal_block = build_goal_context_block(client, prompt_language)
    memory_manager = getattr(client, "memory_manager", None)
    if not memory_manager:
        print("[LLM] 메모리 매니저 없음")
        return goal_block

    context_parts = []
    labels = memory_context_labels(client)
    normalized_query = str(query or "").strip()
    normalized_recent_context = str(recent_context or "").strip()

    settings_config = _settings_config(client)
    max_profile_facts = settings_config.get("max_profile_facts_in_context", 10)
    try:
        max_profile_facts = max(0, int(max_profile_facts))
    except (TypeError, ValueError):
        max_profile_facts = 10

    user_profile = getattr(client, "user_profile", None)
    if user_profile:
        profile_lines = [f"[{labels['master_basic']}]"]

        basic = getattr(user_profile, "basic_info", {}) or {}
        if basic.get("name"):
            profile_lines.append(f"- {labels['name']}: {basic['name']}")
        if basic.get("gender"):
            profile_lines.append(f"- {labels['gender']}: {basic['gender']}")
        if basic.get("birthday"):
            profile_lines.append(f"- {labels['birthday']}: {basic['birthday']}")
        if basic.get("occupation"):
            profile_lines.append(f"- {labels['occupation']}: {basic['occupation']}")
        if basic.get("major"):
            profile_lines.append(f"- {labels['major']}: {basic['major']}")

        prefs = getattr(user_profile, "preferences", {}) or {}
        if prefs.get("likes"):
            profile_lines.append(f"- {labels['likes']}: {', '.join(prefs['likes'])}")

        if len(profile_lines) > 1:
            context_parts.append("\n".join(profile_lines))
            print(f"[LLM] 프로필 정보 포함: {len(profile_lines) - 1}개 항목")

        if hasattr(user_profile, "get_all_facts"):
            facts = user_profile.get_all_facts()
            if facts:
                try:
                    facts = sorted(
                        facts,
                        key=lambda fact: getattr(fact, "timestamp", "") or "",
                        reverse=True,
                    )
                except Exception:
                    facts = list(facts)
                if max_profile_facts > 0:
                    facts = facts[:max_profile_facts]
                fact_lines = [f"[{labels['master_facts']}]"]
                for fact in facts:
                    fact_lines.append(f"- [{fact.category}] : {fact.content}")
                context_parts.append("\n".join(fact_lines))
                print(f"[LLM] facts 포함: {len(facts)}개 항목")

    ene_profile = getattr(client, "ene_profile", None)
    if ene_profile:
        core_profile = getattr(ene_profile, "core_profile", {}) or {}
        ene_core_lines = [f"[{labels['ene_basic']}]"]
        for group_name in ("identity", "speaking_style", "relationship_tone"):
            values = core_profile.get(group_name, []) or []
            for value in values:
                text = str(value or "").strip()
                if text:
                    ene_core_lines.append(f"- {text}")
        if len(ene_core_lines) > 1:
            context_parts.append("\n".join(ene_core_lines))
            print(f"[LLM] 에네 기본 설정 포함: {len(ene_core_lines) - 1}개 항목")

        raw_ene_facts = list(getattr(ene_profile, "facts", []) or [])
        if raw_ene_facts:
            sorted_ene_facts = sorted(
                raw_ene_facts,
                key=lambda fact: (
                    0 if getattr(fact, "origin", "") == "manual" and not getattr(fact, "auto_update", True) else
                    1 if getattr(fact, "origin", "") == "manual" else
                    2,
                    str(getattr(fact, "timestamp", "") or ""),
                ),
            )
            ene_fact_lines = [f"[{labels['ene_facts']}]"]
            for fact in sorted_ene_facts[:max_profile_facts]:
                category = str(getattr(fact, "category", "") or "").strip()
                content = str(getattr(fact, "content", "") or "").strip()
                if not content:
                    continue
                if category:
                    ene_fact_lines.append(f"- [{category}] {content}")
                else:
                    ene_fact_lines.append(f"- {content}")
            if len(ene_fact_lines) > 1:
                context_parts.append("\n".join(ene_fact_lines))
                print(f"[LLM] 에네 facts 포함: {len(ene_fact_lines) - 1}개 항목")

    mood_manager = getattr(client, "mood_manager", None)
    if mood_manager and hasattr(mood_manager, "build_context_block"):
        try:
            mood_block = mood_manager.build_context_block(language=prompt_language)
            if mood_block:
                context_parts.append("\n" + mood_block)
                print("[LLM] Mood context included")
        except Exception as e:
            print(f"[LLM] Mood context append failed: {e}")

    if goal_block:
        context_parts.append("\n" + goal_block)
        print("[LLM] Goal context included")

    overdue_promise_block = build_overdue_promise_context(client, labels, prompt_language)
    if overdue_promise_block:
        context_parts.append("\n" + overdue_promise_block)
        print("[LLM] 지난 약속 컨텍스트 포함")

    past_due_event_block = build_recent_incomplete_past_event_context(client, labels, prompt_language)
    if past_due_event_block:
        context_parts.append("\n" + past_due_event_block)
        print("[LLM] 지난 일정 컨텍스트 포함")

    max_important = settings_config.get("max_important_memories", 3)
    max_similar = settings_config.get("max_similar_memories", 3)
    min_sim = settings_config.get("min_similarity", 0.35)
    max_recent = settings_config.get("max_recent_memories", 2)
    activation_enabled = normalize_bool_setting(
        settings_config.get("memory_activation_enabled", True),
        default=True,
    )
    max_activated = normalize_int_setting(
        settings_config.get("max_activated_memories", max_similar),
        default=max_similar,
        min_value=0,
        max_value=10,
    )
    activation_expand_hops = normalize_int_setting(
        settings_config.get("memory_activation_expand_hops", 1),
        default=1,
        min_value=0,
        max_value=1,
    )
    max_raw_chunks = normalize_int_setting(
        settings_config.get("max_raw_chunks_in_context", 2),
        default=2,
        min_value=0,
        max_value=5,
    )
    raw_chunk_turns = normalize_int_setting(
        settings_config.get("raw_chunk_turns", 6),
        default=6,
        min_value=1,
        max_value=12,
    )

    important_memories = memory_manager.get_important()
    if important_memories:
        print(f"[LLM] 중요 기억 {len(important_memories)}개 발견")
        context_parts.append(f"\n[{labels['important']}]")
        for memory in important_memories[:max_important]:
            context_parts.append(f"- {memory.summary}")
            print(f"  {memory.summary[:50]}...")
    else:
        print("[LLM] 중요 기억 없음")

    similar_memories = []
    activation_attempted = False
    related_memories_reported = False
    try:
        if activation_enabled and max_activated > 0 and hasattr(memory_manager, "find_activated"):
            activation_attempted = True
            activated_results = await memory_manager.find_activated(
                normalized_query,
                recent_context=normalized_recent_context,
                top_k=max_activated,
                min_similarity=min_sim,
                expand_hops=activation_expand_hops,
            )
            similar_memories = [
                (result.memory, result.activation_score)
                for result in activated_results
            ]
            if similar_memories:
                print(f"[LLM] 활성화 기억 {len(similar_memories)}개 발견")

        if not activation_attempted:
            similar_memories = await memory_manager.find_similar(
                normalized_query,
                top_k=max_similar,
                min_similarity=min_sim,
            )

        if similar_memories:
            related_memories_reported = True
            print(f"[LLM] 유사 기억 {len(similar_memories)}개 발견")
            context_parts.append(f"\n[{labels['related']}]")
            for memory, similarity in similar_memories:
                context_parts.append(f"- {memory.summary}")
                print(f"  [{similarity:.2f}] {memory.summary[:50]}...")
        else:
            related_memories_reported = True
            print("[LLM] 유사 기억 없음")

    except Exception as e:
        print(f"[LLM] 기억 검색 실패: {e}")
        import traceback
        traceback.print_exc()

        if activation_attempted:
            try:
                similar_memories = await memory_manager.find_similar(
                    normalized_query,
                    top_k=max_similar,
                    min_similarity=min_sim,
                )
            except Exception as fallback_error:
                print(f"[LLM] 유사 기억 fallback 실패: {fallback_error}")
                import traceback
                traceback.print_exc()

    if not related_memories_reported:
        if similar_memories:
            print(f"[LLM] 유사 기억 {len(similar_memories)}개 발견")
            context_parts.append(f"\n[{labels['related']}]")
            for memory, similarity in similar_memories:
                context_parts.append(f"- {memory.summary}")
                print(f"  [{similarity:.2f}] {memory.summary[:50]}...")
        else:
            print("[LLM] 유사 기억 없음")

    if max_raw_chunks > 0 and similar_memories and hasattr(memory_manager, "find_relevant_raw_chunks"):
        try:
            raw_chunks = await memory_manager.find_relevant_raw_chunks(
                normalized_query,
                similar_memories,
                recent_context=normalized_recent_context,
                top_k=max_raw_chunks,
                chunk_turns=raw_chunk_turns,
            )
            if raw_chunks:
                print(f"[LLM] raw chunk {len(raw_chunks)}개 선택")
                context_parts.append(f"\n[{labels['raw_chunks']}]")
                for index, (chunk, score, score_meta) in enumerate(raw_chunks, start=1):
                    context_parts.append(
                        f"- {labels['chunk']} {index} (turn {chunk.start_turn_index}-{chunk.end_turn_index})"
                    )
                    for line in str(chunk.text or "").splitlines():
                        context_parts.append(f"  {line}")
                    print(
                        "[LLM] raw chunk 선택 "
                        f"{index}: score={score:.3f}, "
                        f"primary={score_meta.get('primary_similarity', 0.0):.3f}, "
                        f"support={score_meta.get('support_similarity', 0.0):.3f}, "
                        f"keyword={score_meta.get('keyword_score', 0.0):.3f}"
                    )
            else:
                print("[LLM] raw chunk 없음")
        except Exception as e:
            print(f"[LLM] raw chunk 검색 실패: {e}")
            import traceback
            traceback.print_exc()

    recent_memories = memory_manager.get_recent(count=max_recent)
    if recent_memories:
        print(f"[LLM] 최근 기억 {len(recent_memories)}개 사용")
        context_parts.append(f"[{labels['recent']}]")
        for memory in recent_memories:
            try:
                dt = datetime.fromisoformat(memory.timestamp)
                date_str = _format_context_full_date(dt, prompt_language)
                context_parts.append(f"- [{date_str}] {memory.summary}")
                print(f"  [{date_str}] {memory.summary[:40]}...")
            except Exception:
                context_parts.append(f"- {memory.summary}")
                print(f"  {memory.summary[:50]}...")

    calendar_manager = getattr(client, "calendar_manager", None)
    if calendar_manager:
        upcoming = calendar_manager.get_upcoming_events(days=3)
        if upcoming:
            print(f"[LLM] 다가오는 일정 {len(upcoming)}개 발견")
            context_parts.append(f"\n[{labels['upcoming']}]")
            for event in upcoming:
                try:
                    event_date = datetime.fromisoformat(event.date)
                    date_str = _format_context_month_day(event_date, prompt_language)
                    status = f" ✓ {labels['done']}" if event.completed else ""
                    if event.description:
                        event_info = f"- {date_str}: {event.title} ({event.description}){status}"
                    else:
                        event_info = f"- {date_str}: {event.title}{status}"
                    context_parts.append(event_info)
                    print(f"  {event_info}")
                except Exception:
                    pass

    if calendar_manager:
        recent_counts = calendar_manager.get_recent_or_latest_conversation_counts(days=7, exclude_today=True)
        if recent_counts:
            context_parts.append(f"\n[{labels['activity']}]")
            for date_str, count in recent_counts.items():
                try:
                    date_obj = datetime.fromisoformat(date_str)
                    date_display = _format_context_month_day(date_obj, prompt_language)
                    context_parts.append(f"- {date_display}: {count}{labels['times']}")
                except Exception:
                    pass
            print(f"[LLM] 최근 대화 횟수 {len(recent_counts)}일 포함")

    if calendar_manager:
        today_str = datetime.now().strftime("%Y-%m-%d")
        today_head_pat_count = int(calendar_manager.get_head_pat_count(today_str))
        if head_pat_count_before_message is None:
            head_pat_count = int(calendar_manager.get_pending_head_pat_count())
        else:
            head_pat_count = int(head_pat_count_before_message)
        context_parts.append(f"\n[{labels['interaction']}]")
        context_parts.append(f"- {labels['head_pat_today']}: {today_head_pat_count}{labels['times']}")
        context_parts.append(f"- {labels['head_pat_before']}: {head_pat_count}{labels['times']}")

    if context_parts:
        result = "\n".join(context_parts)
        print(f"[LLM] 총 메모리 컨텍스트: {len(result)}자")
        return result

    print("[LLM] 사용 가능한 기억 없음")
    return ""
