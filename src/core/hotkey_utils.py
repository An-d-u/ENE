"""
전역 단축키 문자열 정규화/표시 유틸리티.
"""

from __future__ import annotations

from typing import Iterable


MODIFIER_ORDER = ("ctrl", "shift", "alt", "meta")
MODIFIER_TOKENS = set(MODIFIER_ORDER)

TOKEN_ALIASES = {
    "control": "ctrl",
    "ctl": "ctrl",
    "option": "alt",
    "win": "meta",
    "windows": "meta",
    "cmd": "meta",
    "command": "meta",
    "super": "meta",
    "return": "enter",
    "escape": "esc",
    "arrowup": "up",
    "arrowdown": "down",
    "arrowleft": "left",
    "arrowright": "right",
    "pagedown": "page_down",
    "pageup": "page_up",
    "pgdn": "page_down",
    "pgup": "page_up",
    "del": "delete",
    "ins": "insert",
}

DISPLAY_LABELS = {
    "ctrl": "Ctrl",
    "shift": "Shift",
    "alt": "Alt",
    "meta": "Win",
    "enter": "Enter",
    "esc": "Esc",
    "space": "Space",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "insert": "Insert",
    "home": "Home",
    "end": "End",
    "page_up": "PageUp",
    "page_down": "PageDown",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "plus": "+",
    "minus": "-",
    "comma": ",",
    "period": ".",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "quote": "'",
    "backquote": "`",
    "left_bracket": "[",
    "right_bracket": "]",
}


def _normalize_token(token: str) -> str:
    raw = str(token or "").strip().lower()
    if not raw:
        return ""
    if raw == "+":
        return "plus"
    if raw == "-":
        return "minus"
    if raw == ",":
        return "comma"
    if raw == ".":
        return "period"
    if raw == "/":
        return "slash"
    if raw == "\\":
        return "backslash"
    if raw == ";":
        return "semicolon"
    if raw == "'":
        return "quote"
    if raw == "`":
        return "backquote"
    if raw == "[":
        return "left_bracket"
    if raw == "]":
        return "right_bracket"
    return TOKEN_ALIASES.get(raw, raw)


def split_hotkey_tokens(hotkey_text: str) -> list[str]:
    """
    단축키 문자열을 토큰 배열로 분해한다.
    """
    tokens: list[str] = []
    for chunk in str(hotkey_text or "").split("+"):
        token = _normalize_token(chunk)
        if token:
            tokens.append(token)
    return tokens


def _dedupe_keep_order(tokens: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def normalize_hotkey_text(hotkey_text: str, default: str = "alt") -> str:
    """
    단축키 문자열을 canonical 형태로 정규화한다.
    예: "Shift + Ctrl + A" -> "ctrl+shift+a"
    """
    tokens = split_hotkey_tokens(hotkey_text)
    if not tokens:
        tokens = split_hotkey_tokens(default)
    if not tokens:
        tokens = ["alt"]

    modifiers: list[str] = []
    normal_keys: list[str] = []
    for token in tokens:
        if token in MODIFIER_TOKENS:
            modifiers.append(token)
        else:
            normal_keys.append(token)

    modifiers = _dedupe_keep_order(modifiers)
    normal_keys = _dedupe_keep_order(normal_keys)

    if normal_keys:
        key = normal_keys[-1]
    elif modifiers:
        key = modifiers[-1]
        modifiers = modifiers[:-1]
    else:
        key = "alt"

    ordered_modifiers = [mod for mod in MODIFIER_ORDER if mod in modifiers and mod != key]
    parts = [*ordered_modifiers]
    if key not in parts:
        parts.append(key)
    return "+".join(parts)


def hotkey_to_spec(hotkey_text: str, default: str = "alt") -> tuple[set[str], str]:
    """
    단축키 문자열을 (필수 modifier 집합, trigger 키)로 변환한다.
    """
    normalized = normalize_hotkey_text(hotkey_text, default=default)
    tokens = split_hotkey_tokens(normalized)
    if not tokens:
        return set(), "alt"
    trigger_key = tokens[-1]
    required_modifiers = {token for token in tokens[:-1] if token in MODIFIER_TOKENS and token != trigger_key}
    return required_modifiers, trigger_key


def hotkey_to_display(hotkey_text: str, default: str = "alt") -> str:
    """
    UI 표시용 문자열로 변환한다.
    """
    normalized = normalize_hotkey_text(hotkey_text, default=default)
    tokens = split_hotkey_tokens(normalized)
    labels: list[str] = []
    for token in tokens:
        if token in DISPLAY_LABELS:
            labels.append(DISPLAY_LABELS[token])
        elif len(token) == 1:
            labels.append(token.upper())
        elif token.startswith("f") and token[1:].isdigit():
            labels.append(token.upper())
        else:
            labels.append(token.capitalize())
    return "+".join(labels)
