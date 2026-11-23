"""테마 팔레트 배너와 견본에 사용하는 해상도 독립적인 곡선 무늬."""

from functools import lru_cache

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QBoxLayout, QWidget


PALETTE_ART = {
    "light_classic": ("#DCE9FF", "#A3BFF1", "하늘 · 블루"),
    "light_sand": ("#F3E1C9", "#D6B186", "크림 · 모래"),
    "light_mint": ("#CDEADD", "#9CCBBD", "민트 · 세이지"),
    "dark_midnight": ("#BDCDE8", "#838AB8", "남색 · 블루"),
    "dark_graphite": ("#DAD6DE", "#938B9D", "실버 · 차콜"),
    "dark_forest": ("#B5D6CB", "#789D93", "그린 · 청록"),
}


@lru_cache(maxsize=96)
def theme_icon(name: str, color: str) -> QIcon:
    pixmap = QPixmap(36, 36)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor(color), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if name == "light":
        painter.drawEllipse(QPointF(9, 9), 3, 3)
        painter.translate(9, 9)
        for _ in range(8):
            painter.drawLine(0, 5, 0, 7)
            painter.rotate(45)
    elif name == "dark":
        moon = QPainterPath()
        moon.moveTo(8, 2)
        moon.cubicTo(1, 3, 1, 13, 8, 15)
        moon.cubicTo(12, 16, 15, 14, 16, 11)
        moon.cubicTo(10, 14, 5, 8, 8, 2)
        painter.drawPath(moon)
    elif name == "system":
        painter.drawRoundedRect(QRectF(2, 3, 14, 10), 1.5, 1.5)
        painter.drawLine(9, 13, 9, 16)
        painter.drawLine(6, 16, 12, 16)
    elif name == "edit":
        for y, x in ((5, 6), (12, 12)):
            painter.drawLine(2, y, x - 2, y)
            painter.drawLine(x + 2, y, 16, y)
            painter.drawEllipse(QPointF(x, y), 2, 2)
    elif name == "check":
        painter.drawLine(3, 9, 7, 13)
        painter.drawLine(7, 13, 15, 5)
    painter.end()
    return QIcon(pixmap)


class PaletteArtwork(QWidget):
    def __init__(self, compact=False):
        super().__init__()
        self.compact = compact
        self.colors = ("#FAC9AD", "#C6B1EB", "#87548E")
        if compact:
            self.setFixedSize(38, 38)
        else:
            self.setMinimumHeight(160)

    def set_colors(self, first, second, accent):
        colors = (first, second, accent)
        if self.colors != colors:
            self.colors = colors
            self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self.compact and self.layout() is not None:
            narrow = event.size().width() < 400
            self.layout().setDirection(QBoxLayout.Direction.TopToBottom if narrow else QBoxLayout.Direction.LeftToRight)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        width, height = self.width(), self.height()
        bounds = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        outline = QPainterPath()
        radius = 10 if self.compact else 16
        outline.addRoundedRect(bounds, radius, radius)
        painter.setClipPath(outline)
        first, second, accent = map(QColor, self.colors)
        background = QLinearGradient(0, 0, width, height)
        background.setColorAt(0, first if self.compact else first.lighter(110))
        background.setColorAt(0.50, first)
        background.setColorAt(1, second)
        painter.fillPath(outline, background)

        painter.save()
        painter.scale(width, height)
        start = -0.5 if self.compact else 0.0
        for index, (top, bottom) in enumerate(((first, second), (second, first), (first, accent))):
            shift = start + 0.15 * index
            wave = QPainterPath()
            wave.moveTo(0.12 + shift, 1.20)
            wave.cubicTo(0.38 + shift, 1.03, 0.66 + shift, 0.25, 1.34 + shift, -0.24)
            wave.lineTo(1.8, 1.3)
            wave.closeSubpath()
            gradient = QLinearGradient(0.50 + shift, 0.32, 0.89 + shift, 1.02)
            gradient.setColorAt(0, top.lighter(128))
            gradient.setColorAt(0.42, top)
            gradient.setColorAt(1, bottom)
            painter.fillPath(wave, gradient)
            painter.strokePath(wave, QPen(QColor(255, 255, 255, 115), 0))
        painter.restore()
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(71, 55, 76, 34))
        painter.drawPath(outline)
