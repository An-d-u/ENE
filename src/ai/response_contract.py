"""
런타임 최종 응답 형식 계약을 프롬프트에 붙인다.
"""

from __future__ import annotations

from .goal_prompt import build_goal_update_rules, is_goal_prompt_enabled
from .persona_names import resolve_prompt_persona_names
from .prompt_language import resolve_prompt_language, resolve_tts_language
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


_RESPONSE_CONTRACT_BY_LANGUAGE = {
    "ko": {
        "header": "### [최종 응답 형식]",
        "intro": "- 최종 출력 순서는 아래 형식을 따르세요.",
        "analysis": "- `[analysis]` 블록은 기존 내부 분석 규칙에 맞춰 가장 먼저 출력하세요.",
        "names": "- 사용자에게 보이는 답변에서는 캐릭터 자신을 `{assistant_name}`로, 사용자를 `{user_name}`로 부르세요.",
        "names_with_tts": "- 사용자에게 보이는 답변과 `[tts]` 블록에서는 캐릭터 자신을 `{assistant_name}`로, 사용자를 `{user_name}`로 부르세요.",
        "goal": "- 목표 기능이 켜져 있으면 `[analysis]` 블록 뒤에 `[ene_goal_update]...[/ene_goal_update]` 블록을 출력하세요.",
        "proactive": "- 추후 짧게 이어 말하면 자연스러운 대화 계기가 있을 때, 필요할 때만 `[proactive_conversation]...[/proactive_conversation]` 블록을 최대 1개 출력하세요.",
        "tts": "- TTS 언어가 응답 언어와 다르면 답변 본문 뒤에 `[tts]...[/tts]` 블록을 추가하세요. TTS 언어가 같으면 TTS 블록을 만들지 마세요.",
        "subconscious": "- 생각 기능이 켜져 있으면 목표 블록 뒤, 사용자에게 보일 답변 앞에 `[subconscious]...[/subconscious]` 블록을 출력하세요.",
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
        "proactive": "- Only when a short proactive follow-up would feel natural later, output at most one `[proactive_conversation]...[/proactive_conversation]` block.",
        "tts": "- If the TTS language differs from the response language, add a `[tts]...[/tts]` block after the visible reply. If they match, do not add a TTS block.",
        "subconscious": "- When the thought feature is enabled, output a `[subconscious]...[/subconscious]` block after the goal block and before the visible reply.",
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
        "proactive": "- あとで短く自然に話しかけるきっかけがある場合だけ、`[proactive_conversation]...[/proactive_conversation]` ブロックを最大1つ出力してください。",
        "tts": "- TTS言語が返答言語と異なる場合だけ、ユーザーに見える返答の後に `[tts]...[/tts]` ブロックを追加してください。同じ場合はTTSブロックを作らないでください。",
        "subconscious": "- 思考表示機能が有効な場合、目標ブロックの後、ユーザーに見える返答の前に `[subconscious]...[/subconscious]` ブロックを出力してください。",
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
    proactive_enabled = is_proactive_conversation_enabled(settings_source)

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
    if proactive_enabled:
        lines.append(contract["proactive"])
        lines.extend(_build_proactive_conversation_rules(language=language))
    lines.append(_build_format_block(contract, goal_enabled, thought_enabled, language, tts_language))
    return "\n".join(lines)


def _build_proactive_conversation_rules(language: str = "ko") -> list[str]:
    allowed_keys = "short-followup, quiet-checkin, topic-reopen, task-momentum, global-proactive"
    normalized_language = str(language or "ko").strip().lower()
    if normalized_language == "en":
        return [
            "- This block is optional. Do not output it when there is no natural later follow-up.",
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
            "cooldown_key=short-followup",
            "[/proactive_conversation]",
            "```",
        ]
    if normalized_language == "ja":
        return [
            "- このブロックは任意です。あとで自然に話しかける理由がない場合は出力しないでください。",
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
            "cooldown_key=short-followup",
            "[/proactive_conversation]",
            "```",
        ]
    return [
        "- 이 블록은 선택 사항입니다. 나중에 자연스럽게 이어 말할 이유가 없으면 출력하지 마세요.",
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
        "cooldown_key=short-followup",
        "[/proactive_conversation]",
        "```",
    ]
