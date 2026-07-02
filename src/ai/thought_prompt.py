"""
에네 생각 출력 규칙을 만든다.
"""

from __future__ import annotations


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


def build_thought_rules(language: str = "ko") -> list[str]:
    """언어별 subconscious 출력 규칙 목록을 반환한다."""
    return list(_THOUGHT_RULES_BY_LANGUAGE.get(language, _THOUGHT_RULES_BY_LANGUAGE["en"]))


def build_thought_system_appendix(settings_source: object | None = None) -> str:
    """기존 호출자를 위해 응답 계약 빌더로 위임한다."""
    from .response_contract import build_response_contract_appendix

    return build_response_contract_appendix(settings_source=settings_source)
