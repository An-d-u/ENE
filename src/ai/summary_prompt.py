"""
대화 요약 및 장기기억 추출 프롬프트 생성기.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .persona_names import default_prompt_persona_names
from .prompt_language import resolve_prompt_language


@dataclass(frozen=True)
class SummaryPrompt:
    prompt: str
    time_range: str


def _format_now(now: datetime | None = None) -> tuple[datetime, str]:
    current = now or datetime.now()
    return current, f"{current.year:04d}년 {current.month:02d}월 {current.day:02d}일 {current.hour:02d}시 {current.minute:02d}분"


def _format_now_for_language(language: str, now: datetime | None = None) -> tuple[datetime, str]:
    current = now or datetime.now()
    if language == "en":
        return current, current.strftime("%B %d, %Y %H:%M")
    if language == "ja":
        return current, f"{current.year:04d}年{current.month:02d}月{current.day:02d}日 {current.hour:02d}時{current.minute:02d}分"
    return current, f"{current.year:04d}년 {current.month:02d}월 {current.day:02d}일 {current.hour:02d}시 {current.minute:02d}분"


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


def _build_elapsed_hint(first_time: str | None, last_time: str | None, language: str = "ko") -> str:
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
    if language == "en":
        if hours > 0 and minutes > 0:
            return f"{hours} hours {minutes} minutes"
        if hours > 0:
            return f"{hours} hours"
        return f"{minutes} minutes"
    if language == "ja":
        if hours > 0 and minutes > 0:
            return f"{hours}時間{minutes}分"
        if hours > 0:
            return f"{hours}時間"
        return f"{minutes}分"
    if hours > 0 and minutes > 0:
        return f"{hours}시간 {minutes}분"
    if hours > 0:
        return f"{hours}시간"
    return f"{minutes}분"


def build_current_profile_snapshot(user_profile, language: str = "ko") -> str:
    if not user_profile:
        return ""

    language = resolve_prompt_language(language)
    header = {
        "ko": "현재 user_profile 스냅샷 (중복 금지 기준):",
        "en": "Current user_profile snapshot (deduplication reference):",
        "ja": "現在のuser_profileスナップショット（重複防止の基準）:",
    }[language]
    labels = {
        "ko": {"name": "이름", "gender": "성별", "birthday": "생일", "occupation": "직업", "major": "전공"},
        "en": {"name": "name", "gender": "gender", "birthday": "birthday", "occupation": "occupation", "major": "major"},
        "ja": {"name": "名前", "gender": "性別", "birthday": "誕生日", "occupation": "職業", "major": "専攻"},
    }[language]
    profile_lines = [header]

    if hasattr(user_profile, "basic_info"):
        basic = user_profile.basic_info or {}
        basic_lines: list[str] = []
        if basic.get("name"):
            basic_lines.append(f"- {labels['name']}: {basic['name']}")
        if basic.get("gender"):
            basic_lines.append(f"- {labels['gender']}: {basic['gender']}")
        if basic.get("birthday"):
            basic_lines.append(f"- {labels['birthday']}: {basic['birthday']}")
        if basic.get("occupation"):
            basic_lines.append(f"- {labels['occupation']}: {basic['occupation']}")
        if basic.get("major"):
            basic_lines.append(f"- {labels['major']}: {basic['major']}")
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


def build_summary_prompt(
    messages: list,
    user_profile=None,
    now: datetime | None = None,
    language: str | None = None,
    assistant_name: str | None = None,
    user_name: str | None = None,
) -> SummaryPrompt:
    resolved_language = resolve_prompt_language(language)
    _, time_str = _format_now_for_language(resolved_language, now)
    conversation_text, first_time, last_time = _build_conversation_text(messages)
    time_range = f"{first_time} ~ {last_time}" if first_time and last_time else time_str
    elapsed_hint = _build_elapsed_hint(first_time, last_time, resolved_language)
    current_profile = build_current_profile_snapshot(user_profile, resolved_language)
    return build_summary_prompt_from_text(
        conversation_text,
        current_profile=current_profile,
        time_range=time_range,
        elapsed_hint=elapsed_hint,
        time_str=time_str,
        language=resolved_language,
        assistant_name=assistant_name,
        user_name=user_name,
    )


def build_summary_prompt_from_text(
    conversation_text: str,
    *,
    current_profile: str = "",
    time_range: str = "",
    elapsed_hint: str = "",
    time_str: str = "",
    now: datetime | None = None,
    language: str | None = None,
    assistant_name: str | None = None,
    user_name: str | None = None,
) -> SummaryPrompt:
    resolved_language = resolve_prompt_language(language)
    defaults = default_prompt_persona_names(resolved_language)
    prompt_assistant_name = str(assistant_name or "").strip() or defaults.assistant
    prompt_user_name = str(user_name or "").strip() or defaults.user
    if not time_str:
        _, time_str = _format_now_for_language(resolved_language, now)
    resolved_time_range = time_range or time_str

    if resolved_language == "en":
        prompt = f"""Summarize the conversation below and extract {prompt_user_name} information and {prompt_assistant_name} information.
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
- Summary of the conversation that took place at {time_str}
- Use the timestamps in [CONVERSATION] as the primary basis when summarizing the flow of time.
- Do not mechanically force a sentence count; write a natural, readable length, usually 1-3 sentences.
- [TIME_RANGE] and [ELAPSED_HINT] are references only. Do not copy them verbatim; express them in context.
- Do not repeat the same event. Keep only the core actions.
- Example: "Around 5 PM on February 9, 2026, the user talked with {prompt_assistant_name} about eating raw oysters and worrying about norovirus symptoms and diet. Around 6:30 PM, they shared a pixel image they had made, and from around 9:20 PM they played a game and talked about the characters."

[MASTER_INFO]
- If none: none
- If present, write only in this format:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...

[ENE_INFO]
- If none: none
- If present, write only in this format:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
- [speaking_style] ...
- [relationship_tone] ...

[MEMORY_META]
- If none: none
- If present, write only in this format:
- memory_type: fact | preference | promise | event | relationship | task | general
- importance_reason: user_marked | promise | repeated_topic | long_term_preference | none
- confidence: number from 0.0 to 1.0
- entity_names: name1, name2
- aliases: alternate name 1, alternate name 2
- trigger_terms: keyword1, keyword2
- entity_names are distinctive subjects, projects, tools, people, or places only; omit broad conversation participants such as the user, assistant, {prompt_user_name}, or {prompt_assistant_name} unless the memory is specifically about them.
- aliases are short nicknames or noun phrases, not summaries; use how the user might briefly refer to this memory later.
- trigger_terms are search cues, not subjects; use short words a future query might contain.
- Do not use one-off dates, times, weekdays, or relative dates as trigger_terms; allow time-related terms only for recurring routines or when the deadline/event name itself is the core memory.
- Do not use durations, elapsed times, countdown periods, or numeric-only time cues as trigger_terms; keep stable topical words instead.
- aliases/trigger_terms must be short labels only; do not copy full conversation sentences.

[ALLOW]
- basic: stable information such as identity, job, education, environment, or relationships
- preference: preferred methods, tastes, or styles
- goal: goals the user or {prompt_assistant_name} wants to achieve
- habit: repeated behaviors, routines, or tendencies
- speaking_style: {prompt_assistant_name}'s maintained tone, explanation style, and response style
- relationship_tone: durable distance, attitude, or care style with the user

[DISALLOW]
- temporary states such as emotion, mood, fatigue, or excitement
- simple greetings or filler
- job or major statements that duplicate existing basic information
- copying user information into {prompt_assistant_name} information
- unsupported speculation

[DEDUP]
- Do not write new facts if they mean the same thing as existing information.
- Keep only the more specific sentence when meanings overlap.
- If user information and {prompt_assistant_name} information overlap, do not write it under {prompt_assistant_name} information.

[STYLE]
- Keep it concise.
- Follow the output format exactly.
- Do not use emphasis marks such as "**".
"""
    elif resolved_language == "ja":
        prompt = f"""以下の会話を要約し、{prompt_user_name}情報と{prompt_assistant_name}情報を抽出してください。
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
- {time_str}に行われた会話の要約
- [CONVERSATION]のタイムスタンプを優先して、時間の流れを要約してください。
- 文数を機械的に固定せず、自然で読みやすい長さ（通常1〜3文）で書いてください。
- [TIME_RANGE]と[ELAPSED_HINT]は参考情報です。そのまま貼り付けず、文脈に合わせて表現してください。
- 同じ出来事を繰り返さず、核心となる行動だけを要約してください。
- 例: 「2026年2月9日17時ごろ、ユーザーは生牡蠣を食べたあとノロウイルスの症状や食事について{prompt_assistant_name}と話しました。18時30分ごろには自作のドット絵を共有し、21時20分ごろからはゲームをしながら登場人物の感想を話しました。」

[MASTER_INFO]
- なければ: none
- あれば次の形式だけで書く:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...

[ENE_INFO]
- なければ: none
- あれば次の形式だけで書く:
- [basic] ...
- [preference] ...
- [goal] ...
- [habit] ...
- [speaking_style] ...
- [relationship_tone] ...

[MEMORY_META]
- なければ: none
- あれば次の形式だけで書く:
- memory_type: fact | preference | promise | event | relationship | task | general
- importance_reason: user_marked | promise | repeated_topic | long_term_preference | none
- confidence: 0.0〜1.0の数値
- entity_names: 名前1, 名前2
- aliases: 別名1, 別名2
- trigger_terms: キーワード1, キーワード2
- entity_namesは固有の対象、プロジェクト、ツール、人物、場所だけにし、ユーザー、アシスタント、{prompt_user_name}、{prompt_assistant_name}のような会話全体の参加者は、その対象自体についての記憶でない限り省いてください。
- aliasesは要約ではなく、短い呼び名や名詞句にしてください。後でユーザーがその記憶を短く呼ぶときの表現を使ってください。
- trigger_termsは対象名ではなく検索の手がかりです。将来の質問に出そうな短い語を使ってください。
- 一度きりの日付、時刻、曜日、相対日付はtrigger_termsに入れないでください。時間に関する語は、繰り返しのルーティン、または締切・イベント名そのものが記憶の中心である場合だけ許可します。
- 期間、経過時間、カウントダウン、数字だけの時間の手がかりはtrigger_termsに入れず、安定した話題語を残してください。
- aliases/trigger_termsは短いラベルだけにし、会話文をそのままコピーしないでください。

[ALLOW]
- basic: 身元、職業、学歴、環境、関係などの安定した情報
- preference: 好む方法、好み、スタイル
- goal: 達成しようとしている目標
- habit: 繰り返される行動、ルーティン、傾向
- speaking_style: {prompt_assistant_name}が維持する話し方、説明方法、反応スタイル
- relationship_tone: ユーザーとの継続的な距離感、態度、気遣い方

[DISALLOW]
- 感情、気分、疲労、興奮などの一時的な状態
- 単なる挨拶や相づち
- 既存のbasic情報と重複する就職・専攻の記述
- ユーザー情報を{prompt_assistant_name}情報として書き写すこと
- 根拠のない推測

[DEDUP]
- 既存情報と同じ意味なら新しく書かないでください。
- 意味が重なる文は、より具体的な1つだけを残してください。
- ユーザー情報と{prompt_assistant_name}情報が重なる場合、{prompt_assistant_name}情報には書かないでください。

[STYLE]
- 簡潔に書いてください。
- 出力形式を正確に守ってください。
- "**"のような強調表記は禁止です。
"""
    else:
        prompt = f"""아래 대화를 요약하고, {prompt_user_name} 정보와 {prompt_assistant_name} 정보를 추출하세요.
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
- 예 : "2026년 2월 9일 오후 5시경, 사용자가 작업 일정을 정리하며 {prompt_assistant_name}와 우선순위와 작업 범위에 대해 대화를 나눴습니다. 오후 6시 30분 무렵에는 참고 이미지를 공유하며 아이디어를 구체화했고, 오후 9시 20분경부터는 다음 작업 범위와 마감 기준을 정했습니다."

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
- aliases: 별칭1, 별칭2
- trigger_terms: 키워드1, 키워드2
- entity_names는 고유한 대상, 프로젝트, 도구, 인물, 장소만 쓰고, 사용자, 어시스턴트, {prompt_user_name}, {prompt_assistant_name}처럼 대화 전체에 흔한 참여자는 그 자체가 기억의 주제일 때만 쓰세요.
- aliases는 요약문이 아니라 짧은 별명이나 명사구로 쓰세요. 사용자가 나중에 그 기억을 짧게 부를 법한 표현을 사용하세요.
- trigger_terms는 대상명이 아니라 검색 단서입니다. 나중 질문에 나올 법한 짧은 단어를 쓰세요.
- 일회성 날짜, 시간, 요일, 상대 시점은 trigger_terms에 넣지 마세요. 시간 관련 단어는 반복 루틴이거나 마감/이벤트명 자체가 기억의 핵심일 때만 허용하세요.
- 기간, 경과 시간, 카운트다운, 숫자만 남는 시간 단서는 trigger_terms에 넣지 말고 안정적인 주제어만 남기세요.
- aliases/trigger_terms는 짧은 라벨만 쓰고, 대화 문장을 그대로 복사하지 마세요.

[ALLOW]
- basic: 신상/직업/학력/환경/관계 같은 정적 정보
- preference: 선호하는 방식이나 취향/스타일
- goal: 달성하려는 목표
- habit: 반복되는 행동/루틴 성향
- speaking_style: {prompt_assistant_name}가 유지하는 말투, 설명 방식, 반응 스타일
- relationship_tone: 사용자와의 지속적인 거리감, 태도, 챙김 방식

[DISALLOW]
- 감정/기분/피곤함/흥분 등 일시적 상태
- 단순 인사/추임새
- 이미 basic 정보와 중복되는 취업/전공 진술
- 사용자에 대한 정보를 {prompt_assistant_name} 정보처럼 옮겨 적는 것
- 근거 없는 추측성 정보

[DEDUP]
- 기존 정보와 의미가 같으면 새로 쓰지 마세요.
- 같은 의미의 문장은 더 구체적인 1개만 남기세요.
- 사용자 정보와 {prompt_assistant_name} 정보가 겹치면 {prompt_assistant_name} 정보에는 쓰지 마세요.

[STYLE]
- 너무 길지 않게 간결하게 작성하세요.
- 출력 형식을 정확히 지키세요.
- "**"와 같은 강조표시의 사용은 금지합니다.
"""
    return SummaryPrompt(prompt=prompt, time_range=resolved_time_range)


