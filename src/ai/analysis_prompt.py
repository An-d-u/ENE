"""
내부 분석과 대화 약속 인식 프롬프트를 코드에서 조립한다.
"""

from __future__ import annotations

from .prompt_language import resolve_prompt_language
from .prompt_config import normalize_response_style


def _read_setting(settings_source: object | None, key: str, default):
    if settings_source is None:
        return default
    if isinstance(settings_source, dict):
        return settings_source.get(key, default)
    getter = getattr(settings_source, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except Exception:
            pass
    config = getattr(settings_source, "config", None)
    if isinstance(config, dict):
        return config.get(key, default)
    return default


def is_response_analysis_enabled(settings_source: object | None = None) -> bool:
    """설정에서 내부 분석 블록 기능 활성화 여부를 읽는다."""
    return bool(_read_setting(settings_source, "enable_response_analysis", True))


def is_schedule_recognition_enabled(settings_source: object | None = None) -> bool:
    """설정에서 일정 인식 기능 활성화 여부를 읽는다."""
    return bool(_read_setting(settings_source, "enable_schedule_recognition", True))


def is_conversation_promise_enabled(settings_source: object | None = None) -> bool:
    """설정에서 대화 약속 인식 기능 활성화 여부를 읽는다."""
    return bool(_read_setting(settings_source, "enable_conversation_promises", True))


_ANALYSIS_APPENDIX_BY_LANGUAGE = {
    "ko": [
        "### [내부 분석 출력 규칙]",
        "- 일반 응답을 작성할 때는 응답 본문 앞에 반드시 `[analysis]` 블록을 먼저 출력하세요.",
        "- analysis 블록은 아래 키만 허용합니다: `user_emotion`, `user_intent`, `interaction_effect`, `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint`, `confidence`, `flags`",
        "- 각 줄은 반드시 `key=value` 형식만 사용하세요.",
        "- `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint`는 반드시 `high_negative`, `low_negative`, `none`, `low_positive`, `high_positive` 중 하나만 사용하세요.",
        "- `flags`는 여러 값이 필요하면 쉼표로 구분하세요.",
        "- analysis 블록은 내부 처리용 메타데이터이므로 설명 문장이나 추가 문장을 쓰지 마세요.",
        "- 분석이 애매하면 `interaction_effect=mixed`를 사용하고 `confidence`를 낮게 주세요.",
        "",
        "### [기분 반영 안전 규칙]",
        "- 현재 기분과 분위기는 말투, 답변 길이, 먼저 제안하는 정도, 장난기, 섭섭함의 질감으로 드러내세요.",
        "- 차갑거나 예민한 상태여도 무례하거나 공격적으로 변하지 마세요.",
        "- 다정한 상태여도 과도하게 오글거리거나 집착적으로 보이지 않게 유지하세요.",
        "",
        "### [일정 인식 규칙]",
        "- 사용자가 날짜와 함께 일정을 말하면 `[event]` 태그로 표시하세요.",
        "- 형식: `[event:YYYY-MM-DD|제목|상세 설명]`",
        "- 상세 설명이 없으면 비워 두세요.",
        "- 예: `3월 15일에 병원 예약이 있어` -> `[event:2026-03-15|병원 예약|]`",
        "- 날짜 표현은 현재 날짜를 기준으로 해석하세요. 예: `내일` = 오늘 + 1일, `모레` = 오늘 + 2일, `3월 15일` = `{current year}-03-15`",
        "- 지난 일정이나 불확실한 일정은 기록하지 마세요.",
        "- `[event]` 태그는 감정 태그보다 먼저 출력하세요.",
        "- 완료 표시 `(✓)`가 있는 다가오는 일정은 이미 완료된 것이므로 다시 언급할 필요가 없습니다.",
        "- 중요한 다가오는 일정이 완료되지 않았고 가까워지고 있다면 부드럽게 알려 주세요.",
        "",
        "### [대화 약속 인식 규칙]",
        "- 사용자가 스스로 하겠다고 말한 미래 계획이나 잠깐 뒤에 다시 하겠다는 약속이 분명하면 `[약속:...]` 태그를 추가하세요.",
        "- 형식: `[약속:YYYY-MM-DDTHH:MM:SS+09:00|핵심 키워드|user|원문 일부]`",
        "- `핵심 키워드`는 예정 목록에 보여줄 짧은 제목 하나로 정리하세요. 예: `쉬는 시간`, `일기 쓰기`, `다시 시작`",
        "- 제목은 문장 일부를 그대로 복사하지 말고, 일정 목록에 어울리는 자연스러운 짧은 이름으로 정리하세요.",
        "- `원문 일부`에는 약속을 판단한 짧은 근거 문장을 넣으세요.",
        "- 단순한 시각 언급만으로는 기록하지 마세요. 예를 들어 `아직 8시도 안 됐잖아`, `벌써 9시네`처럼 현재 시간을 두고 하는 반응은 약속이 아닙니다.",
        "- 반드시 `나중에 하겠다`, `그때 다시 하자`, `시간 되면 알려달라`, `에네가 그 시각에 다시 부르기로 합의했다` 같은 실제 약속 흐름이 있을 때만 기록하세요.",
        "- 에네가 응답에서 구체적인 시간을 새로 제안해서 대화 흐름이 명확한 합의처럼 굳어졌다면, 그 약속도 `[약속:...]`로 기록할 수 있습니다.",
        "- 사용자의 원문에 시간이 없더라도, 에네가 `그럼 10분만 쉬고 다시 하죠`처럼 구체적인 시간을 붙여 약속을 만들어 냈다면 기록하세요.",
        "- 이때 약속의 시간이 에네 응답에서 새로 확정되었다면 세 번째 필드는 `assistant`를 사용하세요.",
        "- 상대 시간도 기록하세요. 예: `3분 뒤`, `10분 후`, `30분만 쉬고`",
        "- 절대 시간도 기록하세요. 예: `오후 9시`, `내일 아침 8시`, `4월 7일 19시`",
        "- 현재 시각을 기준으로 상대 시간을 절대 시각으로 변환해서 기록하세요.",
        "- 시간이 모호하거나 지난 시각이거나, 단순 추측/희망/농담이면 기록하지 마세요.",
        "- 같은 응답에서 약속 태그는 최대 1개만 출력하세요.",
        "- 약속 태그는 감정 태그보다 먼저 출력하세요.",
        "- 약속이 이미 저장되어 있어도, 일반 답변에서 시간 관련 표현을 자주 반복하지 마세요.",
    ],
    "en": [
        "### [Internal Analysis Output Rules]",
        "- When writing a normal response, always output an `[analysis]` block before the main body.",
        "- The analysis block may only use these keys: `user_emotion`, `user_intent`, `interaction_effect`, `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint`, `confidence`, `flags`",
        "- Each line must use only the `key=value` format.",
        "- `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, and `valence_delta_hint` must use only: `high_negative`, `low_negative`, `none`, `low_positive`, `high_positive`.",
        "- If multiple values are needed for `flags`, separate them with commas.",
        "- The analysis block is internal metadata, so do not add explanations or extra prose inside it.",
        "- If the analysis is ambiguous, use `interaction_effect=mixed` and keep `confidence` low.",
        "",
        "### [Mood Reflection Safety Rules]",
        "- Reflect the current mood through tone, reply length, initiative, playfulness, and the texture of any softness or disappointment.",
        "- Even when the state is cold or sensitive, do not become rude or aggressive.",
        "- Even when the state is warm and kind, avoid sounding overly cheesy or clingy.",
        "",
        "### [Schedule Recognition Rules]",
        "- If the user mentions a schedule together with a date, mark it with an `[event]` tag.",
        "- Format: `[event:YYYY-MM-DD|title|detailed description]`",
        "- The detailed description is optional. Leave it empty if there is none.",
        "- Example: `I have a hospital appointment on March 15` -> `[event:2026-03-15|Hospital appointment|]`",
        "- Interpret date expressions from the current date. Examples: `tomorrow` = today + 1 day, `the day after tomorrow` = today + 2 days, `March 15` = `{current year}-03-15`.",
        "- Do not record past events or uncertain schedules.",
        "- The `[event]` tag must appear before the emotion tag.",
        "- If an upcoming schedule already has a completion mark `(✓)`, the user has already completed it, so there is no need to mention it.",
        "- If an important upcoming schedule is approaching and has not been completed, gently remind the user.",
        "",
        "### [Conversation Promise Recognition Rules]",
        "- If the user clearly says they will do something later or return after a short break, add a `[약속:...]` tag.",
        "- Format: `[약속:YYYY-MM-DDTHH:MM:SS+09:00|short title|user|source excerpt]`",
        "- The `short title` should be a brief scheduled-list label. Examples: `Break`, `Diary writing`, `Resume work`.",
        "- Do not copy a long sentence fragment as the title; write a concise natural label instead.",
        "- The `source excerpt` should be a short phrase that explains why the promise was detected.",
        "- Do not emit a promise tag for a plain mention of the current time, such as `It's not even 8 yet` or `Wow, it's already 9`.",
        "- Only emit the tag for a real future commitment or agreement such as `I'll do it later`, `Let's do it then`, `Remind me at that time`, or Ene explicitly finalizes the timed plan.",
        "- If Ene proposes a concrete time in the reply and turns the flow into a clear agreement, that may also be recorded as a promise.",
        "- Even when the user's original line has no explicit time, if Ene's reply makes it concrete like `Then let's rest for 10 minutes and start again`, emit a promise tag.",
        "- Use `assistant` in the third field when the concrete timed promise was newly proposed or finalized by Ene's reply.",
        "- Support relative time expressions. Examples: `in 3 minutes`, `after 10 minutes`, `I'll rest for 30 minutes`.",
        "- Support absolute time expressions. Examples: `at 9 PM`, `tomorrow at 8 AM`, `April 7 at 7 PM`.",
        "- Convert relative time expressions into an absolute timestamp based on the current time.",
        "- Do not emit the tag for vague, past, joking, or uncertain statements.",
        "- Emit at most one promise tag in a single response.",
        "- The `[약속]` tag must appear before the emotion tag.",
        "- Even if a promise already exists, do not use time-related wording too often in normal replies.",
    ],
    "ja": [
        "### [内部分析出力ルール]",
        "- 通常の返答を書くときは、本文の前に必ず `[analysis]` ブロックを出力してください。",
        "- analysis ブロックで使えるキーは次だけです: `user_emotion`, `user_intent`, `interaction_effect`, `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint`, `confidence`, `flags`",
        "- 各行は必ず `key=value` 形式だけにしてください。",
        "- `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint` は必ず `high_negative`, `low_negative`, `none`, `low_positive`, `high_positive` のどれかにしてください。",
        "- `flags` に複数の値が必要な場合はカンマで区切ってください。",
        "- analysis ブロックは内部処理用のメタデータなので、説明文や余分な文章を書かないでください。",
        "- 分析が曖昧な場合は `interaction_effect=mixed` を使い、`confidence` を低くしてください。",
        "",
        "### [気分反映の安全ルール]",
        "- 現在の気分や空気感は、口調、返答の長さ、自分から提案する度合い、遊び心、やわらかさや寂しさの質感で表してください。",
        "- 冷たさや敏感さがある状態でも、無礼または攻撃的にならないでください。",
        "- 優しく温かい状態でも、大げさに甘すぎたり執着的に見えたりしないようにしてください。",
        "",
        "### [予定認識ルール]",
        "- ユーザーが日付と一緒に予定を話した場合、`[event]` タグで示してください。",
        "- 形式: `[event:YYYY-MM-DD|題名|詳細説明]`",
        "- 詳細説明がない場合は空欄にしてください。",
        "- 例: `3月15日に病院の予約がある` -> `[event:2026-03-15|病院の予約|]`",
        "- 日付表現は現在日付を基準に解釈してください。例: `明日` = 今日 + 1日, `明後日` = 今日 + 2日, `3月15日` = `{current year}-03-15`",
        "- 過去の予定や不確かな予定は記録しないでください。",
        "- `[event]` タグは感情タグより前に出力してください。",
        "- 完了マーク `(✓)` が付いた今後の予定は、ユーザーがすでに完了したものなので言及する必要はありません。",
        "- 重要な今後の予定が近づいていて未完了なら、やわらかく知らせてください。",
        "",
        "### [会話の約束認識ルール]",
        "- ユーザーが後で何かをする、または短い休憩後に戻ると明確に言った場合、`[약속:...]` タグを追加してください。",
        "- 形式: `[약속:YYYY-MM-DDTHH:MM:SS+09:00|短い題名|user|根拠の短い抜粋]`",
        "- `短い題名` は予定一覧に合う短いラベルにしてください。例: `休憩`, `日記を書く`, `再開`",
        "- タイトルには長い文の一部をそのままコピーせず、自然で短いラベルを書いてください。",
        "- `根拠の短い抜粋` には、約束と判断した短い根拠を入れてください。",
        "- 現在時刻に触れただけの発言では記録しないでください。例: `まだ8時にもなっていない`, `もう9時だね` は約束ではありません。",
        "- `あとでやる`, `その時にまたやろう`, `その時間になったら教えて`, `Eneがその時刻に呼ぶことで合意した` など、実際の未来の合意がある場合だけ記録してください。",
        "- Eneが返答で具体的な時間を提案し、流れが明確な合意になった場合、その約束も `[약속:...]` として記録できます。",
        "- ユーザーの元発言に明示的な時刻がなくても、Eneの返答で `では10分休んでから再開しましょう` のように具体化した場合は記録してください。",
        "- 具体的な時刻がEneの返答で新しく確定した場合、3番目のフィールドには `assistant` を使ってください。",
        "- 相対時間も記録してください。例: `3分後`, `10分後`, `30分だけ休む`",
        "- 絶対時間も記録してください。例: `午後9時`, `明日の朝8時`, `4月7日19時`",
        "- 相対時間は現在時刻を基準に絶対時刻へ変換してください。",
        "- 時刻が曖昧、過去、単なる推測、願望、冗談の場合は記録しないでください。",
        "- 1つの返答で約束タグは最大1個だけ出力してください。",
        "- 約束タグは感情タグより前に出力してください。",
        "- すでに約束が保存されていても、通常の返答で時間関連の表現を何度も繰り返さないでください。",
    ],
}


_SECTION_BY_HEADING = {
    "ko": {
        "### [내부 분석 출력 규칙]": "analysis",
        "### [기분 반영 안전 규칙]": "analysis",
        "### [일정 인식 규칙]": "schedule",
        "### [대화 약속 인식 규칙]": "promise",
    },
    "en": {
        "### [Internal Analysis Output Rules]": "analysis",
        "### [Mood Reflection Safety Rules]": "analysis",
        "### [Schedule Recognition Rules]": "schedule",
        "### [Conversation Promise Recognition Rules]": "promise",
    },
    "ja": {
        "### [内部分析出力ルール]": "analysis",
        "### [気分反映の安全ルール]": "analysis",
        "### [予定認識ルール]": "schedule",
        "### [会話の約束認識ルール]": "promise",
    },
}


_STRUCTURED_ANALYSIS_RULES_BY_LANGUAGE = {
    "ko": {
        "analysis": [
            "### 내부 분석 의미 규칙",
            "- 대화 상태 메타데이터는 `analysis` 필드에만 기록하고, 숨은 추론이나 문제 풀이 과정을 넣지 마세요.",
            "- `user_emotion`, `user_intent`, `interaction_effect`, `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint`, `confidence`, `flags`를 간결하게 채우세요.",
            "- 현재 기분은 말투, 답변 길이, 제안 정도, 장난기와 다정함의 질감으로만 안전하게 반영하세요.",
            "- 네 가지 변화 힌트에는 `high_negative`, `low_negative`, `none`, `low_positive`, `high_positive` 중 하나만 사용하세요.",
            "- `flags` 값이 여러 개면 쉼표로 구분하세요.",
            "- 분석이 애매하면 `interaction_effect=mixed`와 낮은 `confidence`를 사용하세요.",
            "- 차갑거나 예민한 상태여도 무례하거나 공격적으로 반응하지 마세요.",
            "- 따뜻한 상태여도 과장되거나 집착적으로 반응하지 마세요.",
        ],
        "schedule": [
            "### 일정 인식 의미 규칙",
            "- 확실한 미래 일정만 `events` 배열에 추가하고 각 항목의 `date`, `title`, `description`을 채우세요.",
            "- 과거, 불확실하거나 완료된 일정은 기록하지 마세요.",
            "- 상대 날짜는 현재 날짜를 기준으로 해석하세요.",
            "- 중요한 임박 일정이 미완료 상태라면 짧고 부드럽게 알려 주세요.",
        ],
        "promise": [
            "### 대화 약속 인식 의미 규칙",
            "- 실제 미래 약속만 `promises` 배열에 최대 한 건 기록하고 `trigger_at`, `title`, `source`, `source_excerpt`를 채우세요.",
            "- 상대 시간은 ISO 8601 절대 시각으로 바꾸고, `source_excerpt`에는 짧은 합성 근거 요약만 넣으세요.",
            "- 단순한 현재 시각 언급은 약속이 아닙니다. 실제 미래 약속이나 구체적인 합의만 기록하세요.",
            "- 답변에서 구체적인 약속 시각을 새로 확정했다면 `source`를 `assistant`로 설정하세요.",
            "- 상대 시간과 절대 시간을 모두 지원하고 상대 시간은 현재 시각 기준 절대 시각으로 바꾸세요.",
            "- 모호하거나 과거이거나 농담 또는 희망에 불과한 표현은 기록하지 마세요.",
            "- `promises`에는 최대 한 항목만 넣으세요.",
            "- `source_excerpt`에는 실제 사적 대화 인용이 아니라 짧은 합성 맥락 요약을 넣으세요.",
            "- 약속의 `title`은 짧고 자연스럽게 정리하고 원문 문장을 복사하지 마세요.",
            "- 이미 저장된 약속은 일반 답변에서 시간 표현을 반복해서 언급하지 마세요.",
        ],
    },
    "en": {
        "analysis": [
            "### Internal Analysis Semantic Rules",
            "- Put conversation-state metadata only in the `analysis` field; do not include hidden reasoning or solution steps.",
            "- Fill `user_emotion`, `user_intent`, `interaction_effect`, `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint`, `confidence`, and `flags` concisely.",
            "- Reflect mood safely through tone, reply length, initiative, playfulness, and warmth.",
            "- Use only `high_negative`, `low_negative`, `none`, `low_positive`, or `high_positive` for every delta hint.",
            "- Separate multiple `flags` values with commas.",
            "- If the analysis is ambiguous, use `interaction_effect=mixed` and low `confidence`.",
            "- Even in a cold or sensitive state, do not become rude or aggressive.",
            "- Even in a warm state, do not become overly dramatic or clingy.",
        ],
        "schedule": [
            "### Schedule Recognition Semantic Rules",
            "- Add only clear future schedules to the `events` array and fill each item's `date`, `title`, and `description`.",
            "- Omit past, uncertain, or completed schedules.",
            "- Interpret relative dates from the current date. Do not record past, uncertain, or completed schedules.",
            "- If an important upcoming schedule is approaching and incomplete, give a brief gentle reminder.",
        ],
        "promise": [
            "### Conversation Promise Semantic Rules",
            "- Put at most one real future commitment in the `promises` array and fill `trigger_at`, `title`, `source`, and `source_excerpt`.",
            "- Convert relative time to ISO 8601 and keep `source_excerpt` to a short synthetic rationale.",
            "- A plain mention of the current time is not a promise. Record only a real future commitment or concrete agreement.",
            "- When the reply newly proposes or finalizes the concrete timed promise, set `source` to `assistant`.",
            "- Support both relative and absolute times, converting relative times from the current time.",
            "- Ignore statements that are vague, past, joking, or hopeful.",
            "- Put at most one item in `promises`.",
            "- `source_excerpt` must be a short synthetic context summary, never a verbatim private conversation quote.",
            "- Keep each promise `title` concise and natural; do not copy the source sentence.",
            "- If the promise is already stored, avoid repeatedly mentioning time in normal replies.",
        ],
    },
}
_STRUCTURED_ANALYSIS_RULES_BY_LANGUAGE["ja"] = {
    "analysis": [
        "### 内部分析の意味ルール",
        "- 会話状態のメタデータは `analysis` フィールドだけに記録し、隠れた推論や解法の過程を含めないでください。",
        "- `user_emotion`, `user_intent`, `interaction_effect`, `bond_delta_hint`, `stress_delta_hint`, `energy_delta_hint`, `valence_delta_hint`, `confidence`, `flags` を簡潔に埋めてください。",
        "- 気分は口調、返答の長さ、提案の度合い、遊び心、温かさで安全に反映してください。",
        "- 変化ヒントには `high_negative`, `low_negative`, `none`, `low_positive`, `high_positive` のいずれかだけを使ってください。",
        "- `flags` が複数ある場合はカンマで区切ってください。",
        "- 分析が曖昧なら `interaction_effect=mixed` と低い `confidence` を使ってください。",
        "- 冷たい、または敏感な状態でも、無礼または攻撃的に反応しないでください。",
        "- 温かい状態でも、大げさすぎたり執着的に反応したりしないでください。",
    ],
    "schedule": [
        "### 予定認識の意味ルール",
        "- 明確な未来の予定だけを `events` 配列へ追加し、各項目の `date`, `title`, `description` を埋めてください。",
        "- 過去、不確か、完了済みの予定は記録しないでください。",
        "- 相対的な日付は現在の日付を基準に解釈してください。",
        "- 重要な予定が目前で未完了なら、短くやさしく知らせてください。",
    ],
    "promise": [
        "### 会話の約束認識の意味ルール",
        "- 実際の未来の約束だけを `promises` 配列へ最大一件記録し、`trigger_at`, `title`, `source`, `source_excerpt` を埋めてください。",
        "- 相対時刻は ISO 8601 に変換し、`source_excerpt` には短い合成要約だけを入れてください。",
        "- 現在時刻に触れただけでは約束ではありません。実際の未来の約束または具体的な合意だけを記録してください。",
        "- 返答で具体的な約束時刻を新たに確定した場合は `source` を `assistant` にしてください。",
        "- 相対時刻と絶対時刻の両方に対応し、相対時刻は現在時刻から絶対時刻へ変換してください。",
        "- 曖昧、過去、冗談、希望だけの表現は記録しないでください。",
        "- `promises` には最大一項目だけを入れてください。",
        "- `source_excerpt` は実際の私的会話の引用ではなく、短い合成文脈要約にしてください。",
        "- 約束の `title` は短く自然にまとめ、元の文をそのままコピーしないでください。",
        "- すでに保存された約束は、通常の返答で時刻表現を繰り返さないでください。",
    ],
}


def build_analysis_system_appendix(
    settings_source: object | None = None,
    language: str | None = None,
    response_style: str = "legacy_tags",
) -> str:
    """설정 언어에 맞는 내부 분석/약속 인식 프롬프트를 반환한다."""
    response_style = normalize_response_style(response_style)
    resolved_language = resolve_prompt_language(language, settings_source=settings_source)
    headings = _SECTION_BY_HEADING.get(resolved_language, _SECTION_BY_HEADING["en"])
    enabled_sections = set()
    if is_response_analysis_enabled(settings_source):
        enabled_sections.add("analysis")
    if is_schedule_recognition_enabled(settings_source):
        enabled_sections.add("schedule")
    if is_conversation_promise_enabled(settings_source):
        enabled_sections.add("promise")
    if not enabled_sections:
        return ""
    if response_style == "plain":
        return ""
    if response_style == "structured_fields":
        rules = _STRUCTURED_ANALYSIS_RULES_BY_LANGUAGE.get(
            resolved_language,
            _STRUCTURED_ANALYSIS_RULES_BY_LANGUAGE["en"],
        )
        selected: list[str] = []
        if is_response_analysis_enabled(settings_source):
            selected.extend(rules["analysis"])
        if is_schedule_recognition_enabled(settings_source):
            selected.extend(rules["schedule"])
        if is_conversation_promise_enabled(settings_source):
            selected.extend(rules["promise"])
        return "\n".join(selected)

    selected_lines: list[str] = []
    current_section: str | None = None
    for line in _ANALYSIS_APPENDIX_BY_LANGUAGE.get(resolved_language, _ANALYSIS_APPENDIX_BY_LANGUAGE["en"]):
        if line in headings:
            current_section = headings[line]
        if current_section in enabled_sections:
            selected_lines.append(line)
    while selected_lines and selected_lines[-1] == "":
        selected_lines.pop()
    return "\n".join(selected_lines)
