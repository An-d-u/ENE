"""
LLM 요약 응답 파싱 유틸리티.
"""

from __future__ import annotations

import re

from .knowledge_map_types import TopicMemoryHint


SUMMARY_REQUIRED_SECTION_LABELS = {
    "summary": "[SUMMARY]",
    "facts": "[MASTER_INFO]",
    "ene_facts": "[ENE_INFO]",
    "memory_meta": "[MEMORY_META]",
}

SUMMARY_MEMORY_META_KEYS = {
    "memory_type",
    "importance_reason",
    "confidence",
    "entity_names",
    "aliases",
    "trigger_terms",
}

TOPIC_MEMORY_HINT_KEYS = {
    "keyword",
    "subject",
    "type",
    "state",
    "text",
    "aliases",
    "retrieval_terms",
    "confidence",
}

TOPIC_MEMORY_LIST_KEYS = {"aliases", "retrieval_terms"}
TOPIC_MEMORY_NONE_VALUES = {"none", "none.", "없음", "?놁쓬"}


def _summary_section_for_line(line: str) -> str | None:
    upper = line.upper()
    if upper in {"[SUMMARY]", "SUMMARY"} or "[요약]" in line or "[?붿빟]" in line:
        return "summary"
    if (
        upper in {"[MASTER_INFO]", "MASTER_INFO"}
        or "[마스터 정보]" in line
        or "[사용자 정보]" in line
        or "[留덉뒪???뺣낫]" in line
        or "[?ъ슜???뺣낫]" in line
        or "MASTER INFO" in upper
    ):
        return "facts"
    if (
        upper in {"[ENE_INFO]", "ENE_INFO"}
        or "[에네 정보]" in line
        or "[?먮꽕 ?뺣낫]" in line
        or "ENE INFO" in upper
    ):
        return "ene_facts"
    if (
        upper in {"[MEMORY_META]", "MEMORY_META"}
        or "[기억 메타]" in line
        or "[湲곗뼲 硫뷀?]" in line
    ):
        return "memory_meta"
    if upper in {"[TOPIC_MEMORY]", "TOPIC_MEMORY", "TOPIC MEMORY"} or line in {
        "[주제 기억]",
        "주제 기억",
    }:
        return "topic_memory"
    return None


def missing_summary_response_sections(response_text: str) -> list[str]:
    """요약 응답이 저장 가능한 구조를 모두 갖췄는지 확인하고 빠진 섹션을 돌려준다."""
    seen_sections: set[str] = set()
    current_section = None
    has_summary_content = False

    for raw in str(response_text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue

        section = _summary_section_for_line(line)
        if section:
            seen_sections.add(section)
            current_section = section
            continue

        if current_section == "summary":
            content = line[1:].strip() if line.startswith("-") else line
            if content:
                has_summary_content = True

    missing = [
        label
        for section, label in SUMMARY_REQUIRED_SECTION_LABELS.items()
        if section not in seen_sections
    ]
    if not has_summary_content:
        missing.append("[SUMMARY] content")
    return missing


def is_complete_summary_response(response_text: str) -> bool:
    """요약 응답이 중간에 끊기지 않고 필수 섹션을 모두 포함했는지 확인한다."""
    return not missing_summary_response_sections(response_text)


def parse_summary_memory_meta(meta_lines: list[str]) -> dict:
    """요약 응답의 MEMORY_META 섹션을 정규화된 딕셔너리로 파싱한다."""
    memory_meta: dict = {}

    for raw_line in meta_lines:
        line = str(raw_line).strip()
        if not line:
            continue
        if line.startswith("-"):
            line = line[1:].strip()
        if not line or line.lower() in {"none", "none.", "없음"}:
            continue
        if ":" not in line:
            continue

        key, value = line.split(":", 1)
        normalized_key = key.strip().lower()
        if normalized_key not in SUMMARY_MEMORY_META_KEYS:
            continue

        normalized_value = value.strip()
        if not normalized_value:
            continue

        if normalized_key == "confidence":
            try:
                memory_meta[normalized_key] = max(0.0, min(1.0, float(normalized_value)))
            except ValueError:
                continue
            continue

        if normalized_key in {"entity_names", "aliases", "trigger_terms"}:
            cleaned_value = normalized_value.strip("[]")
            values = [
                item.strip().strip('\'"')
                for item in cleaned_value.split(",")
                if item.strip().strip('\'"')
            ]
            if values:
                memory_meta[normalized_key] = values
            continue

        memory_meta[normalized_key] = normalized_value

    return memory_meta


def _clean_topic_memory_line(raw_line: str) -> str:
    line = str(raw_line or "").strip()
    if line.startswith("-"):
        line = line[1:].strip()
    return line


def _split_topic_memory_parts(line: str) -> list[str]:
    return [part.strip() for part in line.split("|") if part.strip()]


def _parse_topic_memory_key_value(part: str) -> tuple[str, str] | None:
    if ":" not in part:
        return None
    key, value = part.split(":", 1)
    normalized_key = key.strip().lower()
    if normalized_key not in TOPIC_MEMORY_HINT_KEYS:
        return None
    return normalized_key, value.strip()


def _normalize_topic_memory_list(value: str) -> list[str]:
    cleaned_value = str(value or "").strip().strip("[]")
    return [
        item.strip().strip('\'"')
        for item in cleaned_value.split(",")
        if item.strip().strip('\'"')
    ]


def _topic_memory_hint_from_data(data: dict) -> TopicMemoryHint | None:
    normalized = {
        "type": "status_flow",
        "state": "active",
        "confidence": 0.5,
    }
    normalized.update(data)

    for key in ("keyword", "subject", "text"):
        if not str(normalized.get(key, "") or "").strip():
            return None

    for key in TOPIC_MEMORY_LIST_KEYS:
        normalized[key] = _normalize_topic_memory_list(normalized.get(key, ""))

    return TopicMemoryHint.from_dict(normalized)


def parse_topic_memory_hints(topic_lines: list[str]) -> list[TopicMemoryHint]:
    """TOPIC_MEMORY lines를 TopicMemoryHint 목록으로 변환한다."""
    hints: list[TopicMemoryHint] = []
    current: dict = {}

    def flush_current() -> None:
        nonlocal current
        if not current:
            return
        hint = _topic_memory_hint_from_data(current)
        if hint is not None:
            hints.append(hint)
        current = {}

    for raw_line in topic_lines:
        stripped = str(raw_line or "").strip()
        if not stripped:
            continue

        cleaned_line = _clean_topic_memory_line(stripped)
        if not cleaned_line:
            continue
        if cleaned_line.lower() in TOPIC_MEMORY_NONE_VALUES:
            flush_current()
            continue

        parts = _split_topic_memory_parts(cleaned_line)
        parsed_parts = [
            parsed
            for parsed in (_parse_topic_memory_key_value(part) for part in parts)
            if parsed is not None
        ]
        if not parsed_parts:
            continue

        starts_new_hint = stripped.startswith("-") and parsed_parts[0][0] == "keyword"
        if starts_new_hint and current:
            flush_current()

        for key, value in parsed_parts:
            if value:
                current[key] = value

    flush_current()
    return hints


def parse_summary_topic_memory(response_text: str) -> list[TopicMemoryHint]:
    """요약 응답에서 선택 섹션인 TOPIC_MEMORY만 파싱한다."""
    topic_lines: list[str] = []
    current_section = None

    for raw in str(response_text or "").split("\n"):
        line = raw.strip()
        if not line:
            continue

        section = _summary_section_for_line(line)
        if section:
            current_section = section
            continue

        if current_section == "topic_memory":
            topic_lines.append(line)

    return parse_topic_memory_hints(topic_lines)


def parse_summary_response(response_text: str) -> tuple[str, list[str], list[str], dict]:
    """요약 응답을 [SUMMARY], [MASTER_INFO], [ENE_INFO], [MEMORY_META]로 분리한다."""
    summary_lines: list[str] = []
    user_facts: list[str] = []
    ene_facts: list[str] = []
    memory_meta_lines: list[str] = []

    try:
        lines = response_text.split("\n")
        current_section = None

        for raw in lines:
            line = raw.strip()
            if not line:
                continue

            upper = line.upper()
            if upper in {"[SUMMARY]", "SUMMARY"} or "[요약]" in line:
                current_section = "summary"
                continue
            if (
                upper in {"[MASTER_INFO]", "MASTER_INFO"}
                or "[마스터 정보]" in line
                or "[사용자 정보]" in line
                or "MASTER INFO" in upper
            ):
                current_section = "facts"
                continue
            if upper in {"[ENE_INFO]", "ENE_INFO"} or "[에네 정보]" in line or "ENE INFO" in upper:
                current_section = "ene_facts"
                continue
            if upper in {"[MEMORY_META]", "MEMORY_META"} or "[기억 메타]" in line:
                current_section = "memory_meta"
                continue

            if upper in {"[TOPIC_MEMORY]", "TOPIC_MEMORY", "TOPIC MEMORY"} or line in {
                "[주제 기억]",
                "주제 기억",
            }:
                current_section = "topic_memory"
                continue

            if current_section == "summary":
                if re.match(
                    r"^-\s*\[(basic|preference|goal|habit|speaking_style|relationship_tone)\]\s*.+$",
                    line,
                    re.IGNORECASE,
                ):
                    continue
                if line.startswith("-"):
                    line = line[1:].strip()
                summary_lines.append(line)
                continue

            if current_section == "facts":
                if not line.startswith("-"):
                    continue
                fact_line = line[1:].strip()
                if not fact_line or fact_line.lower() in {"none", "none.", "없음"}:
                    continue

                tagged = re.match(r"^\[(basic|preference|goal|habit)\]\s*(.+)$", fact_line, re.IGNORECASE)
                if tagged:
                    category = tagged.group(1).lower()
                    content = tagged.group(2).strip()
                    if content:
                        user_facts.append(f"[{category}] {content}")
                else:
                    user_facts.append(fact_line)
                continue

            if current_section == "ene_facts":
                if not line.startswith("-"):
                    continue
                fact_line = line[1:].strip()
                if not fact_line or fact_line.lower() in {"none", "none.", "없음"}:
                    continue

                tagged = re.match(
                    r"^\[(basic|preference|goal|habit|speaking_style|relationship_tone)\]\s*(.+)$",
                    fact_line,
                    re.IGNORECASE,
                )
                if tagged:
                    category = tagged.group(1).lower()
                    content = tagged.group(2).strip()
                    if content:
                        ene_facts.append(f"[{category}] {content}")
                else:
                    ene_facts.append(fact_line)
                continue

            if current_section == "memory_meta":
                memory_meta_lines.append(line)

        summary = " ".join(summary_lines).strip()
        summary = re.sub(r"\s+", " ", summary).strip()
        if not summary:
            non_empty = [ln.strip() for ln in response_text.split("\n") if ln.strip()]
            summary = " ".join(non_empty[:2]).strip()
        memory_meta = parse_summary_memory_meta(memory_meta_lines)

    except Exception as e:
        print(f"[LLM] 요약 파싱 실패: {e}")
        non_empty = [ln.strip() for ln in response_text.split("\n") if ln.strip()]
        summary = " ".join(non_empty[:2]).strip()
        user_facts = []
        ene_facts = []
        memory_meta = {}

    return summary, user_facts, ene_facts, memory_meta


def parse_summary_response_with_topic_memory(
    response_text: str,
) -> tuple[str, list[str], list[str], dict, list[TopicMemoryHint]]:
    """기존 요약 파싱 결과에 TOPIC_MEMORY hint 목록을 함께 반환한다."""
    summary, user_facts, ene_facts, memory_meta = parse_summary_response(response_text)
    topic_hints = parse_summary_topic_memory(response_text)
    return summary, user_facts, ene_facts, memory_meta, topic_hints
