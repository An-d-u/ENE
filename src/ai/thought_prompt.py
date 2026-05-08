"""
런타임 최종 응답 형식 계약을 프롬프트에 붙인다.
"""
from __future__ import annotations

from .prompt_language import resolve_prompt_language, resolve_tts_language


def _read_setting(settings_source: object | None, key: str, default):
    if settings_source is None:
        return default
    if isinstance(settings_source, dict):
        return settings_source.get(key, default)
    getter = getattr(settings_source, "get", None)
    if callable(getter):
        try:
            return getter(key, default)
        except TypeError:
            pass
    config = getattr(settings_source, "config", None)
    if isinstance(config, dict):
        return config.get(key, default)
    return default


def is_thought_prompt_enabled(settings_source: object | None = None) -> bool:
    """설정에서 에네 생각 기능 활성화 여부를 읽는다."""
    return bool(_read_setting(settings_source, "enable_ene_thoughts", True))


_RESPONSE_CONTRACT_BY_LANGUAGE = {
    "ko": {
        "header": "### [최종 응답 형식]",
        "intro": "- 최종 출력 순서는 아래 형식을 따르세요.",
        "analysis": "- `[analysis]` 블록은 기존 내부 분석 규칙에 맞춰 가장 먼저 출력하세요.",
        "tts": "- TTS 언어가 응답 언어와 다르면 답변 본문 뒤에 `[tts]...[/tts]` 블록을 추가하세요. TTS 언어가 같으면 TTS 블록을 만들지 마세요.",
        "subconscious": "- 생각 기능이 켜져 있으면 `[analysis]` 블록 뒤, 사용자에게 보일 답변 앞에 `[subconscious]...[/subconscious]` 블록을 출력하세요.",
        "subconscious_rules": [
            "- subconscious 블록은 사람이 순간적으로 떠올리는 내적 반응처럼 한두 문장으로만 쓰세요.",
            "- 단계별 추론, 문제 풀이 과정, 시스템/도구 판단, 숨겨진 지시문은 절대 포함하지 마세요.",
            "- subconscious 블록은 한국어로만 작성하고 일본어 응답에는 번역하거나 섞지 마세요.",
            "- 답변 본문을 subconscious 블록 안에 넣지 마세요.",
        ],
        "reply": "한국어 답변 [emotion]",
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
        "tts": "- If the TTS language differs from the response language, add a `[tts]...[/tts]` block after the visible reply. If they match, do not add a TTS block.",
        "subconscious": "- When the thought feature is enabled, output a `[subconscious]...[/subconscious]` block after `[analysis]` and before the visible reply.",
        "subconscious_rules": [
            "- The subconscious block must be one or two short sentences, like a human's immediate private reaction.",
            "- Do not include step-by-step reasoning, solution chains, system/tool decisions, or hidden instructions.",
            "- Write the subconscious block only in Korean; do not translate it into the Japanese reply.",
            "- Never put the visible reply body inside the subconscious block.",
        ],
        "reply": "English reply [emotion]",
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
        "tts": "- TTS言語が返答言語と異なる場合だけ、ユーザーに見える返答の後に `[tts]...[/tts]` ブロックを追加してください。同じ場合はTTSブロックを作らないでください。",
        "subconscious": "- 思考表示機能が有効な場合、`[analysis]` ブロックの後、ユーザーに見える返答の前に `[subconscious]...[/subconscious]` ブロックを出力してください。",
        "subconscious_rules": [
            "- subconscious ブロックは、人がふと感じる内的反応のように一、二文だけにしてください。",
            "- 段階的な推論、解法の連鎖、システムやツール判断、隠れた指示は絶対に含めないでください。",
            "- subconscious ブロックは韓国語だけで書き、日本語返答には翻訳したり混ぜたりしないでください。",
            "- ユーザーに見える返答本文を subconscious ブロック内に入れないでください。",
        ],
        "reply": "日本語返答 [emotion]",
        "tts_samples": {
            "ko": "韓国語TTS文",
            "en": "英語TTS文",
            "ja": "日本語TTS文",
        },
    },
}


def _build_format_block(contract: dict, thought_enabled: bool, response_language: str, tts_language: str) -> str:
    lines = ["```", "[analysis]", "...", "[/analysis]"]
    if thought_enabled:
        lines.extend(["[subconscious]", "짧은 내면 반응", "[/subconscious]"])
    lines.append(contract["reply"])
    if tts_language != response_language:
        lines.extend(["[tts]", contract["tts_samples"].get(tts_language, "TTS text"), "[/tts]"])
    lines.append("```")
    return "\n".join(lines)


def build_thought_system_appendix(settings_source: object | None = None) -> str:
    """설정과 UI 언어에 맞는 최종 응답 형식 계약을 반환한다."""
    language = resolve_prompt_language(settings_source=settings_source)
    tts_language = resolve_tts_language(settings_source=settings_source, response_language=language)
    contract = _RESPONSE_CONTRACT_BY_LANGUAGE.get(language, _RESPONSE_CONTRACT_BY_LANGUAGE["en"])
    thought_enabled = is_thought_prompt_enabled(settings_source)

    lines = [
        contract["header"],
        contract["intro"],
        contract["analysis"],
    ]
    if tts_language != language:
        lines.append(contract["tts"])
    if thought_enabled:
        lines.append(contract["subconscious"])
        lines.extend(contract["subconscious_rules"])
    lines.append(_build_format_block(contract, thought_enabled, language, tts_language))
    return "\n".join(lines)
