"""사용자가 고른 Windows 창 하나의 수명과 메모리 안의 프레임을 관리한다."""

from __future__ import annotations

import ctypes
from ctypes import wintypes as wt
from dataclasses import dataclass, field
import os
import sys

from PyQt6.QtCore import QObject, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QImage, QWindow
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QListWidget, QVBoxLayout, QWidget

from .i18n import tr


@dataclass(frozen=True)
class _Target:
    hwnd: int
    pid: int
    tid: int
    title: str = field(repr=False)


class _Windows:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("이 환경에서는 창을 공유할 수 없습니다.")
        user = ctypes.WinDLL("user32", use_last_error=True)
        dwm = ctypes.WinDLL("dwmapi", use_last_error=True)
        wts = ctypes.WinDLL("wtsapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.callback = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        ptr = ctypes.POINTER

        def bind(dll, name, result, *args):
            fn = getattr(dll, name)
            fn.argtypes, fn.restype = args, result
            return fn

        self.enum = bind(user, "EnumWindows", wt.BOOL, self.callback, wt.LPARAM)
        self.owner = bind(user, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ptr(wt.DWORD))
        self.visible = bind(user, "IsWindowVisible", wt.BOOL, wt.HWND)
        self.iconic = bind(user, "IsIconic", wt.BOOL, wt.HWND)
        self.root = bind(user, "GetAncestor", wt.HWND, wt.HWND, wt.UINT)
        self.style = bind(user, "GetWindowLongW", wt.LONG, wt.HWND, ctypes.c_int)
        self.shell = bind(user, "GetShellWindow", wt.HWND)
        self.desktop = bind(user, "GetDesktopWindow", wt.HWND)
        self.get_text = bind(user, "GetWindowTextW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
        self.get_class = bind(user, "GetClassNameW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
        self.attribute = bind(dwm, "DwmGetWindowAttribute", wt.LONG, wt.HWND, wt.DWORD,
                              ptr(wt.DWORD), wt.DWORD)
        self.thread_id = bind(kernel, "GetCurrentThreadId", wt.DWORD)
        self.thread_desktop = bind(user, "GetThreadDesktop", wt.HANDLE, wt.DWORD)
        self.object_info = bind(user, "GetUserObjectInformationW", wt.BOOL, wt.HANDLE,
                                ctypes.c_int, ptr(wt.BOOL), wt.DWORD, ptr(wt.DWORD))
        self.query_session = bind(wts, "WTSQuerySessionInformationW", wt.BOOL, wt.HANDLE,
                                  wt.DWORD, ctypes.c_int, ptr(ctypes.c_void_p), ptr(wt.DWORD))
        self.free = bind(wts, "WTSFreeMemory", None, ctypes.c_void_p)
        self.register = bind(wts, "WTSRegisterSessionNotification", wt.BOOL, wt.HWND, wt.DWORD)
        self.unregister = bind(wts, "WTSUnRegisterSessionNotification", wt.BOOL, wt.HWND)
        self.event_proc = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG,
                                             wt.LONG, wt.DWORD, wt.DWORD)
        self.hook = bind(user, "SetWinEventHook", wt.HANDLE, wt.DWORD, wt.DWORD, wt.HANDLE,
                         self.event_proc, wt.DWORD, wt.DWORD, wt.DWORD)
        self.unhook = bind(user, "UnhookWinEvent", wt.BOOL, wt.HANDLE)

    def interactive(self):
        # 현재 스레드의 데스크톱이 입력을 받는지 확인한다. 보안 데스크톱도 차단된다.
        receiving, size = wt.BOOL(), wt.DWORD()
        desk = self.thread_desktop(self.thread_id())
        if not desk or not self.object_info(desk, 6, ctypes.byref(receiving),
                                            ctypes.sizeof(receiving), ctypes.byref(size)):
            return False
        if not receiving.value:
            return False
        data = ctypes.c_void_p()
        if not self.query_session(None, 0xFFFFFFFF, 8, ctypes.byref(data), ctypes.byref(size)):
            return False
        try:
            return bool(data.value and size.value == 4 and wt.DWORD.from_address(data.value).value == 0)
        finally:
            self.free(data)

    def eligible(self, hwnd):
        if not self.visible(hwnd) or self.root(hwnd, 2) != hwnd:
            return False
        if hwnd in (self.shell(), self.desktop()) or self.style(hwnd, -20) & 0x80:
            return False
        name = ctypes.create_unicode_buffer(256)
        if not self.get_class(hwnd, name, len(name)) or name.value in {
            "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
        }:
            return False
        cloaked = wt.DWORD()
        return (self.attribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0
                and not cloaked.value)

    def targets(self):
        targets = []

        @self.callback
        def collect(hwnd, _):
            pid = wt.DWORD()
            tid = self.owner(hwnd, ctypes.byref(pid))
            if tid and pid.value != os.getpid() and self.eligible(hwnd) and not self.iconic(hwnd):
                title = ctypes.create_unicode_buffer(512)
                if self.get_text(hwnd, title, len(title)) and title.value.strip():
                    targets.append(_Target(hwnd, pid.value, tid, title.value.strip()))
            return True

        if self.interactive():
            self.enum(collect, 0)
        return targets

    def status(self, target):
        if not self.interactive():
            return "locked"
        pid = wt.DWORD()
        tid = self.owner(target.hwnd, ctypes.byref(pid))
        if not tid or tid != target.tid or pid.value != target.pid:
            return "closed"
        if self.iconic(target.hwnd):
            return "minimized"
        return "ready" if self.eligible(target.hwnd) else "closed"


class _SessionEvents(QWidget):
    """GUI가 바쁘거나 절전 중에 폴링이 멈춰도 이전 세션을 무효화한다."""

    def __init__(self, api, invalidate):
        super().__init__()
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.api, self.invalidate = api, invalidate
        self._hooks = []
        self.hwnd = int(self.winId())
        if not api.register(self.hwnd, 0):
            self.deleteLater()
            raise RuntimeError("Windows 세션 상태를 감시할 수 없습니다.")

    def watch(self, target, minimized):
        # 선택한 소유 스레드에서 발생한 창 파괴와 최소화 시작만 GUI 스레드로 받는다.
        @self.api.event_proc
        def changed(_hook, event, hwnd, obj, child, _thread, _time):
            if hwnd == target.hwnd and self.invalidate:
                if event == 0x0016:
                    minimized()
                elif event == 0x8001 and obj == 0 and child == 0:
                    self.invalidate()

        self._callback = changed
        for event in (0x0016, 0x8001):
            hook = self.api.hook(event, event, None, changed, target.pid, target.tid, 0)
            if not hook:
                raise RuntimeError("창의 수명을 확인할 수 없습니다.")
            self._hooks.append(hook)

    def nativeEvent(self, kind, message):
        msg = wt.MSG.from_address(int(message))
        # 잠금·연결 해제·로그오프와 절전/재개 알림을 받는다.
        if ((msg.message == 0x02B1 and msg.wParam in (2, 4, 6, 7))
                or (msg.message == 0x0218 and msg.wParam in (4, 7, 18))):
            if self.invalidate:
                self.invalidate()
        return False, 0

    def close(self):
        self.invalidate = None
        for hook in self._hooks:
            self.api.unhook(hook)
        self.api.unregister(self.hwnd)
        self.deleteLater()


def _pick(parent, targets):
    dialog = QDialog(parent if isinstance(parent, QWidget) else None)
    dialog.setWindowTitle(tr("screen.select_window"))
    dialog.resize(480, 340)
    layout = QVBoxLayout(dialog)
    if not targets:
        layout.addWidget(QLabel(tr("screen.no_windows")))
    listing = QListWidget(dialog)
    listing.setAccessibleName(dialog.windowTitle())
    for target in targets:
        listing.addItem(target.title)
    layout.addWidget(listing)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("settings.footer.cancel"))
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
    ok.setEnabled(False)
    listing.currentRowChanged.connect(lambda row: ok.setEnabled(row >= 0))
    listing.itemDoubleClicked.connect(dialog.accept)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() == QDialog.DialogCode.Accepted and listing.currentRow() >= 0:
        return targets[listing.currentRow()]
    return None


def _window_image(frame):
    from PyQt6.QtMultimedia import QVideoFrameFormat

    # 고정한 Qt 6.11 Windows 런타임은 WinRT 창 표면을 RGBX로, GDI를 BGRX로 전달한다.
    if not frame.isValid() or frame.pixelFormat() != QVideoFrameFormat.PixelFormat.Format_RGBX8888:
        return None
    if frame.width() * frame.height() > 64_000_000:
        return None
    image = frame.toImage()
    return image if not image.isNull() else None


class _WindowStream:
    def __init__(self, target, failed):
        from PyQt6.QtMultimedia import QCapturableWindow, QMediaCaptureSession, QVideoSink, QWindowCapture

        if os.environ.setdefault("QT_WINDOW_CAPTURE_BACKEND", "uwp").lower() != "uwp":
            raise RuntimeError("Windows Graphics Capture가 필요합니다.")
        self.window = QWindow.fromWinId(target.hwnd)
        if self.window is None:
            raise RuntimeError("선택한 창을 열 수 없습니다.")
        selected = QCapturableWindow(self.window)
        if not selected.isValid():
            raise RuntimeError("선택한 창이 닫혔습니다.")
        self.session = QMediaCaptureSession()
        self.capture = QWindowCapture(self.session)
        self.sink = QVideoSink(self.session)
        self.session.setVideoSink(self.sink)
        self.session.setWindowCapture(self.capture)
        self.capture.setWindow(selected)
        self.capture.errorOccurred.connect(failed, Qt.ConnectionType.QueuedConnection)
        self.capture.start()
        if not self.capture.isActive():
            self.close()
            raise RuntimeError("선택한 창을 캡처할 수 없습니다.")

    def image(self):
        return _window_image(self.sink.videoFrame())

    def close(self):
        self.capture.stop()
        self.session.setWindowCapture(None)
        self.session.setVideoSink(None)
        self.session.deleteLater()


class ScreenShare(QObject):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._api = _Windows()
        self._target = self._stream = self._events = None
        self._minimized = self.question = self.observe = False
        self._observation_allowed = True
        self.generation = self.question_epoch = self.observe_epoch = 0
        self.error = ""
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.validate)

    @property
    def title(self):
        return self._target.title if self._target else ""

    def choose(self, parent_widget):
        self.stop()
        epoch = self.generation
        self._events = _SessionEvents(self._api, self.stop)
        try:
            targets = self._api.targets()
            target = _pick(parent_widget, targets)
            if self.generation == epoch and target and self._api.status(target) == "ready":
                self._events.watch(target, self._pause_minimized)
                self._target = target
                self._timer.start()
                self.changed.emit()
                return True
        finally:
            if self._target is None:
                self.stop()
        return False

    def _close_stream(self):
        stream, self._stream = self._stream, None
        if stream:
            stream.close()

    def _pause_minimized(self):
        if self._target and not self._minimized:
            self._minimized = True
            self.generation += 1
            self._close_stream()
            self.changed.emit()

    def _start_stream(self):
        epoch = self.generation

        def failed(*_):
            if epoch == self.generation:
                self.stop()
                self.error = "capture_unavailable"
                self.changed.emit()

        try:
            self._stream = _WindowStream(self._target, failed)
        except (ImportError, OSError, RuntimeError):
            failed()

    def set_modes(self, question: bool, observe: bool):
        if not (question or observe):
            self.stop()
            return
        if not self._target:
            return
        if question != self.question:
            self.question_epoch += 1
        if observe != self.observe:
            self.observe_epoch += 1
        self.question, self.observe = question, observe
        self.validate()
        self.changed.emit()

    def set_observation_allowed(self, allowed: bool):
        """자동 관찰만 켜져 있으면 현재 대화 기기가 바뀔 때 창 스트림도 닫는다."""
        if allowed != self._observation_allowed:
            self._observation_allowed = allowed
            self.validate()

    def validate(self) -> bool:
        """GUI에서 만료된 캡처를 폐기하고 복원된 창에는 새 스트림을 연다."""
        if self._target is None:
            return False
        state = self._api.status(self._target)
        if state == "minimized":
            self._pause_minimized()
            return False
        if state != "ready":
            self.stop()
            return False
        self._minimized = False
        if not self.question and not (self.observe and self._observation_allowed):
            if self._stream:
                self.generation += 1
                self._close_stream()
            return False
        if not self._stream:
            self._start_stream()
        return bool(self._stream)

    def can_send(self, generation: int) -> bool:
        """전송 스레드에서 Qt 객체를 건드리지 않고 대상과 세대를 다시 확인한다."""
        target = self._target
        if (target is None or generation != self.generation or self._minimized
                or not (self.question or self.observe)):
            return False
        return (self._api.status(target) == "ready" and target is self._target
                and generation == self.generation and not self._minimized)

    def snapshot(self) -> QImage | None:
        if not self.validate():
            return None
        generation = self.generation
        image = self._stream.image()
        if image is None or image.isNull() or not self.can_send(generation):
            return None
        if max(image.width(), image.height()) > 1280:
            return image.scaled(1280, 1280, Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
        return image.copy()

    def stop(self):
        self.generation += 1
        self.question_epoch += int(self.question)
        self.observe_epoch += int(self.observe)
        self._target = None
        self.question = self.observe = self._minimized = False
        self.error = ""
        self._timer.stop()
        self._close_stream()
        events, self._events = self._events, None
        if events:
            events.close()
        self.changed.emit()
