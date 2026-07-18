"""
LLM 최종 응답 파싱 유틸리티.
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List

from .analysis_prompt import is_conversation_promise_enabled, is_schedule_recognition_enabled
from .prompt_language import resolve_prompt_language, resolve_tts_language
from .response_envelope import (
    LLM_RESPONSE_TUPLE,
    build_response_requirements,
    normalize_response_tuple,
)
from .response_cleanup import (
    extract_goal_update_metadata,
    extract_thought_metadata,
    extract_tts_metadata,
    sanitize_reserved_control_blocks,
    strip_proactive_conversation_blocks,
    strip_thinking_markers,
)


ANALYSIS_KEYS = {
    "user_emotion",
    "user_intent",
    "interaction_effect",
    "bond_delta_hint",
    "stress_delta_hint",
    "energy_delta_hint",
    "valence_delta_hint",
    "confidence",
    "flags",
}

AVAILABLE_GESTURES = {
    "nod",
    "bow",
    "shake",
    "surprise",
    "tilt",
    "sway",
}


PROACTIVE_CONVERSATION_KEYS = {
    "trigger_at",
    "title",
    "generation_prompt",
    "source_excerpt",
    "reason",
    "cooldown_key",
}
REQUIRED_PROACTIVE_CONVERSATION_KEYS = {"trigger_at", "title", "generation_prompt"}


def parse_analysis_lines(raw_block: str) -> Dict[str, str]:
    """analysis 메타 블록의 key=value 줄을 안전하게 파싱한다."""
    analysis: Dict[str, str] = {}
    for raw_line in raw_block.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in ANALYSIS_KEYS and value:
            analysis[key] = value
    return analysis


def extract_analysis_block(response_text: str) -> tuple[str, Dict[str, str]]:
    """응답의 analysis 블록 또는 상단 메타 줄을 분리해 구조화된 딕셔너리로 반환한다."""
    pattern = r"\[\s*analysis\s*\]\s*(.*?)\s*\[\s*/\s*analysis\s*\]"
    match = re.search(pattern, response_text, re.IGNORECASE | re.DOTALL)
    if match:
        analysis = parse_analysis_lines(match.group(1))
        cleaned = re.sub(pattern, "", response_text, flags=re.IGNORECASE | re.DOTALL).strip()
        return cleaned, analysis

    lines = response_text.splitlines()
    prefix_lines = []
    consumed = 0
    seen_analysis_key = False
    started = False

    for index, raw_line in enumerate(lines):
        stripped = raw_line.strip()

        if not started and not stripped:
            consumed = index + 1
            continue

        if not stripped:
            if started and prefix_lines:
                consumed = index + 1
                break
            consumed = index + 1
            continue

        if "=" not in stripped:
            break

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key not in ANALYSIS_KEYS or not value:
            break

        started = True
        seen_analysis_key = True
        prefix_lines.append(f"{key}={value}")
        consumed = index + 1

    if not seen_analysis_key:
        return response_text, {}

    analysis = parse_analysis_lines("\n".join(prefix_lines))
    cleaned = "\n".join(lines[consumed:]).strip()
    return cleaned, analysis


def parse_proactive_conversation_lines(raw_block: str) -> Dict[str, str]:
    """선제 대화 예약 블록의 key=value 줄을 파싱한다."""
    payload: Dict[str, str] = {}
    for raw_line in raw_block.splitlines():
        line = raw_line.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key in PROACTIVE_CONVERSATION_KEYS and value:
            payload[key] = value
    if not REQUIRED_PROACTIVE_CONVERSATION_KEYS.issubset(payload):
        return {}
    return payload


def extract_proactive_conversation_blocks(response_text: str) -> tuple[str, List[Dict[str, str]]]:
    """응답에서 선제 대화 예약 블록을 제거하고 구조화된 예약 후보를 반환한다."""
    pattern = r"\[\s*proactive_conversation\s*\]\s*(.*?)\s*\[\s*/\s*proactive_conversation\s*\]"
    proactive_conversations: List[Dict[str, str]] = []
    for match in re.finditer(pattern, response_text, re.IGNORECASE | re.DOTALL):
        parsed = parse_proactive_conversation_lines(match.group(1))
        if parsed:
            proactive_conversations.append(parsed)
    cleaned = strip_proactive_conversation_blocks(response_text)
    return cleaned, proactive_conversations


def is_japanese(text: str) -> bool:
    """텍스트가 일본어 문자를 충분히 포함하는지 확인한다."""
    japanese_ranges = [
        (0x3040, 0x309F),
        (0x30A0, 0x30FF),
        (0x4E00, 0x9FFF),
    ]

    japanese_chars = 0
    for char in text:
        code = ord(char)
        for start, end in japanese_ranges:
            if start <= code <= end:
                japanese_chars += 1
                break

    return japanese_chars / len(text) > 0.2 if text else False


def extract_legacy_japanese_tts_lines(text: str) -> tuple[str, str | None]:
    """구형 일본어 TTS 줄을 표시 텍스트와 분리한다."""
    visible_lines = []
    japanese_lines = []

    for raw_line in text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            visible_lines.append("")
            continue

        if is_japanese(stripped):
            japanese_lines.append(stripped)
            continue

        visible_lines.append(raw_line.rstrip())

    clean_text = "\n".join(visible_lines).strip()
    tts_text = "\n".join(japanese_lines).strip() if japanese_lines else None
    return clean_text, tts_text


def extract_tts_text(text: str, settings_source: object | None = None) -> tuple[str, str | None]:
    """명시적 TTS 블록 또는 설정 언어에 따라 TTS용 텍스트를 분리한다."""
    clean_text, tts_text = extract_tts_metadata(text)
    if tts_text:
        return clean_text, tts_text

    response_language = resolve_prompt_language(settings_source=settings_source)
    tts_language = resolve_tts_language(
        settings_source=settings_source,
        response_language=response_language,
    )
    if tts_language == response_language:
        normalized = clean_text.strip()
        return normalized, normalized or None
    if tts_language == "ja":
        return extract_legacy_japanese_tts_lines(clean_text)
    return clean_text.strip(), None


def extract_gesture_metadata(response_text: str) -> tuple[str, str]:
    """표시 텍스트에서 선택적 제스처 태그를 제거하고 허용된 제스처만 반환한다."""
    pattern = r"\[\s*gesture\s*:\s*([A-Za-z0-9_-]+)\s*\]"
    gesture = ""
    for match in re.finditer(pattern, response_text, re.IGNORECASE):
        candidate = match.group(1).strip().lower().replace("_", "-")
        if candidate in AVAILABLE_GESTURES and not gesture:
            gesture = candidate
    cleaned = re.sub(pattern, "", response_text, flags=re.IGNORECASE).strip()
    return cleaned, gesture


def parse_llm_response(
    response_text: str,
    *,
    settings_source: object | None = None,
    available_emotions: list[str] | set[str] | tuple[str, ...] | None = None,
    log_event: Callable[[str], None] | None = None,
) -> LLM_RESPONSE_TUPLE:
    """최종 응답 텍스트에서 표시 텍스트, 감정, 메타데이터를 분리한다."""
    response_text = strip_thinking_markers(response_text)
    response_text = sanitize_reserved_control_blocks(response_text)
    response_text, analysis = extract_analysis_block(response_text)
    response_text, goal_update = extract_goal_update_metadata(response_text)
    response_text, thought = extract_thought_metadata(response_text)
    response_text, proactive_conversations = extract_proactive_conversation_blocks(response_text)

    schedule_enabled = is_schedule_recognition_enabled(settings_source)
    events = []
    event_pattern = r"\[(?:event|이벤트):([^\]]+)\]"
    event_matches = re.findall(event_pattern, response_text)
    for match in event_matches:
        parts = [p.strip() for p in match.split("|")]
        if schedule_enabled and len(parts) >= 2:
            events.append(
                {
                    "date": parts[0],
                    "title": parts[1],
                    "description": parts[2] if len(parts) > 2 else "",
                }
            )
            if log_event:
                description = parts[2] if len(parts) > 2 else ""
                log_event(f"[LLM] schedule event extracted: {parts[0]} | {parts[1]} | {description}")
    response_text = re.sub(event_pattern, "", response_text)

    promises_enabled = is_conversation_promise_enabled(settings_source)
    promises = []
    promise_pattern = r"\[약속:([^\]]+)\]"
    promise_matches = re.findall(promise_pattern, response_text)
    for match in promise_matches:
        parts = [p.strip() for p in match.split("|")]
        if promises_enabled and len(parts) >= 2:
            promises.append(
                {
                    "trigger_at": parts[0],
                    "title": parts[1],
                    "source": parts[2] if len(parts) > 2 else "user",
                    "source_excerpt": parts[3] if len(parts) > 3 else "",
                }
            )
    response_text = re.sub(promise_pattern, "", response_text)

    response_text, explicit_tts_text = extract_tts_metadata(response_text)
    response_text, gesture = extract_gesture_metadata(response_text)

    emotion_pattern = r"\[(\w+)\]"
    matches = re.findall(emotion_pattern, response_text)
    clean_text = re.sub(emotion_pattern, "", response_text).strip()

    emotion = "normal"
    normalized_emotions = {str(item).lower() for item in (available_emotions or [])}
    for match in matches:
        low = match.lower()
        if low in normalized_emotions:
            emotion = low
            break

    if explicit_tts_text:
        tts_text = explicit_tts_text
    else:
        clean_text, tts_text = extract_tts_text(clean_text, settings_source=settings_source)

    requirements = build_response_requirements(
        settings_source,
        available_emotions=available_emotions or ("normal",),
    )
    return normalize_response_tuple(
        (
            clean_text,
            emotion,
            tts_text,
            events,
            analysis,
            promises,
            thought,
            goal_update,
            proactive_conversations,
            gesture,
        ),
        requirements=requirements,
        preserve_none_goal=True,
    )
