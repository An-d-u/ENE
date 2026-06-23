"""
에네 목표 업데이트 출력 규칙을 만든다.
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


def is_goal_prompt_enabled(settings_source: object | None = None) -> bool:
    """설정에서 에네 목표 기능 활성화 여부를 읽는다."""
    return bool(_read_setting(settings_source, "enable_ene_goals", True))


_GOAL_RULES_BY_LANGUAGE = {
    "ko": [
        "- 목표 기능이 켜져 있으면 모든 응답마다 `[ene_goal_update]...[/ene_goal_update]` 블록을 출력하세요.",
        "- 목표 변경이 없으면 반드시 `action=none`을 사용하고, 새 목표를 만들지 마세요.",
        "- 목표를 바꿀 때의 action 값은 `create`, `update`, `complete`, `cancel` 중 하나만 사용하세요.",
        "- `short_term`은 지금 대화나 곧바로 이어질 작업처럼 가까운 목표에만 사용하세요.",
        "- `long_term`은 여러 대화에 걸쳐 유지할 사용자 선호, 프로젝트 방향, 장기 약속에만 사용하세요.",
        "- 목표 블록은 짧게 쓰고, 사용자에게 보일 답변 본문을 넣지 마세요.",
    ],
    "en": [
        "- When the goal feature is enabled, output an `[ene_goal_update]...[/ene_goal_update]` block in every response.",
        "- If no goal changes, use `action=none` and do not invent a new goal.",
        "- When changing a goal, use only one action: `create`, `update`, `complete`, or `cancel`.",
        "- Use `short_term` only for goals tied to this conversation or the immediate next task.",
        "- Use `long_term` only for user preferences, project direction, or durable commitments that should survive across conversations.",
        "- Keep the goal block short and never place the visible reply body inside it.",
    ],
    "ja": [
        "- 目標機能が有効な場合、すべての応答で `[ene_goal_update]...[/ene_goal_update]` ブロックを出力してください。",
        "- 目標の変更がない場合は必ず `action=none` を使い、新しい目標を作らないでください。",
        "- 目標を変更するときの action は `create`, `update`, `complete`, `cancel` のいずれか一つだけにしてください。",
        "- `short_term` は、この会話や直後の作業に結びつく近い目標だけに使ってください。",
        "- `long_term` は、会話をまたいで残すべきユーザーの好み、プロジェクト方針、長期的な約束だけに使ってください。",
        "- 目標ブロックは短くし、ユーザーに見える返答本文を入れないでください。",
    ],
}


def build_goal_update_rules(language: str = "ko") -> list[str]:
    """언어별 목표 업데이트 규칙 목록을 반환한다."""
    return list(_GOAL_RULES_BY_LANGUAGE.get(language, _GOAL_RULES_BY_LANGUAGE["en"]))
