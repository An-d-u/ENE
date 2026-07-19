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
_RESERVED_CONTROL_TAG_FAMILIES = (
    ("thought", rf"(?:{_THOUGHT_TAG_PATTERN})"),
    ("tts", "tts"),
    ("analysis", "analysis"),
    ("ene_goal_update", "ene_goal_update"),
    ("proactive_conversation", "proactive_conversation"),
)
_RESERVED_CONTROL_TOKEN_PATTERN = re.compile(
    "|".join(
        (
            rf"(?P<{family}_end>\[\s*/\s*{tag_pattern}\s*\])"
            rf"|(?P<{family}_start>\[\s*{tag_pattern}\s*\])"
        )
        for family, tag_pattern in _RESERVED_CONTROL_TAG_FAMILIES
    ),
    re.IGNORECASE,
)
GOAL_UPDATE_KEYS = ("action", "type", "id", "title", "reason", "completion_reason")
_GOAL_UPDATE_BLOCK_PATTERN = r"\[\s*ene_goal_update\s*\]\s*(.*?)\s*\[\s*/\s*ene_goal_update\s*\]"
_PROACTIVE_CONVERSATION_BLOCK_PATTERN = (
    r"\[\s*proactive_conversation\s*\]\s*"
    r".*?"
    r"\s*\[\s*/\s*proactive_conversation\s*\]"
)


def sanitize_reserved_control_blocks(text: str) -> str:
    """예약 제어 태그의 flat 문법을 검증하고 잘못된 suffix와 orphan close를 제거한다."""
    source = str(text or "")
    active_family = ""
    active_start = -1
    cutoff = len(source)
    orphan_markers: list[tuple[int, int]] = []

    for token_match in _RESERVED_CONTROL_TOKEN_PATTERN.finditer(source):
        marker_group = token_match.lastgroup or ""
        family, marker_kind = marker_group.rsplit("_", 1)
        if marker_kind == "start":
            if active_family:
                cutoff = active_start
                break
            active_family = family
            active_start = token_match.start()
            continue

        if not active_family:
            orphan_markers.append((token_match.start(), token_match.end()))
            continue
        if family != active_family:
            cutoff = active_start
            break
        active_family = ""
        active_start = -1

    if active_family:
        cutoff = active_start

    cleaned_parts: list[str] = []
    cursor = 0
    for marker_start, marker_end in orphan_markers:
        if marker_start >= cutoff:
            break
        cleaned_parts.append(source[cursor:marker_start])
        cursor = marker_end
    cleaned_parts.append(source[cursor:cutoff])
    return "".join(cleaned_parts).strip()


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
    source = sanitize_reserved_control_blocks(text)
    match = re.search(_GOAL_UPDATE_BLOCK_PATTERN, source, re.IGNORECASE | re.DOTALL)
    if not match:
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


def strip_proactive_conversation_blocks(text: str) -> str:
    """화면에 노출되면 안 되는 선제 대화 예약 블록을 제거한다."""
    source = sanitize_reserved_control_blocks(text)
    cleaned = re.sub(_PROACTIVE_CONVERSATION_BLOCK_PATTERN, "", source, flags=re.IGNORECASE | re.DOTALL)
    return cleaned.strip()


def extract_tts_metadata(text: str) -> tuple[str, str]:
    """응답 본문에서 명시적인 TTS 블록을 분리한다."""
    source = str(text or "")
    match = re.search(_TTS_BLOCK_PATTERN, source, re.IGNORECASE | re.DOTALL)
    if not match:
        return source, ""
    tts_text = match.group(1).strip()
    cleaned = re.sub(_TTS_BLOCK_PATTERN, "", source, flags=re.IGNORECASE | re.DOTALL).strip()
    return cleaned, tts_text


_VISIBLE_RESPONSE_ANALYSIS_KEYS = (
    "user_emotion",
    "user_intent",
    "interaction_effect",
    "bond_delta_hint",
    "stress_delta_hint",
    "energy_delta_hint",
    "valence_delta_hint",
    "confidence",
    "flags",
)


def sanitize_visible_response_text(text: str) -> str:
    """화면에 전달할 답변에서 숨김 추론과 레거시 제어 블록을 제거한다."""
    sanitized = strip_thinking_markers(text)
    sanitized = sanitize_reserved_control_blocks(sanitized)
    sanitized = re.sub(
        r"\[\s*analysis\s*\]\s*.*?\s*\[\s*/\s*analysis\s*\]\s*",
        "",
        sanitized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    sanitized, _ = extract_thought_metadata(sanitized)
    sanitized, goal_update = extract_goal_update_metadata(sanitized)
    sanitized = strip_proactive_conversation_blocks(sanitized)
    sanitized, _ = extract_tts_metadata(sanitized)
    if goal_update:
        sanitized = re.sub(r"\n{2,}", "\n", sanitized)

    key_pattern = "|".join(
        re.escape(key) for key in _VISIBLE_RESPONSE_ANALYSIS_KEYS
    )
    leading_meta_pattern = (
        rf"^\s*(?:(?:{key_pattern})\s*=\s*.*(?:\r?\n|$))+"
    )
    sanitized = re.sub(
        leading_meta_pattern,
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"^\s*\n+", "", sanitized)
    sanitized = re.sub(r"\[(\w+)\]", "", sanitized)
    return sanitized.strip()


def sanitize_visible_thought_text(text: str) -> str:
    """공개 생각 필드에서 think 영역과 레거시 thought wrapper를 정리한다."""
    sanitized = strip_thinking_markers(text)
    _, extracted = extract_thought_metadata(sanitized)
    if extracted:
        sanitized = extracted
    sanitized = re.sub(
        rf"\[/?\s*(?:{_THOUGHT_TAG_PATTERN})\s*\]",
        "",
        sanitized,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", sanitized).strip()


def sanitize_spoken_response_text(text: str) -> str:
    """TTS 필드의 예약 제어 블록만 제거하고 정상적인 평문은 보존한다."""
    sanitized = strip_thinking_markers(text)
    sanitized = sanitize_reserved_control_blocks(sanitized)
    cleaned, extracted = extract_tts_metadata(sanitized)
    if extracted:
        sanitized = extracted
    else:
        sanitized = cleaned
    sanitized = re.sub(
        r"\[\s*analysis\s*\]\s*.*?\s*\[\s*/\s*analysis\s*\]\s*",
        "",
        sanitized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    sanitized, _ = extract_thought_metadata(sanitized)
    sanitized, _ = extract_goal_update_metadata(sanitized)
    sanitized = strip_proactive_conversation_blocks(sanitized)
    return sanitized.strip()
