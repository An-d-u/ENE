"""창을 화면에 표시한 채 Windows 캡처에서 잠시 제외하는 도우미."""
import ctypes
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes


_LOGGER = logging.getLogger(__name__)
_WDA_EXCLUDEFROMCAPTURE = 0x11


@contextmanager
def exclude_window_from_capture(window_id: int | None) -> Iterator[bool]:
    """캡처 제외 가능 여부를 전달하고 종료 시 기존 표시 정책을 복원한다."""
    if not window_id or sys.platform != "win32":
        yield False
        return

    excluded = False
    restore_state = None
    try:
        # 이전 Windows에서는 같은 값이 검은 사각형으로 캡처되므로 사용하지 않는다.
        if sys.getwindowsversion().build >= 19041:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
            get_affinity = user32.GetWindowDisplayAffinity
            get_affinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            get_affinity.restype = wintypes.BOOL
            set_affinity = user32.SetWindowDisplayAffinity
            set_affinity.argtypes = [wintypes.HWND, wintypes.DWORD]
            set_affinity.restype = wintypes.BOOL
            flush = dwmapi.DwmFlush
            flush.argtypes = []
            flush.restype = ctypes.c_long

            previous_affinity = wintypes.DWORD()
            if get_affinity(window_id, ctypes.byref(previous_affinity)):
                if set_affinity(window_id, _WDA_EXCLUDEFROMCAPTURE):
                    restore_state = (set_affinity, flush, previous_affinity.value)
                    # 다음 화면 합성까지 기다려 첫 캡처에도 제외 설정을 반영한다.
                    excluded = flush() == 0
    except (AttributeError, OSError):
        pass

    try:
        yield excluded
    finally:
        if restore_state is not None:
            set_affinity, flush, previous_affinity = restore_state
            try:
                if not set_affinity(window_id, previous_affinity):
                    _LOGGER.warning("캡처 제외 설정을 복원하지 못했습니다.")
                elif flush() != 0:
                    _LOGGER.warning("캡처 제외 설정 복원 후 화면 합성을 기다리지 못했습니다.")
            except (AttributeError, OSError):
                _LOGGER.warning("캡처 제외 설정을 복원하지 못했습니다.")
