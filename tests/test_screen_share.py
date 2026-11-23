import os
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage


@pytest.fixture
def capture(monkeypatch):
    from src.core import screen_share as mod

    class Windows:
        state = "ready"
        starts = 0
        stops = 0

        def status(self, target):
            return self.state

        def targets(self):
            return [first, second]

    class Events:
        def __init__(self, api, invalidate):
            self.invalidate = invalidate

        def close(self):
            pass

        def watch(self, target, minimized):
            self.selected = target
            self.minimized = minimized

    class Stream:
        def __init__(self, target, failed):
            self.hwnd = target.hwnd
            self.failed = failed
            api.starts += 1

        def image(self):
            image = QImage(3200, 1600, QImage.Format.Format_RGB32)
            image.fill(QColor("green"))
            return image

        def close(self):
            api.stops += 1

    first = mod._Target(3, 11, 17, "합성 창")
    second = mod._Target(9, 11, 17, "합성 창")
    api = Windows()
    monkeypatch.setattr(mod, "_Windows", lambda: api)
    monkeypatch.setattr(mod, "_SessionEvents", Events)
    monkeypatch.setattr(mod, "_WindowStream", Stream)
    monkeypatch.setattr(mod, "_pick", lambda parent, targets: targets[1])
    share = mod.ScreenShare()
    yield share, api, second
    share.stop()


def test_selection_preserves_identity_and_waits_for_mode(capture):
    share, api, selected = capture
    assert share.choose(None)
    assert share.title == selected.title
    assert share.snapshot() is None and not share.can_send(share.generation)
    assert api.starts == 0
    share.set_modes(True, False)
    assert share._stream.hwnd == selected.hwnd
    frame = share.snapshot()
    assert 0 < frame.width() <= 1280 and frame.height() == frame.width() // 2
    frame.fill(Qt.GlobalColor.red)
    assert share.snapshot().pixelColor(0, 0) == QColor("green")


def test_modes_have_independent_epochs_and_stop_releases_resources(capture):
    share, api, _ = capture
    share.choose(None)
    share.set_modes(True, True)
    gen, q_epoch, o_epoch = share.generation, share.question_epoch, share.observe_epoch
    share.set_modes(False, True)
    assert share.generation == gen and not share.question and share.observe
    assert share.question_epoch != q_epoch and share.observe_epoch == o_epoch
    assert api.starts == 1 and not api.stops
    share.set_modes(False, False)
    assert api.stops == 1 and not share.title and not share.can_send(gen)
    assert share.observe_epoch != o_epoch and not share.observe


@pytest.mark.parametrize("state", ["locked", "closed", "minimized"])
def test_worker_guard_and_snapshot_reject_stale_window_immediately(capture, state):
    share, api, _ = capture
    share.choose(None)
    share.set_modes(True, True)
    gen = share.generation
    assert share.can_send(gen)
    api.state = state
    with ThreadPoolExecutor(max_workers=1) as pool:
        assert not pool.submit(share.can_send, gen).result()
    assert share.snapshot() is None
    assert share.generation != gen and api.stops == 1
    if state == "minimized":
        api.state = "ready"
        assert share.validate() and api.starts == 2
    else:
        assert not share.title and not share.observe and not share.question


def test_late_capture_error_cannot_cancel_new_session(capture):
    share, api, _ = capture
    share.choose(None)
    share.set_modes(True, False)
    old = share._stream
    old_generation = share.generation
    share.stop()
    share.choose(None)
    share.set_modes(True, False)
    old.failed()
    assert share.question and not share.can_send(old_generation)
    share._events.invalidate()
    assert not share.title and not share.question


def test_cancel_and_no_selection_never_activate_capture(capture, monkeypatch):
    from src.core import screen_share as mod

    share, api, _ = capture
    monkeypatch.setattr(mod, "_pick", lambda *_: None)
    assert not share.choose(None)
    share.set_modes(True, True)
    assert not share.question and not share.observe and not api.starts


def test_brief_minimize_between_polls_expires_the_previous_frame(capture):
    share, api, selected = capture
    share.choose(None)
    share.set_modes(False, True)
    epoch = share.generation
    assert share._events.selected == selected
    share._events.minimized()
    assert not share.can_send(epoch)
    assert share.validate() and api.starts == 2
    assert not share.can_send(epoch)


def test_native_lock_and_suspend_notifications_invalidate_without_polling():
    import ctypes
    from ctypes import wintypes
    from types import SimpleNamespace
    from unittest.mock import Mock
    from src.core.screen_share import _SessionEvents

    events = SimpleNamespace(invalidate=Mock())
    for message, param in ((0x02B1, 7), (0x0218, 4)):
        native = wintypes.MSG()
        native.message, native.wParam = message, param
        assert _SessionEvents.nativeEvent(events, None, ctypes.addressof(native)) == (False, 0)
    assert events.invalidate.call_count == 2


def test_duplicate_titles_in_native_picker_select_the_second_identity():
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QListWidget
    from src.core.screen_share import _pick, _Target

    targets = [_Target(hwnd, 11, 17, "합성 창") for hwnd in (3, 9)]

    def accept_second():
        picker = QApplication.activeModalWidget()
        picker.findChild(QListWidget).setCurrentRow(1)
        picker.accept()

    QTimer.singleShot(0, accept_second)
    assert _pick(None, targets) is targets[1]


@pytest.fixture
def monitors():
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPixmap
    from src.core.screen_monitors import Monitor

    class Screen:
        def __init__(self, color, x):
            self.color = color
            self.calls = 0
            self.x = x

        def geometry(self):
            return QRect(self.x, 0, 800, 600)

        def grabWindow(self, window):
            assert window == 0
            self.calls += 1
            pixels = QPixmap(800, 600)
            pixels.fill(QColor(self.color))
            return pixels

    return tuple(Monitor(i, f"DISPLAY{i}", QRect(x, 0, 800, 600), Screen(color, x), f"모니터 {i}")
                 for i, x, color in [(1, -800, "red"), (2, 0, "green"), (3, 800, "blue")])


@pytest.mark.parametrize("rows", [(0,), (1,), (0, 1), (0, 2)])
def test_monitor_picker_requires_explicit_selection_and_captures_only_checked_displays(
        monitors, rows):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QTabWidget
    from src.core.screen_share import _pick, _Target

    enabled = []

    def select():
        picker = QApplication.activeModalWidget()
        tabs = picker.findChild(QTabWidget)
        listing = tabs.currentWidget()
        ok = picker.findChild(QDialogButtonBox).button(QDialogButtonBox.StandardButton.Ok)
        enabled.append(ok.isEnabled())
        for row in rows:
            listing.item(row).setCheckState(Qt.CheckState.Checked)
        enabled.append(ok.isEnabled())
        picker.accept()

    QTimer.singleShot(0, select)
    chosen = _pick(None, [*monitors, _Target(7, 8, 9, "합성 창")])
    assert enabled == [False, True]
    assert chosen.monitors == tuple(monitors[i] for i in rows)
    image = chosen.image()
    assert [m.screen.calls for m in monitors] == [int(i in rows) for i in range(3)]
    assert image.width() <= 1280
    assert image.pixelColor(0, 0) == QColor(monitors[rows[0]].screen.color)
    assert image.pixelColor(image.width() - 1, 0) == QColor(monitors[rows[-1]].screen.color)
    if rows == (0, 2):
        assert image.pixelColor(image.width() // 2, image.height() // 2) == QColor("black")


def test_window_tab_ignores_checked_monitors(monitors):
    from PyQt6.QtCore import QTimer
    from PyQt6.QtWidgets import QApplication, QTabWidget
    from src.core.screen_share import _pick, _Target

    def select_window():
        picker = QApplication.activeModalWidget()
        tabs = picker.findChild(QTabWidget)
        tabs.currentWidget().item(0).setCheckState(Qt.CheckState.Checked)
        tabs.setCurrentIndex(1)
        tabs.currentWidget().setCurrentRow(0)
        picker.accept()

    window = _Target(3, 11, 17, "합성 창")
    QTimer.singleShot(0, select_window)
    assert _pick(None, [*monitors, window]) is window
    assert all(m.screen.calls == 0 for m in monitors)


def test_failed_monitor_capture_discards_whole_image(monitors, monkeypatch):
    from PyQt6.QtGui import QPixmap
    from src.core.screen_monitors import MonitorSelection

    monkeypatch.setattr(monitors[1].screen, "grabWindow", lambda _: QPixmap())
    assert MonitorSelection(monitors[:2]).image() is None
    assert monitors[2].screen.calls == 0


def test_stale_qt_screen_origin_is_rejected_before_capture(monitors):
    from src.core.screen_monitors import MonitorSelection

    monitors[0].screen.x = monitors[1].rect.x()
    assert MonitorSelection(monitors[:1]).image() is None
    assert not monitors[0].screen.calls


def test_monitor_session_stops_on_disconnect_and_invalidates_pending_frames(capture, monitors, monkeypatch):
    from src.core import screen_share as mod
    from src.core.screen_monitors import MonitorSelection

    share, api, _ = capture
    chosen = MonitorSelection(monitors[:2])
    monkeypatch.setattr(mod, "_pick", lambda *_: chosen)
    monkeypatch.setattr(mod.QGuiApplication, "screens", lambda: [m.screen for m in monitors])
    assert share.choose(None)
    share.set_modes(True, True)
    assert share.snapshot() is not None
    assert api.starts == 0
    generation = share.generation
    share._screen_removed(monitors[2].screen)
    assert share.can_send(generation)
    share._screen_removed(monitors[0].screen)
    assert not share.can_send(generation)
    assert not share.question and not share.observe and share.snapshot() is None


def test_monitor_native_guard_rejects_changed_device_or_geometry(monitors):
    from types import SimpleNamespace
    from src.core.screen_monitors import MonitorSelection
    from src.core.screen_share import _Windows

    selected = MonitorSelection(monitors[:2])
    current = {m.handle: (m.device, m.rect) for m in monitors}
    api = SimpleNamespace(interactive=lambda: True,
                          monitors=SimpleNamespace(info=current.get))
    assert _Windows.status(api, selected) == "ready"
    current[monitors[1].handle] = ("다른 장치", monitors[1].rect)
    assert _Windows.status(api, selected) == "closed"
    current[monitors[1].handle] = (monitors[1].device, monitors[2].rect)
    assert _Windows.status(api, selected) == "closed"
    api.interactive = lambda: False
    assert _Windows.status(api, selected) == "locked"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용 창 캡처")
def test_only_windows_graphics_capture_frames_are_accepted():
    from PyQt6.QtMultimedia import QVideoFrame, QVideoFrameFormat
    from PyQt6.QtCore import QSize
    from src.core.screen_share import _window_image

    for pixel, allowed in [
        (QVideoFrameFormat.PixelFormat.Format_BGRX8888, False),
        (QVideoFrameFormat.PixelFormat.Format_RGBX8888, True),
    ]:
        frame = QVideoFrame(QVideoFrameFormat(QSize(8, 8), pixel))
        assert (_window_image(frame) is not None) == allowed


@pytest.mark.skipif(
    os.environ.get("ENE_TEST_NATIVE_WINDOW_CAPTURE") != "1" or sys.platform != "win32",
    reason="대화형 Windows 데스크톱에서 합성 창만 사용하도록 명시한 경우에 실행",
)
def test_native_covered_window_never_includes_foreground(monkeypatch):
    import ctypes
    from ctypes import wintypes
    import subprocess
    import time

    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QWidget
    from src.core import screen_share as mod

    # 별도 앱의 합성 창을 가린 뒤에도 서로 다른 두 색의 새 프레임을 받아야 한다.
    child_code = """
from PyQt6.QtCore import QEvent, Qt, QTimer
from PyQt6.QtWidgets import QApplication, QWidget
from itertools import cycle
import os
app = QApplication([])
class TestWindow(QWidget):
    def changeEvent(self, event):
        global colors
        if (event.type() == QEvent.Type.WindowStateChange
                and event.oldState() & Qt.WindowState.WindowMinimized and not self.isMinimized()):
            colors = cycle(['#ffff00'])
        super().changeEvent(event)
w = TestWindow(None, Qt.WindowType.FramelessWindowHint)
w.setWindowTitle('합성 창')
w.setGeometry(80, 80, 160, 120)
colors = cycle(['#00ff00', '#0000ff'])
def paint():
    w.setStyleSheet('background-color: ' + next(colors))
paint()
w.show()
timer = QTimer()
timer.timeout.connect(paint)
timer.start(350)
print(os.getpid(), int(w.winId()), flush=True)
QTimer.singleShot(20000, app.quit)
app.exec()
"""
    process = subprocess.Popen([sys.executable, "-c", child_code], stdout=subprocess.PIPE, text=True)
    cover = QWidget(None, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
    share = mod.ScreenShare()
    try:
        child_pid, hwnd = map(int, process.stdout.readline().split())
        pid = wintypes.DWORD()
        tid = share._api.owner(hwnd, ctypes.byref(pid))
        assert pid.value == child_pid
        # 실제 데스크톱의 다른 제목을 열거하지 않고 합성 창만 선택 목록에 주입한다.
        monkeypatch.setattr(share._api, "enum", lambda collect, _: collect(hwnd, 0))
        monkeypatch.setattr(mod, "_pick", lambda parent, targets: next(
            t for t in targets if isinstance(t, mod._Target) and t.hwnd == hwnd))
        assert share.choose(None)
        assert share._target.tid == tid and share.title == "합성 창"
        cover.setStyleSheet("background-color: #ff0000")
        cover.setGeometry(60, 60, 220, 180)
        cover.show()
        cover.raise_()
        QTest.qWait(400)
        user = ctypes.WinDLL("user32")
        foreground_at = user.WindowFromPoint
        foreground_at.argtypes, foreground_at.restype = [wintypes.POINT], wintypes.HWND
        rect = wintypes.RECT()
        assert user.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect))
        center = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
        assert foreground_at(center) == int(cover.winId())
        share.set_modes(True, True)
        colors = set()
        deadline = time.monotonic() + 6
        while len(colors) < 2 and time.monotonic() < deadline:
            QTest.qWait(60)
            image = share.snapshot()
            if image is not None:
                colors.add(image.pixelColor(image.width() // 2, image.height() // 2).name())
        assert colors == {"#00ff00", "#0000ff"}
        generation = share.generation
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(share.can_send, generation).result()
        user.ShowWindow(wintypes.HWND(hwnd), 6)
        assert not share.can_send(generation) and share.snapshot() is None
        assert share.generation != generation
        QTest.qWait(250)
        user.ShowWindow(wintypes.HWND(hwnd), 9)
        deadline = time.monotonic() + 5
        restored = False
        while time.monotonic() < deadline and not restored:
            QTest.qWait(60)
            image = share.snapshot()
            restored = image is not None and image.pixelColor(
                image.width() // 2, image.height() // 2
            ).name() == "#ffff00"
        assert restored and not share.can_send(generation)
        assert share.can_send(share.generation)
        user.PostMessageW(wintypes.HWND(hwnd), 0x0010, 0, 0)
        process.wait(timeout=5)
        assert share.snapshot() is None and not share.title
    finally:
        share.stop()
        cover.close()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.stdout.close()
