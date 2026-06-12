import json

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtWidgets import QApplication

if QApplication.instance() is None:
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)

from src.core.overlay_window import OverlayWindow
from src.ui.live2d_parameter_window import Live2DParameterWindow


_QAPP = None


def _get_qapp():
    global _QAPP
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    _QAPP = app
    return app


class _FakeOverlay:
    def frameGeometry(self):
        return QRect(1400, 120, 500, 650)


def test_live2d_parameter_window_is_independent_top_level_window():
    _get_qapp()

    window = Live2DParameterWindow(_FakeOverlay())

    assert window.parent() is None
    assert window.isWindow()
    assert window.windowFlags() & Qt.WindowType.Window
    assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert window.windowFlags() & Qt.WindowType.Tool

    window.deleteLater()


def test_live2d_parameter_window_initial_position_stays_inside_screen():
    position = Live2DParameterWindow.resolve_initial_position(
        overlay_geometry=QRect(1700, 900, 300, 250),
        screen_geometry=QRect(0, 0, 1920, 1080),
        window_size=QSize(520, 680),
    )

    assert position == QPoint(1164, 383)


def test_live2d_parameter_window_batch_resets_visible_items_once():
    _get_qapp()
    calls = []

    class _FakePage:
        def runJavaScript(self, script, callback=None):
            calls.append((script, callback))

    class _FakeWebView:
        def page(self):
            return _FakePage()

    class _Overlay(_FakeOverlay):
        web_view = _FakeWebView()

    window = Live2DParameterWindow(_Overlay())
    window._items = [
        {"id": "ParamRibbon", "recommended": True},
        {"id": "ParamHat", "recommended": True},
        {"id": "ParamMouthOpenY", "recommended": False},
    ]

    window._reset_visible_items()

    assert len(calls) == 1
    script, callback = calls[0]
    assert "window.resetLive2DParameterInspectorValues" in script
    assert json.loads(script.split("(", 1)[1].rsplit(")", 1)[0]) == ["ParamRibbon", "ParamHat"]
    assert callback is not None

    window.deleteLater()


def test_overlay_shutdown_disposes_live2d_parameter_window():
    class _FakeSignal:
        def disconnect(self, _handler):
            pass

    class _FakePage:
        def setWebChannel(self, _channel):
            pass

    class _FakeWebView:
        loadFinished = _FakeSignal()

        def page(self):
            return _FakePage()

        def stop(self):
            pass

        def setHtml(self, *_args):
            pass

    class _FakeTimer:
        def isActive(self):
            return False

    class _FakeParameterWindow:
        def __init__(self):
            self.hidden = False
            self.deleted = False

        def hide(self):
            self.hidden = True

        def deleteLater(self):
            self.deleted = True

    overlay = OverlayWindow.__new__(OverlayWindow)
    overlay._shutting_down = False
    overlay._page_loaded = True
    overlay._last_sent_mouse_pos = (1, 1)
    overlay.mouse_tracking_timer = _FakeTimer()
    overlay.web_view = _FakeWebView()
    parameter_window = _FakeParameterWindow()
    overlay._live2d_parameter_window = parameter_window

    OverlayWindow.shutdown(overlay)

    assert parameter_window.hidden is True
    assert parameter_window.deleted is True
    assert overlay._live2d_parameter_window is None
