"""
Obsidian 파일 트리 전용 플로팅 패널
"""
from __future__ import annotations

import json

from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QFrame,
)


class ObsidianPanelWindow(QWidget):
    """ENE 외부에서 동작하는 Obsidian 전용 패널."""

    def __init__(self, bridge, obs_settings, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.obs_settings = obs_settings
        self._dragging = False
        self._drag_offset = QPoint()
        self._updating_tree = False

        self.setWindowTitle("Obsidian")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumSize(280, 360)
        self.setStyleSheet(
            """
            QWidget {
                background: rgba(24, 28, 36, 230);
                color: #e8edf2;
                border: 1px solid rgba(120, 140, 168, 0.42);
                border-radius: 10px;
            }
            QFrame#obsHeader {
                background: rgba(34, 40, 52, 240);
                border: none;
                border-bottom: 1px solid rgba(120, 140, 168, 0.30);
                border-top-left-radius: 10px;
                border-top-right-radius: 10px;
            }
            QLabel#obsTitle {
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#obsSubTitle {
                font-size: 11px;
                color: #b8c3d1;
                border: none;
                background: transparent;
            }
            QPushButton {
                background: rgba(72, 86, 112, 170);
                border: 1px solid rgba(140, 160, 188, 0.35);
                border-radius: 6px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background: rgba(92, 108, 136, 200);
            }
            QTreeWidget {
                border: none;
                background: rgba(18, 22, 30, 230);
                border-bottom-left-radius: 10px;
                border-bottom-right-radius: 10px;
                outline: none;
            }
            QTreeWidget::item {
                height: 22px;
                padding-left: 2px;
            }
            QTreeWidget::item:selected {
                background: rgba(78, 110, 172, 120);
            }
            """
        )

        self._setup_ui()
        self._restore_geometry()
        self._connect_bridge_signals()
        self.refresh_tree()

    def _setup_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.header = QFrame(self)
        self.header.setObjectName("obsHeader")
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(10, 7, 10, 7)
        header_layout.setSpacing(8)

        self.title_label = QLabel("Obsidian", self.header)
        self.title_label.setObjectName("obsTitle")
        self.subtitle_label = QLabel("드래그로 이동 / 체크 파일은 컨텍스트에 포함", self.header)
        self.subtitle_label.setObjectName("obsSubTitle")
        subtitle_wrap = QVBoxLayout()
        subtitle_wrap.setContentsMargins(0, 0, 0, 0)
        subtitle_wrap.setSpacing(0)
        subtitle_wrap.addWidget(self.title_label)
        subtitle_wrap.addWidget(self.subtitle_label)

        self.refresh_button = QPushButton("새로고침", self.header)
        self.refresh_button.clicked.connect(self.refresh_tree)

        header_layout.addLayout(subtitle_wrap, 1)
        header_layout.addWidget(self.refresh_button, 0)
        root_layout.addWidget(self.header)

        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.tree.itemChanged.connect(self._on_item_changed)
        root_layout.addWidget(self.tree, 1)

    def _connect_bridge_signals(self):
        if hasattr(self.bridge, "obs_tree_updated"):
            self.bridge.obs_tree_updated.connect(self._on_obs_tree_updated)

    def _restore_geometry(self):
        x = int(self.obs_settings.get("floating_window_x", 40) or 40)
        y = int(self.obs_settings.get("floating_window_y", 120) or 120)
        w = int(self.obs_settings.get("floating_window_width", 360) or 360)
        h = int(self.obs_settings.get("floating_window_height", 520) or 520)
        self.setGeometry(x, y, max(280, w), max(360, h))
        self._ensure_visible_on_screen()

    def _ensure_visible_on_screen(self):
        """패널이 화면 밖으로 벗어나면 현재 화면 안으로 보정한다."""
        screens = QGuiApplication.screens() or []
        if not screens:
            return

        frame = self.frameGeometry()
        # 현재 프레임과 교차하는 화면이 있으면 그대로 둔다.
        for screen in screens:
            if screen.availableGeometry().intersects(frame):
                return

        primary = QGuiApplication.primaryScreen()
        if not primary:
            primary = screens[0]
        area = primary.availableGeometry()
        x = max(area.left(), min(area.right() - self.width() + 1, area.left() + 40))
        y = max(area.top(), min(area.bottom() - self.height() + 1, area.top() + 80))
        self.move(x, y)

    def _save_geometry(self):
        self.obs_settings.set("floating_window_x", int(self.x()))
        self.obs_settings.set("floating_window_y", int(self.y()))
        self.obs_settings.set("floating_window_width", int(self.width()))
        self.obs_settings.set("floating_window_height", int(self.height()))
        self.obs_settings.save()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.header.geometry().contains(event.position().toPoint()):
            self._dragging = True
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & Qt.MouseButton.LeftButton):
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._save_geometry()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._save_geometry()

    def closeEvent(self, event):
        self.obs_settings.set("panel_visible", False)
        self._save_geometry()
        event.accept()

    def refresh_tree(self):
        if hasattr(self.bridge, "refresh_obs_tree"):
            self.bridge.refresh_obs_tree()

    def _on_obs_tree_updated(self, payload: str):
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
        except Exception as e:
            data = {"ok": False, "error": f"트리 파싱 실패: {e}", "nodes": []}
        self._render_tree(data)

    def _render_tree(self, payload: dict):
        self._updating_tree = True
        self.tree.clear()

        if not payload or not payload.get("ok"):
            err = str((payload or {}).get("error", "트리 조회 실패"))
            item = QTreeWidgetItem([f"연결 실패: {err}"])
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(item)
            self._updating_tree = False
            return

        checked = set(payload.get("checked_files", []))
        for node in payload.get("nodes", []):
            self.tree.addTopLevelItem(self._create_node_item(node, checked))
        self.tree.expandToDepth(1)
        self._updating_tree = False

    def _create_node_item(self, node: dict, checked: set[str]) -> QTreeWidgetItem:
        node_type = str(node.get("type", ""))
        path = str(node.get("path", "") or node.get("name", ""))
        label = path
        if node_type == "dir":
            label = f"[DIR] {path}"
        else:
            label = f"[FILE] {path}"

        item = QTreeWidgetItem([label])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        item.setData(0, Qt.ItemDataRole.UserRole + 1, node_type)

        if node_type == "file":
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
            )
            state = Qt.CheckState.Checked if path in checked else Qt.CheckState.Unchecked
            item.setCheckState(0, state)
        else:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEnabled)
            for child in node.get("children", []):
                item.addChild(self._create_node_item(child, checked))
        return item

    def _on_item_changed(self, item: QTreeWidgetItem, _column: int):
        if self._updating_tree:
            return
        node_type = str(item.data(0, Qt.ItemDataRole.UserRole + 1) or "")
        if node_type != "file":
            return
        rel_path = str(item.data(0, Qt.ItemDataRole.UserRole) or "").strip()
        if not rel_path:
            return
        checked = item.checkState(0) == Qt.CheckState.Checked
        if hasattr(self.bridge, "set_obs_file_checked"):
            self.bridge.set_obs_file_checked(rel_path, checked)
