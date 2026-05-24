"""
설정 대화상자 공용 위젯.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPoint, QRect, QSize, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

def apply_soft_shadow(widget: QWidget, blur: int = 36, alpha: int = 28) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 12)
    effect.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(effect)


class ClickableFrame(QFrame):
    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


class ToggleSwitch(QCheckBox):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self._accent_color = QColor("#0071E3")
        self._track_off_color = QColor("#E5E7EB")
        self._track_on_color = QColor("#0071E3")
        self._thumb_color = QColor("#FFFFFF")
        self._text_color = QColor("#111827")
        self._muted_border_color = QColor(17, 24, 39, 36)
        self._thumb_progress = 1.0 if self.isChecked() else 0.0
        self._thumb_animation = QVariantAnimation(self)
        self._thumb_animation.setDuration(130)
        self._thumb_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._thumb_animation.valueChanged.connect(self._on_thumb_progress_changed)
        self.toggled.connect(self._animate_thumb)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(30)

    def set_theme_colors(
        self,
        *,
        accent: str,
        track_off: str,
        text_color: str,
        muted_border: str,
    ) -> None:
        self._accent_color = QColor(accent)
        self._track_on_color = QColor(accent)
        self._track_off_color = QColor(track_off)
        self._thumb_color = QColor("#FFFFFF")
        self._text_color = QColor(text_color)
        self._muted_border_color = QColor(muted_border)
        self.update()

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        text_width = metrics.horizontalAdvance(self.text())
        return QSize(text_width + 76, max(30, metrics.height() + 10))

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def hitButton(self, pos: QPoint) -> bool:
        return self.rect().contains(pos)

    def _on_thumb_progress_changed(self, value) -> None:
        self._thumb_progress = float(value)
        self.update()

    def _animate_thumb(self, checked: bool) -> None:
        target = 1.0 if checked else 0.0
        if not self.isVisible() or self.window() is None or not self.window().isVisible():
            self._thumb_animation.stop()
            self._thumb_progress = target
            self.update()
            return

        self._thumb_animation.stop()
        self._thumb_animation.setStartValue(self._thumb_progress)
        self._thumb_animation.setEndValue(target)
        self._thumb_animation.start()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect()
        switch_width = 38
        switch_height = 22
        margin_right = 1
        switch_rect = QRect(
            rect.right() - switch_width - margin_right,
            rect.center().y() - (switch_height // 2),
            switch_width,
            switch_height,
        )
        text_rect = QRect(rect.left(), rect.top(), max(0, switch_rect.left() - 10), rect.height())

        text_color = QColor(self._text_color)
        if not self.isEnabled():
            text_color.setAlpha(120)
        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())

        if self.isChecked():
            track_color = QColor(self._track_on_color)
            track_border = QColor(self._track_on_color)
            track_border.setAlpha(40)
        else:
            track_color = QColor(self._track_off_color)
            track_border = QColor(self._muted_border_color)
            track_border.setAlpha(26)
        if not self.isEnabled():
            track_color.setAlpha(110)
            track_border.setAlpha(18)

        painter.setPen(QPen(track_border, 1))
        painter.setBrush(track_color)
        painter.drawRoundedRect(switch_rect.adjusted(0, 0, -1, -1), switch_height / 2, switch_height / 2)

        gloss_rect = switch_rect.adjusted(1, 1, -2, -(switch_height // 2))
        gloss_color = QColor("#FFFFFF")
        gloss_color.setAlpha(22 if self.isChecked() else 10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gloss_color)
        painter.drawRoundedRect(gloss_rect, gloss_rect.height() / 2, gloss_rect.height() / 2)

        thumb_size = 18
        thumb_margin = 3
        start_x = switch_rect.left() + thumb_margin
        end_x = switch_rect.right() - thumb_size - thumb_margin
        thumb_x = round(start_x + ((end_x - start_x) * self._thumb_progress))
        thumb_rect = QRect(
            thumb_x,
            switch_rect.center().y() - (thumb_size // 2),
            thumb_size,
            thumb_size,
        )
        thumb_color = QColor(self._thumb_color)
        if not self.isEnabled():
            thumb_color.setAlpha(180)

        shadow_rect = thumb_rect.adjusted(0, 1, 0, 1)
        shadow_color = QColor(15, 23, 42, 28 if self.isChecked() else 18)
        if not self.isEnabled():
            shadow_color.setAlpha(10)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shadow_color)
        painter.drawEllipse(shadow_rect)

        painter.setPen(QPen(QColor(15, 23, 42, 16), 1))
        painter.setBrush(thumb_color)
        painter.drawEllipse(thumb_rect)


class ColorPlaneWidget(QWidget):
    colorChanged = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0
        self._saturation = 255
        self._value = 255
        self._image: QImage | None = None
        self.setFixedSize(220, 220)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._rebuild_image()

    def set_hsv(self, hue: int, saturation: int, value: int) -> None:
        new_hue = max(0, min(int(hue), 359))
        hue_changed = new_hue != self._hue
        self._hue = new_hue
        self._saturation = max(0, min(int(saturation), 255))
        self._value = max(0, min(int(value), 255))
        if hue_changed:
            self._rebuild_image()
        self.update()

    def set_hue(self, hue: int) -> None:
        self._hue = max(0, min(int(hue), 359))
        self._rebuild_image()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rebuild_image()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        if self._image is not None:
            painter.drawImage(rect, self._image)

        painter.setPen(QPen(QColor(17, 24, 39, 30), 1))
        painter.drawRect(rect)

        x = rect.left() + round((self._saturation / 255.0) * rect.width())
        y = rect.top() + round((1.0 - (self._value / 255.0)) * rect.height())
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPoint(x, y), 7, 7)
        painter.setPen(QPen(QColor(17, 24, 39, 120), 1))
        painter.drawEllipse(QPoint(x, y), 8, 8)

    def _rebuild_image(self) -> None:
        width = max(1, self.width() - 2)
        height = max(1, self.height() - 2)
        image = QImage(width, height, QImage.Format.Format_RGB32)
        max_x = max(1, width - 1)
        max_y = max(1, height - 1)
        for y in range(height):
            value = round((1.0 - (y / max_y)) * 255)
            for x in range(width):
                saturation = round((x / max_x) * 255)
                image.setPixelColor(x, y, QColor.fromHsv(self._hue, saturation, value))
        self._image = image

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._update_from_pos(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._update_from_pos(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _update_from_pos(self, pos: QPoint) -> None:
        rect = self.rect().adjusted(1, 1, -1, -1)
        x = max(rect.left(), min(pos.x(), rect.right()))
        y = max(rect.top(), min(pos.y(), rect.bottom()))
        saturation = round(((x - rect.left()) / max(1, rect.width())) * 255)
        value = round((1.0 - ((y - rect.top()) / max(1, rect.height()))) * 255)
        self._saturation = max(0, min(saturation, 255))
        self._value = max(0, min(value, 255))
        self.update()
        self.colorChanged.emit(self._saturation, self._value)


class HueSliderWidget(QWidget):
    hueChanged = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hue = 0
        self.setFixedSize(24, 220)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_hue(self, hue: int) -> None:
        self._hue = max(0, min(int(hue), 359))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(4, 1, -4, -1)

        gradient = QLinearGradient(rect.center().x(), rect.top(), rect.center().x(), rect.bottom())
        gradient.setColorAt(0.00, QColor.fromHsv(0, 255, 255))
        gradient.setColorAt(0.17, QColor.fromHsv(300, 255, 255))
        gradient.setColorAt(0.33, QColor.fromHsv(240, 255, 255))
        gradient.setColorAt(0.50, QColor.fromHsv(180, 255, 255))
        gradient.setColorAt(0.67, QColor.fromHsv(120, 255, 255))
        gradient.setColorAt(0.83, QColor.fromHsv(60, 255, 255))
        gradient.setColorAt(1.00, QColor.fromHsv(0, 255, 255))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(rect, 10, 10)

        marker_y = rect.top() + round((self._hue / 359.0) * rect.height())
        marker_rect = QRect(rect.left() - 3, marker_y - 4, rect.width() + 6, 8)
        painter.setPen(QPen(QColor("#FFFFFF"), 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(marker_rect, 4, 4)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._update_from_pos(event.position().toPoint())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._update_from_pos(event.position().toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def _update_from_pos(self, pos: QPoint) -> None:
        rect = self.rect().adjusted(4, 1, -4, -1)
        y = max(rect.top(), min(pos.y(), rect.bottom()))
        hue = round(((y - rect.top()) / max(1, rect.height())) * 359)
        self._hue = max(0, min(hue, 359))
        self.update()
        self.hueChanged.emit(self._hue)


class ThemeColorPickerPopup(QDialog):
    colorChanged = pyqtSignal(str)
    closed = pyqtSignal()

    def __init__(self, parent=None, fallback_title: str = "색상 선택"):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setModal(False)
        self._updating = False
        self._current_title = ""
        self._fallback_title = str(fallback_title or "").strip() or "색상 선택"
        self._current_hue = 0
        self._current_saturation = 255
        self._current_value = 255

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)

        self.surface = QFrame()
        self.surface.setObjectName("ThemeColorPickerPopup")
        apply_soft_shadow(self.surface, blur=34, alpha=34)
        outer_layout.addWidget(self.surface)

        layout = QVBoxLayout(self.surface)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        self.title_label = QLabel(self._fallback_title)
        header_text.addWidget(self.title_label)
        self.value_label = QLabel("#FFFFFF")
        header_text.addWidget(self.value_label)
        header_row.addLayout(header_text)
        header_row.addStretch()

        self.preview = QFrame()
        self.preview.setFixedSize(34, 34)
        header_row.addWidget(self.preview)
        layout.addLayout(header_row)

        picker_row = QHBoxLayout()
        picker_row.setSpacing(12)
        self.color_plane = ColorPlaneWidget()
        self.color_plane.colorChanged.connect(self._on_plane_changed)
        picker_row.addWidget(self.color_plane)

        self.hue_slider = HueSliderWidget()
        self.hue_slider.hueChanged.connect(self._on_hue_changed)
        picker_row.addWidget(self.hue_slider)
        layout.addLayout(picker_row)

        self.swatch_row = QHBoxLayout()
        self.swatch_row.setSpacing(8)
        layout.addLayout(self.swatch_row)

    def hideEvent(self, event):
        self.closed.emit()
        super().hideEvent(event)

    def apply_theme(self, settings_window: str, settings_card: str, settings_input: str, accent: str, text_color: str, muted_text: str, border_color: str) -> None:
        self.setStyleSheet(
            """
            QFrame#ThemeColorPickerPopup {
                background: __CARD__;
                border: 1px solid __BORDER__;
                border-radius: 22px;
            }
            QLabel {
                color: __TEXT__;
            }
            QPushButton {
                min-height: 26px;
                padding: 0 10px;
                border-radius: 13px;
                border: 1px solid __BORDER__;
                background: __INPUT__;
                color: __TEXT__;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                border: 1px solid __ACCENT__;
            }
            """
            .replace("__WINDOW__", settings_window)
            .replace("__CARD__", settings_card)
            .replace("__INPUT__", settings_input)
            .replace("__ACCENT__", accent)
            .replace("__TEXT__", text_color)
            .replace("__MUTED__", muted_text)
            .replace("__BORDER__", border_color)
        )
        self.title_label.setStyleSheet(f"color: {text_color}; font-size: 13px; font-weight: 800;")
        self.value_label.setStyleSheet(f"color: {muted_text}; font-size: 12px; font-weight: 700;")

    def set_title(self, title: str) -> None:
        self._current_title = str(title or "").strip()
        self.title_label.setText(self._current_title or self._fallback_title)

    def set_fallback_title(self, title: str) -> None:
        self._fallback_title = str(title or "").strip() or "색상 선택"
        self.title_label.setText(self._current_title or self._fallback_title)

    def set_recommended_colors(self, colors: list[str], border_fn) -> None:
        while self.swatch_row.count():
            item = self.swatch_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for hex_color in colors:
            swatch = ClickableFrame()
            swatch.setFixedSize(24, 24)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setToolTip(hex_color)
            swatch.setStyleSheet(
                f"background: {hex_color}; border: 1px solid {border_fn(hex_color, 0.22)}; border-radius: 12px;"
            )
            swatch.clicked.connect(lambda selected=hex_color: self.set_color(selected, emit_signal=True))
            self.swatch_row.addWidget(swatch)
        self.swatch_row.addStretch()

    def set_color(self, color_value: str, emit_signal: bool = False) -> None:
        color = QColor(str(color_value or "#FFFFFF"))
        if not color.isValid():
            color = QColor("#FFFFFF")
        source_hex = color.name().upper()
        hue = color.hsvHue()
        if hue < 0:
            hue = 0

        self._updating = True
        self._current_hue = int(hue)
        self._current_saturation = int(color.hsvSaturation())
        self._current_value = int(color.value())
        self.color_plane.set_hsv(self._current_hue, self._current_saturation, self._current_value)
        self.hue_slider.set_hue(self._current_hue)
        self._apply_current_preview(source_hex)
        self._updating = False

        if emit_signal:
            self.colorChanged.emit(source_hex)

    def _apply_current_preview(self, override_hex: str | None = None) -> None:
        if override_hex:
            hex_color = str(override_hex).upper()
        else:
            color = QColor.fromHsv(self._current_hue, self._current_saturation, self._current_value)
            hex_color = color.name().upper()
        self.preview.setStyleSheet(f"background: {hex_color}; border-radius: 17px; border: 1px solid rgba(17, 24, 39, 0.08);")
        self.value_label.setText(hex_color)

    def _on_plane_changed(self, saturation: int, value: int) -> None:
        if self._updating:
            return
        self._current_saturation = int(saturation)
        self._current_value = int(value)
        self._apply_current_preview()
        self.colorChanged.emit(QColor.fromHsv(self._current_hue, self._current_saturation, self._current_value).name().upper())

    def _on_hue_changed(self, hue: int) -> None:
        if self._updating:
            return
        self._current_hue = int(hue)
        self.color_plane.set_hue(self._current_hue)
        self._apply_current_preview()
        self.colorChanged.emit(QColor.fromHsv(self._current_hue, self._current_saturation, self._current_value).name().upper())
