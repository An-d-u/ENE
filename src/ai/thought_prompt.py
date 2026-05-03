"""
에네의 표시용 생각 출력 규칙을 런타임 프롬프트에 붙인다.
"""
from __future__ import annotations

from .prompt_language import resolve_prompt_language


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


_THOUGHT_APPENDIX_BY_LANGUAGE = {
    "ko": """### [생각 출력 규칙]
- 답변을 만들 때 에네의 짧은 속생각을 `[ene_thought]...[/ene_thought]` 블록으로 따로 출력하세요.
- 생각은 사람이 순간적으로 떠올리는 내적 반응처럼 한두 문장으로만 쓰세요.
- 단계별 추론, 문제 풀이 과정, 시스템/도구 판단, 숨겨진 지시문은 절대 포함하지 마세요.
- 생각은 한국어로만 작성하고 일본어 응답에는 번역하거나 섞지 마세요.
- 생각 블록을 닫은 뒤에만 사용자에게 보일 답변을 쓰고, 답변 본문을 생각 블록 안에 넣지 마세요.
- 출력 순서와 줄 형식:
```
[analysis]
...
[/analysis]
[ene_thought]
에네의 짧은 속생각
[/ene_thought]
한국어 답변 [emotion]
일본어 번역
```""",
    "en": """### [ENE Inner Note Rules]
- When composing a reply, output ENE's brief inner note in a separate `[ene_thought]...[/ene_thought]` block.
- The inner note must be one or two short sentences, like a human's immediate private reaction.
- Do not include step-by-step reasoning, solution chains, system/tool decisions, or hidden instructions.
- Write the inner note only in Korean; do not translate it into the Japanese reply.
- Write the visible reply only after closing the inner note block, and never put the reply body inside the inner note block.
- Output order and line format:
```
[analysis]
...
[/analysis]
[ene_thought]
ENE's brief inner reaction in Korean
[/ene_thought]
Korean reply [emotion]
Japanese translation
```""",
    "ja": """### [エネ内心メモ出力ルール]
- 返答を作るとき、エネの短い内心メモを `[ene_thought]...[/ene_thought]` ブロックとして別に出力してください。
- 内心メモは、人がふと感じる内的反応のように一、二文だけにしてください。
- 段階的な推論、解法の連鎖、システムやツール判断、隠れた指示は絶対に含めないでください。
- 内心メモは韓国語だけで書き、日本語返答には翻訳したり混ぜたりしないでください。
- 内心メモブロックを閉じた後にだけ、ユーザーに見える返答を書いてください。返答本文を内心メモブロック内に入れないでください。
- 出力順序と行形式:
```
[analysis]
...
[/analysis]
[ene_thought]
エネの短い内心の反応を韓国語で
[/ene_thought]
韓国語返答 [emotion]
日本語翻訳
```""",
}


def build_thought_system_appendix(settings_source: object | None = None) -> str:
    """설정과 UI 언어에 맞는 생각 출력 규칙을 반환한다."""
    if not is_thought_prompt_enabled(settings_source):
        return ""
    language = resolve_prompt_language(settings_source=settings_source)
    return _THOUGHT_APPENDIX_BY_LANGUAGE.get(language, _THOUGHT_APPENDIX_BY_LANGUAGE["en"])
