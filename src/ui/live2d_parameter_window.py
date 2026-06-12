"""Live2D 파라미터를 ENE 창 밖에서 조절하는 네이티브 패널."""
from __future__ import annotations

import json
from functools import partial
from typing import Any

from PyQt6.QtCore import QPoint, QRect, QSize, Qt
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)


class Live2DParameterWindow(QWidget):
    """QWebEngineView 밖에서 움직일 수 있는 Live2D 파라미터 조절 창."""

    SLIDER_SCALE = 1000

    def __init__(self, overlay_window):
        super().__init__(None)
        self.overlay_window = overlay_window
        self._items: list[dict[str, Any]] = []
        self._pinned: set[str] = set()
        self._row_controls: dict[str, tuple[QSlider, QDoubleSpinBox]] = {}
        self._syncing_controls = False
        self._positioned = False

        self.setWindowTitle("Live2D 파라미터")
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setMinimumSize(460, 560)
        self.resize(520, 680)
        self.setStyleSheet(
            """
            QWidget {
                background: #15181f;
                color: #eef3f8;
                font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QLabel#titleLabel {
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#warningLabel {
                color: #f5d58a;
                background: #2a251a;
                border: 1px solid #6f5a25;
                border-radius: 6px;
                padding: 8px 10px;
            }
            QLineEdit, QComboBox, QDoubleSpinBox {
                background: #202531;
                border: 1px solid #384355;
                border-radius: 5px;
                padding: 5px 7px;
                color: #eef3f8;
            }
            QPushButton {
                background: #2a3444;
                border: 1px solid #46566c;
                border-radius: 5px;
                padding: 6px 9px;
                color: #eef3f8;
            }
            QPushButton:hover {
                background: #344258;
            }
            QPushButton:disabled {
                color: #7f8996;
                background: #20242c;
            }
            QFrame#parameterRow {
                background: #1b202a;
                border: 1px solid #303a4a;
                border-radius: 6px;
            }
            QFrame#parameterRow[blocked="true"] {
                color: #8f98a5;
                background: #181c23;
            }
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea QWidget {
                background: transparent;
            }
            """
        )
        self._setup_ui()

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        header_layout = QHBoxLayout()
        self.title_label = QLabel("Live2D 파라미터", self)
        self.title_label.setObjectName("titleLabel")
        self.refresh_button = QPushButton("새로고침", self)
        self.refresh_button.clicked.connect(self.refresh)
        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.refresh_button)
        root_layout.addLayout(header_layout)

        self.warning_label = QLabel(
            "장식물 변경용 창입니다. 표정, 입, 눈, 몸 각도처럼 감정 표현이나 쓰다듬 기능이 사용하는 파라미터는 건드리지 않는 것을 추천합니다.",
            self,
        )
        self.warning_label.setObjectName("warningLabel")
        self.warning_label.setWordWrap(True)
        root_layout.addWidget(self.warning_label)

        controls_layout = QHBoxLayout()
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("파라미터 검색")
        self.search_input.textChanged.connect(self._render_rows)
        self.filter_combo = QComboBox(self)
        self.filter_combo.addItem("추천", "recommended")
        self.filter_combo.addItem("전체", "all")
        self.filter_combo.addItem("고정", "pinned")
        self.filter_combo.currentIndexChanged.connect(self._render_rows)
        controls_layout.addWidget(self.search_input, 1)
        controls_layout.addWidget(self.filter_combo)
        root_layout.addLayout(controls_layout)

        self.status_label = QLabel("파라미터 목록을 불러오기 전입니다.", self)
        root_layout.addWidget(self.status_label)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.rows_container = QWidget(self.scroll_area)
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        self.rows_layout.setSpacing(8)
        self.rows_layout.addStretch(1)
        self.scroll_area.setWidget(self.rows_container)
        root_layout.addWidget(self.scroll_area, 1)

        footer_layout = QHBoxLayout()
        self.reset_button = QPushButton("보이는 항목 초기화", self)
        self.reset_button.clicked.connect(self._reset_visible_items)
        self.save_button = QPushButton("저장", self)
        self.save_button.clicked.connect(self.save)
        self.close_button = QPushButton("닫기", self)
        self.close_button.clicked.connect(self.hide)
        footer_layout.addWidget(self.reset_button)
        footer_layout.addStretch(1)
        footer_layout.addWidget(self.save_button)
        footer_layout.addWidget(self.close_button)
        root_layout.addLayout(footer_layout)

    def show_and_refresh(self) -> None:
        if not self._positioned:
            self._position_near_overlay()
            self._positioned = True
        self.show()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def refresh(self) -> None:
        self.status_label.setText("파라미터 목록을 불러오는 중입니다.")
        self._run_live2d_js(
            "window.getLive2DParameterInspectorSnapshot ? window.getLive2DParameterInspectorSnapshot() : ''",
            self._apply_snapshot_result,
        )

    def save(self) -> None:
        self._run_live2d_js(
            "window.saveLive2DParameterInspectorOverrides ? window.saveLive2DParameterInspectorOverrides() : false",
            lambda _result: self.refresh(),
        )

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()

    def _position_near_overlay(self) -> None:
        overlay = self.overlay_window
        if not overlay:
            return
        overlay_geometry = overlay.frameGeometry()
        screen = QGuiApplication.screenAt(overlay_geometry.center()) or QGuiApplication.primaryScreen()
        screen_geometry = screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)
        self.move(
            self.resolve_initial_position(
                overlay_geometry=overlay_geometry,
                screen_geometry=screen_geometry,
                window_size=self.size(),
            )
        )

    @staticmethod
    def resolve_initial_position(
        overlay_geometry: QRect,
        screen_geometry: QRect,
        window_size: QSize,
        margin: int = 16,
    ) -> QPoint:
        preferred_x = overlay_geometry.right() + margin
        preferred_y = overlay_geometry.top() + 40
        if preferred_x + window_size.width() > screen_geometry.right() - margin:
            preferred_x = overlay_geometry.left() - window_size.width() - margin
        min_x = screen_geometry.left() + margin
        max_x = screen_geometry.right() - window_size.width() - margin
        min_y = screen_geometry.top() + margin
        max_y = screen_geometry.bottom() - window_size.height() - margin
        return QPoint(
            min(max(preferred_x, min_x), max(min_x, max_x)),
            min(max(preferred_y, min_y), max(min_y, max_y)),
        )

    def _run_live2d_js(self, script: str, callback=None) -> None:
        web_view = getattr(self.overlay_window, "web_view", None)
        page_getter = getattr(web_view, "page", None)
        if not callable(page_getter):
            if callback:
                callback("")
            return
        page = page_getter()
        if callback:
            page.runJavaScript(script, callback)
        else:
            page.runJavaScript(script)

    def _apply_snapshot_result(self, raw_result) -> None:
        payload = self._decode_snapshot(raw_result)
        status = str(payload.get("metadataStatus") or "error")
        self._items = [
            item
            for item in payload.get("metadata", [])
            if isinstance(item, dict) and item.get("id")
        ]
        self._pinned = {str(item) for item in payload.get("pinned", []) if item}
        self.save_button.setEnabled(status == "ready")
        self.reset_button.setEnabled(status == "ready")

        if status == "ready":
            self.status_label.setText(f"읽은 파라미터: {len(self._items)}개")
        elif status == "unavailable":
            self.status_label.setText("현재 Live2D 모델에서 파라미터 목록을 읽을 수 없습니다.")
        elif status == "loading":
            self.status_label.setText("파라미터 목록을 불러오는 중입니다.")
        else:
            self.status_label.setText(str(payload.get("metadataError") or "파라미터 목록을 불러오지 못했습니다."))
        self._render_rows()

    def _decode_snapshot(self, raw_result) -> dict[str, Any]:
        if isinstance(raw_result, dict):
            return raw_result
        if not raw_result:
            return {"metadataStatus": "error", "metadata": []}
        try:
            payload = json.loads(str(raw_result))
        except Exception:
            return {"metadataStatus": "error", "metadata": []}
        return payload if isinstance(payload, dict) else {"metadataStatus": "error", "metadata": []}

    def _filtered_items(self) -> list[dict[str, Any]]:
        query = self.search_input.text().strip().lower()
        filter_name = self.filter_combo.currentData()
        items: list[dict[str, Any]] = []
        for item in self._items:
            param_id = str(item.get("id") or "")
            if filter_name == "recommended" and not item.get("recommended"):
                continue
            if filter_name == "pinned" and param_id not in self._pinned:
                continue
            if query and query not in param_id.lower():
                continue
            items.append(item)
        return items

    def _render_rows(self) -> None:
        while self.rows_layout.count() > 1:
            item = self.rows_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._row_controls = {}

        visible_items = self._filtered_items()
        if not visible_items:
            empty_label = QLabel("표시할 파라미터가 없습니다.", self.rows_container)
            self.rows_layout.insertWidget(0, empty_label)
            return

        for item in visible_items:
            self.rows_layout.insertWidget(self.rows_layout.count() - 1, self._build_row(item))

    def _build_row(self, item: dict[str, Any]) -> QFrame:
        param_id = str(item.get("id") or "")
        is_allowed = bool(item.get("recommended"))
        row = QFrame(self.rows_container)
        row.setObjectName("parameterRow")
        row.setProperty("blocked", "false" if is_allowed else "true")
        row_layout = QVBoxLayout(row)
        row_layout.setContentsMargins(10, 8, 10, 8)
        row_layout.setSpacing(6)

        header_layout = QHBoxLayout()
        pin_box = QCheckBox("고정", row)
        pin_box.setChecked(param_id in self._pinned)
        pin_box.stateChanged.connect(partial(self._set_pinned, param_id))
        title = QLabel(param_id, row)
        title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header_layout.addWidget(title, 1)
        header_layout.addWidget(pin_box)
        row_layout.addLayout(header_layout)

        controls_layout = QHBoxLayout()
        slider = QSlider(Qt.Orientation.Horizontal, row)
        spin_box = QDoubleSpinBox(row)
        spin_box.setDecimals(3)
        spin_box.setSingleStep(0.01)

        minimum = float(item.get("min", 0) or 0)
        maximum = float(item.get("max", 1) or 1)
        current = float(item.get("current", item.get("default", 0)) or 0)
        if minimum > maximum:
            minimum, maximum = maximum, minimum
        slider.setRange(round(minimum * self.SLIDER_SCALE), round(maximum * self.SLIDER_SCALE))
        slider.setValue(round(current * self.SLIDER_SCALE))
        spin_box.setRange(minimum, maximum)
        spin_box.setValue(current)
        slider.setEnabled(is_allowed)
        spin_box.setEnabled(is_allowed)

        slider.valueChanged.connect(partial(self._on_slider_changed, param_id))
        spin_box.valueChanged.connect(partial(self._on_spin_changed, param_id))

        reset_button = QPushButton("초기화", row)
        reset_button.setEnabled(is_allowed)
        reset_button.clicked.connect(partial(self._reset_parameter, param_id))

        controls_layout.addWidget(slider, 1)
        controls_layout.addWidget(spin_box)
        controls_layout.addWidget(reset_button)
        row_layout.addLayout(controls_layout)
        self._row_controls[param_id] = (slider, spin_box)
        return row

    def _on_slider_changed(self, param_id: str, raw_value: int) -> None:
        if self._syncing_controls:
            return
        value = raw_value / self.SLIDER_SCALE
        self._sync_control_value(param_id, value)
        self._set_parameter_value(param_id, value)

    def _on_spin_changed(self, param_id: str, value: float) -> None:
        if self._syncing_controls:
            return
        self._sync_control_value(param_id, value)
        self._set_parameter_value(param_id, value)

    def _sync_control_value(self, param_id: str, value: float) -> None:
        controls = self._row_controls.get(param_id)
        if not controls:
            return
        slider, spin_box = controls
        self._syncing_controls = True
        slider.setValue(round(float(value) * self.SLIDER_SCALE))
        spin_box.setValue(float(value))
        self._syncing_controls = False
        for item in self._items:
            if item.get("id") == param_id:
                item["current"] = float(value)
                break

    def _set_parameter_value(self, param_id: str, value: float) -> None:
        script = (
            "window.setLive2DParameterInspectorValue"
            f" && window.setLive2DParameterInspectorValue({json.dumps(param_id)}, {json.dumps(float(value))})"
        )
        self._run_live2d_js(script)

    def _set_pinned(self, param_id: str, state: int) -> None:
        pinned = state == Qt.CheckState.Checked.value
        if pinned:
            self._pinned.add(param_id)
        else:
            self._pinned.discard(param_id)
        script = (
            "window.setLive2DParameterInspectorPinned"
            f" && window.setLive2DParameterInspectorPinned({json.dumps(param_id)}, {json.dumps(pinned)})"
        )
        self._run_live2d_js(script)
        if self.filter_combo.currentData() == "pinned":
            self._render_rows()

    def _reset_parameter(self, param_id: str) -> None:
        script = (
            "window.resetLive2DParameterInspectorValue"
            f" && window.resetLive2DParameterInspectorValue({json.dumps(param_id)})"
        )
        self._run_live2d_js(script, lambda _result: self.refresh())

    def _reset_visible_items(self) -> None:
        param_ids = [
            str(item.get("id") or "")
            for item in self._filtered_items()
            if item.get("recommended") and item.get("id")
        ]
        if not param_ids:
            return
        script = (
            "window.resetLive2DParameterInspectorValues"
            f" && window.resetLive2DParameterInspectorValues({json.dumps(param_ids, ensure_ascii=False)})"
        )
        self._run_live2d_js(script, lambda _result: self.refresh())
