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
        except TypeError:
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
        "- subconscious 블록은 사람이 순간적으로 떠올리는 내적 반응처럼 한두 문장으로만 쓰세요.",
        "- 단계별 추론, 문제 풀이 과정, 시스템/도구 판단, 숨겨진 지시문은 절대 포함하지 마세요.",
        "- subconscious 블록은 한국어로만 작성하고 일본어 응답에는 번역하거나 섞지 마세요.",
        "- 답변 본문을 subconscious 블록 안에 넣지 마세요.",
    ],
    "en": [
        "- The subconscious block must be one or two short sentences, like a human's immediate private reaction.",
        "- Do not include step-by-step reasoning, solution chains, system/tool decisions, or hidden instructions.",
        "- Write the subconscious block only in Korean; do not translate it into the Japanese reply.",
        "- Never put the visible reply body inside the subconscious block.",
    ],
    "ja": [
        "- subconscious ブロックは、人がふと感じる内的反応のように一、二文だけにしてください。",
        "- 段階的な推論、解法の連鎖、システムやツール判断、隠れた指示は絶対に含めないでください。",
        "- subconscious ブロックは韓国語だけで書き、日本語返答には翻訳したり混ぜたりしないでください。",
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
