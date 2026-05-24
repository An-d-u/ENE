"""
런타임 최종 응답 형식 계약을 프롬프트에 붙인다.
"""

from __future__ import annotations

from .goal_prompt import build_goal_update_rules, is_goal_prompt_enabled
from .persona_names import resolve_prompt_persona_names
from .prompt_language import resolve_prompt_language, resolve_tts_language
from .thought_prompt import build_thought_rules, is_thought_prompt_enabled


_RESPONSE_CONTRACT_BY_LANGUAGE = {
    "ko": {
        "header": "### [최종 응답 형식]",
        "intro": "- 최종 출력 순서는 아래 형식을 따르세요.",
        "analysis": "- `[analysis]` 블록은 기존 내부 분석 규칙에 맞춰 가장 먼저 출력하세요.",
        "names": "- 사용자에게 보이는 답변에서는 캐릭터 자신을 `{assistant_name}`로, 사용자를 `{user_name}`로 부르세요.",
        "names_with_tts": "- 사용자에게 보이는 답변과 `[tts]` 블록에서는 캐릭터 자신을 `{assistant_name}`로, 사용자를 `{user_name}`로 부르세요.",
        "goal": "- 목표 기능이 켜져 있으면 `[analysis]` 블록 뒤에 `[ene_goal_update]...[/ene_goal_update]` 블록을 출력하세요.",
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
    lines.append(_build_format_block(contract, goal_enabled, thought_enabled, language, tts_language))
    return "\n".join(lines)
