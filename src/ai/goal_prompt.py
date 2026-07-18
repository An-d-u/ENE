"""
에네 목표 업데이트 출력 규칙을 만든다.
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


_STRUCTURED_GOAL_RULES_BY_LANGUAGE = {
    "ko": [
        "- 목표 변경은 `goal_update` 필드에만 기록하세요.",
        "- 변경이 없으면 `action`은 `none`으로 두고 나머지 문자열 필드는 비우세요.",
        "- 목표를 바꿀 때 `action`은 `create`, `update`, `complete`, `cancel` 중 하나만 사용하세요.",
        "- `short_term`은 현재 대화나 바로 이어질 작업에만 사용하고, `long_term`은 대화 간 유지할 방향에만 사용하세요.",
        "- 목표 데이터에 사용자에게 표시할 답변 본문을 넣지 마세요.",
        "- `create`에는 `type`, `title`, `reason`이 필요합니다.",
        "- `update`에는 `id`와 `title` 또는 `reason` 중 하나 이상이 필요합니다.",
        "- `complete` 또는 `cancel`에는 `id`가 필요하며, 완료할 때만 `completion_reason`을 채우세요.",
        "- `type`은 `short_term` 또는 `long_term`만 사용하세요.",
    ],
    "en": [
        "- Record goal changes only in the `goal_update` field.",
        "- When no goal changes, set `action` to `none` and leave the remaining string fields empty.",
        "- For a change, use only `create`, `update`, `complete`, or `cancel` as `action`.",
        "- Use `short_term` only for the current conversation or immediate work, and `long_term` only for durable direction.",
        "- Never put the user-visible reply body in the goal data.",
        "- For `create`, require `type`, `title`, and `reason`.",
        "- For `update`, require `id` and at least one of `title` or `reason`.",
        "- For `complete` or `cancel`, require `id`; use `completion_reason` only for completion.",
        "- Use only `short_term` or `long_term` for `type`.",
    ],
    "ja": [
        "- 目標の変更は `goal_update` フィールドだけに記録してください。",
        "- 変更がない場合は `action` を `none` にし、残りの文字列フィールドは空にしてください。",
        "- 変更時の `action` は `create`, `update`, `complete`, `cancel` のいずれか一つだけにしてください。",
        "- `short_term` は現在の会話や直後の作業だけに、`long_term` は長く維持する方向だけに使ってください。",
        "- ユーザーに表示する返答本文を目標データへ入れないでください。",
        "- `create` には `type`, `title`, `reason` が必要です。",
        "- `update` には `id` と、`title` または `reason` の少なくとも一つが必要です。",
        "- `complete` または `cancel` には `id` が必要で、完了時だけ `completion_reason` を使ってください。",
        "- `type` は `short_term` または `long_term` だけを使ってください。",
    ],
}


def build_goal_update_rules(
    language: str = "ko",
    response_style: str = "legacy_tags",
) -> list[str]:
    """언어별 목표 업데이트 규칙 목록을 반환한다."""
    response_style = normalize_response_style(response_style)
    if response_style == "plain":
        return []
    if response_style == "structured_fields":
        return list(
            _STRUCTURED_GOAL_RULES_BY_LANGUAGE.get(
                language,
                _STRUCTURED_GOAL_RULES_BY_LANGUAGE["en"],
            )
        )
    return list(_GOAL_RULES_BY_LANGUAGE.get(language, _GOAL_RULES_BY_LANGUAGE["en"]))
