"""
운영체제의 마지막 마우스/키보드 입력 시간을 읽는 도우미.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes


class LASTINPUTINFO(ctypes.Structure):
    """Windows GetLastInputInfo 호출에 필요한 구조체."""

    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("dwTime", wintypes.DWORD),
    ]


def _elapsed_milliseconds_since_last_input(current_tick: int, last_input_tick: int) -> int:
    """Windows 32비트 tick wraparound를 고려해 경과 ms를 계산한다."""
    return (int(current_tick) - int(last_input_tick)) & 0xFFFF_FFFF


def get_system_idle_seconds() -> float | None:
    """마지막 마우스/키보드 입력 이후 흐른 시간을 초 단위로 반환한다."""
    if not sys.platform.startswith("win"):
        return None

    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None

        ctypes.windll.kernel32.GetTickCount.restype = wintypes.DWORD
        current_tick = ctypes.windll.kernel32.GetTickCount()
        elapsed_ms = _elapsed_milliseconds_since_last_input(current_tick, info.dwTime)
        return elapsed_ms / 1000.0
    except Exception:
        return None
