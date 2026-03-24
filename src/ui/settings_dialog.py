"""
Settings dialog for ENE.
Provides live preview without immediate persistence.
"""
import ast
import importlib
import json
import re
from datetime import datetime
from pathlib import Path

try:
    import tiktoken
except ImportError:
    tiktoken = None
from PyQt6.QtCore import QPoint, QRect, QSize, Qt, QEasingCurve, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsDropShadowEffect,
    QGroupBox,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QListView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..ai.prompt import get_available_emotions
from ..ai.tts_client import get_tts_provider_catalog, get_tts_provider_defaults
from ..ai.llm_provider import LLMFormat, get_llm_provider_catalog
from ..core.i18n import tr
from ..core.system_theme import THEME_PRESETS, THEME_VARIANT_PRESETS, get_theme_preset, get_windows_theme_mode
from ..core.hotkey_utils import hotkey_to_display, normalize_hotkey_text
from .memory_dialog import MemoryDialog


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

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.setModal(False)
        self._updating = False
        self._current_title = ""
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
        self.title_label = QLabel("색상 선택")
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
        self.title_label.setText(self._current_title or "색상 선택")

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


class SettingsDialog(QDialog):
    settings_changed = pyqtSignal(dict)
    settings_preview = pyqtSignal(dict)
    settings_cancelled = pyqtSignal()

    def __init__(self, current_settings: dict, memory_manager=None, bridge=None, parent=None):
        super().__init__(parent)
        self._original_settings = current_settings.copy()
        self._memory_manager = memory_manager
        self._bridge = bridge
        self._browser_tts_voices: list[dict[str, object]] = []
        self._browser_voice_request_inflight = False
        self._browser_voice_refresh_attempts = 0
        self._browser_voice_refresh_timer = QTimer(self)
        self._browser_voice_refresh_timer.setSingleShot(True)
        self._browser_voice_refresh_timer.timeout.connect(self._request_browser_tts_voices)
        self._project_root = Path(__file__).resolve().parents[2]
        self._prompt_path = self._project_root / "src" / "ai" / "prompt.py"
        self._sub_prompt_path = self._project_root / "src" / "ai" / "sub_prompt.py"
        self._user_profile_path = self._project_root / "user_profile.json"
        self._prompt_status_label: QLabel | None = None
        self._profile_status_label: QLabel | None = None
        self._base_prompt_token_label: QLabel | None = None
        self._sub_prompt_token_label: QLabel | None = None
        self._emotion_items: list[dict[str, str]] = []
        self._emotion_current_index = -1
        self._basic_info_items: list[tuple[str, str]] = []
        self._basic_info_current_index = -1
        self._fact_items: list[dict[str, str]] = []
        self._fact_current_index = -1
        self._loading = False
        self._capturing_ptt_hotkey = False
        self._theme_defaults = {
            "theme_accent_color": "#0071E3",
            "settings_window_bg_color": "#EEF1F5",
            "settings_card_bg_color": "#FFFFFF",
            "settings_input_bg_color": "#F8FAFC",
            "chat_panel_bg_color": "#111214",
            "chat_input_bg_color": "#1B1D22",
            "chat_assistant_bubble_color": "#FFFFFF",
            "chat_user_bubble_color": "#0071E3",
        }
        self._theme_color_edits: dict[str, QLineEdit] = {}
        self._theme_preset_frames: dict[str, ClickableFrame] = {}
        self._theme_preset_titles: dict[str, QLabel] = {}
        self._theme_preset_meta: dict[str, QLabel] = {}
        self._theme_preset_input: dict[str, QLabel] = {}
        self._theme_preset_assistant: dict[str, QLabel] = {}
        self._theme_preset_user: dict[str, QLabel] = {}
        self._theme_variant_frames: dict[str, ClickableFrame] = {}
        self._theme_variant_titles: dict[str, QLabel] = {}
        self._theme_variant_meta: dict[str, QLabel] = {}
        self._theme_color_swatches: dict[str, ClickableFrame] = {}
        self._theme_color_reset_buttons: dict[str, QPushButton] = {}
        self._theme_color_titles: dict[str, str] = {}
        self._theme_picker_panels: dict[str, QFrame] = {}
        self._theme_picker_previews: dict[str, QFrame] = {}
        self._theme_picker_value_labels: dict[str, QLabel] = {}
        self._theme_picker_hue_sliders: dict[str, QSlider] = {}
        self._theme_picker_saturation_sliders: dict[str, QSlider] = {}
        self._theme_picker_lightness_sliders: dict[str, QSlider] = {}
        self._theme_picker_popup: ThemeColorPickerPopup | None = None
        self._theme_picker_active_key: str | None = None
        self._theme_live_update_timer = QTimer(self)
        self._theme_live_update_timer.setSingleShot(True)
        self._theme_live_update_timer.setInterval(24)
        self._theme_live_update_timer.timeout.connect(self._flush_theme_live_update)
        self._prompt_token_update_timer = QTimer(self)
        self._prompt_token_update_timer.setSingleShot(True)
        self._prompt_token_update_timer.setInterval(40)
        self._prompt_token_update_timer.timeout.connect(self._refresh_prompt_token_counts)
        self._toggle_checks: list[ToggleSwitch] = []
        self._embedded_memory_panel = None
        self.memory_search_recent_turns_spin: QSpinBox | None = None
        self._lazy_tab_hosts: dict[str, QWidget] = {}
        self._lazy_tab_builders: dict[str, callable] = {}
        self._lazy_tab_loaded: set[str] = set()
        self._lazy_tab_index_to_id: dict[int, str] = {}
        self._section_header_map: dict[int, tuple[str, str]] = {}
        self._section_nav_cards: dict[int, ClickableFrame] = {}
        self._section_nav_titles: dict[int, QLabel] = {}
        self._section_nav_meta: dict[int, QLabel] = {}
        self._prompt_tokenizer = tiktoken.get_encoding("cl100k_base") if tiktoken is not None else None
        self._theme_values = {
            key: self._normalize_theme_color(
                str(self._original_settings.get(key, default_value)),
                fallback=default_value,
            )
            for key, default_value in self._theme_defaults.items()
        }
        self._theme_mode = str(self._original_settings.get("theme_mode", "light")).strip().lower()
        if self._theme_mode not in THEME_PRESETS:
            self._theme_mode = "light"
        self._follow_system_theme = bool(self._original_settings.get("follow_system_theme", False))
        if self._follow_system_theme:
            self._theme_mode = get_windows_theme_mode()
            self._theme_values.update(get_theme_preset(self._theme_mode))
        self._ptt_hotkey_value = normalize_hotkey_text(
            str(self._original_settings.get("global_ptt_hotkey", "alt")),
            default="alt",
        )
        self._tts_catalog = get_tts_provider_catalog()
        raw_tts_configs = self._original_settings.get("tts_provider_configs", {})
        if not isinstance(raw_tts_configs, dict):
            raw_tts_configs = {}
        self._tts_provider_configs = {
            provider: {
                **get_tts_provider_defaults(provider),
                **(provider_config if isinstance(provider_config, dict) else {}),
            }
            for provider, provider_config in raw_tts_configs.items()
        }
        for provider in self._tts_catalog.keys():
            self._tts_provider_configs.setdefault(provider, get_tts_provider_defaults(provider))

        raw_tts_api_keys = self._original_settings.get("tts_api_keys", {})
        self._tts_api_keys = dict(raw_tts_api_keys) if isinstance(raw_tts_api_keys, dict) else {}

        self.setWindowTitle(self._translated_text("settings.window.title", "ENE 설정"))
        icon_path = self._project_root / "assets" / "icons" / "ene_app.ico"
        if not icon_path.exists():
            icon_path = self._project_root / "assets" / "icons" / "tray_icon.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(1020, 700)
        self.resize(1180, 780)
        self.setWindowFlags(
            Qt.WindowType.Dialog 
            | Qt.WindowType.FramelessWindowHint 
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setModal(False)
        self._drag_active = False
        self._drag_offset = QPoint()
        self._resize_active = False
        self._resize_edge = ""
        self._resize_start_global = QPoint()
        self._resize_start_geometry = self.geometry()
        self._resize_margin = 12
        self.setMouseTracking(True)

        self._setup_ui()
        self._load_values()

    def _normalize_theme_color(self, value: str, fallback: str | None = None) -> str:
        match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(value or "").strip())
        if not match:
            return fallback or self._theme_defaults["theme_accent_color"]
        return f"#{match.group(1).upper()}"

    def _translated_text(self, key: str, fallback: str) -> str:
        translated = tr(key)
        return fallback if translated == key else translated

    def _resolve_theme_bundle_text(self, bundle: dict, field: str) -> str:
        fallback = str(bundle.get(field, "")).strip()
        key = str(bundle.get(f"{field}_key", "")).strip()
        if not key:
            return fallback
        return self._translated_text(key, fallback)

    def _llm_provider_label(self, provider_id: str, meta) -> str:
        fallback = meta.display_name if meta is not None else provider_id
        return self._translated_text(f"settings.llm.provider.{provider_id}.label", fallback)

    def _tts_provider_label(self, provider_id: str, meta) -> str:
        fallback = meta.display_name if meta is not None else provider_id
        return self._translated_text(f"settings.tts.provider.{provider_id}.label", fallback)

    def _tts_provider_hint(self, provider_id: str, meta) -> str:
        fallback = meta.description if meta is not None else ""
        return self._translated_text(f"settings.tts.provider.{provider_id}.hint", fallback)

    def _is_valid_theme_color(self, value: str) -> bool:
        return bool(re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(value or "").strip()))

    def _theme_rgba(self, color_value: str, alpha: float) -> str:
        color = QColor(self._normalize_theme_color(color_value))
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f})"

    def _theme_variant(self, color_value: str, *, darker: int | None = None, lighter: int | None = None) -> str:
        color = QColor(self._normalize_theme_color(color_value))
        if darker is not None:
            color = color.darker(darker)
        if lighter is not None:
            color = color.lighter(lighter)
        return color.name().upper()

    def _theme_text_color(self, color_value: str) -> str:
        color = QColor(self._normalize_theme_color(color_value))
        return "#FFFFFF" if color.lightnessF() < 0.62 else "#111827"

    def _theme_muted_text_color(self, color_value: str) -> str:
        color = QColor(self._normalize_theme_color(color_value))
        return "#CBD5E1" if color.lightnessF() < 0.42 else "#6B7280"

    def _theme_border_color(self, color_value: str, alpha: float = 0.14) -> str:
        return self._theme_rgba(self._theme_text_color(color_value), alpha)

    def _set_theme_editors_enabled(self, enabled: bool) -> None:
        for line_edit in self._theme_color_edits.values():
            line_edit.setEnabled(enabled)
        for swatch in self._theme_color_swatches.values():
            swatch.setEnabled(enabled)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        for button in self._theme_color_reset_buttons.values():
            button.setEnabled(enabled)
        if not enabled:
            self._close_all_theme_pickers()
        for frame in self._theme_preset_frames.values():
            frame.setEnabled(True)
            frame.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)

    def _apply_theme_mode(self, mode: str, *, emit_preview: bool = True) -> None:
        normalized_mode = str(mode or "").strip().lower()
        if normalized_mode not in THEME_PRESETS:
            normalized_mode = "light"
        self._close_all_theme_pickers()
        self._theme_mode = normalized_mode
        preset = get_theme_preset(normalized_mode)
        self._theme_values.update(preset)

        for key, value in preset.items():
            if key not in self._theme_color_edits:
                continue
            line_edit = self._theme_color_edits[key]
            was_blocked = line_edit.blockSignals(True)
            line_edit.setText(value)
            line_edit.blockSignals(was_blocked)

        self._apply_stylesheet()
        self._refresh_theme_editor_state()
        if emit_preview and not self._loading:
            self._preview_settings()

    def _on_theme_mode_selected(self, mode: str) -> None:
        self._follow_system_theme = False
        if hasattr(self, "follow_system_theme_check"):
            self.follow_system_theme_check.blockSignals(True)
            self.follow_system_theme_check.setChecked(False)
            self.follow_system_theme_check.blockSignals(False)
        self._set_theme_editors_enabled(True)
        self._apply_theme_mode(mode)

    def _on_follow_system_theme_toggled(self, checked: bool) -> None:
        self._follow_system_theme = bool(checked)
        self._set_theme_editors_enabled(not self._follow_system_theme)
        if self._follow_system_theme:
            self._apply_theme_mode(get_windows_theme_mode(), emit_preview=False)
            self._refresh_theme_editor_state()
            if not self._loading:
                self._preview_settings()
            return

        self._refresh_theme_editor_state()
        if not self._loading:
            self._preview_settings()

    def _pick_theme_color(self, key: str) -> None:
        if self._follow_system_theme:
            return
        popup = self._ensure_theme_picker_popup()
        swatch = self._theme_color_swatches.get(key)
        if swatch is None:
            return

        is_same_target = popup.isVisible() and self._theme_picker_active_key == key
        self._close_all_theme_pickers()
        if is_same_target:
            return

        self._theme_picker_active_key = key
        popup.set_title(self._theme_color_titles.get(key, "색상 선택"))
        popup.apply_theme(
            self._theme_values["settings_window_bg_color"],
            self._theme_values["settings_card_bg_color"],
            self._theme_values["settings_input_bg_color"],
            self._theme_values["theme_accent_color"],
            self._theme_text_color(self._theme_values["settings_card_bg_color"]),
            self._theme_muted_text_color(self._theme_values["settings_card_bg_color"]),
            self._theme_border_color(self._theme_values["settings_card_bg_color"], 0.10),
        )
        popup.set_recommended_colors(self._recommended_theme_swatches(key), self._theme_border_color)
        popup.set_color(self._theme_values.get(key, self._theme_defaults[key]), emit_signal=False)
        popup.adjustSize()

        anchor = swatch.mapToGlobal(QPoint(swatch.width() + 10, 0))
        screen = QApplication.screenAt(anchor) or QApplication.primaryScreen()
        if screen is not None:
            available = screen.availableGeometry()
            x = min(anchor.x(), available.right() - popup.width() - 10)
            y = min(anchor.y(), available.bottom() - popup.height() - 10)
            x = max(available.left() + 10, x)
            y = max(available.top() + 10, y)
            popup.move(x, y)
        else:
            popup.move(anchor)
        popup.show()
        popup.raise_()
        popup.activateWindow()

    def _close_all_theme_pickers(self) -> None:
        self._theme_picker_active_key = None
        if self._theme_picker_popup is not None:
            self._theme_picker_popup.hide()
        for panel in self._theme_picker_panels.values():
            panel.setVisible(False)

    def _ensure_theme_picker_popup(self) -> ThemeColorPickerPopup:
        if self._theme_picker_popup is None:
            self._theme_picker_popup = ThemeColorPickerPopup(self)
            self._theme_picker_popup.colorChanged.connect(self._on_theme_popup_color_changed)
            self._theme_picker_popup.closed.connect(self._on_theme_popup_closed)
        return self._theme_picker_popup

    def _on_theme_popup_color_changed(self, hex_color: str) -> None:
        if not self._theme_picker_active_key:
            return
        normalized = self._normalize_theme_color(hex_color)
        edit = self._theme_color_edits[self._theme_picker_active_key]
        if edit.text().strip().upper() == normalized:
            return
        edit.setText(normalized)

    def _on_theme_popup_closed(self) -> None:
        self._theme_picker_active_key = None

    def _sync_theme_picker_controls(self, key: str) -> None:
        if key not in self._theme_picker_panels:
            return
        color_value = self._theme_values.get(key, self._theme_defaults[key])
        color = QColor(color_value)
        hue = color.hslHue()
        if hue < 0:
            hue = 0

        preview = self._theme_picker_previews.get(key)
        if preview is not None:
            preview.setStyleSheet(
                f"background: {color_value}; border: 1px solid {self._theme_border_color(color_value, 0.22)}; border-radius: 18px;"
            )

        value_label = self._theme_picker_value_labels.get(key)
        if value_label is not None:
            value_label.setText(color_value)
            value_label.setStyleSheet(
                f"color: {self._theme_text_color(self._theme_values['settings_card_bg_color'])}; font-size: 13px; font-weight: 800;"
            )

        slider_map = (
            (self._theme_picker_hue_sliders, hue),
            (self._theme_picker_saturation_sliders, color.hslSaturation()),
            (self._theme_picker_lightness_sliders, color.lightness()),
        )
        for slider_dict, value in slider_map:
            slider = slider_dict.get(key)
            if slider is None:
                continue
            was_blocked = slider.blockSignals(True)
            slider.setValue(int(value))
            slider.blockSignals(was_blocked)

    def _on_theme_picker_slider_changed(self, key: str) -> None:
        hue_slider = self._theme_picker_hue_sliders.get(key)
        saturation_slider = self._theme_picker_saturation_sliders.get(key)
        lightness_slider = self._theme_picker_lightness_sliders.get(key)
        if not hue_slider or not saturation_slider or not lightness_slider:
            return

        color = QColor()
        color.setHsl(
            int(hue_slider.value()),
            int(saturation_slider.value()),
            int(lightness_slider.value()),
        )
        self._theme_color_edits[key].setText(color.name().upper())

    def _recommended_theme_swatches(self, key: str) -> list[str]:
        if key in {"theme_accent_color", "chat_user_bubble_color"}:
            return ["#0071E3", "#0D9A73", "#B86A24", "#7C5CFA", "#D94A67", "#111827"]
        return ["#EEF1F5", "#F2E7D8", "#DFF2EB", "#111724", "#1A1A1C", "#121915"]

    def _build_inline_theme_picker(self, key: str) -> QFrame:
        panel = QFrame()
        panel.setObjectName("ThemePickerPanel")
        panel.setVisible(False)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)
        preview = QFrame()
        preview.setFixedSize(36, 36)
        self._theme_picker_previews[key] = preview
        header_row.addWidget(preview)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        title = QLabel("색상 미세 조정")
        title.setStyleSheet("font-size: 12px; font-weight: 800;")
        header_text.addWidget(title)
        value_label = QLabel(self._theme_defaults[key])
        self._theme_picker_value_labels[key] = value_label
        header_text.addWidget(value_label)
        header_row.addLayout(header_text)
        header_row.addStretch()

        close_button = QPushButton("닫기")
        close_button.setMinimumWidth(72)
        close_button.clicked.connect(lambda _checked=False, field_key=key: self._theme_picker_panels[field_key].setVisible(False))
        header_row.addWidget(close_button)
        layout.addLayout(header_row)

        palette_row = QHBoxLayout()
        palette_row.setSpacing(8)
        for swatch_color in self._recommended_theme_swatches(key):
            swatch_button = ClickableFrame()
            swatch_button.setFixedSize(26, 26)
            swatch_button.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch_button.setToolTip(swatch_color)
            swatch_button.setStyleSheet(
                f"background: {swatch_color}; border: 1px solid {self._theme_border_color(swatch_color, 0.24)}; border-radius: 13px;"
            )
            swatch_button.clicked.connect(lambda selected=swatch_color, field_key=key: self._theme_color_edits[field_key].setText(selected))
            palette_row.addWidget(swatch_button)
        palette_row.addStretch()
        layout.addLayout(palette_row)

        slider_specs = [
            ("색조", 0, 359, self._theme_picker_hue_sliders),
            ("채도", 0, 255, self._theme_picker_saturation_sliders),
            ("밝기", 0, 255, self._theme_picker_lightness_sliders),
        ]
        for label_text, minimum, maximum, slider_store in slider_specs:
            row = QHBoxLayout()
            row.setSpacing(10)
            label = QLabel(label_text)
            label.setFixedWidth(34)
            row.addWidget(label)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(minimum, maximum)
            slider.valueChanged.connect(lambda _value, field_key=key: self._on_theme_picker_slider_changed(field_key))
            slider_store[key] = slider
            row.addWidget(slider, 1)
            layout.addLayout(row)

        self._theme_picker_panels[key] = panel
        return panel

    def _apply_theme_variant(self, mode: str, variant_id: str) -> None:
        variant_bundle = THEME_VARIANT_PRESETS.get(mode, {}).get(variant_id)
        if not variant_bundle:
            return

        self._follow_system_theme = False
        if hasattr(self, "follow_system_theme_check"):
            self.follow_system_theme_check.blockSignals(True)
            self.follow_system_theme_check.setChecked(False)
            self.follow_system_theme_check.blockSignals(False)
        self._set_theme_editors_enabled(True)

        self._close_all_theme_pickers()
        self._theme_mode = mode
        palette = variant_bundle["colors"]
        self._theme_values.update(palette)
        for key, value in palette.items():
            if key not in self._theme_color_edits:
                continue
            line_edit = self._theme_color_edits[key]
            was_blocked = line_edit.blockSignals(True)
            line_edit.setText(value)
            line_edit.blockSignals(was_blocked)

        self._apply_stylesheet()
        self._refresh_theme_editor_state()
        if not self._loading:
            self._preview_settings()

    def _current_theme_variant_id(self, mode: str) -> str | None:
        for variant_id, bundle in THEME_VARIANT_PRESETS.get(mode, {}).items():
            palette = bundle["colors"]
            if all(
                self._theme_values.get(key, "").upper() == self._normalize_theme_color(value).upper()
                for key, value in palette.items()
            ):
                return variant_id
        return None

    def _build_theme_color_editor(self, key: str, title: str, description: str) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._theme_color_titles[key] = title

        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)

        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet("font-size: 12px; font-weight: 600; color: #6B7280;")
        layout.addWidget(desc_label)

        row = QHBoxLayout()
        row.setSpacing(8)

        line_edit = QLineEdit()
        line_edit.setPlaceholderText(self._theme_defaults[key])
        line_edit.setMaxLength(7)
        line_edit.textChanged.connect(lambda text, field_key=key: self._on_theme_color_field_changed(field_key, text))
        self._theme_color_edits[key] = line_edit
        row.addWidget(line_edit, 1)

        swatch = ClickableFrame()
        swatch.setFixedSize(38, 38)
        swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        swatch.setToolTip("클릭해서 색상 선택")
        swatch.clicked.connect(lambda field_key=key: self._pick_theme_color(field_key))
        self._theme_color_swatches[key] = swatch
        setattr(self, f"{key}_swatch", swatch)
        row.addWidget(swatch)

        reset_button = QPushButton("기본값")
        reset_button.setMinimumWidth(84)
        reset_button.clicked.connect(
            lambda _checked=False, field_key=key: self._theme_color_edits[field_key].setText(self._theme_defaults[field_key])
        )
        self._theme_color_reset_buttons[key] = reset_button
        row.addWidget(reset_button)
        layout.addLayout(row)
        return container

    def _build_theme_mode_preview(self, mode: str, title: str, description: str) -> QFrame:
        frame = ClickableFrame()
        frame.clicked.connect(lambda selected_mode=mode: self._on_theme_mode_selected(selected_mode))
        frame.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title_label = QLabel(title)
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(title_label)
        self._theme_preset_titles[mode] = title_label

        meta_label = QLabel(description)
        meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        meta_label.setWordWrap(True)
        layout.addWidget(meta_label)
        self._theme_preset_meta[mode] = meta_label

        sample_row = QHBoxLayout()
        sample_row.setSpacing(10)
        assistant = QLabel("응답")
        assistant.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        assistant.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sample_row.addWidget(assistant, 1)
        user = QLabel("사용자")
        user.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        user.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sample_row.addWidget(user, 1)
        layout.addLayout(sample_row)
        self._theme_preset_assistant[mode] = assistant
        self._theme_preset_user[mode] = user

        input_preview = QLabel("입력 필드 예시")
        input_preview.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(input_preview)
        self._theme_preset_input[mode] = input_preview

        self._theme_preset_frames[mode] = frame
        return frame

    def _build_theme_variant_preview(self, mode: str, variant_id: str, title: str, description: str) -> QFrame:
        frame = ClickableFrame()
        frame.clicked.connect(lambda selected_mode=mode, selected_variant=variant_id: self._apply_theme_variant(selected_mode, selected_variant))
        frame.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(title_label)
        self._theme_variant_titles[variant_id] = title_label

        meta_label = QLabel(description)
        meta_label.setWordWrap(True)
        meta_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(meta_label)
        self._theme_variant_meta[variant_id] = meta_label

        swatch_row = QHBoxLayout()
        swatch_row.setSpacing(6)
        for palette_key in ("settings_window_bg_color", "settings_card_bg_color", "chat_panel_bg_color", "theme_accent_color"):
            swatch = QFrame()
            swatch.setFixedSize(22, 22)
            swatch.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            setattr(self, f"{variant_id}_{palette_key}_swatch", swatch)
            swatch_row.addWidget(swatch)
        swatch_row.addStretch()
        layout.addLayout(swatch_row)

        self._theme_variant_frames[variant_id] = frame
        return frame

    def _refresh_theme_editor_state(self) -> None:
        invalid_keys = []
        settings_card = self._theme_values["settings_card_bg_color"]
        settings_input = self._theme_values["settings_input_bg_color"]
        for key, line_edit in self._theme_color_edits.items():
            raw_value = line_edit.text().strip()
            is_valid = self._is_valid_theme_color(raw_value)
            color_value = self._theme_values[key] if is_valid else self._theme_defaults[key]
            swatch = getattr(self, f"{key}_swatch", None)
            if swatch is not None:
                swatch.setStyleSheet(
                    f"background: {color_value}; border: 1px solid rgba(17, 24, 39, 0.10); border-radius: 12px;"
                )
            panel = self._theme_picker_panels.get(key)
            if panel is not None:
                panel.setStyleSheet(
                    f"QFrame#ThemePickerPanel {{ background: {settings_input}; border: 1px solid {self._theme_border_color(settings_card, 0.10)}; border-radius: 18px; }}"
                    f" QLabel {{ color: {self._theme_text_color(settings_card)}; font-size: 12px; font-weight: 700; }}"
                )
                self._sync_theme_picker_controls(key)
            if not is_valid and raw_value:
                invalid_keys.append(key)

        if self._theme_picker_popup is not None and self._theme_picker_popup.isVisible() and self._theme_picker_active_key:
            active_key = self._theme_picker_active_key
            self._theme_picker_popup.apply_theme(
                self._theme_values["settings_window_bg_color"],
                self._theme_values["settings_card_bg_color"],
                self._theme_values["settings_input_bg_color"],
                self._theme_values["theme_accent_color"],
                self._theme_text_color(self._theme_values["settings_card_bg_color"]),
                self._theme_muted_text_color(self._theme_values["settings_card_bg_color"]),
                self._theme_border_color(self._theme_values["settings_card_bg_color"], 0.10),
            )
            self._theme_picker_popup.set_recommended_colors(
                self._recommended_theme_swatches(active_key),
                self._theme_border_color,
            )
            self._theme_picker_popup.set_color(self._theme_values.get(active_key, self._theme_defaults[active_key]), emit_signal=False)

        for mode, preset_bundle in THEME_PRESETS.items():
            frame = self._theme_preset_frames.get(mode)
            if frame is None:
                continue

            preset = preset_bundle.get("colors", preset_bundle)
            accent = preset["theme_accent_color"]
            settings_window = preset["settings_window_bg_color"]
            settings_card = preset["settings_card_bg_color"]
            settings_input = preset["settings_input_bg_color"]
            chat_panel = preset["chat_panel_bg_color"]
            chat_input = preset["chat_input_bg_color"]
            chat_assistant = preset["chat_assistant_bubble_color"]
            chat_user = preset["chat_user_bubble_color"]
            is_active = self._theme_mode == mode

            frame.setStyleSheet(
                f"background: {settings_window}; "
                f"border: 1px solid {self._theme_border_color(settings_window, 0.12)}; "
                "border-radius: 22px;"
            )
            self._theme_preset_titles[mode].setText(self._resolve_theme_bundle_text(preset_bundle, "title"))
            self._theme_preset_titles[mode].setStyleSheet(
                f"color: {self._theme_text_color(settings_window)}; font-size: 15px; font-weight: 800;"
            )
            base_description = self._resolve_theme_bundle_text(preset_bundle, "description")
            meta_suffix = "윈도우와 동기화 중" if self._follow_system_theme and self._theme_mode == mode else ("현재 선택됨" if is_active else "클릭해서 적용")
            self._theme_preset_meta[mode].setText(
                f"{base_description} · {meta_suffix}"
            )
            self._theme_preset_meta[mode].setStyleSheet(
                f"color: {self._theme_muted_text_color(settings_window)}; font-size: 12px; font-weight: 600;"
            )
            self._theme_preset_assistant[mode].setStyleSheet(
                f"background: {chat_assistant}; color: {self._theme_text_color(chat_assistant)}; "
                "border-radius: 16px; padding: 10px 14px; font-size: 12px; font-weight: 700;"
            )
            self._theme_preset_user[mode].setStyleSheet(
                f"background: {chat_user}; color: {self._theme_text_color(chat_user)}; "
                "border-radius: 16px; padding: 10px 14px; font-size: 12px; font-weight: 700;"
            )
            self._theme_preset_input[mode].setStyleSheet(
                f"background: {settings_input if mode == 'light' else chat_input}; "
                f"color: {self._theme_text_color(settings_input if mode == 'light' else chat_input)}; "
                f"border: 1px solid {self._theme_border_color(settings_card if mode == 'light' else chat_panel, 0.14)}; "
                "border-radius: 14px; padding: 10px 12px; font-size: 12px; font-weight: 600;"
            )

        for mode, variant_map in THEME_VARIANT_PRESETS.items():
            active_variant_id = self._current_theme_variant_id(mode)
            for variant_id, bundle in variant_map.items():
                frame = self._theme_variant_frames.get(variant_id)
                if frame is None:
                    continue

                palette = bundle["colors"]
                window_color = palette["settings_window_bg_color"]
                card_color = palette["settings_card_bg_color"]
                is_active = self._theme_mode == mode and active_variant_id == variant_id
                border_color = self._theme_border_color(window_color, 0.18 if is_active else 0.10)
                frame.setStyleSheet(
                    f"background: {card_color}; "
                    f"border: 1px solid {border_color}; "
                    "border-radius: 18px;"
                )
                self._theme_variant_titles[variant_id].setText(self._resolve_theme_bundle_text(bundle, "title"))
                self._theme_variant_titles[variant_id].setStyleSheet(
                    f"color: {self._theme_text_color(card_color)}; font-size: 13px; font-weight: 800;"
                )
                suffix = "현재 팔레트" if is_active else "클릭해서 적용"
                self._theme_variant_meta[variant_id].setText(
                    f"{self._resolve_theme_bundle_text(bundle, 'description')} · {suffix}"
                )
                self._theme_variant_meta[variant_id].setStyleSheet(
                    f"color: {self._theme_muted_text_color(card_color)}; font-size: 11px; font-weight: 600;"
                )

                for palette_key in ("settings_window_bg_color", "settings_card_bg_color", "chat_panel_bg_color", "theme_accent_color"):
                    swatch = getattr(self, f"{variant_id}_{palette_key}_swatch", None)
                    if swatch is None:
                        continue
                    swatch.setStyleSheet(
                        f"background: {palette[palette_key]}; "
                        f"border: 1px solid {self._theme_border_color(palette[palette_key], 0.20)}; "
                        "border-radius: 11px;"
                    )

        if hasattr(self, "theme_status_label"):
            if invalid_keys:
                self.theme_status_label.setStyleSheet("color: #B42318; font-size: 12px; font-weight: 600;")
                self.theme_status_label.setText("모든 테마 값은 `#RRGGBB` 형식의 6자리 HEX 코드여야 합니다.")
            else:
                self.theme_status_label.setStyleSheet("color: #6B7280; font-size: 12px; font-weight: 600;")
                if self._follow_system_theme:
                    current_mode_text = "라이트" if self._theme_mode == "light" else "다크"
                    self.theme_status_label.setText(f"현재 윈도우 앱 테마({current_mode_text})를 따라가고 있습니다.")
                else:
                    self.theme_status_label.setText("설정창과 채팅창이 같은 테마 모드로 함께 움직이도록 구성되어 있습니다.")

    def _on_theme_color_field_changed(self, key: str, text: str) -> None:
        if self._is_valid_theme_color(text):
            self._theme_values[key] = self._normalize_theme_color(text, fallback=self._theme_defaults[key])
            self._schedule_theme_live_update()
            return

        self._refresh_theme_editor_state()

    def _schedule_theme_live_update(self) -> None:
        if self._loading:
            return
        self._theme_live_update_timer.start()

    def _flush_theme_live_update(self) -> None:
        self._apply_stylesheet()
        self._refresh_theme_editor_state()
        if not self._loading:
            self._preview_settings()

    def _count_prompt_tokens(self, text: str) -> int:
        normalized = str(text or "")
        if self._prompt_tokenizer is None:
            # 선택 의존성이 없을 때도 앱 실행은 유지하고, 완만한 근사치만 제공한다.
            return max(0, round(len(normalized.strip()) / 2.2))
        try:
            return len(self._prompt_tokenizer.encode(normalized, disallowed_special=()))
        except Exception:
            # 토크나이저 실패 시에는 완만한 문자 기반 근사치로 폴백한다.
            return max(0, round(len(normalized.strip()) / 2.2))

    def _format_token_count_text(self, title: str, text: str) -> str:
        token_count = self._count_prompt_tokens(text)
        char_count = len(str(text or ""))
        return f"{title} 현재 토큰: {token_count:,}개 · 문자 수: {char_count:,}자"

    def _schedule_prompt_token_refresh(self) -> None:
        self._prompt_token_update_timer.start()

    def _refresh_prompt_token_counts(self) -> None:
        if self._base_prompt_token_label is not None and hasattr(self, "base_prompt_editor"):
            self._base_prompt_token_label.setText(
                self._format_token_count_text("BASE_SYSTEM_PROMPT", self.base_prompt_editor.toPlainText())
            )
        if self._sub_prompt_token_label is not None and hasattr(self, "sub_prompt_editor"):
            self._sub_prompt_token_label.setText(
                self._format_token_count_text("SUB_PROMPT", self.sub_prompt_editor.toPlainText())
            )

    def _create_toggle(self, text: str) -> ToggleSwitch:
        toggle = ToggleSwitch(text)
        self._toggle_checks.append(toggle)
        toggle.set_theme_colors(
            accent=self._theme_values["theme_accent_color"],
            track_off=self._theme_values["settings_input_bg_color"],
            text_color=self._theme_text_color(self._theme_values["settings_card_bg_color"]),
            muted_border=self._theme_rgba(self._theme_text_color(self._theme_values["settings_card_bg_color"]), 0.12),
        )
        return toggle

    def _apply_stylesheet(self):
        accent = self._theme_values["theme_accent_color"]
        settings_window = self._theme_values["settings_window_bg_color"]
        settings_card = self._theme_values["settings_card_bg_color"]
        settings_input = self._theme_values["settings_input_bg_color"]
        primary_text = self._theme_text_color(settings_card)
        muted_text = self._theme_muted_text_color(settings_card)
        title_muted = self._theme_muted_text_color(settings_window)
        input_text = self._theme_text_color(settings_input)
        card_border = self._theme_border_color(settings_card, 0.10)
        window_border = self._theme_border_color(settings_window, 0.10)
        input_border = self._theme_border_color(settings_input, 0.14)
        tab_shell_bg = self._theme_variant(settings_window, lighter=102) if self._theme_text_color(settings_window) == "#111827" else self._theme_variant(settings_window, darker=104)
        accent_hover = self._theme_variant(accent, darker=108)
        accent_title = self._theme_variant(accent, darker=116)
        accent_soft = self._theme_rgba(accent, 0.10)
        accent_soft_strong = self._theme_rgba(accent, 0.18)
        accent_border = self._theme_rgba(accent, 0.22)
        accent_focus = self._theme_rgba(accent, 0.55)
        accent_slider = self._theme_rgba(accent, 0.80)
        accent_slider_hover = self._theme_rgba(accent, 1.0)
        accent_dropdown = self._theme_rgba(accent, 0.12)
        style = """
        QDialog { background: __SETTINGS_WINDOW__; color: __PRIMARY_TEXT__; font-family: 'Malgun Gothic', 'Segoe UI Variable', 'Segoe UI', sans-serif; }
        QWidget { background: transparent; }
        #MainFrame { background: __SETTINGS_CARD__; border: 1px solid __WINDOW_BORDER__; border-radius: 30px; }
        #TitleBar, #FooterCard, #SidebarShell, #ContentShell { background: __SETTINGS_CARD__; border: 1px solid __CARD_BORDER__; border-radius: 24px; }
        #TitleLabel { color: __PRIMARY_TEXT__; font-size: 18px; font-weight: 700; }
        #TitleSubLabel { color: __TITLE_MUTED__; font-size: 12px; font-weight: 600; }
        #CloseButton { background: transparent; border: none; color: __MUTED_TEXT__; min-width: 34px; min-height: 34px; border-radius: 17px; font-size: 18px; }
        #CloseButton:hover { background: __PRIMARY_TEXT_SOFT__; color: __PRIMARY_TEXT__; }
        #FooterTitle { color: __PRIMARY_TEXT__; font-size: 15px; font-weight: 700; }
        #FooterBody { color: __MUTED_TEXT__; font-size: 13px; }
        #InlineHint { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
        #ValueBadge { color: __PRIMARY_TEXT__; font-size: 13px; font-weight: 700; background: __SETTINGS_INPUT__; border: 1px solid __INPUT_BORDER__; border-radius: 12px; padding: 8px 12px; }
        #SidebarTitle { color: __PRIMARY_TEXT__; font-size: 15px; font-weight: 700; }
        #SidebarMeta { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
        #ContentHeaderTitle { color: __PRIMARY_TEXT__; font-size: 18px; font-weight: 700; }
        #ContentHeaderMeta { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
        QFrame#NavItemCard { background: __TAB_SHELL_BG__; border: 1px solid __CARD_BORDER__; border-radius: 20px; }
        QFrame#NavItemCard:hover { border: 1px solid __ACCENT_BORDER__; background: __PRIMARY_TEXT_SOFT__; }
        QFrame#NavItemCard[selected='true'] { background: __SETTINGS_CARD__; border: 1px solid __ACCENT_BORDER__; }
        QLabel#NavItemTitle { color: __PRIMARY_TEXT__; font-size: 14px; font-weight: 700; }
        QLabel#NavItemMeta { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
        QFrame#NavItemCard[selected='true'] QLabel#NavItemMeta { color: __PRIMARY_TEXT__; }

        QLabel, QCheckBox { color: __PRIMARY_TEXT__; font-size: 13px; }
        QCheckBox { spacing: 0px; background: transparent; }
        QGroupBox { background: __SETTINGS_CARD__; border: 1px solid __CARD_BORDER__; border-radius: 22px; margin-top: 12px; padding-top: 20px; padding-left: 18px; padding-right: 18px; padding-bottom: 18px; font-weight: 700; color: __PRIMARY_TEXT__; }
        QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 9px; top: -2px; padding: 0 4px; color: __ACCENT_TITLE__; background: __SETTINGS_CARD__; }
        QPushButton { min-height: 44px; padding: 0 18px; border-radius: 18px; border: 1px solid __CARD_BORDER__; background: __SETTINGS_CARD__; color: __PRIMARY_TEXT__; font-size: 13px; font-weight: 600; }
        QPushButton:hover { background: __SETTINGS_INPUT__; }
        QPushButton:disabled { background: __SETTINGS_CARD__; color: __DISABLED_TEXT__; }
        QPushButton[accent='true'] { background: __ACCENT__; color: __ACCENT_TEXT__; border: 1px solid __ACCENT__; }
        QPushButton[accent='true']:hover { background: __ACCENT_HOVER__; }
        QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { min-height: 42px; padding: 0 14px; border-radius: 16px; background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; font-size: 13px; selection-background-color: __ACCENT_SOFT_STRONG__; }
        QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid __ACCENT_FOCUS__; background: __SETTINGS_INPUT__; }
        QPlainTextEdit { background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; border-radius: 18px; padding: 14px; font-size: 13px; font-family: 'Consolas', 'D2Coding', 'Malgun Gothic', monospace; selection-background-color: __ACCENT_SOFT_STRONG__; }
        QPlainTextEdit:focus { border: 1px solid __ACCENT_FOCUS__; background: __SETTINGS_INPUT__; }
        QListWidget { background: __SETTINGS_INPUT__; color: __INPUT_TEXT__; border: 1px solid __INPUT_BORDER__; border-radius: 18px; padding: 8px; outline: none; }
        QListWidget::item { color: __INPUT_TEXT__; background: transparent; border: 1px solid transparent; border-radius: 14px; padding: 10px 12px; margin: 2px 0; }
        QListWidget::item:hover { background: __PRIMARY_TEXT_SOFT__; border: 1px solid __CARD_BORDER__; }
        QListWidget::item:selected { background: __ACCENT_SOFT__; color: __INPUT_TEXT__; border: 1px solid __ACCENT_BORDER__; }
        QComboBox::drop-down { border: none; width: 28px; }
        QComboBox QAbstractItemView { background: __SETTINGS_CARD__; color: __PRIMARY_TEXT__; border: 1px solid __CARD_BORDER__; selection-background-color: __ACCENT_DROPDOWN__; outline: none; padding: 4px; }
        QSlider::groove:horizontal { border: 1px solid __INPUT_BORDER__; height: 6px; background: __TAB_SHELL_BG__; border-radius: 3px; }
        QSlider::sub-page:horizontal { background: __ACCENT_SLIDER__; border-radius: 3px; }
        QSlider::handle:horizontal { background: __SETTINGS_CARD__; border: 2px solid __ACCENT_SLIDER__; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }
        QSlider::handle:horizontal:hover { border: 2px solid __ACCENT_SLIDER_HOVER__; }
        QScrollArea { border: none; background: transparent; }
        QScrollBar:vertical { width: 10px; background: transparent; margin: 8px 0; }
        QScrollBar::handle:vertical { background: __MUTED_TEXT_SOFT__; min-height: 20px; border-radius: 5px; }
        QScrollBar::handle:vertical:hover { background: __MUTED_TEXT_STRONG__; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { border: none; background: none; }
        """
        style = (
            style.replace("__ACCENT__", accent)
            .replace("__ACCENT_HOVER__", accent_hover)
            .replace("__ACCENT_TEXT__", self._theme_text_color(accent))
            .replace("__ACCENT_TITLE__", accent_title)
            .replace("__ACCENT_SOFT__", accent_soft)
            .replace("__ACCENT_SOFT_STRONG__", accent_soft_strong)
            .replace("__ACCENT_BORDER__", accent_border)
            .replace("__ACCENT_FOCUS__", accent_focus)
            .replace("__ACCENT_SLIDER__", accent_slider)
            .replace("__ACCENT_SLIDER_HOVER__", accent_slider_hover)
            .replace("__ACCENT_DROPDOWN__", accent_dropdown)
            .replace("__SETTINGS_WINDOW__", settings_window)
            .replace("__SETTINGS_CARD__", settings_card)
            .replace("__SETTINGS_INPUT__", settings_input)
            .replace("__PRIMARY_TEXT__", primary_text)
            .replace("__MUTED_TEXT__", muted_text)
            .replace("__TITLE_MUTED__", title_muted)
            .replace("__INPUT_TEXT__", input_text)
            .replace("__CARD_BORDER__", card_border)
            .replace("__WINDOW_BORDER__", window_border)
            .replace("__INPUT_BORDER__", input_border)
            .replace("__TAB_SHELL_BG__", tab_shell_bg)
            .replace("__PRIMARY_TEXT_SOFT__", self._theme_rgba(primary_text, 0.08))
            .replace("__DISABLED_TEXT__", self._theme_rgba(primary_text, 0.42))
            .replace("__MUTED_TEXT_SOFT__", self._theme_rgba(muted_text, 0.35))
            .replace("__MUTED_TEXT_STRONG__", self._theme_rgba(muted_text, 0.55))
        )
        self.setStyleSheet(style)

        for toggle in self._toggle_checks:
            toggle.set_theme_colors(
                accent=accent,
                track_off=settings_input,
                text_color=primary_text,
                muted_border=self._theme_rgba(primary_text, 0.12),
            )
        if self._embedded_memory_panel is not None:
            self._embedded_memory_panel.apply_theme(dict(self._theme_values))

    def _setup_ui(self):
        self._apply_stylesheet()

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(18, 18, 18, 18)

        self.main_frame = QFrame()
        self.main_frame.setObjectName("MainFrame")
        apply_soft_shadow(self.main_frame)
        layout = QVBoxLayout(self.main_frame)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        main_layout.addWidget(self.main_frame)

        workspace_row = QHBoxLayout()
        workspace_row.setSpacing(14)

        sidebar_shell = QFrame()
        sidebar_shell.setObjectName("SidebarShell")
        sidebar_shell.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar_shell)
        sidebar_layout.setContentsMargins(14, 14, 14, 14)
        sidebar_layout.setSpacing(12)

        sidebar_title = QLabel("ENE 설정")
        sidebar_title.setObjectName("SidebarTitle")
        sidebar_layout.addWidget(sidebar_title)

        sidebar_meta = QLabel("섹션을 옆 메뉴에서 고르고 오른쪽에서 세부 설정을 조정합니다.")
        sidebar_meta.setObjectName("SidebarMeta")
        sidebar_meta.setWordWrap(True)
        sidebar_layout.addWidget(sidebar_meta)

        self.section_nav_container = QWidget()
        section_nav_layout = QVBoxLayout(self.section_nav_container)
        section_nav_layout.setContentsMargins(0, 4, 0, 0)
        section_nav_layout.setSpacing(10)
        sidebar_layout.addWidget(self.section_nav_container)
        sidebar_layout.addStretch()

        content_shell = QFrame()
        content_shell.setObjectName("ContentShell")
        content_layout = QVBoxLayout(content_shell)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(8)

        content_header = QWidget()
        content_header_layout = QHBoxLayout(content_header)
        content_header_layout.setContentsMargins(4, 0, 0, 0)
        content_header_layout.setSpacing(10)

        content_header_text = QVBoxLayout()
        content_header_text.setContentsMargins(0, 0, 0, 0)
        content_header_text.setSpacing(2)

        self.content_header_title = QLabel("창 설정")
        self.content_header_title.setObjectName("ContentHeaderTitle")
        content_header_text.addWidget(self.content_header_title)

        self.content_header_meta = QLabel("창 위치와 크기를 조정합니다.")
        self.content_header_meta.setObjectName("ContentHeaderMeta")
        self.content_header_meta.setWordWrap(True)
        content_header_text.addWidget(self.content_header_meta)

        content_header_layout.addLayout(content_header_text, 1)
        content_header_layout.addStretch()

        close_btn = QPushButton("×")
        close_btn.setObjectName("CloseButton")
        close_btn.clicked.connect(self._cancel_settings)
        content_header_layout.addWidget(close_btn, 0, Qt.AlignmentFlag.AlignTop)

        content_layout.addWidget(content_header)

        self.content_stack = QStackedWidget()
        self.content_stack.currentChanged.connect(self._on_tab_changed)
        content_layout.addWidget(self.content_stack)

        self._add_section("창 설정", "창 위치와 크기", self._create_window_tab())
        self._add_section("테마 설정", "라이트/다크와 팔레트", self._create_theme_tab())
        self._add_section("모델 설정", "배치와 Live2D 경로", self._create_model_tab())
        self._add_section("LLM 설정", "공급자와 응답 스타일", self._create_llm_tab())
        self._add_section("TTS 설정", "공급자와 음성 합성 구성", self._create_tts_tab())
        self._add_section("동작 설정", "버튼, PTT, 감지 옵션", self._create_behavior_tab())
        self._add_lazy_tab("memory", "기억 관리", "기억 목록과 검색 설정", self._create_memory_tab)
        self._add_lazy_tab("profile", "사용자 기억 관리", "user_profile.json 구조 편집", self._create_user_profile_tab)
        self._add_lazy_tab("prompt", "프롬프트 설정", "프롬프트와 감정 규칙", self._create_prompt_tab)
        self._set_section_index(0)

        workspace_row.addWidget(sidebar_shell)
        workspace_row.addWidget(content_shell, 1)
        layout.addLayout(workspace_row, 1)

        layout.addWidget(self._build_footer_note())

    def _build_footer_note(self):
        card = QFrame()
        card.setObjectName("FooterCard")
        footer_layout = QHBoxLayout(card)
        footer_layout.setContentsMargins(18, 16, 18, 16)
        footer_layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        title = QLabel("설정 적용 안내")
        title.setObjectName("FooterTitle")
        text_col.addWidget(title)

        body = QLabel("변경사항은 저장 전까지 미리보기로만 반영됩니다. 취소하면 이전 설정으로 돌아가며, 일부 LLM 설정은 저장 후 다시 시작해야 완전히 반영됩니다.")
        body.setObjectName("FooterBody")
        body.setWordWrap(True)
        text_col.addWidget(body)
        footer_layout.addLayout(text_col, 1)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)
        action_row.setContentsMargins(0, 0, 0, 0)

        cancel_btn = QPushButton("취소")
        cancel_btn.clicked.connect(self._cancel_settings)
        action_row.addWidget(cancel_btn)

        save_btn = QPushButton("변경사항 저장")
        save_btn.setProperty("accent", True)
        save_btn.style().unpolish(save_btn)
        save_btn.style().polish(save_btn)
        save_btn.clicked.connect(self._save_settings)
        action_row.addWidget(save_btn)

        footer_layout.addLayout(action_row, 0)
        return card

    def _build_hint_label(self, text: str):
        label = QLabel(text)
        label.setObjectName("InlineHint")
        label.setWordWrap(True)
        return label

    def _build_section_nav_card(self, title: str, description: str, index: int) -> ClickableFrame:
        card = ClickableFrame()
        card.setObjectName("NavItemCard")
        card.setProperty("selected", "false")
        card.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(4)

        title_label = QLabel(title)
        title_label.setObjectName("NavItemTitle")
        layout.addWidget(title_label)

        meta_label = QLabel(description)
        meta_label.setObjectName("NavItemMeta")
        meta_label.setWordWrap(True)
        layout.addWidget(meta_label)

        card.clicked.connect(lambda idx=index: self._set_section_index(idx))
        self._section_nav_cards[index] = card
        self._section_nav_titles[index] = title_label
        self._section_nav_meta[index] = meta_label
        return card

    def _add_section(self, title: str, description: str, widget: QWidget) -> int:
        index = self.content_stack.addWidget(widget)
        self._section_header_map[index] = (title, description)
        nav_layout = self.section_nav_container.layout()
        if nav_layout is not None:
            nav_layout.addWidget(self._build_section_nav_card(title, description, index))
        return index

    def _set_section_index(self, index: int) -> None:
        if not hasattr(self, "content_stack"):
            return
        if index < 0 or index >= self.content_stack.count():
            return
        self.content_stack.setCurrentIndex(index)
        self._update_section_nav_selection(index)

    def _update_section_nav_selection(self, current_index: int) -> None:
        for index, card in self._section_nav_cards.items():
            card.setProperty("selected", "true" if index == current_index else "false")
            card.style().unpolish(card)
            card.style().polish(card)

        title, description = self._section_header_map.get(current_index, ("ENE 설정", "섹션을 선택해 세부 설정을 조정합니다."))
        if hasattr(self, "content_header_title"):
            self.content_header_title.setText(title)
        if hasattr(self, "content_header_meta"):
            self.content_header_meta.setText(description)

    def _add_lazy_tab(self, tab_id: str, title: str, description: str, builder) -> None:
        host = QWidget()
        host_layout = QVBoxLayout(host)
        host_layout.setContentsMargins(10, 10, 10, 10)
        host_layout.setSpacing(12)

        card = QFrame()
        card.setObjectName("FooterCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 18, 20, 18)
        card_layout.setSpacing(6)

        title_label = QLabel(title)
        title_label.setObjectName("FooterTitle")
        card_layout.addWidget(title_label)

        body_label = QLabel(description)
        body_label.setObjectName("FooterBody")
        body_label.setWordWrap(True)
        card_layout.addWidget(body_label)

        host_layout.addWidget(card)
        host_layout.addStretch()

        index = self._add_section(title, description, host)
        self._lazy_tab_hosts[tab_id] = host
        self._lazy_tab_builders[tab_id] = builder
        self._lazy_tab_index_to_id[index] = tab_id

    def _on_tab_changed(self, index: int) -> None:
        self._update_section_nav_selection(index)
        tab_id = self._lazy_tab_index_to_id.get(index)
        if tab_id:
            self._ensure_lazy_tab_loaded(tab_id)

    def _ensure_lazy_tab_loaded(self, tab_id: str) -> None:
        if tab_id in self._lazy_tab_loaded:
            return

        host = self._lazy_tab_hosts.get(tab_id)
        builder = self._lazy_tab_builders.get(tab_id)
        if host is None or builder is None:
            return

        built_widget = builder()
        layout = host.layout()
        if layout is None:
            return

        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        layout.addWidget(built_widget)
        self._lazy_tab_loaded.add(tab_id)

    def _build_secret_row(self, line_edit: QLineEdit, toggle_handler, button_attr_name: str):
        line_edit.setEchoMode(QLineEdit.EchoMode.Password)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(line_edit, 1)

        toggle_btn = QPushButton("표시")
        toggle_btn.setMinimumWidth(72)
        toggle_btn.clicked.connect(toggle_handler)
        setattr(self, button_attr_name, toggle_btn)
        layout.addWidget(toggle_btn)
        return row

    def _toggle_secret_field(self, line_edit: QLineEdit, button: QPushButton):
        is_password = line_edit.echoMode() == QLineEdit.EchoMode.Password
        line_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if is_password else QLineEdit.EchoMode.Password
        )
        button.setText("숨김" if is_password else "표시")

    def _normalize_path_for_storage(self, path_text: str) -> str:
        raw_path = str(path_text or "").strip()
        if not raw_path:
            return ""

        try:
            path_obj = Path(raw_path)
            if not path_obj.is_absolute():
                return raw_path.replace("\\", "/")
            relative = path_obj.resolve().relative_to(self._project_root.resolve())
            return str(relative).replace("\\", "/")
        except Exception:
            return raw_path.replace("\\", "/")

    def _browse_live2d_model_path(self):
        start_dir = self._project_root / "assets" / "live2d_models"
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "Live2D 모델 파일 선택",
            str(start_dir),
            "Live2D 모델 (*.model3.json);;JSON 파일 (*.json);;모든 파일 (*.*)",
        )
        if not selected:
            return
        self.model_json_path_edit.setText(self._normalize_path_for_storage(selected))

    def _browse_tts_ref_audio_path(self):
        start_dir = self._project_root / "assets" / "ref_audio"
        selected, _ = QFileDialog.getOpenFileName(
            self,
            "참조 오디오 선택",
            str(start_dir),
            "Audio Files (*.wav *.mp3 *.flac *.ogg);;모든 파일 (*.*)",
        )
        if not selected:
            return
        self.tts_ref_audio_path_edit.setText(self._normalize_path_for_storage(selected))

    def _get_overlay_web_page(self):
        if not self._bridge:
            return None
        parent = self._bridge.parent()
        if not parent or not hasattr(parent, "web_view"):
            return None
        try:
            return parent.web_view.page()
        except Exception:
            return None

    def _request_browser_tts_voices(self):
        if self._browser_voice_request_inflight:
            return
        page = self._get_overlay_web_page()
        if page is None:
            if hasattr(self, "tts_browser_voice_status_label"):
                self.tts_browser_voice_status_label.setText("현재 웹뷰를 찾을 수 없어 음성 목록을 읽지 못했습니다.")
            return

        self._browser_voice_request_inflight = True
        if hasattr(self, "tts_browser_voice_status_label"):
            self.tts_browser_voice_status_label.setText("현재 환경의 브라우저 음성 목록을 불러오는 중입니다...")
        page.runJavaScript(
            "(function(){"
            "if (typeof window.getBrowserTTSVoices === 'function') {"
            "return window.getBrowserTTSVoices();"
            "}"
            "return [];"
            "})();",
            self._handle_browser_tts_voices_result,
        )

    def _handle_browser_tts_voices_result(self, result):
        self._browser_voice_request_inflight = False
        voices = result if isinstance(result, list) else []
        normalized_voices = []
        for item in voices:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            lang = str(item.get("lang", "")).strip()
            if not name:
                continue
            normalized_voices.append(
                {
                    "name": name,
                    "lang": lang,
                    "default": bool(item.get("default", False)),
                }
            )

        if normalized_voices:
            self._browser_voice_refresh_attempts = 0
            self._browser_tts_voices = normalized_voices
            self._populate_browser_tts_language_filter(normalized_voices)
            self._populate_browser_tts_voice_combo()
            if hasattr(self, "tts_browser_voice_status_label"):
                self.tts_browser_voice_status_label.setText(
                    f"현재 환경에서 사용 가능한 음성 {len(normalized_voices)}개를 불러왔습니다."
                )
            return

        self._browser_voice_refresh_attempts += 1
        if hasattr(self, "tts_browser_voice_status_label"):
            self.tts_browser_voice_status_label.setText(
                "아직 음성 목록을 받지 못했습니다. 시스템 음성 초기화 뒤 다시 시도합니다."
            )
        if self._browser_voice_refresh_attempts < 4:
            self._browser_voice_refresh_timer.start(450)

    def _populate_browser_tts_language_filter(self, voices: list[dict]) -> None:
        if not hasattr(self, "tts_browser_voice_lang_filter_combo"):
            return
        current_data = self.tts_browser_voice_lang_filter_combo.currentData()
        current_lang = self.tts_browser_lang_edit.text().strip()
        languages = sorted({str(voice.get("lang", "")).strip() for voice in voices if str(voice.get("lang", "")).strip()})

        self.tts_browser_voice_lang_filter_combo.blockSignals(True)
        self.tts_browser_voice_lang_filter_combo.clear()
        self.tts_browser_voice_lang_filter_combo.addItem("전체 언어", "")
        for lang in languages:
            self.tts_browser_voice_lang_filter_combo.addItem(lang, lang)

        matched_index = -1
        if current_data:
            matched_index = self.tts_browser_voice_lang_filter_combo.findData(current_data)
        if matched_index < 0 and current_lang:
            matched_index = self.tts_browser_voice_lang_filter_combo.findData(current_lang)
        self.tts_browser_voice_lang_filter_combo.setCurrentIndex(matched_index if matched_index >= 0 else 0)
        self.tts_browser_voice_lang_filter_combo.blockSignals(False)

    def _populate_browser_tts_voice_combo(self) -> None:
        if not hasattr(self, "tts_browser_voice_combo"):
            return
        voices = list(self._browser_tts_voices)
        current_text = self.tts_browser_voice_combo.currentText().strip()
        selected_lang = ""
        if hasattr(self, "tts_browser_voice_lang_filter_combo"):
            selected_lang = str(self.tts_browser_voice_lang_filter_combo.currentData() or "").strip().lower()
        if selected_lang:
            voices = [
                voice for voice in voices
                if str(voice.get("lang", "")).strip().lower().startswith(selected_lang)
            ]
        self.tts_browser_voice_combo.blockSignals(True)
        self.tts_browser_voice_combo.clear()
        for voice in sorted(
            voices,
            key=lambda item: (
                0 if item.get("default") else 1,
                str(item.get("lang", "")),
                str(item.get("name", "")).lower(),
            ),
        ):
            label = str(voice["name"])
            lang = str(voice.get("lang", "")).strip()
            if lang:
                label = f"{label} ({lang})"
            if voice.get("default"):
                label = f"{label} · 기본"
            self.tts_browser_voice_combo.addItem(label, str(voice["name"]))

        if current_text:
            matched_index = self.tts_browser_voice_combo.findData(current_text)
            if matched_index >= 0:
                self.tts_browser_voice_combo.setCurrentIndex(matched_index)
            else:
                self.tts_browser_voice_combo.setEditText(current_text)
        self.tts_browser_voice_combo.blockSignals(False)

        if hasattr(self, "tts_browser_voice_status_label") and self._browser_tts_voices:
            filter_suffix = ""
            if selected_lang:
                filter_suffix = f" · {selected_lang} 기준 {len(voices)}개 표시"
            self.tts_browser_voice_status_label.setText(
                f"현재 환경에서 사용 가능한 음성 {len(self._browser_tts_voices)}개를 불러왔습니다{filter_suffix}."
            )

    def _on_browser_tts_language_filter_changed(self, *_):
        self._populate_browser_tts_voice_combo()

    def _on_browser_tts_lang_changed(self, *_):
        self._on_setting_changed()
        if not hasattr(self, "tts_browser_voice_lang_filter_combo"):
            return
        current_lang = self.tts_browser_lang_edit.text().strip()
        if not current_lang:
            return
        matched_index = self.tts_browser_voice_lang_filter_combo.findData(current_lang)
        if matched_index >= 0 and self.tts_browser_voice_lang_filter_combo.currentIndex() != matched_index:
            self.tts_browser_voice_lang_filter_combo.setCurrentIndex(matched_index)

    def _on_tts_provider_changed(self, *_):
        self._sync_tts_provider_ui()
        self._on_setting_changed()

    def _sync_tts_provider_ui(self):
        provider = str(self.tts_provider_combo.currentData() or "gpt_sovits_http")
        if hasattr(self, "tts_provider_stack"):
            page = self._tts_provider_pages.get(provider)
            if page is not None:
                self.tts_provider_stack.setCurrentWidget(page)
        if hasattr(self, "tts_provider_hint_label"):
            meta = self._tts_catalog.get(provider)
            self.tts_provider_hint_label.setText(self._tts_provider_hint(provider, meta))
        if provider == "browser_speech":
            self._browser_voice_refresh_attempts = 0
            self._request_browser_tts_voices()

    def _collect_tts_provider_configs(self) -> dict:
        return {
            "gpt_sovits_http": {
                "api_url": self.tts_api_url_edit.text().strip() or "http://127.0.0.1:9880",
                "ref_audio_path": self.tts_ref_audio_path_edit.text().strip() or "assets/ref_audio/refvoice.wav",
                "ref_text": self.tts_ref_text_edit.toPlainText().strip(),
                "ref_language": self.tts_ref_language_edit.text().strip() or "ja",
                "target_language": self.tts_target_language_edit.text().strip() or "ja",
            },
            "openai_audio_speech": {
                "api_url": self.tts_openai_api_url_edit.text().strip() or "https://api.openai.com/v1",
                "model": str(self.tts_openai_model_combo.currentData() or "gpt-4o-mini-tts"),
                "voice": str(self.tts_openai_voice_combo.currentData() or "alloy"),
                "speed": round(self.tts_openai_speed_spin.value(), 2),
                "response_format": "wav",
            },
            "openai_compatible_audio_speech": {
                "api_url": self.tts_compatible_api_url_edit.text().strip() or "http://127.0.0.1:8000/v1",
                "model": self.tts_compatible_model_edit.text().strip() or "tts-1",
                "voice": self.tts_compatible_voice_edit.text().strip() or "alloy",
                "speed": round(self.tts_compatible_speed_spin.value(), 2),
                "response_format": "wav",
            },
            "elevenlabs": {
                "api_url": self.tts_elevenlabs_api_url_edit.text().strip() or "https://api.elevenlabs.io/v1",
                "model": str(self.tts_elevenlabs_model_combo.currentData() or "eleven_multilingual_v2"),
                "voice": self.tts_elevenlabs_voice_edit.text().strip() or "EXAVITQu4vr4xnSDxMaL",
                "speed": round(self.tts_elevenlabs_speed_spin.value(), 2),
                "stability": round(self.tts_elevenlabs_stability_spin.value(), 2),
                "similarity_boost": round(self.tts_elevenlabs_similarity_spin.value(), 2),
                "style": round(self.tts_elevenlabs_style_spin.value(), 2),
                "use_speaker_boost": self.tts_elevenlabs_speaker_boost_check.isChecked(),
                "output_format": "pcm_44100",
            },
            "browser_speech": {
                "lang": self.tts_browser_lang_edit.text().strip() or "ja-JP",
                "voice": self.tts_browser_voice_combo.currentData() or self.tts_browser_voice_combo.currentText().strip(),
                "rate": round(self.tts_browser_rate_spin.value(), 2),
                "pitch": round(self.tts_browser_pitch_spin.value(), 2),
                "volume": round(self.tts_browser_volume_spin.value(), 2),
            },
        }

    def _collect_tts_api_keys(self) -> dict:
        return {
            "openai_audio_speech": self.tts_openai_api_key_edit.text().strip(),
            "openai_compatible_audio_speech": self.tts_compatible_api_key_edit.text().strip(),
            "elevenlabs": self.tts_elevenlabs_api_key_edit.text().strip(),
        }

    def _load_tts_values(self):
        configs = self._tts_provider_configs
        gpt_sovits = {**get_tts_provider_defaults("gpt_sovits_http"), **configs.get("gpt_sovits_http", {})}
        openai = {**get_tts_provider_defaults("openai_audio_speech"), **configs.get("openai_audio_speech", {})}
        compatible = {**get_tts_provider_defaults("openai_compatible_audio_speech"), **configs.get("openai_compatible_audio_speech", {})}
        elevenlabs = {**get_tts_provider_defaults("elevenlabs"), **configs.get("elevenlabs", {})}
        browser = {**get_tts_provider_defaults("browser_speech"), **configs.get("browser_speech", {})}

        self.enable_tts_check.setChecked(self._original_settings.get("enable_tts", True))

        tts_provider = str(self._original_settings.get("tts_provider", "gpt_sovits_http")).strip().lower()
        tts_provider_index = self.tts_provider_combo.findData(tts_provider)
        if tts_provider_index < 0:
            tts_provider_index = 0
        self.tts_provider_combo.setCurrentIndex(tts_provider_index)

        self.tts_api_url_edit.setText(str(gpt_sovits.get("api_url", "http://127.0.0.1:9880")))
        self.tts_ref_audio_path_edit.setText(str(gpt_sovits.get("ref_audio_path", "assets/ref_audio/refvoice.wav")))
        self.tts_ref_text_edit.setPlainText(str(gpt_sovits.get("ref_text", "")))
        self.tts_ref_language_edit.setText(str(gpt_sovits.get("ref_language", "ja")))
        self.tts_target_language_edit.setText(str(gpt_sovits.get("target_language", "ja")))

        self.tts_openai_api_key_edit.setText(str(self._tts_api_keys.get("openai_audio_speech", "")))
        self.tts_openai_api_url_edit.setText(str(openai.get("api_url", "https://api.openai.com/v1")))
        openai_model_index = self.tts_openai_model_combo.findData(str(openai.get("model", "gpt-4o-mini-tts")))
        if openai_model_index < 0:
            openai_model_index = 0
        self.tts_openai_model_combo.setCurrentIndex(openai_model_index)
        openai_voice_index = self.tts_openai_voice_combo.findData(str(openai.get("voice", "alloy")))
        if openai_voice_index < 0:
            openai_voice_index = 0
        self.tts_openai_voice_combo.setCurrentIndex(openai_voice_index)
        self.tts_openai_speed_spin.setValue(float(openai.get("speed", 1.0) or 1.0))

        self.tts_compatible_api_key_edit.setText(str(self._tts_api_keys.get("openai_compatible_audio_speech", "")))
        self.tts_compatible_api_url_edit.setText(str(compatible.get("api_url", "http://127.0.0.1:8000/v1")))
        self.tts_compatible_model_edit.setText(str(compatible.get("model", "tts-1")))
        self.tts_compatible_voice_edit.setText(str(compatible.get("voice", "alloy")))
        self.tts_compatible_speed_spin.setValue(float(compatible.get("speed", 1.0) or 1.0))

        self.tts_elevenlabs_api_key_edit.setText(str(self._tts_api_keys.get("elevenlabs", "")))
        self.tts_elevenlabs_api_url_edit.setText(str(elevenlabs.get("api_url", "https://api.elevenlabs.io/v1")))
        elevenlabs_model_index = self.tts_elevenlabs_model_combo.findData(str(elevenlabs.get("model", "eleven_multilingual_v2")))
        if elevenlabs_model_index < 0:
            elevenlabs_model_index = 0
        self.tts_elevenlabs_model_combo.setCurrentIndex(elevenlabs_model_index)
        self.tts_elevenlabs_voice_edit.setText(str(elevenlabs.get("voice", "EXAVITQu4vr4xnSDxMaL")))
        self.tts_elevenlabs_speed_spin.setValue(float(elevenlabs.get("speed", 1.0) or 1.0))
        self.tts_elevenlabs_stability_spin.setValue(float(elevenlabs.get("stability", 0.5) or 0.5))
        self.tts_elevenlabs_similarity_spin.setValue(float(elevenlabs.get("similarity_boost", 0.75) or 0.75))
        self.tts_elevenlabs_style_spin.setValue(float(elevenlabs.get("style", 0.0) or 0.0))
        self.tts_elevenlabs_speaker_boost_check.setChecked(bool(elevenlabs.get("use_speaker_boost", True)))

        self.tts_browser_lang_edit.setText(str(browser.get("lang", "ja-JP")))
        self.tts_browser_voice_combo.setEditText(str(browser.get("voice", "")))
        self.tts_browser_rate_spin.setValue(float(browser.get("rate", 1.0) or 1.0))
        self.tts_browser_pitch_spin.setValue(float(browser.get("pitch", 1.0) or 1.0))
        self.tts_browser_volume_spin.setValue(float(browser.get("volume", 1.0) or 1.0))
        self._sync_tts_provider_ui()

    def _create_window_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)

        quick_group = QGroupBox("빠른 배치")
        quick_layout = QVBoxLayout(quick_group)
        quick_layout.setSpacing(10)
        quick_layout.addWidget(self._build_hint_label("자주 쓰는 위치를 먼저 고른 뒤, 아래에서 좌표와 크기를 미세 조정할 수 있습니다."))

        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(10)
        center_btn = QPushButton("화면 중앙")
        center_btn.clicked.connect(self._preset_center)
        preset_layout.addWidget(center_btn)

        br_btn = QPushButton("우측 하단")
        br_btn.clicked.connect(self._preset_bottom_right)
        preset_layout.addWidget(br_btn)

        bl_btn = QPushButton("좌측 하단")
        bl_btn.clicked.connect(self._preset_bottom_left)
        preset_layout.addWidget(bl_btn)
        quick_layout.addLayout(preset_layout)
        layout.addWidget(quick_group)

        position_group = QGroupBox("정밀 위치")
        position_layout = QFormLayout()
        position_layout.setSpacing(8)

        self.window_x_spin = QSpinBox()
        self.window_x_spin.setRange(-9999, 9999)
        self.window_x_spin.setSuffix(" px")
        self.window_x_spin.valueChanged.connect(self._on_setting_changed)
        position_layout.addRow("X 좌표:", self.window_x_spin)

        self.window_y_spin = QSpinBox()
        self.window_y_spin.setRange(-9999, 9999)
        self.window_y_spin.setSuffix(" px")
        self.window_y_spin.valueChanged.connect(self._on_setting_changed)
        position_layout.addRow("Y 좌표:", self.window_y_spin)
        position_group.setLayout(position_layout)
        layout.addWidget(position_group)

        size_group = QGroupBox("창 크기")
        size_layout = QFormLayout()
        size_layout.setSpacing(8)

        self.window_width_spin = QSpinBox()
        self.window_width_spin.setRange(200, 3840)
        self.window_width_spin.setSuffix(" px")
        self.window_width_spin.valueChanged.connect(self._on_setting_changed)
        size_layout.addRow("너비:", self.window_width_spin)

        self.window_height_spin = QSpinBox()
        self.window_height_spin.setRange(200, 2160)
        self.window_height_spin.setSuffix(" px")
        self.window_height_spin.valueChanged.connect(self._on_setting_changed)
        size_layout.addRow("높이:", self.window_height_spin)
        size_group.setLayout(size_layout)
        layout.addWidget(size_group)

        layout.addStretch()
        return widget

    def _create_theme_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        overview_group = QGroupBox("테마 개요")
        overview_layout = QVBoxLayout(overview_group)
        overview_layout.setSpacing(12)
        overview_layout.addWidget(self._build_hint_label("설정창과 채팅창은 같은 테마 모드로 움직입니다. 위에서 라이트 또는 다크를 고르고, 필요하면 아래에서 세부 색만 조정할 수 있습니다."))

        preview_row = QHBoxLayout()
        preview_row.setSpacing(12)
        preview_row.addWidget(
            self._build_theme_mode_preview(
                "light",
                self._resolve_theme_bundle_text(THEME_PRESETS["light"], "title"),
                self._resolve_theme_bundle_text(THEME_PRESETS["light"], "description"),
            ),
            1,
        )
        preview_row.addWidget(
            self._build_theme_mode_preview(
                "dark",
                self._resolve_theme_bundle_text(THEME_PRESETS["dark"], "title"),
                self._resolve_theme_bundle_text(THEME_PRESETS["dark"], "description"),
            ),
            1,
        )

        overview_layout.addLayout(preview_row)

        variant_row = QHBoxLayout()
        variant_row.setSpacing(12)

        light_variant_group = QGroupBox("라이트 프리셋")
        light_variant_layout = QVBoxLayout(light_variant_group)
        light_variant_layout.setSpacing(10)
        for variant_id, bundle in THEME_VARIANT_PRESETS["light"].items():
            light_variant_layout.addWidget(
                self._build_theme_variant_preview(
                    "light",
                    variant_id,
                    self._resolve_theme_bundle_text(bundle, "title"),
                    self._resolve_theme_bundle_text(bundle, "description"),
                )
            )
        variant_row.addWidget(light_variant_group, 1)

        dark_variant_group = QGroupBox("다크 프리셋")
        dark_variant_layout = QVBoxLayout(dark_variant_group)
        dark_variant_layout.setSpacing(10)
        for variant_id, bundle in THEME_VARIANT_PRESETS["dark"].items():
            dark_variant_layout.addWidget(
                self._build_theme_variant_preview(
                    "dark",
                    variant_id,
                    self._resolve_theme_bundle_text(bundle, "title"),
                    self._resolve_theme_bundle_text(bundle, "description"),
                )
            )
        variant_row.addWidget(dark_variant_group, 1)

        overview_layout.addLayout(variant_row)

        self.follow_system_theme_check = self._create_toggle("현재 윈도우 앱 테마(라이트/다크)를 따라가기")
        self.follow_system_theme_check.toggled.connect(self._on_follow_system_theme_toggled)
        overview_layout.addWidget(self.follow_system_theme_check)
        layout.addWidget(overview_group)

        settings_group = QGroupBox("설정창 팔레트")
        settings_group_layout = QVBoxLayout(settings_group)
        settings_group_layout.setSpacing(12)
        settings_group_layout.addWidget(self._build_theme_color_editor("settings_window_bg_color", "설정창 바깥 배경", "설정창 전체의 기본 바탕색입니다."))
        settings_group_layout.addWidget(self._build_theme_color_editor("settings_card_bg_color", "설정 카드 배경", "타이틀 바, 카드, 탭 영역의 기본 표면색입니다."))
        settings_group_layout.addWidget(self._build_theme_color_editor("settings_input_bg_color", "입력 필드 배경", "입력창, 드롭다운, 리스트의 기본 배경색입니다."))
        layout.addWidget(settings_group)

        chat_group = QGroupBox("채팅창 팔레트")
        chat_group_layout = QVBoxLayout(chat_group)
        chat_group_layout.setSpacing(12)
        chat_group_layout.addWidget(self._build_theme_color_editor("chat_panel_bg_color", "채팅 메인 배경", "채팅창 하단 패널과 보조 위젯의 기본 배경색입니다."))
        chat_group_layout.addWidget(self._build_theme_color_editor("chat_input_bg_color", "채팅 입력 배경", "입력창과 입력 래퍼의 기본 배경색입니다."))
        chat_group_layout.addWidget(self._build_theme_color_editor("chat_assistant_bubble_color", "응답 버블 배경", "AI 응답 말풍선의 기본 배경색입니다."))
        chat_group_layout.addWidget(self._build_theme_color_editor("chat_user_bubble_color", "사용자 버블 배경", "사용자 말풍선의 기본 배경색입니다."))
        layout.addWidget(chat_group)

        accent_group = QGroupBox("포인트 색상")
        accent_group_layout = QVBoxLayout(accent_group)
        accent_group_layout.setSpacing(12)
        accent_group_layout.addWidget(self._build_theme_color_editor("theme_accent_color", "포인트 색상", "저장 버튼, 포커스 링, 선택 상태와 강조 요소에 사용됩니다."))
        layout.addWidget(accent_group)

        self.theme_status_label = QLabel()
        self.theme_status_label.setWordWrap(True)
        layout.addWidget(self.theme_status_label)
        layout.addStretch()

        scroll.setWidget(widget)
        return scroll

    def _create_model_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        preset_group = QGroupBox("빠른 배치")
        preset_group_layout = QVBoxLayout(preset_group)
        preset_group_layout.setSpacing(10)
        preset_group_layout.addWidget(self._build_hint_label("자주 쓰는 위치를 먼저 고른 뒤, 아래 슬라이더로 세밀하게 맞추면 더 편합니다."))

        preset_layout = QHBoxLayout()
        center_btn = QPushButton("중앙")
        center_btn.clicked.connect(lambda: self._set_model_position(50, 50))
        preset_layout.addWidget(center_btn)
        left_btn = QPushButton("좌측")
        left_btn.clicked.connect(lambda: self._set_model_position(25, 50))
        preset_layout.addWidget(left_btn)
        right_btn = QPushButton("우측")
        right_btn.clicked.connect(lambda: self._set_model_position(75, 50))
        preset_layout.addWidget(right_btn)
        preset_group_layout.addLayout(preset_layout)
        layout.addWidget(preset_group)

        scale_group = QGroupBox("모델 크기")
        scale_layout = QVBoxLayout()
        scale_layout.setSpacing(8)
        scale_layout.setContentsMargins(10, 15, 10, 10)
        scale_form = QFormLayout()
        self.model_scale_spin = QDoubleSpinBox()
        self.model_scale_spin.setRange(0.1, 2.0)
        self.model_scale_spin.setSingleStep(0.05)
        self.model_scale_spin.setDecimals(2)
        self.model_scale_spin.setSuffix("x")
        self.model_scale_spin.valueChanged.connect(self._on_setting_changed)
        scale_form.addRow("스케일:", self.model_scale_spin)
        scale_layout.addLayout(scale_form)
        scale_layout.addWidget(self._build_hint_label("1.00x를 기준으로 모델 전체 크기를 조정합니다."))

        self.scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.scale_slider.setRange(10, 200)
        self.scale_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.scale_slider.setTickInterval(10)
        scale_layout.addWidget(self.scale_slider)
        self.model_scale_spin.valueChanged.connect(lambda v: self.scale_slider.setValue(int(v * 100)))
        self.scale_slider.valueChanged.connect(lambda v: self.model_scale_spin.setValue(v / 100.0))
        scale_group.setLayout(scale_layout)
        layout.addWidget(scale_group)

        x_group = QGroupBox("모델 X 위치")
        x_layout = QVBoxLayout()
        x_layout.setSpacing(8)
        x_layout.setContentsMargins(10, 15, 10, 10)
        x_layout.addWidget(self._build_hint_label("모델을 화면의 왼쪽과 오른쪽 사이에서 조정합니다."))
        x_info = QHBoxLayout()
        x_info.addWidget(QLabel("왼쪽"))
        x_info.addStretch()
        self.model_x_value_label = QLabel("50%")
        self.model_x_value_label.setObjectName("ValueBadge")
        x_info.addWidget(self.model_x_value_label)
        x_info.addStretch()
        x_info.addWidget(QLabel("오른쪽"))
        x_layout.addLayout(x_info)
        self.model_x_slider = QSlider(Qt.Orientation.Horizontal)
        self.model_x_slider.setRange(-100, 200)
        self.model_x_slider.valueChanged.connect(lambda v: self.model_x_value_label.setText(f"{v}%"))
        self.model_x_slider.valueChanged.connect(self._on_setting_changed)
        x_layout.addWidget(self.model_x_slider)
        x_group.setLayout(x_layout)
        layout.addWidget(x_group)

        y_group = QGroupBox("모델 Y 위치")
        y_layout = QVBoxLayout()
        y_layout.setSpacing(8)
        y_layout.setContentsMargins(10, 15, 10, 10)
        y_layout.addWidget(self._build_hint_label("모델을 화면의 위쪽과 아래쪽 사이에서 조정합니다."))
        y_info = QHBoxLayout()
        y_info.addWidget(QLabel("위쪽"))
        y_info.addStretch()
        self.model_y_value_label = QLabel("50%")
        self.model_y_value_label.setObjectName("ValueBadge")
        y_info.addWidget(self.model_y_value_label)
        y_info.addStretch()
        y_info.addWidget(QLabel("아래쪽"))
        y_layout.addLayout(y_info)
        self.model_y_slider = QSlider(Qt.Orientation.Horizontal)
        self.model_y_slider.setRange(-100, 200)
        self.model_y_slider.valueChanged.connect(lambda v: self.model_y_value_label.setText(f"{v}%"))
        self.model_y_slider.valueChanged.connect(self._on_setting_changed)
        y_layout.addWidget(self.model_y_slider)
        y_group.setLayout(y_layout)
        layout.addWidget(y_group)

        model_path_group = QGroupBox("Live2D 모델 파일")
        model_path_layout = QVBoxLayout(model_path_group)
        model_path_layout.setSpacing(10)
        model_path_layout.addWidget(self._build_hint_label("`.model3.json` 파일 경로를 직접 지정합니다. 저장 전에도 미리보기에서 모델이 다시 로드됩니다."))

        model_path_row = QHBoxLayout()
        model_path_row.setSpacing(8)
        self.model_json_path_edit = QLineEdit()
        self.model_json_path_edit.setPlaceholderText("예: assets/live2d_models/jksalt/jksalt.model3.json")
        self.model_json_path_edit.textChanged.connect(self._on_setting_changed)
        model_path_row.addWidget(self.model_json_path_edit, 1)

        browse_model_btn = QPushButton("찾아보기")
        browse_model_btn.clicked.connect(self._browse_live2d_model_path)
        model_path_row.addWidget(browse_model_btn)
        model_path_layout.addLayout(model_path_row)
        layout.addWidget(model_path_group)

        layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _create_llm_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        provider_group = QGroupBox("공급자와 인증")
        provider_form = QFormLayout(provider_group)
        provider_form.setSpacing(8)
        provider_form.setContentsMargins(10, 15, 10, 10)

        self.llm_provider_combo = QComboBox()
        self._provider_values = []
        catalog = get_llm_provider_catalog()
        for provider in sorted(catalog.keys()):
            meta = catalog[provider]
            self.llm_provider_combo.addItem(self._llm_provider_label(provider, meta), provider)
            self._provider_values.append(provider)
        self._llm_api_keys = {}
        self._llm_models = {}
        self._llm_model_params = {}
        self._active_model_key_by_provider = {}
        self.llm_provider_combo.currentIndexChanged.connect(self._on_llm_provider_changed)
        provider_form.addRow("공급자:", self.llm_provider_combo)

        self.llm_api_key_edit = QLineEdit()
        self.llm_api_key_edit.setPlaceholderText("선택한 공급자의 API 키")
        self.llm_api_key_edit.textChanged.connect(self._on_llm_api_key_changed)
        provider_form.addRow(
            "API 키:",
            self._build_secret_row(
                self.llm_api_key_edit,
                lambda: self._toggle_secret_field(self.llm_api_key_edit, self.llm_api_key_toggle_button),
                "llm_api_key_toggle_button",
            ),
        )
        provider_form.addRow(self._build_hint_label("민감한 값은 기본적으로 숨겨집니다. 현재 선택한 공급자 기준으로 저장됩니다."))
        layout.addWidget(provider_group)

        model_group = QGroupBox("모델과 응답 스타일")
        model_form = QFormLayout(model_group)
        model_form.setSpacing(8)
        model_form.setContentsMargins(10, 15, 10, 10)

        self.llm_model_edit = QLineEdit()
        self.llm_model_edit.setPlaceholderText("예: gemini-3-flash-preview, gpt-4o-mini")
        self.llm_model_edit.textChanged.connect(self._on_llm_model_changed)
        model_form.addRow("모델:", self.llm_model_edit)

        self.llm_temperature_spin = QDoubleSpinBox()
        self.llm_temperature_spin.setRange(0.0, 2.0)
        self.llm_temperature_spin.setSingleStep(0.1)
        self.llm_temperature_spin.setDecimals(2)
        self.llm_temperature_spin.valueChanged.connect(self._on_llm_param_changed)
        model_form.addRow("Temperature:", self.llm_temperature_spin)

        self.llm_top_p_spin = QDoubleSpinBox()
        self.llm_top_p_spin.setRange(0.0, 1.0)
        self.llm_top_p_spin.setSingleStep(0.05)
        self.llm_top_p_spin.setDecimals(2)
        self.llm_top_p_spin.valueChanged.connect(self._on_llm_param_changed)
        model_form.addRow("Top P:", self.llm_top_p_spin)

        self.llm_max_tokens_spin = QSpinBox()
        self.llm_max_tokens_spin.setRange(0, 65536)
        self.llm_max_tokens_spin.setSpecialValueText("자동")
        self.llm_max_tokens_spin.valueChanged.connect(self._on_llm_param_changed)
        model_form.addRow("Max Tokens:", self.llm_max_tokens_spin)
        model_form.addRow(self._build_hint_label("Temperature와 Top P는 창의성 조절용이고, Max Tokens는 응답 길이 제한입니다."))
        layout.addWidget(model_group)

        self.custom_api_group = QGroupBox("Custom API")
        custom_form = QFormLayout(self.custom_api_group)
        custom_form.setSpacing(8)
        custom_form.setContentsMargins(10, 15, 10, 10)

        self.custom_api_url_edit = QLineEdit()
        self.custom_api_url_edit.setPlaceholderText("예: https://api.example.com/v1/chat/completions")
        self.custom_api_url_edit.textChanged.connect(self._on_setting_changed)
        custom_form.addRow("URL:", self.custom_api_url_edit)

        self.custom_api_key_or_password_edit = QLineEdit()
        self.custom_api_key_or_password_edit.setPlaceholderText("키 또는 패스워드")
        self.custom_api_key_or_password_edit.textChanged.connect(self._on_setting_changed)
        custom_form.addRow(
            "키/패스워드:",
            self._build_secret_row(
                self.custom_api_key_or_password_edit,
                lambda: self._toggle_secret_field(self.custom_api_key_or_password_edit, self.custom_api_secret_toggle_button),
                "custom_api_secret_toggle_button",
            ),
        )

        self.custom_api_request_model_edit = QLineEdit()
        self.custom_api_request_model_edit.setPlaceholderText("요청 모델명")
        self.custom_api_request_model_edit.textChanged.connect(self._on_setting_changed)
        custom_form.addRow("요청 모델:", self.custom_api_request_model_edit)

        self.custom_api_format_combo = QComboBox()
        custom_format_options = [
            ("OpenAI Compatible", LLMFormat.OPENAI_COMPATIBLE.value),
            ("OpenAI Response API", LLMFormat.OPENAI_RESPONSE_API.value),
            ("Anthropic Claude", LLMFormat.ANTHROPIC.value),
            ("Mistral", LLMFormat.MISTRAL.value),
            ("Google Cloud", LLMFormat.GOOGLE_CLOUD.value),
            ("Cohere", LLMFormat.COHERE.value),
        ]
        for label, value in custom_format_options:
            self.custom_api_format_combo.addItem(label, value)
        self.custom_api_format_combo.currentIndexChanged.connect(self._on_setting_changed)
        custom_form.addRow("포맷:", self.custom_api_format_combo)
        custom_form.addRow(self._build_hint_label("Custom API 공급자를 선택한 경우에만 이 섹션이 사용됩니다."))

        self.custom_api_group.setVisible(False)
        layout.addWidget(self.custom_api_group)

        embedding_group = QGroupBox("임베딩 설정")
        embedding_form = QFormLayout(embedding_group)
        embedding_form.setSpacing(8)
        embedding_form.setContentsMargins(10, 15, 10, 10)

        self.embedding_provider_combo = QComboBox()
        self.embedding_provider_combo.addItem("Voyage AI", "voyage")
        self.embedding_provider_combo.currentIndexChanged.connect(self._on_setting_changed)
        embedding_form.addRow("임베딩 공급자:", self.embedding_provider_combo)

        self.embedding_api_key_edit = QLineEdit()
        self.embedding_api_key_edit.setPlaceholderText("Voyage AI API 키")
        self.embedding_api_key_edit.textChanged.connect(self._on_setting_changed)
        embedding_form.addRow(
            "임베딩 API 키:",
            self._build_secret_row(
                self.embedding_api_key_edit,
                lambda: self._toggle_secret_field(self.embedding_api_key_edit, self.embedding_api_key_toggle_button),
                "embedding_api_key_toggle_button",
            ),
        )

        self.embedding_model_combo = QComboBox()
        self.embedding_model_combo.addItem("voyage-3", "voyage-3")
        self.embedding_model_combo.currentIndexChanged.connect(self._on_setting_changed)
        embedding_form.addRow("임베딩 모델:", self.embedding_model_combo)
        embedding_form.addRow(self._build_hint_label("현재는 Voyage AI만 지원합니다. 저장 후 새 기억 생성과 유사 기억 검색에 같은 모델이 사용됩니다. API 키는 api_keys.json의 embedding_api_keys에 저장됩니다."))
        layout.addWidget(embedding_group)

        restart_group = QGroupBox("적용 안내")
        restart_layout = QVBoxLayout(restart_group)
        restart_layout.setSpacing(8)
        restart_layout.setContentsMargins(10, 15, 10, 10)

        self.llm_restart_info = QLabel("공급자, 키, 모델 변경은 일부 세션에 즉시 보이지 않을 수 있습니다. 저장 후 앱을 다시 시작하면 가장 확실하게 반영됩니다.")
        self.llm_restart_info.setWordWrap(True)
        self.llm_restart_info.setObjectName("FooterBody")
        restart_layout.addWidget(self.llm_restart_info)
        layout.addWidget(restart_group)
        layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _create_tts_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        overview_group = QGroupBox("공급자 선택")
        overview_form = QFormLayout(overview_group)
        overview_form.setSpacing(8)
        overview_form.setContentsMargins(10, 15, 10, 10)

        self.enable_tts_check = self._create_toggle("일본어 응답 TTS 활성화")
        self.enable_tts_check.toggled.connect(self._on_setting_changed)
        overview_form.addRow(self.enable_tts_check)

        self.tts_provider_combo = QComboBox()
        for provider_id, meta in self._tts_catalog.items():
            self.tts_provider_combo.addItem(self._tts_provider_label(provider_id, meta), provider_id)
        self.tts_provider_combo.currentIndexChanged.connect(self._on_tts_provider_changed)
        overview_form.addRow("공급자:", self.tts_provider_combo)

        self.tts_provider_hint_label = QLabel("")
        self.tts_provider_hint_label.setWordWrap(True)
        self.tts_provider_hint_label.setObjectName("InlineHint")
        overview_form.addRow(self.tts_provider_hint_label)
        layout.addWidget(overview_group)

        self._tts_provider_pages = {}
        self.tts_provider_stack = QStackedWidget()

        gpt_page = QWidget()
        gpt_layout = QVBoxLayout(gpt_page)
        gpt_layout.setSpacing(12)
        gpt_layout.setContentsMargins(0, 0, 0, 0)

        gpt_connection_group = QGroupBox("연결")
        gpt_connection_form = QFormLayout(gpt_connection_group)
        gpt_connection_form.setSpacing(8)
        gpt_connection_form.setContentsMargins(10, 15, 10, 10)
        self.tts_api_url_edit = QLineEdit()
        self.tts_api_url_edit.setPlaceholderText("예: http://127.0.0.1:9880")
        self.tts_api_url_edit.textChanged.connect(self._on_setting_changed)
        gpt_connection_form.addRow("TTS API URL:", self.tts_api_url_edit)
        gpt_layout.addWidget(gpt_connection_group)

        gpt_reference_group = QGroupBox("참조 음성")
        gpt_reference_form = QFormLayout(gpt_reference_group)
        gpt_reference_form.setSpacing(8)
        gpt_reference_form.setContentsMargins(10, 15, 10, 10)

        audio_row = QHBoxLayout()
        audio_row.setSpacing(8)
        self.tts_ref_audio_path_edit = QLineEdit()
        self.tts_ref_audio_path_edit.setPlaceholderText("예: assets/ref_audio/refvoice.wav")
        self.tts_ref_audio_path_edit.textChanged.connect(self._on_setting_changed)
        audio_row.addWidget(self.tts_ref_audio_path_edit, 1)

        browse_audio_btn = QPushButton("찾아보기")
        browse_audio_btn.clicked.connect(self._browse_tts_ref_audio_path)
        audio_row.addWidget(browse_audio_btn)
        gpt_reference_form.addRow("참조 오디오:", audio_row)

        self.tts_ref_text_edit = QPlainTextEdit()
        self.tts_ref_text_edit.setPlaceholderText("참조 오디오의 원문 텍스트")
        self.tts_ref_text_edit.setFixedHeight(96)
        self.tts_ref_text_edit.textChanged.connect(self._on_setting_changed)
        gpt_reference_form.addRow("참조 텍스트:", self.tts_ref_text_edit)

        self.tts_ref_language_edit = QLineEdit()
        self.tts_ref_language_edit.setPlaceholderText("예: ja")
        self.tts_ref_language_edit.textChanged.connect(self._on_setting_changed)
        gpt_reference_form.addRow("참조 언어:", self.tts_ref_language_edit)

        self.tts_target_language_edit = QLineEdit()
        self.tts_target_language_edit.setPlaceholderText("예: ja")
        self.tts_target_language_edit.textChanged.connect(self._on_setting_changed)
        gpt_reference_form.addRow("출력 언어:", self.tts_target_language_edit)
        gpt_reference_form.addRow(self._build_hint_label("참조 음성 기반 합성입니다. 로컬 서버나 별도 머신의 GPT-SoVITS 엔드포인트를 그대로 지정할 수 있습니다."))
        gpt_layout.addWidget(gpt_reference_group)
        gpt_layout.addStretch()
        self.tts_provider_stack.addWidget(gpt_page)
        self._tts_provider_pages["gpt_sovits_http"] = gpt_page

        openai_page = QWidget()
        openai_layout = QVBoxLayout(openai_page)
        openai_layout.setSpacing(12)
        openai_layout.setContentsMargins(0, 0, 0, 0)

        openai_connection_group = QGroupBox("OpenAI 연결")
        openai_connection_form = QFormLayout(openai_connection_group)
        openai_connection_form.setSpacing(8)
        openai_connection_form.setContentsMargins(10, 15, 10, 10)
        self.tts_openai_api_key_edit = QLineEdit()
        self.tts_openai_api_key_edit.setPlaceholderText("OpenAI API 키")
        self.tts_openai_api_key_edit.textChanged.connect(self._on_setting_changed)
        openai_connection_form.addRow(
            "API 키:",
            self._build_secret_row(
                self.tts_openai_api_key_edit,
                lambda: self._toggle_secret_field(self.tts_openai_api_key_edit, self.tts_openai_api_key_toggle_button),
                "tts_openai_api_key_toggle_button",
            ),
        )
        self.tts_openai_api_url_edit = QLineEdit()
        self.tts_openai_api_url_edit.setPlaceholderText("예: https://api.openai.com/v1")
        self.tts_openai_api_url_edit.textChanged.connect(self._on_setting_changed)
        openai_connection_form.addRow("API URL:", self.tts_openai_api_url_edit)
        openai_layout.addWidget(openai_connection_group)

        openai_voice_group = QGroupBox("모델과 음성")
        openai_voice_form = QFormLayout(openai_voice_group)
        openai_voice_form.setSpacing(8)
        openai_voice_form.setContentsMargins(10, 15, 10, 10)
        self.tts_openai_model_combo = QComboBox()
        for model_name in ("gpt-4o-mini-tts", "tts-1", "tts-1-hd"):
            self.tts_openai_model_combo.addItem(model_name, model_name)
        self.tts_openai_model_combo.currentIndexChanged.connect(self._on_setting_changed)
        openai_voice_form.addRow("모델:", self.tts_openai_model_combo)
        self.tts_openai_voice_combo = QComboBox()
        for voice_name in ("alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse", "marin", "cedar"):
            self.tts_openai_voice_combo.addItem(voice_name, voice_name)
        self.tts_openai_voice_combo.currentIndexChanged.connect(self._on_setting_changed)
        openai_voice_form.addRow("음성:", self.tts_openai_voice_combo)
        self.tts_openai_speed_spin = QDoubleSpinBox()
        self.tts_openai_speed_spin.setRange(0.25, 4.0)
        self.tts_openai_speed_spin.setSingleStep(0.05)
        self.tts_openai_speed_spin.setDecimals(2)
        self.tts_openai_speed_spin.setValue(1.0)
        self.tts_openai_speed_spin.valueChanged.connect(self._on_setting_changed)
        openai_voice_form.addRow("속도:", self.tts_openai_speed_spin)
        openai_voice_form.addRow(self._build_hint_label("AIRI의 OpenAI Speech 설정처럼 API URL, 모델, 음성, 속도를 분리했습니다. 응답 포맷은 립싱크 분석을 위해 WAV로 고정합니다."))
        openai_layout.addWidget(openai_voice_group)
        openai_layout.addStretch()
        self.tts_provider_stack.addWidget(openai_page)
        self._tts_provider_pages["openai_audio_speech"] = openai_page

        compatible_page = QWidget()
        compatible_layout = QVBoxLayout(compatible_page)
        compatible_layout.setSpacing(12)
        compatible_layout.setContentsMargins(0, 0, 0, 0)

        compatible_connection_group = QGroupBox("호환 API 연결")
        compatible_connection_form = QFormLayout(compatible_connection_group)
        compatible_connection_form.setSpacing(8)
        compatible_connection_form.setContentsMargins(10, 15, 10, 10)
        self.tts_compatible_api_key_edit = QLineEdit()
        self.tts_compatible_api_key_edit.setPlaceholderText("필요한 경우에만 API 키 입력")
        self.tts_compatible_api_key_edit.textChanged.connect(self._on_setting_changed)
        compatible_connection_form.addRow(
            "API 키:",
            self._build_secret_row(
                self.tts_compatible_api_key_edit,
                lambda: self._toggle_secret_field(self.tts_compatible_api_key_edit, self.tts_compatible_api_key_toggle_button),
                "tts_compatible_api_key_toggle_button",
            ),
        )
        self.tts_compatible_api_url_edit = QLineEdit()
        self.tts_compatible_api_url_edit.setPlaceholderText("예: http://127.0.0.1:8000/v1")
        self.tts_compatible_api_url_edit.textChanged.connect(self._on_setting_changed)
        compatible_connection_form.addRow("API URL:", self.tts_compatible_api_url_edit)
        compatible_layout.addWidget(compatible_connection_group)

        compatible_voice_group = QGroupBox("모델과 음성")
        compatible_voice_form = QFormLayout(compatible_voice_group)
        compatible_voice_form.setSpacing(8)
        compatible_voice_form.setContentsMargins(10, 15, 10, 10)
        self.tts_compatible_model_edit = QLineEdit()
        self.tts_compatible_model_edit.setPlaceholderText("예: tts-1")
        self.tts_compatible_model_edit.textChanged.connect(self._on_setting_changed)
        compatible_voice_form.addRow("모델:", self.tts_compatible_model_edit)
        self.tts_compatible_voice_edit = QLineEdit()
        self.tts_compatible_voice_edit.setPlaceholderText("예: alloy")
        self.tts_compatible_voice_edit.textChanged.connect(self._on_setting_changed)
        compatible_voice_form.addRow("음성:", self.tts_compatible_voice_edit)
        self.tts_compatible_speed_spin = QDoubleSpinBox()
        self.tts_compatible_speed_spin.setRange(0.25, 4.0)
        self.tts_compatible_speed_spin.setSingleStep(0.05)
        self.tts_compatible_speed_spin.setDecimals(2)
        self.tts_compatible_speed_spin.setValue(1.0)
        self.tts_compatible_speed_spin.valueChanged.connect(self._on_setting_changed)
        compatible_voice_form.addRow("속도:", self.tts_compatible_speed_spin)
        compatible_voice_form.addRow(self._build_hint_label("로컬 TTS 서버나 프록시 API처럼 OpenAI 음성 합성 스펙을 흉내내는 엔드포인트에 맞춘 범용 설정입니다."))
        compatible_layout.addWidget(compatible_voice_group)
        compatible_layout.addStretch()
        self.tts_provider_stack.addWidget(compatible_page)
        self._tts_provider_pages["openai_compatible_audio_speech"] = compatible_page

        elevenlabs_page = QWidget()
        elevenlabs_layout = QVBoxLayout(elevenlabs_page)
        elevenlabs_layout.setSpacing(12)
        elevenlabs_layout.setContentsMargins(0, 0, 0, 0)

        elevenlabs_connection_group = QGroupBox("ElevenLabs 연결")
        elevenlabs_connection_form = QFormLayout(elevenlabs_connection_group)
        elevenlabs_connection_form.setSpacing(8)
        elevenlabs_connection_form.setContentsMargins(10, 15, 10, 10)
        self.tts_elevenlabs_api_key_edit = QLineEdit()
        self.tts_elevenlabs_api_key_edit.setPlaceholderText("ElevenLabs API 키")
        self.tts_elevenlabs_api_key_edit.textChanged.connect(self._on_setting_changed)
        elevenlabs_connection_form.addRow(
            "API 키:",
            self._build_secret_row(
                self.tts_elevenlabs_api_key_edit,
                lambda: self._toggle_secret_field(self.tts_elevenlabs_api_key_edit, self.tts_elevenlabs_api_key_toggle_button),
                "tts_elevenlabs_api_key_toggle_button",
            ),
        )
        self.tts_elevenlabs_api_url_edit = QLineEdit()
        self.tts_elevenlabs_api_url_edit.setPlaceholderText("예: https://api.elevenlabs.io/v1")
        self.tts_elevenlabs_api_url_edit.textChanged.connect(self._on_setting_changed)
        elevenlabs_connection_form.addRow("API URL:", self.tts_elevenlabs_api_url_edit)
        elevenlabs_layout.addWidget(elevenlabs_connection_group)

        elevenlabs_voice_group = QGroupBox("모델과 음성 스타일")
        elevenlabs_voice_form = QFormLayout(elevenlabs_voice_group)
        elevenlabs_voice_form.setSpacing(8)
        elevenlabs_voice_form.setContentsMargins(10, 15, 10, 10)
        self.tts_elevenlabs_model_combo = QComboBox()
        for model_name in ("eleven_multilingual_v2", "eleven_multilingual_v1", "eleven_monolingual_v1"):
            self.tts_elevenlabs_model_combo.addItem(model_name, model_name)
        self.tts_elevenlabs_model_combo.currentIndexChanged.connect(self._on_setting_changed)
        elevenlabs_voice_form.addRow("모델:", self.tts_elevenlabs_model_combo)
        self.tts_elevenlabs_voice_edit = QLineEdit()
        self.tts_elevenlabs_voice_edit.setPlaceholderText("예: EXAVITQu4vr4xnSDxMaL")
        self.tts_elevenlabs_voice_edit.textChanged.connect(self._on_setting_changed)
        elevenlabs_voice_form.addRow("Voice ID:", self.tts_elevenlabs_voice_edit)
        self.tts_elevenlabs_speed_spin = QDoubleSpinBox()
        self.tts_elevenlabs_speed_spin.setRange(0.5, 2.0)
        self.tts_elevenlabs_speed_spin.setSingleStep(0.05)
        self.tts_elevenlabs_speed_spin.setDecimals(2)
        self.tts_elevenlabs_speed_spin.setValue(1.0)
        self.tts_elevenlabs_speed_spin.valueChanged.connect(self._on_setting_changed)
        elevenlabs_voice_form.addRow("속도:", self.tts_elevenlabs_speed_spin)
        self.tts_elevenlabs_stability_spin = QDoubleSpinBox()
        self.tts_elevenlabs_stability_spin.setRange(0.0, 1.0)
        self.tts_elevenlabs_stability_spin.setSingleStep(0.05)
        self.tts_elevenlabs_stability_spin.setDecimals(2)
        self.tts_elevenlabs_stability_spin.valueChanged.connect(self._on_setting_changed)
        elevenlabs_voice_form.addRow("Stability:", self.tts_elevenlabs_stability_spin)
        self.tts_elevenlabs_similarity_spin = QDoubleSpinBox()
        self.tts_elevenlabs_similarity_spin.setRange(0.0, 1.0)
        self.tts_elevenlabs_similarity_spin.setSingleStep(0.05)
        self.tts_elevenlabs_similarity_spin.setDecimals(2)
        self.tts_elevenlabs_similarity_spin.valueChanged.connect(self._on_setting_changed)
        elevenlabs_voice_form.addRow("Similarity Boost:", self.tts_elevenlabs_similarity_spin)
        self.tts_elevenlabs_style_spin = QDoubleSpinBox()
        self.tts_elevenlabs_style_spin.setRange(0.0, 1.0)
        self.tts_elevenlabs_style_spin.setSingleStep(0.05)
        self.tts_elevenlabs_style_spin.setDecimals(2)
        self.tts_elevenlabs_style_spin.valueChanged.connect(self._on_setting_changed)
        elevenlabs_voice_form.addRow("Style:", self.tts_elevenlabs_style_spin)
        self.tts_elevenlabs_speaker_boost_check = self._create_toggle("Speaker Boost 사용")
        self.tts_elevenlabs_speaker_boost_check.toggled.connect(self._on_setting_changed)
        elevenlabs_voice_form.addRow(self.tts_elevenlabs_speaker_boost_check)
        elevenlabs_voice_form.addRow(self._build_hint_label("AIRI 코드의 ElevenLabs 설정에서 핵심인 모델, Voice ID, stability, similarity boost, style, speaker boost를 그대로 가져왔습니다."))
        elevenlabs_layout.addWidget(elevenlabs_voice_group)
        elevenlabs_layout.addStretch()
        self.tts_provider_stack.addWidget(elevenlabs_page)
        self._tts_provider_pages["elevenlabs"] = elevenlabs_page

        browser_page = QWidget()
        browser_layout = QVBoxLayout(browser_page)
        browser_layout.setSpacing(12)
        browser_layout.setContentsMargins(0, 0, 0, 0)

        browser_group = QGroupBox("브라우저 기본 TTS")
        browser_form = QFormLayout(browser_group)
        browser_form.setSpacing(8)
        browser_form.setContentsMargins(10, 15, 10, 10)
        self.tts_browser_lang_edit = QLineEdit()
        self.tts_browser_lang_edit.setPlaceholderText("예: ja-JP")
        self.tts_browser_lang_edit.textChanged.connect(self._on_browser_tts_lang_changed)
        browser_form.addRow("언어:", self.tts_browser_lang_edit)

        self.tts_browser_voice_lang_filter_combo = QComboBox()
        self.tts_browser_voice_lang_filter_combo.addItem("전체 언어", "")
        self.tts_browser_voice_lang_filter_combo.currentIndexChanged.connect(self._on_browser_tts_language_filter_changed)
        browser_form.addRow("목록 필터:", self.tts_browser_voice_lang_filter_combo)

        browser_voice_row = QHBoxLayout()
        browser_voice_row.setSpacing(8)
        self.tts_browser_voice_combo = QComboBox()
        self.tts_browser_voice_combo.setEditable(True)
        self.tts_browser_voice_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.tts_browser_voice_combo.setPlaceholderText("사용 가능한 음성을 자동으로 불러옵니다")
        self.tts_browser_voice_combo.currentIndexChanged.connect(self._on_setting_changed)
        self.tts_browser_voice_combo.currentTextChanged.connect(self._on_setting_changed)
        browser_voice_row.addWidget(self.tts_browser_voice_combo, 1)
        self.tts_browser_voice_refresh_button = QPushButton("새로고침")
        self.tts_browser_voice_refresh_button.clicked.connect(self._request_browser_tts_voices)
        browser_voice_row.addWidget(self.tts_browser_voice_refresh_button)
        browser_form.addRow("음성:", browser_voice_row)

        self.tts_browser_voice_status_label = self._build_hint_label(
            "설정창이 열려 있는 현재 ENE 웹뷰 환경에서 음성 목록을 읽습니다. 다른 PC에서는 그 환경 기준 목록이 다시 표시됩니다."
        )
        browser_form.addRow(self.tts_browser_voice_status_label)

        self.tts_browser_rate_spin = QDoubleSpinBox()
        self.tts_browser_rate_spin.setRange(0.1, 3.0)
        self.tts_browser_rate_spin.setSingleStep(0.05)
        self.tts_browser_rate_spin.setDecimals(2)
        self.tts_browser_rate_spin.setValue(1.0)
        self.tts_browser_rate_spin.valueChanged.connect(self._on_setting_changed)
        browser_form.addRow("속도:", self.tts_browser_rate_spin)
        self.tts_browser_pitch_spin = QDoubleSpinBox()
        self.tts_browser_pitch_spin.setRange(0.0, 2.0)
        self.tts_browser_pitch_spin.setSingleStep(0.05)
        self.tts_browser_pitch_spin.setDecimals(2)
        self.tts_browser_pitch_spin.setValue(1.0)
        self.tts_browser_pitch_spin.valueChanged.connect(self._on_setting_changed)
        browser_form.addRow("Pitch:", self.tts_browser_pitch_spin)
        self.tts_browser_volume_spin = QDoubleSpinBox()
        self.tts_browser_volume_spin.setRange(0.0, 1.0)
        self.tts_browser_volume_spin.setSingleStep(0.05)
        self.tts_browser_volume_spin.setDecimals(2)
        self.tts_browser_volume_spin.setValue(1.0)
        self.tts_browser_volume_spin.valueChanged.connect(self._on_setting_changed)
        browser_form.addRow("볼륨:", self.tts_browser_volume_spin)
        browser_form.addRow(self._build_hint_label("테스트용/폴백용 공급자입니다. API 키 없이 바로 말하게 할 수 있지만, 음질과 사용 가능한 음성은 배포 환경의 브라우저/OS에 따라 달라집니다. 저장된 음성이 현재 환경에 없으면 같은 언어 음성이나 시스템 기본 음성으로 자연스럽게 대체됩니다. 립싱크는 적용되지 않습니다."))
        browser_layout.addWidget(browser_group)
        browser_layout.addStretch()
        self.tts_provider_stack.addWidget(browser_page)
        self._tts_provider_pages["browser_speech"] = browser_page

        layout.addWidget(self.tts_provider_stack)

        layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _create_behavior_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        display_group = QGroupBox("표시 요소")
        display_layout = QVBoxLayout(display_group)
        display_layout.setSpacing(8)

        self.show_drag_bar_check = self._create_toggle("드래그 바 표시")
        self.show_drag_bar_check.toggled.connect(self._on_setting_changed)
        display_layout.addWidget(self.show_drag_bar_check)

        self.show_recent_reroll_button_check = self._create_toggle("최근 메시지 리롤 버튼 표시")
        self.show_recent_reroll_button_check.toggled.connect(self._on_setting_changed)
        display_layout.addWidget(self.show_recent_reroll_button_check)

        self.show_recent_edit_button_check = self._create_toggle("최근 메시지 수정 버튼 표시")
        self.show_recent_edit_button_check.toggled.connect(self._on_setting_changed)
        display_layout.addWidget(self.show_recent_edit_button_check)

        self.show_token_usage_bubble_check = self._create_toggle("대화 토큰 확인")
        self.show_token_usage_bubble_check.toggled.connect(self._on_setting_changed)
        display_layout.addWidget(self.show_token_usage_bubble_check)

        self.mouse_tracking_check = self._create_toggle("마우스 트래킹 활성화")
        self.mouse_tracking_check.toggled.connect(self._on_setting_changed)
        display_layout.addWidget(self.mouse_tracking_check)
        display_layout.addWidget(self._build_hint_label("기본 노출 요소와 마우스 상호작용을 한 묶음으로 관리합니다."))
        layout.addWidget(display_group)

        action_group = QGroupBox("대화와 보조 버튼")
        action_layout = QVBoxLayout(action_group)
        action_layout.setSpacing(8)
        self.show_manual_summary_button_check = self._create_toggle("수동 요약 버튼 표시")
        self.show_manual_summary_button_check.toggled.connect(self._on_setting_changed)
        action_layout.addWidget(self.show_manual_summary_button_check)

        self.show_obsidian_note_button_check = self._create_toggle("노트 버튼 표시")
        self.show_obsidian_note_button_check.toggled.connect(self._on_setting_changed)
        action_layout.addWidget(self.show_obsidian_note_button_check)

        self.show_mood_toggle_button_check = self._create_toggle("기분 버튼 표시")
        self.show_mood_toggle_button_check.toggled.connect(self._on_setting_changed)
        action_layout.addWidget(self.show_mood_toggle_button_check)
        action_layout.addWidget(self._build_hint_label("자주 누르는 버튼만 켜두면 화면이 덜 복잡해집니다."))
        layout.addWidget(action_group)

        ptt_group = QGroupBox("음성 입력 (전역 PTT)")
        ptt_layout = QFormLayout(ptt_group)
        ptt_layout.setSpacing(8)
        ptt_layout.setContentsMargins(10, 15, 10, 10)

        self.enable_global_ptt_check = self._create_toggle("전역 Push-to-Talk 활성화")
        self.enable_global_ptt_check.toggled.connect(self._on_setting_changed)
        ptt_layout.addRow(self.enable_global_ptt_check)

        self.interrupt_tts_on_ptt_check = self._create_toggle("PTT 시작 시 ENE 음성 출력 끊기")
        self.interrupt_tts_on_ptt_check.toggled.connect(self._on_setting_changed)
        ptt_layout.addRow(self.interrupt_tts_on_ptt_check)

        ptt_hotkey_row = QHBoxLayout()
        self.global_ptt_hotkey_value_label = QLabel("")
        self.global_ptt_hotkey_value_label.setMinimumWidth(140)
        self.global_ptt_hotkey_value_label.setObjectName("ValueBadge")
        ptt_hotkey_row.addWidget(self.global_ptt_hotkey_value_label)

        self.global_ptt_hotkey_set_button = QPushButton("단축키 설정")
        self.global_ptt_hotkey_set_button.clicked.connect(self._start_ptt_hotkey_capture)
        ptt_hotkey_row.addWidget(self.global_ptt_hotkey_set_button)

        self.global_ptt_hotkey_reset_button = QPushButton("기본값")
        self.global_ptt_hotkey_reset_button.clicked.connect(self._reset_ptt_hotkey)
        ptt_hotkey_row.addWidget(self.global_ptt_hotkey_reset_button)
        ptt_layout.addRow("PTT 단축키:", ptt_hotkey_row)

        self.global_ptt_hotkey_hint_label = QLabel("")
        self.global_ptt_hotkey_hint_label.setWordWrap(True)
        self.global_ptt_hotkey_hint_label.setObjectName("InlineHint")
        ptt_layout.addRow(self.global_ptt_hotkey_hint_label)

        layout.addWidget(ptt_group)

        note_group = QGroupBox("노트 설정")
        note_layout = QFormLayout(note_group)
        note_layout.setSpacing(8)
        note_layout.setContentsMargins(10, 15, 10, 10)

        self.note_include_recent_context_check = self._create_toggle("/note에 최근 대화 맥락 자동 주입")
        self.note_include_recent_context_check.toggled.connect(self._on_note_context_toggle)
        note_layout.addRow(self.note_include_recent_context_check)

        self.note_recent_context_turns_spin = QSpinBox()
        self.note_recent_context_turns_spin.setRange(0, 200)
        self.note_recent_context_turns_spin.setSpecialValueText("전체 세션")
        self.note_recent_context_turns_spin.setSuffix(" 턴")
        self.note_recent_context_turns_spin.valueChanged.connect(self._on_setting_changed)
        note_layout.addRow("주입 턴 수 (0=전체):", self.note_recent_context_turns_spin)
        layout.addWidget(note_group)

        idle_group = QGroupBox("유휴 모션")
        idle_layout = QFormLayout(idle_group)
        idle_layout.setSpacing(8)
        idle_layout.setContentsMargins(10, 15, 10, 10)
        self.idle_motion_check = self._create_toggle("유휴 모션 활성화 (말하지 않을 때 자동 움직임)")
        self.idle_motion_check.toggled.connect(self._on_setting_changed)
        idle_layout.addRow(self.idle_motion_check)

        self.idle_motion_dynamic_check = self._create_toggle("유휴 모션 다이나믹 모드")
        self.idle_motion_dynamic_check.toggled.connect(self._on_setting_changed)
        idle_layout.addRow(self.idle_motion_dynamic_check)

        self.idle_motion_strength_spin = QDoubleSpinBox()
        self.idle_motion_strength_spin.setRange(0.2, 2.0)
        self.idle_motion_strength_spin.setSingleStep(0.1)
        self.idle_motion_strength_spin.setDecimals(2)
        self.idle_motion_strength_spin.setSuffix("x")
        self.idle_motion_strength_spin.valueChanged.connect(self._on_setting_changed)
        idle_layout.addRow("유휴 모션 강도:", self.idle_motion_strength_spin)

        self.idle_motion_speed_spin = QDoubleSpinBox()
        self.idle_motion_speed_spin.setRange(0.5, 2.0)
        self.idle_motion_speed_spin.setSingleStep(0.1)
        self.idle_motion_speed_spin.setDecimals(2)
        self.idle_motion_speed_spin.setSuffix("x")
        self.idle_motion_speed_spin.valueChanged.connect(self._on_setting_changed)
        idle_layout.addRow("유휴 모션 속도:", self.idle_motion_speed_spin)
        layout.addWidget(idle_group)

        pat_group = QGroupBox("머리 쓰다듬기")
        pat_layout = QFormLayout(pat_group)
        pat_layout.setSpacing(8)
        pat_layout.setContentsMargins(10, 15, 10, 10)
        self.head_pat_check = self._create_toggle("머리 쓰다듬기 활성화")
        self.head_pat_check.toggled.connect(self._on_setting_changed)
        pat_layout.addRow(self.head_pat_check)

        self.head_pat_strength_spin = QDoubleSpinBox()
        self.head_pat_strength_spin.setRange(0.5, 2.5)
        self.head_pat_strength_spin.setSingleStep(0.1)
        self.head_pat_strength_spin.setDecimals(2)
        self.head_pat_strength_spin.setSuffix("x")
        self.head_pat_strength_spin.valueChanged.connect(self._on_setting_changed)
        pat_layout.addRow("쓰다듬기 강도:", self.head_pat_strength_spin)

        self.head_pat_fade_in_spin = QSpinBox()
        self.head_pat_fade_in_spin.setRange(50, 1000)
        self.head_pat_fade_in_spin.setSuffix(" ms")
        self.head_pat_fade_in_spin.valueChanged.connect(self._on_setting_changed)
        pat_layout.addRow("시작 페이드:", self.head_pat_fade_in_spin)

        self.head_pat_fade_out_spin = QSpinBox()
        self.head_pat_fade_out_spin.setRange(50, 1200)
        self.head_pat_fade_out_spin.setSuffix(" ms")
        self.head_pat_fade_out_spin.valueChanged.connect(self._on_setting_changed)
        pat_layout.addRow("종료 페이드:", self.head_pat_fade_out_spin)

        self.head_pat_active_emotion_combo = QComboBox()
        self._emotion_options = get_available_emotions()
        if "eyeclose" not in self._emotion_options:
            self._emotion_options.append("eyeclose")
        self.head_pat_active_emotion_combo.addItems(self._emotion_options)
        self.head_pat_active_emotion_combo.currentTextChanged.connect(self._on_setting_changed)
        pat_layout.addRow("쓰다듬기 중 감정(기본):", self.head_pat_active_emotion_combo)

        self.head_pat_active_emotion_custom_edit = QLineEdit()
        self.head_pat_active_emotion_custom_edit.setPlaceholderText("커스텀 감정 (텍스트 우선)")
        self.head_pat_active_emotion_custom_edit.textChanged.connect(self._on_setting_changed)
        pat_layout.addRow("쓰다듬기 중 감정(커스텀):", self.head_pat_active_emotion_custom_edit)

        self.head_pat_end_emotion_combo = QComboBox()
        self.head_pat_end_emotion_combo.addItems(self._emotion_options)
        self.head_pat_end_emotion_combo.currentTextChanged.connect(self._on_setting_changed)
        pat_layout.addRow("종료 감정(기본):", self.head_pat_end_emotion_combo)

        self.head_pat_end_emotion_custom_edit = QLineEdit()
        self.head_pat_end_emotion_custom_edit.setPlaceholderText("커스텀 감정 (텍스트 우선)")
        self.head_pat_end_emotion_custom_edit.textChanged.connect(self._on_setting_changed)
        pat_layout.addRow("종료 감정(커스텀):", self.head_pat_end_emotion_custom_edit)

        self.head_pat_end_emotion_duration_spin = QSpinBox()
        self.head_pat_end_emotion_duration_spin.setRange(1, 30)
        self.head_pat_end_emotion_duration_spin.setSuffix(" s")
        self.head_pat_end_emotion_duration_spin.valueChanged.connect(self._on_setting_changed)
        pat_layout.addRow("감정 유지 시간:", self.head_pat_end_emotion_duration_spin)
        layout.addWidget(pat_group)

        away_group = QGroupBox("자리 비움/유휴 감지")
        away_layout = QFormLayout(away_group)
        away_layout.setSpacing(8)
        away_layout.setContentsMargins(10, 15, 10, 10)

        self.enable_away_nudge_check = self._create_toggle("유휴 감지 자동 말걸기 활성화")
        self.enable_away_nudge_check.toggled.connect(self._on_setting_changed)
        away_layout.addRow(self.enable_away_nudge_check)

        self.away_idle_minutes_spin = QSpinBox()
        self.away_idle_minutes_spin.setRange(5, 240)
        self.away_idle_minutes_spin.setSuffix(" 분")
        self.away_idle_minutes_spin.valueChanged.connect(self._on_setting_changed)
        away_layout.addRow("유휴 시간:", self.away_idle_minutes_spin)

        self.away_diff_threshold_spin = QDoubleSpinBox()
        self.away_diff_threshold_spin.setRange(1.0, 15.0)
        self.away_diff_threshold_spin.setSingleStep(0.5)
        self.away_diff_threshold_spin.setDecimals(1)
        self.away_diff_threshold_spin.setSuffix(" %")
        self.away_diff_threshold_spin.valueChanged.connect(self._on_setting_changed)
        away_layout.addRow("화면 차이 민감도:", self.away_diff_threshold_spin)

        self.away_retry_limit_spin = QSpinBox()
        self.away_retry_limit_spin.setRange(0, 20)
        self.away_retry_limit_spin.setSuffix(" 회")
        self.away_retry_limit_spin.valueChanged.connect(self._on_setting_changed)
        away_layout.addRow("추가 재실행 횟수:", self.away_retry_limit_spin)

        layout.addWidget(away_group)

        layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _create_memory_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(12)

        search_card = QFrame()
        search_card.setObjectName("FooterCard")
        search_layout = QVBoxLayout(search_card)
        search_layout.setContentsMargins(20, 18, 20, 18)
        search_layout.setSpacing(10)

        title = QLabel("기억 검색 범위")
        title.setObjectName("FooterTitle")
        search_layout.addWidget(title)

        body = QLabel("장기기억 검색 시 최신 사용자 메시지와 함께 참고할 최근 보이는 대화 턴 수를 조절합니다. 현재 턴에만 임시 주입되고, 히스토리에는 순수 대화만 남도록 동작합니다.")
        body.setObjectName("FooterBody")
        body.setWordWrap(True)
        search_layout.addWidget(body)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(10)

        self.memory_search_recent_turns_spin = QSpinBox()
        self.memory_search_recent_turns_spin.setRange(0, 50)
        self.memory_search_recent_turns_spin.setSuffix(" 턴")
        self.memory_search_recent_turns_spin.setSpecialValueText("현재 메시지만")
        self.memory_search_recent_turns_spin.valueChanged.connect(self._on_setting_changed)
        try:
            memory_turns = int(self._original_settings.get("memory_search_recent_turns", 2) or 0)
        except Exception:
            memory_turns = 2
        self.memory_search_recent_turns_spin.setValue(max(0, min(memory_turns, 50)))
        form.addRow("검색에 포함할 최근 대화:", self.memory_search_recent_turns_spin)
        form.addRow(self._build_hint_label("예: 2턴이면 직전 사용자/에네 2쌍을 보고 현재 메시지와 함께 장기기억을 검색합니다."))

        search_layout.addLayout(form)
        layout.addWidget(search_card)

        if self._memory_manager:
            panel = MemoryDialog(self._memory_manager, self._bridge, self, embedded=True)
            panel.apply_theme(dict(self._theme_values))
            self._embedded_memory_panel = panel
            panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            panel.setMinimumSize(0, 0)
            layout.addWidget(panel)
        else:
            card = QFrame()
            card.setObjectName("FooterCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(22, 20, 22, 20)
            card_layout.setSpacing(8)

            title = QLabel("기억 관리")
            title.setObjectName("FooterTitle")
            card_layout.addWidget(title)

            body = QLabel("메모리 매니저가 초기화되지 않아 기억 목록 패널을 표시할 수 없습니다.")
            body.setObjectName("FooterBody")
            body.setWordWrap(True)
            card_layout.addWidget(body)
            layout.addWidget(card)

        layout.addStretch()
        scroll.setWidget(widget)
        return scroll

    def _create_user_profile_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QFrame()
        header.setObjectName("FooterCard")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setSpacing(6)

        title = QLabel("사용자 기억 관리")
        title.setObjectName("FooterTitle")
        header_layout.addWidget(title)

        body = QLabel("user_profile.json의 기본 정보, likes, dislikes, facts만 구조적으로 관리합니다. 원본 JSON 전체를 직접 열지 않고 필요한 항목만 수정합니다.")
        body.setObjectName("FooterBody")
        body.setWordWrap(True)
        header_layout.addWidget(body)
        layout.addWidget(header)

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        basic_group = QGroupBox("기본 정보")
        basic_layout = QVBoxLayout(basic_group)
        basic_layout.setSpacing(10)

        self.basic_info_list = QListWidget()
        self.basic_info_list.setMinimumHeight(190)
        self.basic_info_list.currentRowChanged.connect(self._on_basic_info_selected)
        basic_layout.addWidget(self.basic_info_list)

        self.basic_info_key_input = QLineEdit()
        self.basic_info_key_input.setPlaceholderText("항목 이름")
        basic_layout.addWidget(self.basic_info_key_input)

        self.basic_info_value_input = QLineEdit()
        self.basic_info_value_input.setPlaceholderText("값")
        basic_layout.addWidget(self.basic_info_value_input)

        basic_actions = QHBoxLayout()
        basic_actions.setSpacing(8)

        basic_new_btn = QPushButton("새 항목")
        basic_new_btn.clicked.connect(self._new_basic_info_item)
        basic_actions.addWidget(basic_new_btn)

        basic_apply_btn = QPushButton("목록에 반영")
        basic_apply_btn.setProperty("accent", True)
        basic_apply_btn.style().unpolish(basic_apply_btn)
        basic_apply_btn.style().polish(basic_apply_btn)
        basic_apply_btn.clicked.connect(self._apply_basic_info_item)
        basic_actions.addWidget(basic_apply_btn)

        basic_delete_btn = QPushButton("삭제")
        basic_delete_btn.clicked.connect(self._delete_basic_info_item)
        basic_actions.addWidget(basic_delete_btn)
        basic_layout.addLayout(basic_actions)

        top_row.addWidget(basic_group, 1)

        preference_group = QGroupBox("선호와 비선호")
        preference_layout = QVBoxLayout(preference_group)
        preference_layout.setSpacing(12)

        likes_row = QVBoxLayout()
        likes_row.setSpacing(10)
        likes_label = QLabel("likes")
        likes_label.setObjectName("FooterTitle")
        likes_row.addWidget(likes_label)

        likes_col = QVBoxLayout()
        likes_col.setSpacing(10)
        self.likes_list = QListWidget()
        self.likes_list.setMinimumHeight(92)
        self.likes_list.setMaximumHeight(120)
        self._configure_preference_list(self.likes_list)
        likes_col.addWidget(self.likes_list)
        self.likes_input = QLineEdit()
        self.likes_input.setPlaceholderText("좋아하는 항목 추가")
        likes_col.addWidget(self.likes_input)
        likes_actions = QHBoxLayout()
        likes_actions.setSpacing(8)
        likes_actions.addStretch()
        likes_add_btn = QPushButton("추가")
        likes_add_btn.clicked.connect(lambda: self._add_preference_item("likes"))
        likes_actions.addWidget(likes_add_btn)
        likes_delete_btn = QPushButton("삭제")
        likes_delete_btn.clicked.connect(lambda: self._delete_preference_item("likes"))
        likes_actions.addWidget(likes_delete_btn)
        likes_col.addLayout(likes_actions)
        likes_row.addLayout(likes_col)
        preference_layout.addLayout(likes_row)

        dislikes_row = QVBoxLayout()
        dislikes_row.setSpacing(10)
        dislikes_label = QLabel("dislikes")
        dislikes_label.setObjectName("FooterTitle")
        dislikes_row.addWidget(dislikes_label)

        dislikes_col = QVBoxLayout()
        dislikes_col.setSpacing(10)
        self.dislikes_list = QListWidget()
        self.dislikes_list.setMinimumHeight(92)
        self.dislikes_list.setMaximumHeight(120)
        self._configure_preference_list(self.dislikes_list)
        dislikes_col.addWidget(self.dislikes_list)
        self.dislikes_input = QLineEdit()
        self.dislikes_input.setPlaceholderText("싫어하는 항목 추가")
        dislikes_col.addWidget(self.dislikes_input)
        dislikes_actions = QHBoxLayout()
        dislikes_actions.setSpacing(8)
        dislikes_actions.addStretch()
        dislikes_add_btn = QPushButton("추가")
        dislikes_add_btn.clicked.connect(lambda: self._add_preference_item("dislikes"))
        dislikes_actions.addWidget(dislikes_add_btn)
        dislikes_delete_btn = QPushButton("삭제")
        dislikes_delete_btn.clicked.connect(lambda: self._delete_preference_item("dislikes"))
        dislikes_actions.addWidget(dislikes_delete_btn)
        dislikes_col.addLayout(dislikes_actions)
        dislikes_row.addLayout(dislikes_col)
        preference_layout.addLayout(dislikes_row)

        top_row.addWidget(preference_group, 1)
        layout.addLayout(top_row)

        facts_group = QGroupBox("facts")
        facts_layout = QHBoxLayout(facts_group)
        facts_layout.setSpacing(12)

        self.fact_list = QListWidget()
        self.fact_list.setMinimumHeight(320)
        self.fact_list.currentRowChanged.connect(self._on_fact_selected)
        facts_layout.addWidget(self.fact_list, 1)

        fact_editor_col = QVBoxLayout()
        fact_editor_col.setSpacing(10)

        self.fact_content_edit = QPlainTextEdit()
        self.fact_content_edit.setPlaceholderText("기억 내용")
        self.fact_content_edit.setMinimumHeight(150)
        fact_editor_col.addWidget(self.fact_content_edit)

        fact_meta_row = QHBoxLayout()
        fact_meta_row.setSpacing(10)

        self.fact_category_combo = QComboBox()
        self.fact_category_combo.addItems(["basic", "preference", "goal", "habit"])
        fact_meta_row.addWidget(self.fact_category_combo)

        self.fact_source_input = QLineEdit()
        self.fact_source_input.setPlaceholderText("출처")
        fact_meta_row.addWidget(self.fact_source_input, 1)
        fact_editor_col.addLayout(fact_meta_row)

        self.fact_timestamp_label = QLabel("신규 항목")
        self.fact_timestamp_label.setObjectName("FooterBody")
        fact_editor_col.addWidget(self.fact_timestamp_label)

        fact_actions = QHBoxLayout()
        fact_actions.setSpacing(8)

        fact_new_btn = QPushButton("새 항목")
        fact_new_btn.clicked.connect(self._new_fact_item)
        fact_actions.addWidget(fact_new_btn)

        fact_apply_btn = QPushButton("목록에 반영")
        fact_apply_btn.setProperty("accent", True)
        fact_apply_btn.style().unpolish(fact_apply_btn)
        fact_apply_btn.style().polish(fact_apply_btn)
        fact_apply_btn.clicked.connect(self._apply_fact_item)
        fact_actions.addWidget(fact_apply_btn)

        fact_delete_btn = QPushButton("삭제")
        fact_delete_btn.clicked.connect(self._delete_fact_item)
        fact_actions.addWidget(fact_delete_btn)
        fact_editor_col.addLayout(fact_actions)

        facts_layout.addLayout(fact_editor_col, 1)
        layout.addWidget(facts_group)

        footer_row = QHBoxLayout()
        footer_row.setSpacing(10)

        self._profile_status_label = QLabel("로드 대기")
        self._profile_status_label.setObjectName("FooterBody")
        footer_row.addWidget(self._profile_status_label)

        footer_row.addStretch()

        profile_reload_btn = QPushButton("다시 불러오기")
        profile_reload_btn.clicked.connect(self._load_user_profile_data)
        footer_row.addWidget(profile_reload_btn)

        profile_save_btn = QPushButton("저장")
        profile_save_btn.setProperty("accent", True)
        profile_save_btn.style().unpolish(profile_save_btn)
        profile_save_btn.style().polish(profile_save_btn)
        profile_save_btn.clicked.connect(self._save_user_profile_data)
        footer_row.addWidget(profile_save_btn)

        layout.addLayout(footer_row)
        layout.addStretch()

        scroll.setWidget(widget)
        self._load_user_profile_data()
        return scroll

    def _create_prompt_tab(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setSpacing(12)
        layout.setContentsMargins(10, 10, 10, 10)

        header = QFrame()
        header.setObjectName("FooterCard")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(20, 18, 20, 18)
        header_layout.setSpacing(6)

        title = QLabel("프롬프트 설정")
        title.setObjectName("FooterTitle")
        header_layout.addWidget(title)

        body = QLabel("파이썬 파일 전체를 직접 수정하지 않고 BASE_SYSTEM_PROMPT, SUB_PROMPT, EMOTIONS와 감정 사용 가이드만 안전하게 관리합니다.")
        body.setObjectName("FooterBody")
        body.setWordWrap(True)
        header_layout.addWidget(body)
        layout.addWidget(header)

        prompt_row = QHBoxLayout()
        prompt_row.setSpacing(12)

        base_group = QGroupBox("BASE_SYSTEM_PROMPT")
        base_layout = QVBoxLayout(base_group)
        base_layout.setSpacing(10)
        base_path = QLabel(str(self._prompt_path))
        base_path.setObjectName("FooterBody")
        base_path.setWordWrap(True)
        base_layout.addWidget(base_path)
        self.base_prompt_editor = QPlainTextEdit()
        self.base_prompt_editor.setMinimumHeight(320)
        self.base_prompt_editor.textChanged.connect(self._schedule_prompt_token_refresh)
        base_layout.addWidget(self.base_prompt_editor, 1)
        self._base_prompt_token_label = QLabel("BASE_SYSTEM_PROMPT 현재 토큰: 0개 · 문자 수: 0자")
        self._base_prompt_token_label.setObjectName("FooterBody")
        base_layout.addWidget(self._base_prompt_token_label)
        prompt_row.addWidget(base_group, 1)

        sub_group = QGroupBox("SUB_PROMPT 본문")
        sub_layout = QVBoxLayout(sub_group)
        sub_layout.setSpacing(10)
        sub_path = QLabel(str(self._sub_prompt_path))
        sub_path.setObjectName("FooterBody")
        sub_path.setWordWrap(True)
        sub_layout.addWidget(sub_path)
        sub_note = QLabel("감정 규칙과 감정 사용 가이드는 아래 감정 편집 카드에서 별도로 관리됩니다.")
        sub_note.setObjectName("FooterBody")
        sub_note.setWordWrap(True)
        sub_layout.addWidget(sub_note)
        self.sub_prompt_editor = QPlainTextEdit()
        self.sub_prompt_editor.setMinimumHeight(320)
        self.sub_prompt_editor.textChanged.connect(self._schedule_prompt_token_refresh)
        sub_layout.addWidget(self.sub_prompt_editor, 1)
        self._sub_prompt_token_label = QLabel("SUB_PROMPT 현재 토큰: 0개 · 문자 수: 0자")
        self._sub_prompt_token_label.setObjectName("FooterBody")
        sub_layout.addWidget(self._sub_prompt_token_label)
        prompt_row.addWidget(sub_group, 1)
        layout.addLayout(prompt_row)

        emotion_group = QGroupBox("감정 목록과 사용 가이드")
        emotion_layout = QHBoxLayout(emotion_group)
        emotion_layout.setSpacing(12)

        self.emotion_list = QListWidget()
        self.emotion_list.setMinimumHeight(260)
        self.emotion_list.currentRowChanged.connect(self._on_emotion_selected)
        emotion_layout.addWidget(self.emotion_list, 1)

        emotion_editor_col = QVBoxLayout()
        emotion_editor_col.setSpacing(10)

        self.emotion_name_input = QLineEdit()
        self.emotion_name_input.setPlaceholderText("감정 키 (예: shy)")
        emotion_editor_col.addWidget(self.emotion_name_input)

        self.emotion_guide_editor = QPlainTextEdit()
        self.emotion_guide_editor.setPlaceholderText("감정 사용 가이드")
        self.emotion_guide_editor.setMinimumHeight(180)
        emotion_editor_col.addWidget(self.emotion_guide_editor, 1)

        emotion_actions = QHBoxLayout()
        emotion_actions.setSpacing(8)

        emotion_new_btn = QPushButton("새 감정")
        emotion_new_btn.clicked.connect(self._new_emotion_item)
        emotion_actions.addWidget(emotion_new_btn)

        emotion_apply_btn = QPushButton("목록에 반영")
        emotion_apply_btn.setProperty("accent", True)
        emotion_apply_btn.style().unpolish(emotion_apply_btn)
        emotion_apply_btn.style().polish(emotion_apply_btn)
        emotion_apply_btn.clicked.connect(self._apply_emotion_item)
        emotion_actions.addWidget(emotion_apply_btn)

        emotion_delete_btn = QPushButton("삭제")
        emotion_delete_btn.clicked.connect(self._delete_emotion_item)
        emotion_actions.addWidget(emotion_delete_btn)

        emotion_editor_col.addLayout(emotion_actions)
        emotion_layout.addLayout(emotion_editor_col, 1)
        layout.addWidget(emotion_group)

        footer_row = QHBoxLayout()
        footer_row.setSpacing(10)

        self._prompt_status_label = QLabel("로드 대기")
        self._prompt_status_label.setObjectName("FooterBody")
        footer_row.addWidget(self._prompt_status_label)

        footer_row.addStretch()

        reload_btn = QPushButton("다시 불러오기")
        reload_btn.clicked.connect(self._load_prompt_configuration)
        footer_row.addWidget(reload_btn)

        save_btn = QPushButton("저장")
        save_btn.setProperty("accent", True)
        save_btn.style().unpolish(save_btn)
        save_btn.style().polish(save_btn)
        save_btn.clicked.connect(self._save_prompt_configuration)
        footer_row.addWidget(save_btn)
        layout.addLayout(footer_row)

        layout.addStretch()
        scroll.setWidget(widget)
        self._load_prompt_configuration()
        self._refresh_prompt_token_counts()
        return scroll

    def _read_text_file(self, path: Path) -> str:
        return path.read_text(encoding="utf-8-sig")

    def _write_text_file(self, path: Path, text: str) -> None:
        normalized = text.replace("\r\n", "\n")
        path.write_text(normalized, encoding="utf-8-sig")

    def _find_assignment_value_node(self, source: str, var_name: str):
        tree = ast.parse(source)
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == var_name:
                        return node.value
        raise ValueError(f"{var_name} 값을 찾지 못했습니다.")

    def _extract_assignment_literal(self, source: str, var_name: str):
        value_node = self._find_assignment_value_node(source, var_name)
        return ast.literal_eval(value_node)

    def _replace_assignment_value(self, source: str, var_name: str, replacement: str) -> str:
        value_node = self._find_assignment_value_node(source, var_name)
        lines = source.splitlines(keepends=True)

        def to_offset(lineno: int, col: int) -> int:
            return sum(len(line) for line in lines[:lineno - 1]) + col

        start = to_offset(value_node.lineno, value_node.col_offset)
        end = to_offset(value_node.end_lineno, value_node.end_col_offset)
        return source[:start] + replacement + source[end:]

    def _format_triple_quoted_string(self, text: str) -> str:
        escaped = (text or "").strip("\n").replace('"""', '\\"\\"\\"')
        return f'"""\n{escaped}\n"""'

    def _format_emotions_list(self, emotions: list[str]) -> str:
        lines = ["["]
        lines.extend(f"    {emotion!r}," for emotion in emotions)
        lines.append("]")
        return "\n".join(lines)

    def _split_sub_prompt_content(self, text: str) -> tuple[str, dict[str, str]]:
        content = (text or "").strip()
        if not content:
            return "", {}

        pattern = re.compile(r"^### \[(.+?)\]\s*$", re.MULTILINE)
        matches = list(pattern.finditer(content))
        if not matches:
            return content, {}

        sections: list[tuple[str, str]] = []
        for index, match in enumerate(matches):
            title = match.group(1).strip()
            start = match.start()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            section_text = content[start:end].strip()
            sections.append((title, section_text))

        guides: dict[str, str] = {}
        remaining_sections: list[str] = []

        for title, section_text in sections:
            if title == "감정 표현 규칙":
                continue
            if title == "감정 사용 가이드":
                for line in section_text.splitlines()[1:]:
                    stripped = line.strip()
                    if not stripped.startswith("- "):
                        continue
                    name, separator, guide = stripped[2:].partition(":")
                    if separator:
                        guides[name.strip()] = guide.strip()
                continue
            remaining_sections.append(section_text)

        return "\n\n".join(remaining_sections).strip(), guides

    def _build_sub_prompt_text(self, body_text: str, emotions: list[dict[str, str]]) -> str:
        emotion_names = ", ".join(item["name"] for item in emotions)
        rules_section = "\n".join(
            [
                "### [감정 표현 규칙]",
                "- 답변 말 마지막에 반드시 감정 태그를 추가하세요.",
                "- 형식: `[emotion]`",
                f"- 사용 가능한 감정: `{emotion_names}`",
            ]
        )

        guide_lines = ["### [감정 사용 가이드]"]
        for item in emotions:
            guide = item["guide"].strip() or "이 감정을 어떤 상황에서 쓰는지 설명하세요."
            guide_lines.append(f"- {item['name']}: {guide}")

        parts = [rules_section]
        cleaned_body = (body_text or "").strip()
        if cleaned_body:
            parts.append(cleaned_body)
        parts.append("\n".join(guide_lines))
        return "\n\n".join(parts).strip()

    def _normalize_emotion_name(self, text: str) -> str:
        normalized = re.sub(r"[^a-z0-9_]", "_", str(text or "").strip().lower())
        return re.sub(r"_+", "_", normalized).strip("_")

    def _refresh_emotion_list(self):
        self.emotion_list.clear()
        for item in self._emotion_items:
            label = item["name"]
            if item["guide"].strip():
                label = f"{label}  |  {item['guide'].strip()[:28]}"
            self.emotion_list.addItem(label)

    def _sync_emotion_combo_options(self):
        if not hasattr(self, "head_pat_active_emotion_combo"):
            return

        current_text = self.head_pat_active_emotion_combo.currentText()
        options = [item["name"] for item in self._emotion_items if item["name"].strip()]
        if "eyeclose" not in options:
            options.append("eyeclose")

        self.head_pat_active_emotion_combo.blockSignals(True)
        self.head_pat_active_emotion_combo.clear()
        self.head_pat_active_emotion_combo.addItems(options)
        if current_text in options:
            self.head_pat_active_emotion_combo.setCurrentText(current_text)
        self.head_pat_active_emotion_combo.blockSignals(False)

    def _new_emotion_item(self):
        self._emotion_current_index = -1
        self.emotion_list.clearSelection()
        self.emotion_name_input.clear()
        self.emotion_guide_editor.clear()
        self.emotion_name_input.setFocus()

    def _on_emotion_selected(self, row: int):
        self._emotion_current_index = row
        if 0 <= row < len(self._emotion_items):
            item = self._emotion_items[row]
            self.emotion_name_input.setText(item["name"])
            self.emotion_guide_editor.setPlainText(item["guide"])
            return
        self.emotion_name_input.clear()
        self.emotion_guide_editor.clear()

    def _apply_emotion_item(self):
        name = self._normalize_emotion_name(self.emotion_name_input.text())
        guide = self.emotion_guide_editor.toPlainText().strip()
        if not name:
            QMessageBox.warning(self, "감정 저장 실패", "감정 키를 입력하세요.")
            return

        duplicate_index = next((idx for idx, item in enumerate(self._emotion_items) if item["name"] == name), -1)
        if duplicate_index != -1 and duplicate_index != self._emotion_current_index:
            QMessageBox.warning(self, "감정 저장 실패", f"'{name}' 감정은 이미 존재합니다.")
            return

        payload = {"name": name, "guide": guide}
        if 0 <= self._emotion_current_index < len(self._emotion_items):
            self._emotion_items[self._emotion_current_index] = payload
            target_index = self._emotion_current_index
        else:
            self._emotion_items.append(payload)
            target_index = len(self._emotion_items) - 1

        self._refresh_emotion_list()
        self._sync_emotion_combo_options()
        self.emotion_list.setCurrentRow(target_index)

    def _delete_emotion_item(self):
        row = self.emotion_list.currentRow()
        if row < 0:
            return
        del self._emotion_items[row]
        self._refresh_emotion_list()
        self._sync_emotion_combo_options()
        self._new_emotion_item()

    def _load_prompt_configuration(self):
        try:
            prompt_source = self._read_text_file(self._prompt_path)
            sub_prompt_source = self._read_text_file(self._sub_prompt_path)

            base_prompt = self._extract_assignment_literal(prompt_source, "BASE_SYSTEM_PROMPT")
            emotions = list(self._extract_assignment_literal(prompt_source, "EMOTIONS"))
            sub_prompt_text = self._extract_assignment_literal(sub_prompt_source, "SUB_PROMPT")
            sub_prompt_body, guides = self._split_sub_prompt_content(sub_prompt_text)

            merged_items = [{"name": name, "guide": guides.get(name, "")} for name in emotions]
            known_names = {item["name"] for item in merged_items}
            for name, guide in guides.items():
                if name not in known_names:
                    merged_items.append({"name": name, "guide": guide})

            self.base_prompt_editor.setPlainText(str(base_prompt).strip("\n"))
            self.sub_prompt_editor.setPlainText(sub_prompt_body)
            self._emotion_items = merged_items
            self._refresh_emotion_list()
            self._sync_emotion_combo_options()
            self._new_emotion_item()

            if self._prompt_status_label:
                self._prompt_status_label.setText("prompt.py / sub_prompt.py 로드 완료")
        except Exception as e:
            if self._prompt_status_label:
                self._prompt_status_label.setText(f"로드 실패: {e}")
            QMessageBox.warning(self, "불러오기 실패", f"프롬프트 설정을 불러오지 못했습니다.\n{e}")

    def _save_prompt_configuration(self):
        try:
            emotion_names = [item["name"] for item in self._emotion_items if item["name"].strip()]
            if not emotion_names:
                raise ValueError("감정은 하나 이상 있어야 합니다.")

            prompt_source = self._read_text_file(self._prompt_path)
            sub_prompt_source = self._read_text_file(self._sub_prompt_path)

            prompt_source = self._replace_assignment_value(
                prompt_source,
                "EMOTIONS",
                self._format_emotions_list(emotion_names),
            )
            prompt_source = self._replace_assignment_value(
                prompt_source,
                "BASE_SYSTEM_PROMPT",
                self._format_triple_quoted_string(self.base_prompt_editor.toPlainText()),
            )

            rebuilt_sub_prompt = self._build_sub_prompt_text(
                self.sub_prompt_editor.toPlainText(),
                self._emotion_items,
            )
            sub_prompt_source = self._replace_assignment_value(
                sub_prompt_source,
                "SUB_PROMPT",
                self._format_triple_quoted_string(rebuilt_sub_prompt),
            )

            compile(prompt_source, str(self._prompt_path), "exec")
            compile(sub_prompt_source, str(self._sub_prompt_path), "exec")

            self._write_text_file(self._prompt_path, prompt_source)
            self._write_text_file(self._sub_prompt_path, sub_prompt_source)
            importlib.reload(importlib.import_module("src.ai.sub_prompt"))
            importlib.reload(importlib.import_module("src.ai.prompt"))
            self._sync_emotion_combo_options()

            if self._prompt_status_label:
                self._prompt_status_label.setText("prompt.py / sub_prompt.py 저장 완료")
            QMessageBox.information(self, "저장 완료", "프롬프트 설정을 저장했습니다.")
        except Exception as e:
            if self._prompt_status_label:
                self._prompt_status_label.setText(f"저장 실패: {e}")
            QMessageBox.warning(self, "저장 실패", f"프롬프트 설정을 저장하지 못했습니다.\n{e}")

    def _refresh_basic_info_list(self):
        self.basic_info_list.clear()
        for key, value in self._basic_info_items:
            self.basic_info_list.addItem(f"{key}: {value}")

    def _configure_preference_list(self, list_widget: QListWidget):
        list_widget.setViewMode(QListView.ViewMode.IconMode)
        list_widget.setFlow(QListView.Flow.LeftToRight)
        list_widget.setWrapping(True)
        list_widget.setResizeMode(QListView.ResizeMode.Adjust)
        list_widget.setMovement(QListView.Movement.Static)
        list_widget.setWordWrap(False)
        list_widget.setSpacing(8)
        list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def _new_basic_info_item(self):
        self._basic_info_current_index = -1
        self.basic_info_list.clearSelection()
        self.basic_info_key_input.clear()
        self.basic_info_value_input.clear()
        self.basic_info_key_input.setFocus()

    def _on_basic_info_selected(self, row: int):
        self._basic_info_current_index = row
        if 0 <= row < len(self._basic_info_items):
            key, value = self._basic_info_items[row]
            self.basic_info_key_input.setText(key)
            self.basic_info_value_input.setText(value)
            return
        self.basic_info_key_input.clear()
        self.basic_info_value_input.clear()

    def _apply_basic_info_item(self):
        key = self.basic_info_key_input.text().strip()
        value = self.basic_info_value_input.text().strip()
        if not key:
            QMessageBox.warning(self, "기본 정보 저장 실패", "항목 이름을 입력하세요.")
            return

        duplicate_index = next((idx for idx, item in enumerate(self._basic_info_items) if item[0] == key), -1)
        if duplicate_index != -1 and duplicate_index != self._basic_info_current_index:
            QMessageBox.warning(self, "기본 정보 저장 실패", f"'{key}' 항목은 이미 존재합니다.")
            return

        payload = (key, value)
        if 0 <= self._basic_info_current_index < len(self._basic_info_items):
            self._basic_info_items[self._basic_info_current_index] = payload
            target_index = self._basic_info_current_index
        else:
            self._basic_info_items.append(payload)
            target_index = len(self._basic_info_items) - 1

        self._refresh_basic_info_list()
        self.basic_info_list.setCurrentRow(target_index)

    def _delete_basic_info_item(self):
        row = self.basic_info_list.currentRow()
        if row < 0:
            return
        del self._basic_info_items[row]
        self._refresh_basic_info_list()
        self._new_basic_info_item()

    def _refresh_preference_lists(self, preferences: dict):
        self.likes_list.clear()
        self.likes_list.addItems(preferences.get("likes", []))
        self.dislikes_list.clear()
        self.dislikes_list.addItems(preferences.get("dislikes", []))

    def _add_preference_item(self, kind: str):
        input_widget = self.likes_input if kind == "likes" else self.dislikes_input
        list_widget = self.likes_list if kind == "likes" else self.dislikes_list
        text = input_widget.text().strip()
        if not text:
            return

        values = [list_widget.item(index).text() for index in range(list_widget.count())]
        if text in values:
            QMessageBox.warning(self, "항목 추가 실패", "이미 같은 항목이 있습니다.")
            return

        list_widget.addItem(text)
        input_widget.clear()
        list_widget.setCurrentRow(list_widget.count() - 1)

    def _delete_preference_item(self, kind: str):
        list_widget = self.likes_list if kind == "likes" else self.dislikes_list
        row = list_widget.currentRow()
        if row >= 0:
            list_widget.takeItem(row)

    def _refresh_fact_list(self):
        self.fact_list.clear()
        for fact in self._fact_items:
            preview = fact["content"].strip().replace("\n", " ")
            if len(preview) > 36:
                preview = preview[:36] + "..."
            self.fact_list.addItem(f"[{fact['category']}] {preview}")

    def _new_fact_item(self):
        self._fact_current_index = -1
        self.fact_list.clearSelection()
        self.fact_content_edit.clear()
        self.fact_category_combo.setCurrentText("basic")
        self.fact_source_input.clear()
        self.fact_timestamp_label.setText("신규 항목")
        self.fact_content_edit.setFocus()

    def _on_fact_selected(self, row: int):
        self._fact_current_index = row
        if 0 <= row < len(self._fact_items):
            fact = self._fact_items[row]
            self.fact_content_edit.setPlainText(fact["content"])
            self.fact_category_combo.setCurrentText(fact["category"])
            self.fact_source_input.setText(fact["source"])
            self.fact_timestamp_label.setText(f"기록 시각: {fact['timestamp']}")
            return
        self.fact_content_edit.clear()
        self.fact_source_input.clear()
        self.fact_timestamp_label.setText("신규 항목")

    def _apply_fact_item(self):
        content = self.fact_content_edit.toPlainText().strip()
        category = self.fact_category_combo.currentText().strip()
        source = self.fact_source_input.text().strip()
        if not content:
            QMessageBox.warning(self, "facts 저장 실패", "기억 내용을 입력하세요.")
            return

        payload = {
            "content": content,
            "category": category,
            "source": source,
            "timestamp": datetime.now().isoformat(),
        }

        if 0 <= self._fact_current_index < len(self._fact_items):
            payload["timestamp"] = self._fact_items[self._fact_current_index].get("timestamp") or payload["timestamp"]
            self._fact_items[self._fact_current_index] = payload
            target_index = self._fact_current_index
        else:
            self._fact_items.append(payload)
            target_index = len(self._fact_items) - 1

        self._refresh_fact_list()
        self.fact_list.setCurrentRow(target_index)

    def _delete_fact_item(self):
        row = self.fact_list.currentRow()
        if row < 0:
            return
        del self._fact_items[row]
        self._refresh_fact_list()
        self._new_fact_item()

    def _load_user_profile_data(self):
        try:
            if self._user_profile_path.exists():
                raw = json.loads(self._read_text_file(self._user_profile_path))
            else:
                raw = {}

            self._basic_info_items = list((raw.get("basic_info") or {}).items())
            preferences = raw.get("preferences") or {}
            self._fact_items = [
                {
                    "content": str(item.get("content", "")).strip(),
                    "category": str(item.get("category", "basic")).strip() or "basic",
                    "timestamp": str(item.get("timestamp", "")).strip(),
                    "source": str(item.get("source", "")).strip(),
                }
                for item in raw.get("facts", [])
            ]

            self._refresh_basic_info_list()
            self._refresh_preference_lists(
                {
                    "likes": list(preferences.get("likes", [])),
                    "dislikes": list(preferences.get("dislikes", [])),
                }
            )
            self._refresh_fact_list()
            self._new_basic_info_item()
            self._new_fact_item()

            if self._profile_status_label:
                self._profile_status_label.setText("user_profile.json 로드 완료")
        except Exception as e:
            if self._profile_status_label:
                self._profile_status_label.setText(f"로드 실패: {e}")
            QMessageBox.warning(self, "불러오기 실패", f"user_profile.json을 불러오지 못했습니다.\n{e}")

    def _save_user_profile_data(self):
        try:
            likes = [
                self.likes_list.item(index).text().strip()
                for index in range(self.likes_list.count())
                if self.likes_list.item(index).text().strip()
            ]
            dislikes = [
                self.dislikes_list.item(index).text().strip()
                for index in range(self.dislikes_list.count())
                if self.dislikes_list.item(index).text().strip()
            ]

            profile_data = {
                "facts": self._fact_items,
                "basic_info": {key: value for key, value in self._basic_info_items if key},
                "preferences": {
                    "likes": likes,
                    "dislikes": dislikes,
                },
                "last_updated": datetime.now().isoformat(),
            }

            serialized = json.dumps(profile_data, ensure_ascii=False, indent=2) + "\n"
            self._write_text_file(self._user_profile_path, serialized)

            user_profile = getattr(self._bridge, "user_profile", None) if self._bridge else None
            if user_profile:
                user_profile.load()

            if self._profile_status_label:
                self._profile_status_label.setText("user_profile.json 저장 완료")
            QMessageBox.information(self, "저장 완료", "사용자 기억 정보를 저장했습니다.")
        except Exception as e:
            if self._profile_status_label:
                self._profile_status_label.setText(f"저장 실패: {e}")
            QMessageBox.warning(self, "저장 실패", f"user_profile.json을 저장하지 못했습니다.\n{e}")
    def _qt_key_to_hotkey_token(self, event) -> str:
        key = event.key()
        special_map = {
            Qt.Key.Key_Space: "space",
            Qt.Key.Key_Return: "enter",
            Qt.Key.Key_Enter: "enter",
            Qt.Key.Key_Escape: "esc",
            Qt.Key.Key_Tab: "tab",
            Qt.Key.Key_Backspace: "backspace",
            Qt.Key.Key_Delete: "delete",
            Qt.Key.Key_Insert: "insert",
            Qt.Key.Key_Home: "home",
            Qt.Key.Key_End: "end",
            Qt.Key.Key_PageUp: "page_up",
            Qt.Key.Key_PageDown: "page_down",
            Qt.Key.Key_Up: "up",
            Qt.Key.Key_Down: "down",
            Qt.Key.Key_Left: "left",
            Qt.Key.Key_Right: "right",
            Qt.Key.Key_Minus: "minus",
            Qt.Key.Key_Equal: "plus",
            Qt.Key.Key_Comma: "comma",
            Qt.Key.Key_Period: "period",
            Qt.Key.Key_Slash: "slash",
            Qt.Key.Key_Backslash: "backslash",
            Qt.Key.Key_Semicolon: "semicolon",
            Qt.Key.Key_Apostrophe: "quote",
            Qt.Key.Key_QuoteLeft: "backquote",
            Qt.Key.Key_BracketLeft: "left_bracket",
            Qt.Key.Key_BracketRight: "right_bracket",
            Qt.Key.Key_Control: "ctrl",
            Qt.Key.Key_Shift: "shift",
            Qt.Key.Key_Alt: "alt",
            Qt.Key.Key_Meta: "meta",
        }
        if key in special_map:
            return special_map[key]
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            return chr(ord("a") + (key - Qt.Key.Key_A))
        if Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            return chr(ord("0") + (key - Qt.Key.Key_0))
        if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F35:
            return f"f{key - Qt.Key.Key_F1 + 1}"

        text = str(event.text() or "").strip().lower()
        if not text:
            return ""
        if text == "+":
            return "plus"
        if text == "-":
            return "minus"
        if text == ",":
            return "comma"
        if text == ".":
            return "period"
        if text == "/":
            return "slash"
        if text == "\\":
            return "backslash"
        if text == ";":
            return "semicolon"
        if text == "'":
            return "quote"
        if text == "`":
            return "backquote"
        if text == "[":
            return "left_bracket"
        if text == "]":
            return "right_bracket"
        if len(text) == 1 and text.isprintable():
            return text
        return ""

    def _build_hotkey_from_event(self, event) -> str:
        modifier_tokens: list[str] = []
        mods = event.modifiers()
        if mods & Qt.KeyboardModifier.ControlModifier:
            modifier_tokens.append("ctrl")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            modifier_tokens.append("shift")
        if mods & Qt.KeyboardModifier.AltModifier:
            modifier_tokens.append("alt")
        if mods & Qt.KeyboardModifier.MetaModifier:
            modifier_tokens.append("meta")

        trigger = self._qt_key_to_hotkey_token(event)
        if not trigger:
            return ""
        modifier_tokens = [mod for mod in modifier_tokens if mod != trigger]

        ordered = [mod for mod in ("ctrl", "shift", "alt", "meta") if mod in modifier_tokens]
        if trigger not in ordered:
            ordered.append(trigger)
        return normalize_hotkey_text("+".join(ordered), default="alt")

    def _update_ptt_hotkey_ui(self):
        self.global_ptt_hotkey_value_label.setText(hotkey_to_display(self._ptt_hotkey_value, default="alt"))
        if self._capturing_ptt_hotkey:
            self.global_ptt_hotkey_set_button.setText("입력 대기 중...")
            self.global_ptt_hotkey_hint_label.setText("설정할 키를 누르세요. Esc를 누르면 취소됩니다.")
        else:
            self.global_ptt_hotkey_set_button.setText("단축키 설정")
            self.global_ptt_hotkey_hint_label.setText("누르고 있는 동안만 녹음됩니다.")

    def _start_ptt_hotkey_capture(self):
        if self._capturing_ptt_hotkey:
            return
        self._capturing_ptt_hotkey = True
        self._update_ptt_hotkey_ui()
        self.grabKeyboard()

    def _stop_ptt_hotkey_capture(self):
        if not self._capturing_ptt_hotkey:
            return
        self._capturing_ptt_hotkey = False
        self.releaseKeyboard()
        self._update_ptt_hotkey_ui()

    def _reset_ptt_hotkey(self):
        self._ptt_hotkey_value = normalize_hotkey_text("alt", default="alt")
        self._update_ptt_hotkey_ui()
        self._on_setting_changed()

    def _on_llm_provider_changed(self, *_):
        provider = str(self.llm_provider_combo.currentData() or "gemini")

        self._loading = True
        try:
            self.llm_api_key_edit.setText(str(self._llm_api_keys.get(provider, "")))
            model_text = str(self._llm_models.get(provider, ""))
            self.llm_model_edit.setText(model_text)
            self._active_model_key_by_provider[provider] = self._model_param_key(model_text)
            self._apply_model_params_to_widgets(provider, model_text)
            self.custom_api_group.setVisible(provider == "custom_api")
        finally:
            self._loading = False

        self._on_setting_changed()

    def _on_llm_api_key_changed(self, text: str):
        provider = str(self.llm_provider_combo.currentData() or "gemini")
        self._llm_api_keys[provider] = text
        self._on_setting_changed()

    def _on_llm_model_changed(self, text: str):
        provider = str(self.llm_provider_combo.currentData() or "gemini")
        old_key = self._active_model_key_by_provider.get(provider, "__default__")
        new_key = self._model_param_key(text)
        provider_params = self._llm_model_params.setdefault(provider, {})
        if new_key not in provider_params:
            provider_params[new_key] = dict(provider_params.get(old_key, self._default_model_params()))
        self._active_model_key_by_provider[provider] = new_key
        self._llm_models[provider] = text.strip()
        self._apply_model_params_to_widgets(provider, text)
        self._on_setting_changed()

    def _on_llm_param_changed(self, *_):
        if self._loading:
            return
        self._set_current_model_params()
        self._on_setting_changed()

    def _default_model_params(self) -> dict:
        return {"temperature": 0.9, "top_p": 1.0, "max_tokens": 2048}

    def _model_param_key(self, model_name: str) -> str:
        key = str(model_name or "").strip()
        return key if key else "__default__"

    def _normalize_model_params(self, params) -> dict:
        defaults = self._default_model_params()
        if not isinstance(params, dict):
            return defaults
        normalized = dict(defaults)
        try:
            normalized["temperature"] = max(0.0, min(2.0, float(params.get("temperature", defaults["temperature"]))))
        except (TypeError, ValueError):
            pass
        try:
            normalized["top_p"] = max(0.0, min(1.0, float(params.get("top_p", defaults["top_p"]))))
        except (TypeError, ValueError):
            pass
        try:
            normalized["max_tokens"] = max(0, int(params.get("max_tokens", defaults["max_tokens"])))
        except (TypeError, ValueError):
            pass
        return normalized

    def _get_model_params(self, provider: str, model_name: str) -> dict:
        store = self._llm_model_params.setdefault(provider, {})
        model_key = self._model_param_key(model_name)
        params = store.get(model_key)
        if not isinstance(params, dict):
            params = store.get("__default__")
        if not isinstance(params, dict):
            params = self._default_model_params()
        normalized = self._normalize_model_params(params)
        store[model_key] = dict(normalized)
        store.setdefault("__default__", dict(normalized))
        return normalized

    def _set_current_model_params(self):
        provider = str(self.llm_provider_combo.currentData() or "gemini")
        model_text = self.llm_model_edit.text().strip()
        model_key = self._model_param_key(model_text)
        self._active_model_key_by_provider[provider] = model_key
        provider_store = self._llm_model_params.setdefault(provider, {})
        provider_store[model_key] = self._normalize_model_params(
            {
                "temperature": self.llm_temperature_spin.value(),
                "top_p": self.llm_top_p_spin.value(),
                "max_tokens": self.llm_max_tokens_spin.value(),
            }
        )
        provider_store.setdefault("__default__", dict(provider_store[model_key]))

    def _apply_model_params_to_widgets(self, provider: str, model_name: str):
        params = self._get_model_params(provider, model_name)
        self.llm_temperature_spin.setValue(float(params["temperature"]))
        self.llm_top_p_spin.setValue(float(params["top_p"]))
        self.llm_max_tokens_spin.setValue(int(params["max_tokens"]))

    def _on_setting_changed(self):
        if self._loading:
            return
        self._preview_settings()

    def _on_note_context_toggle(self, checked: bool):
        self.note_recent_context_turns_spin.setEnabled(bool(checked))
        self._on_setting_changed()

    def _load_values(self):
        self._loading = True
        try:
            self.window_x_spin.setValue(self._original_settings.get("window_x", 100))
            self.window_y_spin.setValue(self._original_settings.get("window_y", 100))
            self.window_width_spin.setValue(self._original_settings.get("window_width", 400))
            self.window_height_spin.setValue(self._original_settings.get("window_height", 600))
            for key, default_value in self._theme_defaults.items():
                if key in self._theme_color_edits:
                    self._theme_values[key] = self._normalize_theme_color(
                        str(self._original_settings.get(key, default_value)),
                        fallback=default_value,
                    )
                    self._theme_color_edits[key].setText(self._theme_values[key])
            self._theme_mode = str(self._original_settings.get("theme_mode", self._theme_mode)).strip().lower()
            if self._theme_mode not in THEME_PRESETS:
                self._theme_mode = "light"
            self._follow_system_theme = bool(self._original_settings.get("follow_system_theme", False))
            if self._follow_system_theme:
                self._theme_mode = get_windows_theme_mode()
                self._apply_theme_mode(self._theme_mode, emit_preview=False)
            if hasattr(self, "follow_system_theme_check"):
                self.follow_system_theme_check.setChecked(self._follow_system_theme)
            self._set_theme_editors_enabled(not self._follow_system_theme)
            self._refresh_theme_editor_state()

            self.show_drag_bar_check.setChecked(self._original_settings.get("show_drag_bar", True))
            self.show_recent_reroll_button_check.setChecked(
                self._original_settings.get("show_recent_reroll_button", True)
            )
            self.show_recent_edit_button_check.setChecked(
                self._original_settings.get("show_recent_edit_button", True)
            )
            self.show_token_usage_bubble_check.setChecked(
                self._original_settings.get("show_token_usage_bubble", False)
            )
            self.show_manual_summary_button_check.setChecked(
                self._original_settings.get("show_manual_summary_button", True)
            )
            self.show_obsidian_note_button_check.setChecked(
                self._original_settings.get("show_obsidian_note_button", True)
            )
            self.show_mood_toggle_button_check.setChecked(
                self._original_settings.get("show_mood_toggle_button", True)
            )
            self.enable_global_ptt_check.setChecked(
                self._original_settings.get("enable_global_ptt", True)
            )
            self.interrupt_tts_on_ptt_check.setChecked(
                self._original_settings.get("interrupt_tts_on_ptt", True)
            )
            self._load_tts_values()
            self._ptt_hotkey_value = normalize_hotkey_text(
                str(self._original_settings.get("global_ptt_hotkey", "alt")),
                default="alt",
            )
            self._update_ptt_hotkey_ui()
            self.note_include_recent_context_check.setChecked(
                self._original_settings.get("note_include_recent_context", False)
            )
            try:
                note_turns = int(self._original_settings.get("note_recent_context_turns", 4) or 0)
            except Exception:
                note_turns = 4
            self.note_recent_context_turns_spin.setValue(max(0, min(note_turns, 200)))
            self.note_recent_context_turns_spin.setEnabled(
                bool(self.note_include_recent_context_check.isChecked())
            )
            if self.memory_search_recent_turns_spin is not None:
                try:
                    memory_turns = int(self._original_settings.get("memory_search_recent_turns", 2) or 0)
                except Exception:
                    memory_turns = 2
                self.memory_search_recent_turns_spin.setValue(max(0, min(memory_turns, 50)))
            self.mouse_tracking_check.setChecked(self._original_settings.get("mouse_tracking_enabled", True))

            self.idle_motion_check.setChecked(self._original_settings.get("enable_idle_motion", True))
            self.idle_motion_dynamic_check.setChecked(self._original_settings.get("idle_motion_dynamic_mode", False))
            self.idle_motion_strength_spin.setValue(float(self._original_settings.get("idle_motion_strength", 1.0)))
            self.idle_motion_speed_spin.setValue(float(self._original_settings.get("idle_motion_speed", 1.0)))

            self.head_pat_check.setChecked(self._original_settings.get("enable_head_pat", True))
            self.head_pat_strength_spin.setValue(float(self._original_settings.get("head_pat_strength", 1.0)))
            self.head_pat_fade_in_spin.setValue(int(self._original_settings.get("head_pat_fade_in_ms", 180)))
            self.head_pat_fade_out_spin.setValue(int(self._original_settings.get("head_pat_fade_out_ms", 220)))

            active_default_emotion = str(
                self._original_settings.get("head_pat_active_emotion_default", "eyeclose")
            ).strip() or "eyeclose"
            if active_default_emotion not in self._emotion_options:
                active_default_emotion = "eyeclose"
            self.head_pat_active_emotion_combo.setCurrentText(active_default_emotion)
            self.head_pat_active_emotion_custom_edit.setText(
                str(self._original_settings.get("head_pat_active_emotion_custom", ""))
            )

            default_emotion = str(self._original_settings.get("head_pat_end_emotion_default", "shy")).strip() or "shy"
            if default_emotion not in self._emotion_options:
                default_emotion = "shy"
            self.head_pat_end_emotion_combo.setCurrentText(default_emotion)
            self.head_pat_end_emotion_custom_edit.setText(
                str(self._original_settings.get("head_pat_end_emotion_custom", ""))
            )
            self.head_pat_end_emotion_duration_spin.setValue(
                int(self._original_settings.get("head_pat_end_emotion_duration_sec", 5))
            )
            self.enable_away_nudge_check.setChecked(self._original_settings.get("enable_away_nudge", True))
            self.away_idle_minutes_spin.setValue(int(self._original_settings.get("away_idle_minutes", 60)))
            self.away_diff_threshold_spin.setValue(float(self._original_settings.get("away_diff_threshold_percent", 3.0)))
            self.away_retry_limit_spin.setValue(int(self._original_settings.get("away_additional_retry_limit", 0)))

            self.model_scale_spin.setValue(self._original_settings.get("model_scale", 1.0))
            self.model_x_slider.setValue(int(self._original_settings.get("model_x_percent", 50)))
            self.model_y_slider.setValue(int(self._original_settings.get("model_y_percent", 50)))
            self.model_json_path_edit.setText(
                self._normalize_path_for_storage(
                    str(self._original_settings.get("model_json_path", "assets/live2d_models/jksalt/jksalt.model3.json"))
                )
            )

            llm_provider = str(self._original_settings.get("llm_provider", "gemini")).strip().lower()
            loaded_keys = self._original_settings.get("llm_api_keys", {})
            self._llm_api_keys = loaded_keys.copy() if isinstance(loaded_keys, dict) else {}
            for provider_name in self._provider_values:
                self._llm_api_keys.setdefault(provider_name, "")

            loaded_models = self._original_settings.get("llm_models", {})
            self._llm_models = loaded_models.copy() if isinstance(loaded_models, dict) else {}
            legacy_model = str(self._original_settings.get("llm_model", "gemini-3-flash-preview")).strip()
            for provider_name in self._provider_values:
                if provider_name not in self._llm_models:
                    self._llm_models[provider_name] = legacy_model if provider_name == "gemini" else ""
                self._active_model_key_by_provider[provider_name] = self._model_param_key(
                    self._llm_models.get(provider_name, "")
                )

            loaded_params = self._original_settings.get("llm_model_params", {})
            self._llm_model_params = {}
            if isinstance(loaded_params, dict):
                for provider_name, provider_params in loaded_params.items():
                    if isinstance(provider_params, dict):
                        mapped = {}
                        for model_name, params in provider_params.items():
                            mapped[str(model_name)] = self._normalize_model_params(params)
                        self._llm_model_params[str(provider_name)] = mapped
            for provider_name in self._provider_values:
                provider_store = self._llm_model_params.setdefault(provider_name, {})
                active_key = self._active_model_key_by_provider.get(provider_name, "__default__")
                if active_key not in provider_store:
                    provider_store[active_key] = self._default_model_params()
                provider_store.setdefault("__default__", dict(provider_store[active_key]))

            if llm_provider in self._provider_values:
                idx = self.llm_provider_combo.findData(llm_provider)
                if idx >= 0:
                    self.llm_provider_combo.setCurrentIndex(idx)
            selected_provider = str(self.llm_provider_combo.currentData() or "gemini")
            self.llm_model_edit.setText(str(self._llm_models.get(selected_provider, "")))
            self._apply_model_params_to_widgets(selected_provider, self.llm_model_edit.text())

            self.custom_api_url_edit.setText(str(self._original_settings.get("custom_api_url", "")))
            self.custom_api_key_or_password_edit.setText(
                str(self._original_settings.get("custom_api_key_or_password", ""))
            )
            self.custom_api_request_model_edit.setText(
                str(self._original_settings.get("custom_api_request_model", ""))
            )
            custom_api_format = str(self._original_settings.get("custom_api_format", LLMFormat.OPENAI_COMPATIBLE.value))
            format_index = self.custom_api_format_combo.findData(custom_api_format)
            if format_index >= 0:
                self.custom_api_format_combo.setCurrentIndex(format_index)

            embedding_provider = str(self._original_settings.get("embedding_provider", "voyage")).strip().lower()
            provider_index = self.embedding_provider_combo.findData(embedding_provider)
            if provider_index < 0:
                provider_index = 0
            self.embedding_provider_combo.setCurrentIndex(provider_index)

            embedding_api_keys = self._original_settings.get("embedding_api_keys", {})
            if isinstance(embedding_api_keys, dict):
                self.embedding_api_key_edit.setText(str(embedding_api_keys.get(embedding_provider, "")))
            else:
                self.embedding_api_key_edit.setText("")

            embedding_model = str(self._original_settings.get("embedding_model", "voyage-3")).strip() or "voyage-3"
            model_index = self.embedding_model_combo.findData(embedding_model)
            if model_index < 0:
                model_index = 0
            self.embedding_model_combo.setCurrentIndex(model_index)

            self.llm_api_key_edit.setText(str(self._llm_api_keys.get(selected_provider, "")))
            self.custom_api_group.setVisible(selected_provider == "custom_api")
        finally:
            self._loading = False

    def update_position(self, x: int, y: int):
        self._loading = True
        try:
            self.window_x_spin.setValue(x)
            self.window_y_spin.setValue(y)
        finally:
            self._loading = False

    def _preset_center(self):
        screen = QApplication.primaryScreen().geometry()
        width = self.window_width_spin.value()
        height = self.window_height_spin.value()
        self.window_x_spin.setValue((screen.width() - width) // 2)
        self.window_y_spin.setValue((screen.height() - height) // 2)

    def _preset_bottom_right(self):
        screen = QApplication.primaryScreen().geometry()
        width = self.window_width_spin.value()
        height = self.window_height_spin.value()
        self.window_x_spin.setValue(screen.width() - width - 50)
        self.window_y_spin.setValue(screen.height() - height - 50)

    def _preset_bottom_left(self):
        screen = QApplication.primaryScreen().geometry()
        height = self.window_height_spin.value()
        self.window_x_spin.setValue(50)
        self.window_y_spin.setValue(screen.height() - height - 50)

    def _set_model_position(self, x_percent, y_percent):
        self.model_x_slider.setValue(int(x_percent))
        self.model_y_slider.setValue(int(y_percent))

    def _get_current_values(self):
        current_provider = str(self.llm_provider_combo.currentData() or "gemini")
        self._llm_api_keys[current_provider] = self.llm_api_key_edit.text()
        self._llm_models[current_provider] = self.llm_model_edit.text().strip()
        self._set_current_model_params()

        active_custom_emotion = self.head_pat_active_emotion_custom_edit.text().strip()
        active_default_emotion = self.head_pat_active_emotion_combo.currentText().strip() or "eyeclose"
        resolved_active_emotion = active_custom_emotion if active_custom_emotion else active_default_emotion

        custom_emotion = self.head_pat_end_emotion_custom_edit.text().strip()
        default_emotion = self.head_pat_end_emotion_combo.currentText().strip() or "shy"
        resolved_emotion = custom_emotion if custom_emotion else default_emotion

        if not resolved_active_emotion:
            resolved_active_emotion = "eyeclose"
        if not resolved_emotion:
            resolved_emotion = "shy"

        preserved_hidden_settings = {
            key: self._original_settings[key]
            for key in (
                "stt_model_size",
                "stt_language",
                "stt_device",
                "stt_compute_type",
                "stt_min_record_sec",
                "stt_max_record_sec",
            )
            if key in self._original_settings
        }
        embedding_provider = str(self.embedding_provider_combo.currentData() or "voyage")
        embedding_api_keys = self._original_settings.get("embedding_api_keys", {})
        embedding_api_keys = dict(embedding_api_keys) if isinstance(embedding_api_keys, dict) else {}
        embedding_api_keys[embedding_provider] = self.embedding_api_key_edit.text().strip()
        memory_search_recent_turns = (
            self.memory_search_recent_turns_spin.value()
            if self.memory_search_recent_turns_spin is not None
            else int(self._original_settings.get("memory_search_recent_turns", 2) or 0)
        )

        return {
            **preserved_hidden_settings,
            "window_x": self.window_x_spin.value(),
            "window_y": self.window_y_spin.value(),
            "window_width": self.window_width_spin.value(),
            "window_height": self.window_height_spin.value(),
            **dict(self._theme_values),
            "theme_mode": self._theme_mode,
            "follow_system_theme": self._follow_system_theme,
            "show_drag_bar": self.show_drag_bar_check.isChecked(),
            "show_recent_reroll_button": self.show_recent_reroll_button_check.isChecked(),
            "show_recent_edit_button": self.show_recent_edit_button_check.isChecked(),
            "show_token_usage_bubble": self.show_token_usage_bubble_check.isChecked(),
            "show_manual_summary_button": self.show_manual_summary_button_check.isChecked(),
            "show_obsidian_note_button": self.show_obsidian_note_button_check.isChecked(),
            "show_mood_toggle_button": self.show_mood_toggle_button_check.isChecked(),
            "enable_global_ptt": self.enable_global_ptt_check.isChecked(),
            "interrupt_tts_on_ptt": self.interrupt_tts_on_ptt_check.isChecked(),
            "enable_tts": self.enable_tts_check.isChecked(),
            "tts_provider": str(self.tts_provider_combo.currentData() or "gpt_sovits_http"),
            "tts_api_url": self.tts_api_url_edit.text().strip(),
            "tts_ref_audio_path": self.tts_ref_audio_path_edit.text().strip(),
            "tts_ref_text": self.tts_ref_text_edit.toPlainText().strip(),
            "tts_ref_language": self.tts_ref_language_edit.text().strip() or "ja",
            "tts_target_language": self.tts_target_language_edit.text().strip() or "ja",
            "tts_provider_configs": self._collect_tts_provider_configs(),
            "tts_api_keys": self._collect_tts_api_keys(),
            "global_ptt_hotkey": normalize_hotkey_text(self._ptt_hotkey_value, default="alt"),
            "note_include_recent_context": self.note_include_recent_context_check.isChecked(),
            "note_recent_context_turns": self.note_recent_context_turns_spin.value(),
            "memory_search_recent_turns": max(0, min(memory_search_recent_turns, 50)),
            "mouse_tracking_enabled": self.mouse_tracking_check.isChecked(),
            "enable_idle_motion": self.idle_motion_check.isChecked(),
            "idle_motion_dynamic_mode": self.idle_motion_dynamic_check.isChecked(),
            "idle_motion_strength": self.idle_motion_strength_spin.value(),
            "idle_motion_speed": self.idle_motion_speed_spin.value(),
            "enable_head_pat": self.head_pat_check.isChecked(),
            "head_pat_strength": self.head_pat_strength_spin.value(),
            "head_pat_fade_in_ms": self.head_pat_fade_in_spin.value(),
            "head_pat_fade_out_ms": self.head_pat_fade_out_spin.value(),
            "head_pat_active_emotion_default": active_default_emotion,
            "head_pat_active_emotion_custom": active_custom_emotion,
            "head_pat_active_emotion": resolved_active_emotion,
            "head_pat_end_emotion_default": default_emotion,
            "head_pat_end_emotion_custom": custom_emotion,
            "head_pat_end_emotion": resolved_emotion,
            "head_pat_end_emotion_duration_sec": self.head_pat_end_emotion_duration_spin.value(),
            "enable_away_nudge": self.enable_away_nudge_check.isChecked(),
            "away_idle_minutes": self.away_idle_minutes_spin.value(),
            "away_diff_threshold_percent": self.away_diff_threshold_spin.value(),
            "away_additional_retry_limit": self.away_retry_limit_spin.value(),
            "model_scale": self.model_scale_spin.value(),
            "model_x_percent": self.model_x_slider.value(),
            "model_y_percent": self.model_y_slider.value(),
            "model_json_path": self._normalize_path_for_storage(self.model_json_path_edit.text()),
            "llm_provider": str(self.llm_provider_combo.currentData() or "gemini"),
            "llm_model": self.llm_model_edit.text().strip() or "gemini-3-flash-preview",
            "llm_models": dict(self._llm_models),
            "llm_model_params": dict(self._llm_model_params),
            "llm_api_keys": dict(self._llm_api_keys),
            "custom_api_url": self.custom_api_url_edit.text().strip(),
            "custom_api_key_or_password": self.custom_api_key_or_password_edit.text().strip(),
            "custom_api_request_model": self.custom_api_request_model_edit.text().strip(),
            "custom_api_format": str(self.custom_api_format_combo.currentData() or LLMFormat.OPENAI_COMPATIBLE.value),
            "embedding_api_keys": embedding_api_keys,
            "embedding_provider": str(self.embedding_provider_combo.currentData() or "voyage"),
            "embedding_model": str(self.embedding_model_combo.currentData() or "voyage-3"),
        }

    def _preview_settings(self):
        self.settings_preview.emit(self._get_current_values())

    def _save_settings(self):
        invalid_key = next(
            (key for key, edit in self._theme_color_edits.items() if edit.text().strip() and not self._is_valid_theme_color(edit.text().strip())),
            None,
        )
        if invalid_key is not None:
            QMessageBox.warning(
                self,
                "테마 색상 확인",
                "모든 테마 값은 `#RRGGBB` 형식의 6자리 HEX 코드만 사용할 수 있습니다.",
            )
            self._theme_color_edits[invalid_key].setFocus()
            return
        self._saved = True
        self.settings_changed.emit(self._get_current_values())
        self.close()

    def _cancel_settings(self):
        self._saved = False
        self.settings_cancelled.emit()
        self.close()

    def closeEvent(self, event):
        self._stop_ptt_hotkey_capture()
        if not hasattr(self, "_saved"):
            self.settings_cancelled.emit()
        event.accept()

    def _hit_test_resize_edge(self, pos: QPoint) -> str:
        margin = self._resize_margin
        left = pos.x() <= margin
        right = pos.x() >= self.width() - margin
        top = pos.y() <= margin
        bottom = pos.y() >= self.height() - margin

        if top and left:
            return "top_left"
        if top and right:
            return "top_right"
        if bottom and left:
            return "bottom_left"
        if bottom and right:
            return "bottom_right"
        if left:
            return "left"
        if right:
            return "right"
        if top:
            return "top"
        if bottom:
            return "bottom"
        return ""

    def _update_resize_cursor(self, pos: QPoint) -> None:
        edge = self._hit_test_resize_edge(pos)
        cursor_map = {
            "left": Qt.CursorShape.SizeHorCursor,
            "right": Qt.CursorShape.SizeHorCursor,
            "top": Qt.CursorShape.SizeVerCursor,
            "bottom": Qt.CursorShape.SizeVerCursor,
            "top_left": Qt.CursorShape.SizeFDiagCursor,
            "bottom_right": Qt.CursorShape.SizeFDiagCursor,
            "top_right": Qt.CursorShape.SizeBDiagCursor,
            "bottom_left": Qt.CursorShape.SizeBDiagCursor,
        }
        self.setCursor(cursor_map.get(edge, Qt.CursorShape.ArrowCursor))

    def _apply_resize(self, global_pos: QPoint) -> None:
        delta = global_pos - self._resize_start_global
        geometry = self._resize_start_geometry
        x = geometry.x()
        y = geometry.y()
        width = geometry.width()
        height = geometry.height()

        minimum_width = self.minimumWidth()
        minimum_height = self.minimumHeight()

        if "right" in self._resize_edge:
            width = max(minimum_width, width + delta.x())
        if "bottom" in self._resize_edge:
            height = max(minimum_height, height + delta.y())
        if "left" in self._resize_edge:
            new_width = max(minimum_width, width - delta.x())
            x += width - new_width
            width = new_width
        if "top" in self._resize_edge:
            new_height = max(minimum_height, height - delta.y())
            y += height - new_height
            height = new_height

        self.setGeometry(x, y, width, height)

    def mousePressEvent(self, event):
        if self._capturing_ptt_hotkey:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            edge = self._hit_test_resize_edge(event.position().toPoint())
            if edge:
                self._resize_active = True
                self._resize_edge = edge
                self._resize_start_global = event.globalPosition().toPoint()
                self._resize_start_geometry = self.geometry()
                event.accept()
                return

            if event.pos().y() < 80:
                self._drag_active = True
                self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                event.accept()

    def mouseMoveEvent(self, event):
        if self._capturing_ptt_hotkey:
            event.accept()
            return
        if self._resize_active:
            self._apply_resize(event.globalPosition().toPoint())
            event.accept()
            return
        if self._drag_active:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return

        self._update_resize_cursor(event.position().toPoint())

    def keyPressEvent(self, event):
        if self._capturing_ptt_hotkey:
            if event.key() == Qt.Key.Key_Escape:
                self._stop_ptt_hotkey_capture()
                event.accept()
                return

            hotkey_text = self._build_hotkey_from_event(event)
            if hotkey_text:
                self._ptt_hotkey_value = normalize_hotkey_text(hotkey_text, default="alt")
                self._stop_ptt_hotkey_capture()
                self._on_setting_changed()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._capturing_ptt_hotkey:
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._resize_active = False
            self._resize_edge = ""
            self._update_resize_cursor(event.position().toPoint())
            event.accept()

    def keyReleaseEvent(self, event):
        if self._capturing_ptt_hotkey:
            event.accept()
            return
        super().keyReleaseEvent(event)
