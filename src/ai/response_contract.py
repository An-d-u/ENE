"""
런타임 최종 응답 형식 계약을 프롬프트에 붙인다.
"""

from __future__ import annotations

from .goal_prompt import build_goal_update_rules, is_goal_prompt_enabled
from .persona_names import resolve_prompt_persona_names
from .prompt_language import resolve_prompt_language, resolve_tts_language
from .proactive_conversation_manager import COOLDOWN_KEY_ORDER
from .thought_prompt import build_thought_rules, is_thought_prompt_enabled


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


def is_proactive_conversation_enabled(settings_source: object | None = None) -> bool:
    """설정에서 선제 대화 기능 활성화 여부를 읽는다."""
    return bool(_read_setting(settings_source, "enable_proactive_conversation", True))


def is_synthetic_gesture_enabled(settings_source: object | None = None) -> bool:
    """설정에서 합성 제스처 기능 활성화 여부를 읽는다."""
    return bool(_read_setting(settings_source, "enable_synthetic_gestures", True))


def _available_proactive_cooldown_keys(settings_source: object | None = None) -> list[str]:
    raw_keys = _read_setting(settings_source, "proactive_available_cooldown_keys", None)
    if raw_keys is None:
        return list(COOLDOWN_KEY_ORDER)
    if not isinstance(raw_keys, (list, tuple, set)):
        return list(COOLDOWN_KEY_ORDER)
    requested = {str(key or "").strip() for key in raw_keys if str(key or "").strip()}
    return [key for key in COOLDOWN_KEY_ORDER if key in requested]


_RESPONSE_CONTRACT_BY_LANGUAGE = {
    "ko": {
        "header": "### [최종 응답 형식]",
        "intro": "- 최종 출력 순서는 아래 형식을 따르세요.",
        "analysis": "- `[analysis]` 블록은 기존 내부 분석 규칙에 맞춰 가장 먼저 출력하세요.",
        "names": "- 사용자에게 보이는 답변에서는 캐릭터 자신을 `{assistant_name}`로, 사용자를 `{user_name}`로 부르세요.",
        "names_with_tts": "- 사용자에게 보이는 답변과 `[tts]` 블록에서는 캐릭터 자신을 `{assistant_name}`로, 사용자를 `{user_name}`로 부르세요.",
        "goal": "- 목표 기능이 켜져 있으면 `[analysis]` 블록 뒤에 `[ene_goal_update]...[/ene_goal_update]` 블록을 출력하세요.",
        "proactive": "- 선제 대화 기능이 켜져 있으면 원칙적으로 모든 일반 대화 응답에서 `[proactive_conversation]...[/proactive_conversation]` 블록을 1개 출력하세요.",
        "tts": "- TTS 언어가 응답 언어와 다르면 답변 본문 뒤에 `[tts]...[/tts]` 블록을 추가하세요. TTS 언어가 같으면 TTS 블록을 만들지 마세요.",
        "subconscious": "- 생각 기능이 켜져 있으면 목표 블록 뒤, 사용자에게 보일 답변 앞에 `[subconscious]...[/subconscious]` 블록을 출력하세요.",
        "gesture": "\n".join(
            [
                "- 필요한 경우에만, 제스처 태그는 감정 표현을 보조할 때 답변 감정 태그 뒤에 `[gesture:<name>]` 형식으로 한 번 붙이세요.",
                "- 필요 없으면 제스처 태그를 출력하지 마세요. 대사가 짧고 자연스러워도 생략하세요.",
                "- 한 응답에는 gesture 태그를 최대 1개만 사용하세요.",
                "- 감정 태그와 gesture가 어울리지 않으면 gesture를 출력하지 마세요.",
                "- 사용 가능한 gesture:",
                "- nod: 동의, 안심, 기쁜 수긍, 부드러운 긍정",
                "- bow: 미안함, 슬픔, 조심스러운 사과, 풀이 죽은 반응",
                "- shake: 부정, 당황한 거절, 화남, \"그건 아니야\"라는 반응",
                "- surprise: 놀람, 갑작스러운 깨달음, 예상 밖의 반응",
                "- tilt: 궁금함, 혼란, 귀엽게 갸웃하는 반응",
                "- sway: 장난스러움, 기분 좋음, 가벼운 애교나 여유",
            ]
        ),
        "reply": "한국어 답변 [emotion]",
        "thought_sample": "짧은 내면 반응",
        "tts_samples": {
            "ko": "한국어 TTS 문장",
            "en": "영어 TTS 문장",
            "ja": "일본어 TTS 문장",
        },
    },
    "en": {
        "header": "### [Final Response Format]",
        "intro": "- Follow this final output order.",
        "analysis": "- Output the `[analysis]` block first, following the existing internal analysis rules.",
        "names": "- In the visible reply, refer to the assistant persona as `{assistant_name}` and address the user as `{user_name}`.",
        "names_with_tts": "- In the visible reply and any `[tts]` block, refer to the assistant persona as `{assistant_name}` and address the user as `{user_name}`.",
        "goal": "- When the goal feature is enabled, output an `[ene_goal_update]...[/ene_goal_update]` block after `[analysis]`.",
        "proactive": "- When proactive conversation is enabled, output exactly one `[proactive_conversation]...[/proactive_conversation]` block for normal chat replies by default.",
        "tts": "- If the TTS language differs from the response language, add a `[tts]...[/tts]` block after the visible reply. If they match, do not add a TTS block.",
        "subconscious": "- When the thought feature is enabled, output a `[subconscious]...[/subconscious]` block after the goal block and before the visible reply.",
        "gesture": "\n".join(
            [
                "- Use a gesture tag only when it supports the emotional delivery, and place it once after the reply emotion tag.",
                "- If it is not needed, the line is short, or the reply already feels natural, do not output a gesture tag.",
                "- Use at most one gesture tag per reply.",
                "- If the emotion tag and gesture do not fit together, do not output a gesture tag.",
                "- Available gestures:",
                "- nod: agreement, reassurance, happy acknowledgement, gentle affirmation",
                "- bow: apology, sadness, careful remorse, subdued reaction",
                "- shake: denial, flustered refusal, anger, a clear \"that's not it\" reaction",
                "- surprise: surprise, sudden realization, unexpected reaction",
                "- tilt: curiosity, confusion, cute questioning tilt",
                "- sway: playfulness, good mood, light affection, relaxed teasing",
            ]
        ),
        "reply": "English reply [emotion]",
        "thought_sample": "짧은 내면 반응",
        "tts_samples": {
            "ko": "Korean TTS text",
            "en": "English TTS text",
            "ja": "Japanese TTS text",
        },
    },
    "ja": {
        "header": "### [最終応答形式]",
        "intro": "- 最終出力は次の順序に従ってください。",
        "analysis": "- `[analysis]` ブロックは既存の内部分析ルールに従い、最初に出力してください。",
        "names": "- ユーザーに見える返答では、キャラクター自身を `{assistant_name}`、ユーザーを `{user_name}` と呼んでください。",
        "names_with_tts": "- ユーザーに見える返答と `[tts]` ブロックでは、キャラクター自身を `{assistant_name}`、ユーザーを `{user_name}` と呼んでください。",
        "goal": "- 目標機能が有効な場合、`[analysis]` ブロックの後に `[ene_goal_update]...[/ene_goal_update]` ブロックを出力してください。",
        "proactive": "- 先回り会話が有効な場合、通常の会話返答では原則として `[proactive_conversation]...[/proactive_conversation]` ブロックを1つ出力してください。",
        "tts": "- TTS言語が返答言語と異なる場合だけ、ユーザーに見える返答の後に `[tts]...[/tts]` ブロックを追加してください。同じ場合はTTSブロックを作らないでください。",
        "subconscious": "- 思考表示機能が有効な場合、目標ブロックの後、ユーザーに見える返答の前に `[subconscious]...[/subconscious]` ブロックを出力してください。",
        "gesture": "\n".join(
            [
                "- ジェスチャータグは感情表現を補助する場合だけ、返答の感情タグの後に1回だけ付けてください。",
                "- 不要な場合、短い返答で自然な場合はジェスチャータグを出力しないでください。",
                "- 1つの返答で使えるgestureタグは最大1つです。",
                "- 感情タグとgestureが合わない場合はgestureを出力しないでください。",
                "- 使用できるgesture:",
                "- nod: 同意、安心、うれしい相づち、やわらかい肯定",
                "- bow: 謝罪、悲しみ、控えめな反省、しょんぼりした反応",
                "- shake: 否定、戸惑った拒否、怒り、「それは違う」という反応",
                "- surprise: 驚き、急な気づき、予想外の反応",
                "- tilt: 好奇心、混乱、かわいく首をかしげる反応",
                "- sway: いたずらっぽさ、上機嫌、軽い甘え、余裕のある反応",
            ]
        ),
        "reply": "日本語返答 [emotion]",
        "thought_sample": "짧은 내면 반응",
        "tts_samples": {
            "ko": "韓国語TTS文",
            "en": "英語TTS文",
            "ja": "日本語TTS文",
        },
    },
}


def _build_format_block(
    contract: dict,
    goal_enabled: bool,
    thought_enabled: bool,
    proactive_enabled: bool,
    proactive_cooldown_keys: list[str],
    response_language: str,
    tts_language: str,
) -> str:
    lines = ["```", "[analysis]", "...", "[/analysis]"]
    if goal_enabled:
        lines.extend(
            [
                "[ene_goal_update]",
                "action=none",
                "type=short_term",
                "id=",
                "title=",
                "reason=",
                "completion_reason=",
                "[/ene_goal_update]",
            ]
        )
    if thought_enabled:
        lines.extend(["[subconscious]", contract["thought_sample"], "[/subconscious]"])
    if proactive_enabled:
        sample_key = proactive_cooldown_keys[0] if proactive_cooldown_keys else "quiet-checkin"
        lines.extend(
            [
                "[proactive_conversation]",
                "trigger_at=<ISO8601 +09:00, 1-60 minutes after the current time>",
                "title=short title",
                "generation_prompt=natural-language instruction for ENE's later proactive reply",
                "source_excerpt=short synthetic context summary",
                "reason=why this later follow-up is natural",
                f"cooldown_key={sample_key}",
                "[/proactive_conversation]",
            ]
        )
    lines.append(contract["reply"])
    if tts_language != response_language:
        lines.extend(["[tts]", contract["tts_samples"].get(tts_language, "TTS text"), "[/tts]"])
    lines.append("```")
    return "\n".join(lines)


def build_response_contract_appendix(settings_source: object | None = None) -> str:
    """설정과 UI 언어에 맞는 최종 응답 형식 계약을 반환한다."""
    language = resolve_prompt_language(settings_source=settings_source)
    tts_language = resolve_tts_language(settings_source=settings_source, response_language=language)
    contract = _RESPONSE_CONTRACT_BY_LANGUAGE.get(language, _RESPONSE_CONTRACT_BY_LANGUAGE["en"])
    names = resolve_prompt_persona_names(settings_source=settings_source, language=language)
    goal_enabled = is_goal_prompt_enabled(settings_source)
    thought_enabled = is_thought_prompt_enabled(settings_source)
    gesture_enabled = is_synthetic_gesture_enabled(settings_source)
    proactive_cooldown_keys = _available_proactive_cooldown_keys(settings_source)
    proactive_enabled = is_proactive_conversation_enabled(settings_source) and bool(proactive_cooldown_keys)

    names_key = "names_with_tts" if tts_language != language else "names"

    lines = [
        contract["header"],
        contract["intro"],
        contract["analysis"],
        contract[names_key].format(assistant_name=names.assistant, user_name=names.user),
    ]
    if goal_enabled:
        lines.append(contract["goal"])
        lines.extend(build_goal_update_rules(language=language))
    if tts_language != language:
        lines.append(contract["tts"])
    if thought_enabled:
        lines.append(contract["subconscious"])
        lines.extend(build_thought_rules(language=language))
    if gesture_enabled:
        lines.append(contract["gesture"])
    if proactive_enabled:
        lines.append(contract["proactive"])
        lines.extend(_build_proactive_conversation_rules(language=language, cooldown_keys=proactive_cooldown_keys))
    lines.append(
        _build_format_block(
            contract,
            goal_enabled,
            thought_enabled,
            proactive_enabled,
            proactive_cooldown_keys,
            language,
            tts_language,
        )
    )
    return "\n".join(lines)


def _build_proactive_conversation_rules(language: str = "ko", cooldown_keys: list[str] | None = None) -> list[str]:
    available_keys = [key for key in COOLDOWN_KEY_ORDER if key in set(cooldown_keys or COOLDOWN_KEY_ORDER)]
    allowed_keys = ", ".join(available_keys)
    topic_shift_keys = [
        key
        for key in ("topic-reopen", "quiet-checkin", "global-proactive")
        if key in available_keys
    ] or available_keys
    topic_shift_key_text = ", ".join(topic_shift_keys)
    sample_key = available_keys[0] if available_keys else "quiet-checkin"
    normalized_language = str(language or "ko").strip().lower()
    if normalized_language == "en":
        return [
            "- Prefer a lightweight later follow-up when the conversation is still open or the user is likely to return to the same task.",
            f"- If the conversation has naturally wrapped up, do not force the previous topic to continue; use one of the available topic-shift keys ({topic_shift_key_text}) for a light new topic, a mood shift, or a gentle check-in.",
            "- Keys not listed below are currently on cooldown; do not output them.",
            "- Do not output this block when the reply already creates a conversation promise/reminder.",
            "- `trigger_at` must be an ISO 8601 timestamp with `+09:00`, chosen from the current time and conversation context.",
            "- `generation_prompt` is the instruction for ENE's later reply, not the final line itself.",
            "- `source_excerpt` must be a short synthetic context summary, not a verbatim private conversation quote.",
            f"- `cooldown_key` must be one of: {allowed_keys}.",
            "- Optional example:",
            "```",
            "[proactive_conversation]",
            "trigger_at=<ISO8601 +09:00, 1-60 minutes after the current time>",
            "title=short title",
            "generation_prompt=natural-language instruction for ENE's later proactive reply",
            "source_excerpt=short synthetic context summary",
            "reason=why this later follow-up is natural",
            f"cooldown_key={sample_key}",
            "[/proactive_conversation]",
            "```",
        ]
    if normalized_language == "ja":
        return [
            "- 会話がまだ続いている、またはユーザーが同じ作業に戻りそうな場合は、軽い後続確認を優先してください。",
            f"- 会話が自然に一区切りついている場合は、前の話題を無理に続けず、使用可能な話題転換キー（{topic_shift_key_text}）で軽い新しい話題、気分転換、静かな確認にしてください。",
            "- 下にないキーは現在クールダウン中です。出力しないでください。",
            "- 返答内で会話の約束やリマインダーを作る場合、このブロックは出力しないでください。",
            "- `trigger_at` は現在時刻と会話文脈から選んだ `+09:00` 付きISO 8601時刻にしてください。",
            "- `generation_prompt` は後でENEが返答を作るための指示であり、最終セリフそのものではありません。",
            "- `source_excerpt` は実際の私的な会話の引用ではなく、短い合成文脈要約にしてください。",
            f"- `cooldown_key` は次のどれかだけを使ってください: {allowed_keys}。",
            "- 任意の例:",
            "```",
            "[proactive_conversation]",
            "trigger_at=<ISO8601 +09:00, 現在時刻の1-60分後>",
            "title=短い題名",
            "generation_prompt=後でENEが自然に話しかけるための指示",
            "source_excerpt=短い合成文脈要約",
            "reason=あとで話しかけるのが自然な理由",
            f"cooldown_key={sample_key}",
            "[/proactive_conversation]",
            "```",
        ]
    return [
        "- 대화가 아직 열린 흐름이거나 사용자가 같은 작업으로 돌아올 가능성이 높으면 가벼운 후속 확인을 우선 만드세요.",
        f"- 대화가 자연스럽게 마무리된 흐름이면 기존 화제를 억지로 이어가지 말고 사용 가능한 화제 전환 키({topic_shift_key_text})로 가벼운 새 화제, 분위기 전환, 조용한 확인을 만드세요.",
        "- 아래 목록에 없는 키는 현재 쿨다운 중입니다. 출력하지 마세요.",
        "- 응답에서 대화 약속이나 리마인더를 만들 때는 이 블록을 출력하지 마세요.",
        "- `trigger_at`은 현재 시각과 대화 맥락을 보고 고른 `+09:00` 포함 ISO 8601 시각이어야 합니다.",
        "- `generation_prompt`는 나중에 ENE가 답변을 생성할 때 쓸 지시문이며 최종 대사 자체가 아닙니다.",
        "- `source_excerpt`는 실제 사적인 대화 원문 인용이 아니라 짧은 합성 맥락 요약이어야 합니다.",
        f"- `cooldown_key`는 다음 값 중 하나만 사용하세요: {allowed_keys}.",
        "- 선택 예시:",
        "```",
        "[proactive_conversation]",
        "trigger_at=<ISO8601 +09:00, 현재 시각 기준 1-60분 뒤>",
        "title=짧은 제목",
        "generation_prompt=나중에 ENE가 자연스럽게 먼저 말할 때 사용할 지시문",
        "source_excerpt=짧은 합성 맥락 요약",
        "reason=나중에 이어 말하는 것이 자연스러운 이유",
        f"cooldown_key={sample_key}",
        "[/proactive_conversation]",
        "```",
    ]
