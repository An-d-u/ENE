import json

from PyQt6.QtCore import QEventLoop, QPoint, QRect, QSize, Qt, QTimer
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


def _wait_for_qt_timer(milliseconds=50):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


class _FakeOverlay:
    def frameGeometry(self):
        return QRect(1400, 120, 500, 650)


def test_live2d_parameter_window_is_independent_top_level_window():
    _get_qapp()

    window = Live2DParameterWindow(_FakeOverlay())

    assert window.parent() is None
    assert window.isWindow()
    assert window.windowFlags() & Qt.WindowType.Window
    assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
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


def test_live2d_parameter_window_uses_ene_style_header_bar():
    _get_qapp()

    window = Live2DParameterWindow(_FakeOverlay())

    assert window.objectName() == "live2dParameterWindow"
    assert window.header.objectName() == "parameterHeader"
    assert window.title_label.parent() is window.header
    assert window.refresh_button.parent() is window.header
    assert window.header_close_button.parent() is window.header
    assert window.refresh_button.property("headerAction") is True
    assert window.header_close_button.property("headerClose") is True
    assert "QFrame#parameterHeader" in window.styleSheet()
    assert "rgba(0, 0, 0, 0.64)" in window.styleSheet()

    window.deleteLater()


def test_live2d_parameter_window_uses_all_and_favorites_filters():
    _get_qapp()

    window = Live2DParameterWindow(_FakeOverlay())

    filters = [
        (window.filter_combo.itemText(index), window.filter_combo.itemData(index))
        for index in range(window.filter_combo.count())
    ]

    assert filters == [("전체", "all"), ("즐겨찾기", "favorites")]
    assert window.show_all_parameters_checkbox.text() == "세부 파라미터 표시"

    window.deleteLater()


def test_live2d_parameter_window_header_drags_frameless_window():
    _get_qapp()

    class _PointWrapper:
        def __init__(self, point):
            self._point = point

        def toPoint(self):
            return self._point

    class _FakeMouseEvent:
        def __init__(self, *, button, buttons, position, global_position):
            self._button = button
            self._buttons = buttons
            self._position = _PointWrapper(position)
            self._global_position = _PointWrapper(global_position)
            self.accepted = False

        def button(self):
            return self._button

        def buttons(self):
            return self._buttons

        def position(self):
            return self._position

        def globalPosition(self):
            return self._global_position

        def accept(self):
            self.accepted = True

    window = Live2DParameterWindow(_FakeOverlay())
    window.move(100, 120)

    press_event = _FakeMouseEvent(
        button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.LeftButton,
        position=QPoint(20, 12),
        global_position=QPoint(130, 150),
    )
    window.mousePressEvent(press_event)
    move_event = _FakeMouseEvent(
        button=Qt.MouseButton.NoButton,
        buttons=Qt.MouseButton.LeftButton,
        position=QPoint(60, 12),
        global_position=QPoint(190, 150),
    )
    window.mouseMoveEvent(move_event)
    release_event = _FakeMouseEvent(
        button=Qt.MouseButton.LeftButton,
        buttons=Qt.MouseButton.NoButton,
        position=QPoint(60, 12),
        global_position=QPoint(190, 150),
    )
    window.mouseReleaseEvent(release_event)

    assert press_event.accepted is True
    assert move_event.accepted is True
    assert release_event.accepted is True
    assert window.pos() == QPoint(160, 120)

    window.deleteLater()


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


def test_live2d_parameter_window_coalesces_repeated_value_updates():
    _get_qapp()
    calls = []

    class _FakePage:
        def runJavaScript(self, script, callback=None):
            calls.append(script)

    class _FakeWebView:
        def page(self):
            return _FakePage()

    class _Overlay(_FakeOverlay):
        web_view = _FakeWebView()

    window = Live2DParameterWindow(_Overlay())

    window._queue_parameter_value("ParamRibbon", 0.1)
    window._queue_parameter_value("ParamRibbon", 0.2)
    _wait_for_qt_timer()

    assert len(calls) == 1
    assert "ParamRibbon" in calls[0]
    assert "0.2" in calls[0]
    assert "0.1" not in calls[0]

    window.deleteLater()


def test_live2d_parameter_window_show_all_toggle_controls_detailed_parameters():
    _get_qapp()

    window = Live2DParameterWindow(_FakeOverlay())
    window._items = [
        {
            "id": "ParamRibbon",
            "displayName": "리본",
            "groupName": "장식",
            "recommended": True,
        },
        {
            "id": "ParamEyeLOpen",
            "displayName": "왼쪽 눈 뜨기",
            "groupName": "눈",
            "recommended": False,
        },
    ]

    assert [item["id"] for item in window._filtered_items()] == ["ParamRibbon"]

    window.show_all_parameters_checkbox.setChecked(True)

    assert [item["id"] for item in window._filtered_items()] == ["ParamRibbon", "ParamEyeLOpen"]

    window.search_input.setText("눈")

    assert [item["id"] for item in window._filtered_items()] == ["ParamEyeLOpen"]

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
