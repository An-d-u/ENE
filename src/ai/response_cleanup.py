"""LLM 응답을 화면/TTS 파싱 전에 정리하는 공통 유틸리티."""

from __future__ import annotations

import re

THOUGHT_TAG_ALIASES = (
    "subconscious",
    "thought",
    "ene_thought",
    "inner_thought",
    "생각",
    "속마음",
    "에네생각",
    "에네 생각",
)

THOUGHT_LABEL_ALIASES = (
    "subconscious",
    "thought",
    "ene_thought",
    "inner_thought",
    "생각",
    "속마음",
    "에네\\s*생각",
)

_THOUGHT_TAG_PATTERN = "|".join(re.escape(alias).replace("\\ ", r"\s+") for alias in THOUGHT_TAG_ALIASES)
_THOUGHT_BLOCK_PATTERN = rf"\[\s*(?:{_THOUGHT_TAG_PATTERN})\s*\]\s*(.*?)\s*\[\s*/\s*(?:{_THOUGHT_TAG_PATTERN})\s*\]"
_THOUGHT_LABEL_PATTERN = rf"^\s*(?:{'|'.join(THOUGHT_LABEL_ALIASES)})\s*[:=：]\s*(.+?)\s*$"
_TTS_BLOCK_PATTERN = r"\[\s*tts\s*\]\s*(.*?)\s*\[\s*/\s*tts\s*\]"
GOAL_UPDATE_KEYS = ("action", "type", "id", "title", "reason", "completion_reason")
_GOAL_UPDATE_BLOCK_PATTERN = r"\[\s*ene_goal_update\s*\]\s*(.*?)\s*\[\s*/\s*ene_goal_update\s*\]"
_UNCLOSED_GOAL_UPDATE_BLOCK_PATTERN = r"\[\s*ene_goal_update\s*\].*$"


def strip_thinking_markers(text: str) -> str:
    """로컬 reasoning 모델이 노출할 수 있는 think 태그와 내부 블록을 제거한다."""
    cleaned = str(text or "")
    cleaned = re.sub(r"<think\b[^>]*>.*?</think\s*>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"</?think\b[^>]*>\s*", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def extract_thought_metadata(text: str) -> tuple[str, str]:
    """응답 본문에서 에네 생각 메타데이터를 분리한다."""
    source = str(text or "")
    match = re.search(_THOUGHT_BLOCK_PATTERN, source, re.IGNORECASE | re.DOTALL)
    if match:
        thought = re.sub(r"\s+", " ", match.group(1)).strip()
        cleaned = re.sub(_THOUGHT_BLOCK_PATTERN, "", source, flags=re.IGNORECASE | re.DOTALL).strip()
        if not cleaned:
            return match.group(1).strip(), ""
        return cleaned, thought

    lines = source.splitlines()
    thought_lines: list[str] = []
    consumed = 0
    started = False

    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()
        if not started and not stripped:
            consumed = index + 1
            continue

        label_match = re.match(_THOUGHT_LABEL_PATTERN, raw_line, re.IGNORECASE)
        if label_match:
            started = True
            thought_lines.append(label_match.group(1).strip())
            consumed = index + 1
            continue

        break

    if not thought_lines:
        return source, ""

    while consumed < len(lines) and not lines[consumed].strip():
        consumed += 1

    cleaned = "\n".join(lines[consumed:]).strip()
    thought = re.sub(r"\s+", " ", " ".join(thought_lines)).strip()
    if not cleaned:
        return source, ""
    return cleaned, thought


def extract_goal_update_metadata(text: str) -> tuple[str, dict[str, str]]:
    """응답 본문에서 목표 업데이트 메타데이터를 분리한다."""
    source = str(text or "")
    match = re.search(_GOAL_UPDATE_BLOCK_PATTERN, source, re.IGNORECASE | re.DOTALL)
    if not match:
        cleaned = re.sub(_UNCLOSED_GOAL_UPDATE_BLOCK_PATTERN, "", source, flags=re.IGNORECASE | re.DOTALL).strip()
        if cleaned != source.strip():
            return cleaned, {}
        return source, {}

    parsed: dict[str, str] = {}
    allowed_keys = set(GOAL_UPDATE_KEYS)
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip().lower()
        if normalized_key in allowed_keys:
            parsed[normalized_key] = value.strip()

    cleaned = re.sub(_GOAL_UPDATE_BLOCK_PATTERN, "", source, flags=re.IGNORECASE | re.DOTALL).strip()
    return cleaned, parsed


def extract_tts_metadata(text: str) -> tuple[str, str]:
    """응답 본문에서 명시적인 TTS 블록을 분리한다."""
    source = str(text or "")
    match = re.search(_TTS_BLOCK_PATTERN, source, re.IGNORECASE | re.DOTALL)
    if not match:
        return source, ""
    tts_text = match.group(1).strip()
    cleaned = re.sub(_TTS_BLOCK_PATTERN, "", source, flags=re.IGNORECASE | re.DOTALL).strip()
    return cleaned, tts_text
