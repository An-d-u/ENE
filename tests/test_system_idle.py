from types import SimpleNamespace

from src.core import system_idle
from src.core.system_idle import _elapsed_milliseconds_since_last_input


def test_elapsed_milliseconds_handles_normal_tick_values():
    assert _elapsed_milliseconds_since_last_input(10_000, 7_500) == 2_500


def test_elapsed_milliseconds_handles_32_bit_tick_wraparound():
    assert _elapsed_milliseconds_since_last_input(250, 0xFFFF_FF00) == 506


def test_get_system_idle_seconds_returns_none_outside_windows(monkeypatch):
    monkeypatch.setattr(system_idle.sys, "platform", "linux")

    assert system_idle.get_system_idle_seconds() is None


def test_get_system_idle_seconds_returns_none_when_windows_api_fails(monkeypatch):
    class _FailingUser32:
        def GetLastInputInfo(self, _info):
            return False

    fake_windll = SimpleNamespace(
        user32=_FailingUser32(),
        kernel32=SimpleNamespace(GetTickCount=lambda: 0),
    )
    monkeypatch.setattr(system_idle.sys, "platform", "win32")
    monkeypatch.setattr(system_idle.ctypes, "windll", fake_windll, raising=False)

    assert system_idle.get_system_idle_seconds() is None
