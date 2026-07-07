from __future__ import annotations

import inspect
from typing import Any


def empty_embedding_rebuild_result() -> dict[str, int]:
    return {"total": 0, "updated": 0, "failed": 0, "skipped": 0}


def combine_embedding_rebuild_results(*results: dict[str, Any] | None) -> dict[str, int]:
    combined = empty_embedding_rebuild_result()
    for result in results:
        if not isinstance(result, dict):
            continue
        for key in combined:
            try:
                combined[key] += int(result.get(key, 0) or 0)
            except (TypeError, ValueError):
                continue
    return combined


def has_embedding_regenerator(manager: Any) -> bool:
    return callable(getattr(manager, "regenerate_embeddings", None))


def count_memory_embeddings(memory_manager: Any) -> int:
    stats_getter = getattr(memory_manager, "get_stats", None)
    if not callable(stats_getter):
        return 0
    stats = stats_getter()
    if not isinstance(stats, dict):
        return 0
    try:
        return max(0, int(stats.get("with_embedding", 0) or 0))
    except (TypeError, ValueError):
        return 0


def count_topic_embeddings(knowledge_map_manager: Any) -> int:
    count = 0
    for topic in getattr(knowledge_map_manager, "topics", []) or []:
        for clue in getattr(topic, "clues", []) or []:
            if getattr(clue, "embedding", None):
                count += 1
    return count


def count_saved_embeddings(memory_manager: Any, knowledge_map_manager: Any = None) -> int:
    return count_memory_embeddings(memory_manager) + count_topic_embeddings(knowledge_map_manager)


async def _regenerate_manager_embeddings(manager: Any) -> dict[str, int]:
    regenerate = getattr(manager, "regenerate_embeddings", None)
    if not callable(regenerate):
        return empty_embedding_rebuild_result()
    result = regenerate()
    if inspect.isawaitable(result):
        result = await result
    return combine_embedding_rebuild_results(result)


async def regenerate_saved_embeddings(
    memory_manager: Any,
    knowledge_map_manager: Any = None,
) -> dict[str, int]:
    results = []
    for manager in (memory_manager, knowledge_map_manager):
        if manager is None:
            continue
        results.append(await _regenerate_manager_embeddings(manager))
    return combine_embedding_rebuild_results(*results)
