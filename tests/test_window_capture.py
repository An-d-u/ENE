import ctypes
from types import SimpleNamespace

import pytest

from src.core import window_capture


class _ApiFunction:
    def __init__(self, callback):
        self.callback = callback

    def __call__(self, *args):
        return self.callback(*args)


@pytest.fixture
def capture_api(monkeypatch):
    state = SimpleNamespace(
        affinity=0,
        calls=[],
        read_ok=True,
        exclude_ok=True,
        restore_ok=True,
        flush_result=0,
    )

    def get_affinity(window_id, result):
        state.calls.append(("get", window_id))
        result._obj.value = state.affinity
        return state.read_ok

    def set_affinity(window_id, affinity):
        state.calls.append(("set", window_id, affinity))
        succeeds = state.exclude_ok if affinity == 0x11 else state.restore_ok
        if succeeds:
            state.affinity = affinity
        return succeeds

    def flush():
        state.calls.append(("flush",))
        return state.flush_result

    user32 = SimpleNamespace(
        GetWindowDisplayAffinity=_ApiFunction(get_affinity),
        SetWindowDisplayAffinity=_ApiFunction(set_affinity),
    )
    dwmapi = SimpleNamespace(DwmFlush=_ApiFunction(flush))
    state.user32 = user32
    monkeypatch.setattr(window_capture.sys, "platform", "win32")
    monkeypatch.setattr(
        window_capture.sys, "getwindowsversion",
        lambda: SimpleNamespace(build=19041), raising=False,
    )
    monkeypatch.setattr(
        window_capture.ctypes, "WinDLL",
        lambda name, **_kwargs: {"user32": user32, "dwmapi": dwmapi}[name],
        raising=False,
    )
    return state


@pytest.mark.parametrize("previous_affinity", [0, 1, 0x11])
def test_exclusion_restores_original_affinity_even_when_capture_raises(capture_api, previous_affinity):
    capture_api.affinity = previous_affinity
    window_id = 0x1_0000_1234

    with pytest.raises(RuntimeError, match="합성 캡처 실패"):
        with window_capture.exclude_window_from_capture(window_id) as excluded:
            assert excluded
            assert capture_api.affinity == 0x11
            assert capture_api.calls[-1] == ("flush",)
            raise RuntimeError("합성 캡처 실패")

    assert capture_api.affinity == previous_affinity
    assert capture_api.calls[-2:] == [("set", window_id, previous_affinity), ("flush",)]
    assert capture_api.user32.SetWindowDisplayAffinity.argtypes[0] is ctypes.wintypes.HWND


@pytest.mark.parametrize("failure", ["read_ok", "exclude_ok", "flush_result"])
def test_exclusion_reports_failure_and_restores_any_change(capture_api, failure):
    setattr(capture_api, failure, -1 if failure == "flush_result" else False)

    with window_capture.exclude_window_from_capture(123) as excluded:
        assert not excluded

    assert capture_api.affinity == 0


@pytest.mark.parametrize("platform,build,window_id", [("linux", 19041, 123), ("win32", 18363, 123), ("win32", 19041, None)])
def test_unsupported_environment_does_not_change_affinity(monkeypatch, capture_api, platform, build, window_id):
    monkeypatch.setattr(window_capture.sys, "platform", platform)
    monkeypatch.setattr(window_capture.sys, "getwindowsversion", lambda: SimpleNamespace(build=build))

    with window_capture.exclude_window_from_capture(window_id) as excluded:
        assert not excluded

    assert capture_api.calls == []


def test_api_loading_failure_allows_fallback(monkeypatch, capture_api):
    def fail_loading(*_args, **_kwargs):
        raise OSError("합성 API 로드 실패")

    monkeypatch.setattr(window_capture.ctypes, "WinDLL", fail_loading)

    with window_capture.exclude_window_from_capture(123) as excluded:
        assert not excluded


def test_restore_failure_is_logged_without_masking_capture_error(capture_api, caplog):
    capture_api.restore_ok = False

    with pytest.raises(RuntimeError, match="합성 캡처 실패"):
        with window_capture.exclude_window_from_capture(123) as excluded:
            assert excluded
            raise RuntimeError("합성 캡처 실패")

    assert "캡처 제외 설정을 복원하지 못했습니다" in caplog.text
