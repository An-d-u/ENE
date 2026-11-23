"""사용자가 고른 Windows 모니터를 확인하고 한 장의 화면으로 합친다."""

import ctypes
from ctypes import wintypes as wt
from dataclasses import dataclass, field

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter, QScreen

from .i18n import tr


@dataclass(frozen=True)
class Monitor:
    handle: int
    device: str
    rect: QRect
    screen: QScreen = field(repr=False)
    title: str


@dataclass(frozen=True)
class MonitorSelection:
    monitors: tuple[Monitor, ...]

    @property
    def title(self):
        return ", ".join(m.title for m in self.monitors)

    def image(self):
        # 선택 사이에 놓인 다른 모니터는 읽지 않고 빈 공간으로 남긴다.
        bounds = QRect()
        for monitor in self.monitors:
            bounds = bounds.united(monitor.rect)
        if bounds.isEmpty():
            return None
        scale = min(1, 1280 / max(bounds.width(), bounds.height()))
        canvas = QImage(max(1, round(bounds.width() * scale)), max(1, round(bounds.height() * scale)),
                        QImage.Format.Format_RGB32)
        canvas.fill(Qt.GlobalColor.black)
        with QPainter(canvas) as painter:
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.scale(canvas.width() / bounds.width(), canvas.height() / bounds.height())
            painter.translate(-bounds.left(), -bounds.top())
            for monitor in self.monitors:
                if monitor.screen.geometry().topLeft() != monitor.rect.topLeft():
                    return None
                pixels = monitor.screen.grabWindow(0).toImage()
                if pixels.isNull() or pixels.size() != monitor.rect.size():
                    return None
                painter.drawImage(monitor.rect, pixels)
        return canvas


class _MonitorInfo(ctypes.Structure):
    _fields_ = [("size", wt.DWORD), ("bounds", wt.RECT), ("work", wt.RECT),
                ("flags", wt.DWORD), ("device", wt.WCHAR * 32)]


class WindowsMonitors:
    def __init__(self, user):
        self._at = user.MonitorFromPoint
        self._at.argtypes, self._at.restype = [wt.POINT, wt.DWORD], wt.HMONITOR
        self._info = user.GetMonitorInfoW
        self._info.argtypes, self._info.restype = [wt.HMONITOR, ctypes.POINTER(_MonitorInfo)], wt.BOOL

    def info(self, handle):
        data = _MonitorInfo()
        data.size = ctypes.sizeof(data)
        if not handle or not self._info(handle, ctypes.byref(data)):
            return None
        box = data.bounds
        return data.device, QRect(box.left, box.top, box.right - box.left, box.bottom - box.top)

    def options(self):
        monitors = []
        for screen in QGuiApplication.screens():
            # Windows에서 Qt는 화면 원점을 네이티브 데스크톱 좌표로 유지한다.
            origin = screen.geometry().topLeft()
            handle = self._at(wt.POINT(origin.x(), origin.y()), 0)
            info = self.info(handle)
            if info is None:
                continue
            device, rect = info
            if rect.topLeft() != origin or rect.isEmpty() or rect.width() * rect.height() > 64_000_000:
                continue
            number = device.rpartition("DISPLAY")[2]
            title = tr("screen.monitor", number=number) if number.isdecimal() else screen.name()
            monitors.append(Monitor(handle, device, rect, screen, title))
        return monitors
