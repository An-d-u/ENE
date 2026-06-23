"""
사용자 채팅 입력의 슬래시 명령을 파싱한다.
"""

from __future__ import annotations

import re


_DIARY_COMMAND_PATTERN = re.compile(r"^/diary(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_OBS_COMMAND_PATTERN = re.compile(r"^/obs(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)
_NOTE_COMMAND_PATTERN = re.compile(r"^/note(?:\s+(.*))?$", re.IGNORECASE | re.DOTALL)


def parse_diary_command(message: str) -> tuple[bool, str]:
    """/diary 명령 여부와 본문을 반환한다."""
    return _parse_command(message, _DIARY_COMMAND_PATTERN)


def parse_obs_command(message: str) -> tuple[bool, str]:
    """/obs 명령 여부와 본문을 반환한다."""
    return _parse_command(message, _OBS_COMMAND_PATTERN)


def parse_note_command(message: str) -> tuple[bool, str]:
    """/note 명령 여부와 본문을 반환한다."""
    return _parse_command(message, _NOTE_COMMAND_PATTERN)


def _parse_command(message: str, pattern: re.Pattern[str]) -> tuple[bool, str]:
    text = (message or "").strip()
    match = pattern.match(text)
    if not match:
        return False, ""
    body = (match.group(1) or "").strip()
    return True, body
