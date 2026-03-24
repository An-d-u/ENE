"""
기억 관리 다이얼로그
"""
from datetime import datetime
import re

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..core.i18n import tr as t


def apply_soft_shadow(widget: QWidget, blur: int = 36, alpha: int = 28) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, 12)
    effect.setColor(QColor(15, 23, 42, alpha))
    widget.setGraphicsEffect(effect)


class CardFrame(QFrame):
    def __init__(self, object_name: str = "Card", parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setFrameShape(QFrame.Shape.NoFrame)
        apply_soft_shadow(self)


class MemoryDialog(QDialog):
    """기억 관리 다이얼로그"""

    def __init__(self, memory_manager, bridge=None, parent=None, embedded: bool = False):
        super().__init__(parent)
        self.memory_manager = memory_manager
        self.bridge = bridge
        self._embedded = embedded
        self._theme_defaults = {
            "theme_accent_color": "#0071E3",
            "settings_window_bg_color": "#EEF1F5",
            "settings_card_bg_color": "#FFFFFF",
            "settings_input_bg_color": "#F8FAFC",
        }
        self._theme_values = dict(self._theme_defaults)
        self._drag_active = False
        self._drag_offset = QPoint()
        self._resize_active = False
        self._resize_edge = ""
        self._resize_start_global = QPoint()
        self._resize_start_geometry = self.geometry()
        self._resize_margin = 12
        self._show_only_important = False
        self._sort_descending = True
        self._item_frames: dict[str, QFrame] = {}

        self.setWindowTitle(t("memory.window.title"))
        if self._embedded:
            self.resize(1000, 720)
            self.setMinimumSize(0, 0)
            self.setMouseTracking(False)
        else:
            self.resize(1240, 820)
            self.setMinimumSize(980, 700)
            self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setMouseTracking(True)

        self._apply_stylesheet()
        self._setup_ui()
        self._load_settings()
        self._load_memories()

    def _normalize_theme_color(self, value: str, fallback: str | None = None) -> str:
        match = re.fullmatch(r"#?([0-9A-Fa-f]{6})", str(value or "").strip())
        if not match:
            return fallback or self._theme_defaults["theme_accent_color"]
        return f"#{match.group(1).upper()}"

    def _theme_rgba(self, color_value: str, alpha: float) -> str:
        color = QColor(self._normalize_theme_color(color_value))
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f})"

    def _theme_text_color(self, color_value: str) -> str:
        color = QColor(self._normalize_theme_color(color_value))
        return "#FFFFFF" if color.lightnessF() < 0.62 else "#111827"

    def _theme_muted_text_color(self, color_value: str) -> str:
        color = QColor(self._normalize_theme_color(color_value))
        return "#CBD5E1" if color.lightnessF() < 0.42 else "#6B7280"

    def _theme_border_color(self, color_value: str, alpha: float = 0.14) -> str:
        return self._theme_rgba(self._theme_text_color(color_value), alpha)

    def apply_theme(self, theme_values: dict | None = None) -> None:
        if isinstance(theme_values, dict):
            for key, default_value in self._theme_defaults.items():
                self._theme_values[key] = self._normalize_theme_color(
                    str(theme_values.get(key, default_value)),
                    fallback=default_value,
                )
        self._apply_stylesheet()

    def _apply_stylesheet(self) -> None:
        accent = self._theme_values["theme_accent_color"]
        settings_window = self._theme_values["settings_window_bg_color"]
        settings_card = self._theme_values["settings_card_bg_color"]
        settings_input = self._theme_values["settings_input_bg_color"]
        primary_text = self._theme_text_color(settings_card)
        muted_text = self._theme_muted_text_color(settings_card)
        body_text = self._theme_muted_text_color(settings_input)
        input_text = self._theme_text_color(settings_input)
        card_border = self._theme_border_color(settings_card, 0.10)
        input_border = self._theme_border_color(settings_input, 0.14)
        window_border = self._theme_border_color(settings_window, 0.10)
        accent_hover = QColor(accent).darker(108).name().upper()
        accent_soft = self._theme_rgba(accent, 0.10)
        accent_border = self._theme_rgba(accent, 0.24)
        selected_bg = self._theme_rgba(accent, 0.08)

        self.setStyleSheet(
            """
            QDialog { background: __SETTINGS_WINDOW__; color: __PRIMARY_TEXT__; font-family: 'Malgun Gothic', 'Segoe UI Variable', 'Segoe UI', sans-serif; }
            QWidget { background: transparent; }
            QFrame#Surface { background: __SETTINGS_WINDOW__; border: 1px solid __WINDOW_BORDER__; border-radius: 30px; }
            QFrame#TitleBar { background: __SETTINGS_CARD__; border: 1px solid __CARD_BORDER__; border-radius: 22px; }
            QFrame#Card, QFrame#MetricCard, QFrame#ListCard, QFrame#MemoryItem { background: __SETTINGS_CARD__; border: 1px solid __CARD_BORDER__; border-radius: 26px; }
            QFrame#MemoryItem[selected='true'] { border: 1px solid __ACCENT_BORDER__; background: __SELECTED_BG__; }
            QLabel#WindowTitle { color: __PRIMARY_TEXT__; font-size: 18px; font-weight: 700; }
            QLabel#WindowSubtitle { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
            QLabel#CardTitle { color: __PRIMARY_TEXT__; font-size: 18px; font-weight: 700; }
            QLabel#Body { color: __BODY_TEXT__; font-size: 14px; line-height: 1.5; }
            QLabel#MetricValue { color: __PRIMARY_TEXT__; font-size: 24px; font-weight: 700; }
            QLabel#MetricLabel { color: __MUTED_TEXT__; font-size: 12px; font-weight: 600; }
            QLabel#Pill, QLabel#TagPill, QLabel#BluePill, QLabel#MutedPill { border-radius: 14px; padding: 6px 12px; font-size: 12px; font-weight: 600; }
            QLabel#Pill { background: __TEXT_SOFT__; color: __PRIMARY_TEXT__; border: 1px solid __CARD_BORDER__; }
            QLabel#TagPill { background: __SETTINGS_INPUT__; color: __BODY_TEXT__; border: 1px solid __INPUT_BORDER__; }
            QLabel#BluePill { background: __ACCENT_SOFT__; color: __ACCENT__; border: 1px solid __ACCENT_BORDER__; }
            QLabel#MutedPill { background: __SETTINGS_CARD__; color: __MUTED_TEXT__; border: 1px solid __CARD_BORDER__; }
            QLabel#KeyValueLabel { color: __MUTED_TEXT__; font-size: 13px; font-weight: 600; }
            QLabel#KeyValueValue { color: __PRIMARY_TEXT__; font-size: 14px; font-weight: 600; }
            QLineEdit, QSpinBox { min-height: 44px; padding: 0 14px; border-radius: 16px; background: __SETTINGS_INPUT__; border: 1px solid __INPUT_BORDER__; color: __INPUT_TEXT__; font-size: 14px; font-weight: 600; }
            QLineEdit:focus, QSpinBox:focus { border: 1px solid __ACCENT_BORDER__; background: __SETTINGS_INPUT__; }
            QSpinBox::up-button, QSpinBox::down-button { width: 28px; border: none; background: transparent; }
            QPushButton { min-height: 44px; padding: 0 18px; border-radius: 18px; border: 1px solid __CARD_BORDER__; background: __SETTINGS_CARD__; color: __PRIMARY_TEXT__; font-size: 13px; font-weight: 600; }
            QPushButton:hover { background: __SETTINGS_INPUT__; }
            QPushButton[accent='true'] { background: __ACCENT__; color: __ACCENT_TEXT__; border: 1px solid __ACCENT__; }
            QPushButton[accent='true']:hover { background: __ACCENT_HOVER__; }
            QPushButton[ghost='true'] { background: transparent; border: none; min-width: 34px; min-height: 34px; padding: 0; border-radius: 17px; color: __MUTED_TEXT__; }
            QPushButton[ghost='true']:hover { background: __TEXT_SOFT__; }
            QListWidget { border: none; background: transparent; outline: none; }
            QListWidget::item { border: none; padding: 0; margin: 0 0 10px 0; }
            QScrollBar:vertical { width: 10px; background: transparent; margin: 8px 0; }
            QScrollBar::handle:vertical { background: __SCROLLBAR__; border-radius: 5px; min-height: 42px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; background: transparent; border: none; }
            """
            .replace("__ACCENT__", accent)
            .replace("__ACCENT_HOVER__", accent_hover)
            .replace("__ACCENT_TEXT__", self._theme_text_color(accent))
            .replace("__ACCENT_SOFT__", accent_soft)
            .replace("__ACCENT_BORDER__", accent_border)
            .replace("__SETTINGS_WINDOW__", settings_window)
            .replace("__SETTINGS_CARD__", settings_card)
            .replace("__SETTINGS_INPUT__", settings_input)
            .replace("__PRIMARY_TEXT__", primary_text)
            .replace("__MUTED_TEXT__", muted_text)
            .replace("__BODY_TEXT__", body_text)
            .replace("__INPUT_TEXT__", input_text)
            .replace("__CARD_BORDER__", card_border)
            .replace("__INPUT_BORDER__", input_border)
            .replace("__WINDOW_BORDER__", window_border)
            .replace("__SELECTED_BG__", selected_bg)
            .replace("__TEXT_SOFT__", self._theme_rgba(primary_text, 0.06))
            .replace("__SCROLLBAR__", self._theme_rgba(muted_text, 0.40))
        )

    def _count_text(self, count: int) -> str:
        return t("memory.unit.count", count=f"{count:,}")

    def _item_count_text(self, count: int) -> str:
        return t("memory.unit.items", count=f"{count:,}")

    def _message_count_text(self, count: int) -> str:
        return t("memory.unit.messages", count=f"{count:,}")

    def _sort_button_text(self) -> str:
        return t("memory.sort.newest") if self._sort_descending else t("memory.sort.oldest")

    def _profile_has_content(self, profile) -> bool:
        if profile is None:
            return False

        basic_info = getattr(profile, "basic_info", {}) or {}
        if any(value for value in basic_info.values()):
            return True

        preferences = getattr(profile, "preferences", {}) or {}
        if any(preferences.get(key) for key in ("likes", "dislikes")):
            return True

        facts = getattr(profile, "facts", None) or []
        return bool(facts)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0 if self._embedded else 18, 0 if self._embedded else 18, 0 if self._embedded else 18, 0 if self._embedded else 18)

        surface = CardFrame("Surface")
        root.addWidget(surface)

        layout = QVBoxLayout(surface)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)

        if not self._embedded:
            layout.addWidget(self._build_title_bar())
        layout.addLayout(self._build_stats_row())
        layout.addWidget(self._build_filter_card())

        body_grid = QGridLayout()
        body_grid.setHorizontalSpacing(14)
        body_grid.setVerticalSpacing(14)
        body_grid.addWidget(self._build_memory_list_card(), 0, 0, 2, 2)
        body_grid.addWidget(self._build_inspector_card(), 0, 2)
        body_grid.addWidget(self._build_tuning_card(), 1, 2)
        body_grid.setColumnStretch(0, 1)
        body_grid.setColumnStretch(1, 1)
        body_grid.setColumnStretch(2, 1)
        layout.addLayout(body_grid, 1)

    def _build_title_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TitleBar")
        bar.setFixedHeight(68)

        layout = QHBoxLayout(bar)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(14)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title = QLabel(t("memory.window.title"))
        title.setObjectName("WindowTitle")
        title_col.addWidget(title)

        subtitle = QLabel(t("memory.window.subtitle"))
        subtitle.setObjectName("WindowSubtitle")
        title_col.addWidget(subtitle)
        layout.addLayout(title_col)

        layout.addStretch()

        close_btn = QPushButton("×")
        close_btn.setProperty("ghost", True)
        close_btn.style().unpolish(close_btn)
        close_btn.style().polish(close_btn)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
        return bar

    def _build_stats_row(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.total_metric = self._metric_card(
            t("memory.metric.total.label"),
            "-",
            t("memory.metric.total.detail"),
        )
        self.important_metric = self._metric_card(
            t("memory.metric.important.label"),
            "-",
            t("memory.metric.important.detail"),
        )
        self.embedding_metric = self._metric_card(
            t("memory.metric.embedding.label"),
            "-",
            t("memory.metric.embedding.detail", count="0"),
        )
        self.threshold_metric = self._metric_card(
            t("memory.metric.threshold.label"),
            "-",
            t("memory.metric.threshold.detail"),
        )

        grid.addWidget(self.total_metric, 0, 0)
        grid.addWidget(self.important_metric, 0, 1)
        grid.addWidget(self.embedding_metric, 0, 2)
        grid.addWidget(self.threshold_metric, 0, 3)
        return grid

    def _build_filter_card(self) -> QWidget:
        card = CardFrame("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(14)

        top = QHBoxLayout()
        top.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(t("memory.search.placeholder"))
        self.search_input.textChanged.connect(self._apply_filters)
        top.addWidget(self.search_input, 1)

        self.important_filter_btn = QPushButton(t("memory.filter.important_only"))
        self.important_filter_btn.clicked.connect(self._toggle_important_filter)
        top.addWidget(self.important_filter_btn)

        self.sort_button = QPushButton(self._sort_button_text())
        self.sort_button.setProperty("accent", True)
        self.sort_button.style().unpolish(self.sort_button)
        self.sort_button.style().polish(self.sort_button)
        self.sort_button.clicked.connect(self._toggle_sort_order)
        top.addWidget(self.sort_button)

        self.refresh_btn = QPushButton(t("memory.button.refresh"))
        self.refresh_btn.clicked.connect(self._load_memories)
        top.addWidget(self.refresh_btn)
        layout.addLayout(top)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(10)
        chip_row.addWidget(self._pill(t("memory.chip.summary_tags"), "TagPill"))
        chip_row.addWidget(self._pill(t("memory.chip.retrieval_mix"), "TagPill"))
        chip_row.addWidget(self._pill(t("memory.chip.auto_save"), "TagPill"))
        chip_row.addStretch()
        layout.addLayout(chip_row)
        return card

    def _build_memory_list_card(self) -> QWidget:
        card = CardFrame("ListCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        top = QHBoxLayout()
        top.addWidget(self._pill(t("memory.list.title"), "MutedPill"))
        top.addStretch()

        self.list_hint_label = QLabel(t("memory.list.latest_hint"))
        self.list_hint_label.setObjectName("Body")
        top.addWidget(self.list_hint_label)
        layout.addLayout(top)

        self.memory_list = QListWidget()
        self.memory_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.memory_list.verticalScrollBar().rangeChanged.connect(lambda *_args: self._refresh_memory_item_size_hints())
        self.memory_list.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.memory_list, 1)
        return card

    def _build_inspector_card(self) -> QWidget:
        card = CardFrame("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        layout.addWidget(self._pill(t("memory.inspector.title"), "BluePill"), alignment=Qt.AlignmentFlag.AlignLeft)

        self.inspector_title = QLabel(t("memory.empty.title"))
        self.inspector_title.setObjectName("CardTitle")
        self.inspector_title.setWordWrap(True)
        layout.addWidget(self.inspector_title)

        self.inspector_body = QLabel(t("memory.empty.body"))
        self.inspector_body.setObjectName("Body")
        self.inspector_body.setWordWrap(True)
        layout.addWidget(self.inspector_body)

        self.inspector_tags_row = QHBoxLayout()
        self.inspector_tags_row.setSpacing(8)
        self.inspector_tags_row.addStretch()
        layout.addLayout(self.inspector_tags_row)

        time_row, self.inspector_time_value = self._key_value_row(t("memory.detail.time"))
        layout.addWidget(time_row)
        source_row, self.inspector_source_value = self._key_value_row(t("memory.detail.source_count"))
        layout.addWidget(source_row)
        important_row, self.inspector_important_value = self._key_value_row(t("memory.detail.important"))
        layout.addWidget(important_row)
        embedding_row, self.inspector_embedding_value = self._key_value_row(t("memory.detail.embedding"))
        layout.addWidget(embedding_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        self.important_btn = QPushButton(t("memory.button.mark_important"))
        self.important_btn.setProperty("accent", True)
        self.important_btn.style().unpolish(self.important_btn)
        self.important_btn.style().polish(self.important_btn)
        self.important_btn.clicked.connect(self._toggle_important)
        self.important_btn.setEnabled(False)
        action_row.addWidget(self.important_btn)

        self.delete_btn = QPushButton(t("memory.button.delete"))
        self.delete_btn.clicked.connect(self._delete_memory)
        self.delete_btn.setEnabled(False)
        action_row.addWidget(self.delete_btn)
        layout.addLayout(action_row)

        layout.addStretch(1)
        return card

    def _build_tuning_card(self) -> QWidget:
        card = CardFrame("Card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(14)

        title = QLabel(t("memory.tuning.title"))
        title.setObjectName("CardTitle")
        layout.addWidget(title)

        body = QLabel(t("memory.tuning.body"))
        body.setObjectName("Body")
        body.setWordWrap(True)
        layout.addWidget(body)

        self.threshold_spinbox = QSpinBox()
        self.threshold_spinbox.setRange(2, 100)
        self.threshold_spinbox.setValue(10)
        self.threshold_spinbox.setSuffix(t("memory.unit.count_suffix"))
        self.threshold_spinbox.valueChanged.connect(self._on_threshold_changed)
        layout.addWidget(
            self._wrap_setting_row(
                self.threshold_spinbox,
                t("memory.tuning.threshold.title"),
                t("memory.tuning.threshold.body"),
            )
        )

        self.important_spinbox = QSpinBox()
        self.important_spinbox.setRange(0, 20)
        self.important_spinbox.setValue(3)
        self.important_spinbox.setSuffix(t("memory.unit.count_suffix"))
        self.important_spinbox.valueChanged.connect(self._on_memory_setting_changed)
        layout.addWidget(
            self._wrap_setting_row(
                self.important_spinbox,
                t("memory.tuning.important.title"),
                t("memory.tuning.important.body"),
            )
        )

        self.similar_spinbox = QSpinBox()
        self.similar_spinbox.setRange(0, 20)
        self.similar_spinbox.setValue(3)
        self.similar_spinbox.setSuffix(t("memory.unit.count_suffix"))
        self.similar_spinbox.valueChanged.connect(self._on_memory_setting_changed)
        layout.addWidget(
            self._wrap_setting_row(
                self.similar_spinbox,
                t("memory.tuning.similar.title"),
                t("memory.tuning.similar.body"),
            )
        )

        self.recent_spinbox = QSpinBox()
        self.recent_spinbox.setRange(0, 20)
        self.recent_spinbox.setValue(2)
        self.recent_spinbox.setSuffix(t("memory.unit.count_suffix"))
        self.recent_spinbox.valueChanged.connect(self._on_memory_setting_changed)
        layout.addWidget(
            self._wrap_setting_row(
                self.recent_spinbox,
                t("memory.tuning.recent.title"),
                t("memory.tuning.recent.body"),
            )
        )

        self.similarity_spinbox = QSpinBox()
        self.similarity_spinbox.setRange(1, 100)
        self.similarity_spinbox.setValue(35)
        self.similarity_spinbox.setSuffix(t("memory.unit.percent_suffix"))
        self.similarity_spinbox.valueChanged.connect(self._on_memory_setting_changed)
        layout.addWidget(
            self._wrap_setting_row(
                self.similarity_spinbox,
                t("memory.tuning.similarity.title"),
                t("memory.tuning.similarity.body"),
            )
        )

        note = QLabel(t("memory.tuning.note"))
        note.setObjectName("Body")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return card

    def _metric_card(self, label_text: str, value_text: str, detail_text: str) -> QWidget:
        card = CardFrame("MetricCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(8)

        label = QLabel(label_text)
        label.setObjectName("MetricLabel")
        layout.addWidget(label)

        value = QLabel(value_text)
        value.setObjectName("MetricValue")
        layout.addWidget(value)

        detail = QLabel(detail_text)
        detail.setObjectName("Body")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        card.value_label = value
        card.detail_label = detail
        return card

    def _pill(self, text: str, object_name: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName(object_name)
        return label

    def _key_value_row(self, key_text: str) -> tuple[QWidget, QLabel]:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        key = QLabel(key_text)
        key.setObjectName("KeyValueLabel")
        layout.addWidget(key)
        layout.addStretch()

        value = QLabel("-")
        value.setObjectName("KeyValueValue")
        layout.addWidget(value)
        return widget, value

    def _wrap_setting_row(self, control: QWidget, title_text: str, body_text: str) -> QWidget:
        card = CardFrame("Card")
        layout = QHBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(16)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        title = QLabel(title_text)
        title.setObjectName("KeyValueValue")
        text_col.addWidget(title)

        body = QLabel(body_text)
        body.setObjectName("Body")
        body.setWordWrap(True)
        text_col.addWidget(body)

        layout.addLayout(text_col, 1)
        layout.addWidget(control)
        return card

    def _load_memories(self):
        selected_id = self._selected_memory_id()
        self.memory_list.clear()
        self._item_frames.clear()

        if not self.memory_manager:
            self._update_stats(0, 0, 0)
            self._update_inspector(None)
            return

        stats = self.memory_manager.get_stats()
        self._update_stats(stats["total"], stats["important"], stats["with_embedding"])

        memories = sorted(
            self.memory_manager.memories,
            key=lambda memory: memory.timestamp,
            reverse=self._sort_descending,
        )

        for memory in memories:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, memory.id)

            widget = self._create_memory_widget(memory)
            item.setSizeHint(widget.sizeHint())
            self.memory_list.addItem(item)
            self.memory_list.setItemWidget(item, widget)
            self._item_frames[memory.id] = widget

        self._apply_filters()
        QTimer.singleShot(0, self._refresh_memory_item_size_hints)

        if selected_id:
            self._select_memory_by_id(selected_id)
        elif self.memory_list.count() > 0:
            self._select_first_visible_item()

    def _memory_preview_text(self, memory) -> str:
        text = re.sub(r"\s+", " ", str(memory.summary or "")).strip()
        if not text:
            return t("memory.preview.empty")

        preview_limit = 104
        if len(text) <= preview_limit:
            return text

        trimmed = text[:preview_limit].rstrip(" ,.;:")
        return f"{trimmed}..."

    def _memory_meta_pill(self, text: str, object_name: str, width: int) -> QLabel:
        label = self._pill(text, object_name)
        label.setFixedWidth(width)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return label

    def _refresh_memory_item_size_hints(self) -> None:
        if not hasattr(self, "memory_list"):
            return

        viewport_width = max(0, self.memory_list.viewport().width() - 2)
        if viewport_width <= 0:
            return

        for index in range(self.memory_list.count()):
            item = self.memory_list.item(index)
            widget = self.memory_list.itemWidget(item)
            if widget is None:
                continue

            widget.setFixedWidth(viewport_width)
            widget.layout().activate()
            height = max(84, widget.sizeHint().height())
            item.setSizeHint(QSize(viewport_width, height))

    def _create_memory_widget(self, memory):
        card = CardFrame("MemoryItem")
        card.setProperty("selected", "false")
        card.style().unpolish(card)
        card.style().polish(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(9)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self._memory_meta_pill(self._format_timestamp(memory.timestamp), "MutedPill", 116))
        if memory.is_important:
            top.addWidget(self._memory_meta_pill(t("memory.badge.important"), "BluePill", 68))
        if memory.embedding:
            top.addWidget(self._memory_meta_pill(t("memory.badge.embedding"), "TagPill", 68))
        top.addStretch()
        layout.addLayout(top)

        summary = QLabel(self._memory_preview_text(memory))
        summary.setObjectName("Body")
        summary.setWordWrap(True)
        layout.addWidget(summary)

        if memory.tags:
            tags_row = QHBoxLayout()
            tags_row.setSpacing(8)
            for tag in memory.tags[:4]:
                tags_row.addWidget(self._pill(f"#{tag}", "TagPill"))
            tags_row.addStretch()
            layout.addLayout(tags_row)
        return card

    def _update_stats(self, total: int, important: int, with_embedding: int) -> None:
        coverage = f"{round((with_embedding / total) * 100) if total else 0}%"
        self.total_metric.value_label.setText(f"{total:,}")
        self.important_metric.value_label.setText(f"{important:,}")
        self.embedding_metric.value_label.setText(coverage)
        self.embedding_metric.detail_label.setText(
            t("memory.metric.embedding.detail", count=f"{with_embedding:,}")
        )
        self.threshold_metric.value_label.setText(self._count_text(self.threshold_spinbox.value()))

    def _selected_memory_id(self) -> str | None:
        item = self.memory_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _select_memory_by_id(self, memory_id: str) -> None:
        for index in range(self.memory_list.count()):
            item = self.memory_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == memory_id and not item.isHidden():
                self.memory_list.setCurrentItem(item)
                return
        self._select_first_visible_item()

    def _select_first_visible_item(self) -> None:
        for index in range(self.memory_list.count()):
            item = self.memory_list.item(index)
            if not item.isHidden():
                self.memory_list.setCurrentItem(item)
                return
        self.memory_list.clearSelection()
        self._on_selection_changed()

    def _get_memory_by_id(self, memory_id: str | None):
        if not memory_id or not self.memory_manager:
            return None
        return next((memory for memory in self.memory_manager.memories if memory.id == memory_id), None)

    def _on_selection_changed(self):
        current_id = self._selected_memory_id()
        for memory_id, frame in self._item_frames.items():
            frame.setProperty("selected", "true" if memory_id == current_id else "false")
            frame.style().unpolish(frame)
            frame.style().polish(frame)

        has_selection = bool(current_id)
        self.important_btn.setEnabled(has_selection)
        self.delete_btn.setEnabled(has_selection)
        self._update_inspector(self._get_memory_by_id(current_id))

    def _update_inspector(self, memory) -> None:
        if memory is None:
            self.inspector_title.setText(t("memory.empty.title"))
            self.inspector_body.setText(t("memory.empty.body"))
            self.inspector_time_value.setText("-")
            self.inspector_source_value.setText("-")
            self.inspector_important_value.setText("-")
            self.inspector_embedding_value.setText("-")
            self.important_btn.setText(t("memory.button.mark_important"))
            self._replace_inspector_tags([])
            return

        self.inspector_title.setText((memory.summary or t("memory.summary.empty"))[:60])
        self.inspector_body.setText(memory.summary or "")
        self.inspector_time_value.setText(self._format_timestamp(memory.timestamp))
        self.inspector_source_value.setText(self._message_count_text(len(memory.original_messages)))
        self.inspector_important_value.setText(
            t("memory.value.important.true") if memory.is_important else t("memory.value.important.false")
        )
        self.inspector_embedding_value.setText(
            t("memory.value.embedding.true") if memory.embedding else t("memory.value.embedding.false")
        )
        self.important_btn.setText(
            t("memory.button.unmark_important") if memory.is_important else t("memory.button.mark_important")
        )
        self._replace_inspector_tags(memory.tags)

    def _replace_inspector_tags(self, tags: list[str]) -> None:
        while self.inspector_tags_row.count():
            item = self.inspector_tags_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for tag in tags[:4]:
            self.inspector_tags_row.addWidget(self._pill(f"#{tag}", "TagPill"))
        self.inspector_tags_row.addStretch()

    def _toggle_important_filter(self) -> None:
        self._show_only_important = not self._show_only_important
        self.important_filter_btn.setProperty("accent", self._show_only_important)
        self.important_filter_btn.style().unpolish(self.important_filter_btn)
        self.important_filter_btn.style().polish(self.important_filter_btn)
        self._apply_filters()

    def _toggle_sort_order(self) -> None:
        self._sort_descending = not self._sort_descending
        self.sort_button.setText(self._sort_button_text())
        self._load_memories()

    def _apply_filters(self) -> None:
        query = self.search_input.text().strip().lower()
        visible_count = 0

        for index in range(self.memory_list.count()):
            item = self.memory_list.item(index)
            memory = self._get_memory_by_id(item.data(Qt.ItemDataRole.UserRole))
            if memory is None:
                item.setHidden(True)
                continue

            matches_query = (
                not query
                or query in (memory.summary or "").lower()
                or any(query in str(tag).lower() for tag in memory.tags)
            )
            matches_flag = (not self._show_only_important) or memory.is_important
            visible = matches_query and matches_flag
            item.setHidden(not visible)
            if visible:
                visible_count += 1

        self.list_hint_label.setText(t("memory.list.visible_count", count=f"{visible_count:,}"))
        current_item = self.memory_list.currentItem()
        if current_item is None or current_item.isHidden():
            self._select_first_visible_item()

    def _toggle_important(self):
        memory_id = self._selected_memory_id()
        if not memory_id or not self.memory_manager:
            return

        memory = self._get_memory_by_id(memory_id)
        if memory is None:
            return

        self.memory_manager.set_important(memory_id, not memory.is_important)
        self._load_memories()

    def _delete_memory(self):
        memory_id = self._selected_memory_id()
        if not memory_id or not self.memory_manager:
            return

        memory = self._get_memory_by_id(memory_id)
        summary = memory.summary if memory else t("memory.delete.summary_fallback")
        if len(summary) > 60:
            summary = summary[:60] + "..."

        reply = QMessageBox.question(
            self,
            t("memory.delete.title"),
            t("memory.delete.body", summary=summary),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.memory_manager.delete(memory_id)
        self._load_memories()

    def _load_settings(self):
        if not self.bridge:
            return

        self.threshold_spinbox.setValue(int(getattr(self.bridge, "summarize_threshold", 10)))
        if hasattr(self.bridge, "settings") and self.bridge.settings:
            config = self.bridge.settings.config
            self.important_spinbox.setValue(int(config.get("max_important_memories", 3)))
            self.similar_spinbox.setValue(int(config.get("max_similar_memories", 3)))
            self.similarity_spinbox.setValue(int(config.get("min_similarity", 0.35) * 100))
            self.recent_spinbox.setValue(int(config.get("max_recent_memories", 2)))

    def _on_threshold_changed(self, value):
        self.threshold_metric.value_label.setText(self._count_text(value))
        if self.bridge:
            self.bridge.summarize_threshold = value
            print(f"[Memory Dialog] 자동 요약 임계값: {value}개")
            if hasattr(self.bridge, "settings") and self.bridge.settings:
                self.bridge.settings.config["summarize_threshold"] = value
                self.bridge.settings.save()
                print("[Memory Dialog] 설정 저장 완료")

    def _on_memory_setting_changed(self):
        if not self.bridge or not hasattr(self.bridge, "settings") or not self.bridge.settings:
            return

        config = self.bridge.settings.config
        config["max_important_memories"] = self.important_spinbox.value()
        config["max_similar_memories"] = self.similar_spinbox.value()
        config["min_similarity"] = self.similarity_spinbox.value() / 100.0
        config["max_recent_memories"] = self.recent_spinbox.value()
        self.bridge.settings.save()

        print(
            f"[Memory Dialog] 기억 검색 설정 변경: "
            f"중요={config['max_important_memories']}, "
            f"유사={config['max_similar_memories']}, "
            f"유사도={config['min_similarity']:.2f}, "
            f"최근={config['max_recent_memories']}"
        )

    def _show_profile_dialog(self):
        if not self.bridge or not hasattr(self.bridge, "user_profile"):
            QMessageBox.warning(
                self,
                t("memory.profile.missing.title"),
                t("memory.profile.missing.body"),
            )
            return

        if not self._profile_has_content(self.bridge.user_profile):
            QMessageBox.information(
                self,
                t("memory.profile.empty.title"),
                t("memory.profile.empty.body"),
            )
            return

        from src.ui.profile_dialog import ProfileDialog

        dialog = ProfileDialog(self.bridge.user_profile, self)
        dialog.exec()

    def _format_timestamp(self, timestamp: str) -> str:
        try:
            return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(timestamp)[:16]

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        QTimer.singleShot(0, self._refresh_memory_item_size_hints)

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

    def mousePressEvent(self, event) -> None:
        if self._embedded:
            super().mousePressEvent(event)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        edge = self._hit_test_resize_edge(event.position().toPoint())
        if edge:
            self._resize_active = True
            self._resize_edge = edge
            self._resize_start_global = event.globalPosition().toPoint()
            self._resize_start_geometry = self.geometry()
            event.accept()
            return

        if event.position().y() <= 78:
            self._drag_active = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._embedded:
            super().mouseMoveEvent(event)
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
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._embedded:
            super().mouseReleaseEvent(event)
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_active = False
            self._resize_active = False
            self._resize_edge = ""
            self._update_resize_cursor(event.position().toPoint())
            event.accept()
            return
        super().mouseReleaseEvent(event)
