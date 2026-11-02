from contextlib import contextmanager

import pytest

from src.core.bridge_mixins import away


class _Overlay:
    def __init__(self, visible=True):
        self.visible = visible
        self.visibility_changes = []

    def isVisible(self):
        return self.visible

    def winId(self):
        return 123

    def hide(self):
        self.visible = False
        self.visibility_changes.append(False)

    def show(self):
        self.visible = True
        self.visibility_changes.append(True)


class _CaptureBridge(away.AwayNudgeBridgeMixin):
    def __init__(self, overlay, capture):
        self.overlay = overlay
        self.capture = capture

    def parent(self):
        return self.overlay

    def _capture_full_desktop_image(self):
        return self.capture()

    def _qimage_to_data_url(self, _image):
        return "data:image/png;base64,synthetic"


@pytest.mark.parametrize("supported", [True, False])
@pytest.mark.parametrize("capture_result", ["success", "empty", "error"])
def test_capture_keeps_overlay_visible_when_supported_and_restores_state(monkeypatch, supported, capture_result):
    overlay = _Overlay()
    exclusion = {"active": False, "restored": False}

    @contextmanager
    def exclude(window_id):
        assert window_id == 123
        exclusion["active"] = supported
        try:
            yield supported
        finally:
            exclusion["active"] = False
            exclusion["restored"] = True

    def capture():
        assert overlay.visible is supported
        assert exclusion["active"] is supported
        if capture_result == "error":
            raise RuntimeError("합성 캡처 실패")
        return None if capture_result == "empty" else object()

    monkeypatch.setattr(away, "exclude_window_from_capture", exclude)
    bridge = _CaptureBridge(overlay, capture)

    if capture_result == "error":
        with pytest.raises(RuntimeError, match="합성 캡처 실패"):
            bridge._capture_full_desktop_without_overlay()
    else:
        result = bridge._capture_full_desktop_without_overlay()
        assert (result is None) is (capture_result == "empty")

    assert overlay.visible
    assert overlay.visibility_changes == ([] if supported else [False, True])
    assert exclusion == {"active": False, "restored": True}


@pytest.mark.parametrize("overlay", [None, _Overlay(visible=False)])
def test_capture_does_not_show_previously_hidden_overlay(monkeypatch, overlay):
    @contextmanager
    def exclude(window_id):
        assert window_id is None
        yield False

    monkeypatch.setattr(away, "exclude_window_from_capture", exclude)
    bridge = _CaptureBridge(overlay, object)

    assert bridge._capture_full_desktop_without_overlay() is not None
    if overlay is not None:
        assert not overlay.visible
        assert overlay.visibility_changes == []
