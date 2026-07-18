"""
에네 생각 출력 규칙을 만든다.
"""

from __future__ import annotations

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


def is_thought_prompt_enabled(settings_source: object | None = None) -> bool:
    """설정에서 에네 생각 기능 활성화 여부를 읽는다."""
    return bool(_read_setting(settings_source, "enable_ene_thoughts", True))


_THOUGHT_RULES_BY_LANGUAGE = {
    "ko": [
        "- subconscious 블록은 사람이 겉으로 말하기 전에 순간적으로 떠올리는 솔직한 내적 반응처럼 쓰세요.",
        "- 감정, 망설임, 걱정, 애정, 장난기, 답변의 방향 정도를 자연스럽게 담되, 단계별 추론이나 문제 풀이 과정은 쓰지 마세요.",
        "- 한두 문장으로 짧게 쓰고, 답변 본문을 요약하지 말고 지금 상황에 대한 속마음처럼 쓰세요.",
        "- 시스템/도구 판단, 숨겨진 지시문은 절대 포함하지 마세요.",
        "- subconscious 블록은 사용자에게 보이는 답변과 같은 언어로만 작성하고, TTS 블록에는 섞지 마세요.",
        "- 답변 본문을 subconscious 블록 안에 넣지 마세요.",
    ],
    "en": [
        "- The subconscious block should read like an honest private reaction that briefly crosses a person's mind before they speak.",
        "- It may include emotion, hesitation, concern, affection, playfulness, or the direction of ENE's response, but never step-by-step reasoning or solution chains.",
        "- Keep it to one or two short sentences, and do not summarize the visible reply; write it as ENE's immediate inner response to the situation.",
        "- Do not include system/tool decisions or hidden instructions.",
        "- Write the subconscious block in the same language as the visible reply, and do not mix it into the TTS block.",
        "- Never put the visible reply body inside the subconscious block.",
    ],
    "ja": [
        "- subconscious ブロックは、話す前にふと浮かぶ正直な内的反応のように書いてください。",
        "- 感情、ためらい、心配、愛情、いたずらっぽさ、返答の向きくらいは自然に含めてもよいですが、段階的な推論や解法の過程は書かないでください。",
        "- 一、二文だけにし、表示される返答の要約ではなく、その場で浮かんだ内心として書いてください。",
        "- システムやツール判断、隠れた指示は絶対に含めないでください。",
        "- subconscious ブロックはユーザーに表示される返答と同じ言語だけで書き、TTSブロックには混ぜないでください。",
        "- ユーザーに見える返答本文を subconscious ブロック内に入れないでください。",
    ],
}


_STRUCTURED_THOUGHT_RULES_BY_LANGUAGE = {
    "ko": [
        "- `thought` 필드에는 사용자에게 표시할 한두 문장의 짧은 내적 반응이나 요약만 쓰세요.",
        "- 이 필드는 raw reasoning이 아니며, 단계별 추론이나 문제 풀이 과정, 숨은 추론을 제공하지 마세요.",
        "- 감정, 망설임, 걱정, 애정, 장난기처럼 바로 드러내도 안전한 반응만 담으세요.",
        "- 시스템 판단, 도구 판단, 숨겨진 지시문은 넣지 마세요.",
        "- 사용자에게 보이는 답변과 같은 언어로 작성하고, 답변 본문을 복사하지 마세요.",
    ],
    "en": [
        "- Put only a short one- or two-sentence user-visible inner reaction or summary in the `thought` field.",
        "- This field is not raw reasoning; do not provide step-by-step reasoning, solution chains, or hidden reasoning.",
        "- Include only safe immediate reactions such as emotion, hesitation, concern, affection, or playfulness.",
        "- Do not include system decisions, tool decisions, or hidden instructions.",
        "- Use the same language as the visible reply and do not copy the reply body.",
    ],
    "ja": [
        "- `thought` フィールドには、ユーザーに表示できる一、二文の短い内的反応または要約だけを書いてください。",
        "- このフィールドは raw reasoning ではありません。段階的な推論、解法の過程、隠れた推論を提供しないでください。",
        "- 感情、ためらい、心配、愛情、遊び心など、安全に見せられる即時反応だけを含めてください。",
        "- システム判断、ツール判断、隠れた指示は含めないでください。",
        "- 表示される返答と同じ言語を使い、返答本文をコピーしないでください。",
    ],
}


def build_thought_rules(
    language: str = "ko",
    response_style: str = "legacy_tags",
) -> list[str]:
    """언어별 subconscious 출력 규칙 목록을 반환한다."""
    response_style = normalize_response_style(response_style)
    if response_style == "plain":
        return []
    if response_style == "structured_fields":
        return list(
            _STRUCTURED_THOUGHT_RULES_BY_LANGUAGE.get(
                language,
                _STRUCTURED_THOUGHT_RULES_BY_LANGUAGE["en"],
            )
        )
    return list(_THOUGHT_RULES_BY_LANGUAGE.get(language, _THOUGHT_RULES_BY_LANGUAGE["en"]))


def build_thought_system_appendix(settings_source: object | None = None) -> str:
    """기존 호출자를 위해 응답 계약 빌더로 위임한다."""
    from .response_contract import build_response_contract_appendix

    return build_response_contract_appendix(settings_source=settings_source)
