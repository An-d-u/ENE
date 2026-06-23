"""
설정 대화상자 에네 목표 관리 mixin.
"""

from __future__ import annotations

import json

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class SettingsDialogGoalsMixin:
    def _create_ene_goals_group(self) -> QGroupBox:
        goals_group = QGroupBox("에네 목표")
        self._bind_group_title(goals_group, "settings.behavior.goals.title", "에네 목표")
        goals_layout = QVBoxLayout(goals_group)
        goals_layout.setSpacing(10)

        lists_layout = QHBoxLayout()
        lists_layout.setSpacing(10)

        active_col = QVBoxLayout()
        active_label = self._create_form_label("settings.behavior.goals.active", "활성 목표")
        active_col.addWidget(active_label)
        self._goal_active_list = QListWidget()
        self._goal_active_list.setMinimumHeight(120)
        self._goal_active_list.currentItemChanged.connect(self._on_goal_selection_changed)
        self._goal_active_list.itemSelectionChanged.connect(self._refresh_ene_goal_controls)
        active_col.addWidget(self._goal_active_list)
        lists_layout.addLayout(active_col, 1)

        history_col = QVBoxLayout()
        history_label = self._create_form_label("settings.behavior.goals.history", "기록 미리보기")
        history_col.addWidget(history_label)
        self._goal_history_list = QListWidget()
        self._goal_history_list.setMinimumHeight(120)
        self._goal_history_list.currentItemChanged.connect(self._on_goal_history_selected)
        history_col.addWidget(self._goal_history_list)
        lists_layout.addLayout(history_col, 1)
        goals_layout.addLayout(lists_layout)

        self._goal_empty_label = self._build_hint_label(
            "표시할 목표가 아직 없습니다.",
            key="settings.behavior.goals.empty",
        )
        goals_layout.addWidget(self._goal_empty_label)

        form = QFormLayout()
        form.setSpacing(8)
        form.setContentsMargins(0, 0, 0, 0)

        self._goal_type_combo = QComboBox()
        self._goal_type_combo.addItem(
            self._translated_text("settings.behavior.goals.short_term", "단기"),
            "short_term",
        )
        self._bind_combo_item(self._goal_type_combo, 0, "settings.behavior.goals.short_term", "단기")
        self._goal_type_combo.addItem(
            self._translated_text("settings.behavior.goals.long_term", "장기"),
            "long_term",
        )
        self._bind_combo_item(self._goal_type_combo, 1, "settings.behavior.goals.long_term", "장기")
        self._goal_form_labels.append(
            self._add_form_row(form, "settings.behavior.goals.type", "유형:", self._goal_type_combo)
        )

        self._goal_title_edit = QLineEdit()
        self._goal_form_labels.append(
            self._add_form_row(form, "settings.behavior.goals.title_label", "제목:", self._goal_title_edit)
        )

        self._goal_reason_edit = QPlainTextEdit()
        self._goal_reason_edit.setMinimumHeight(80)
        self._goal_form_labels.append(
            self._add_form_row(form, "settings.behavior.goals.reason", "이유/메모:", self._goal_reason_edit)
        )
        goals_layout.addLayout(form)

        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(8)
        buttons_layout.addStretch()

        self._goal_add_button = QPushButton("추가")
        self._bind_widget_text(self._goal_add_button, "settings.behavior.goals.add", "추가")
        self._goal_add_button.clicked.connect(self._on_goal_add_clicked)
        buttons_layout.addWidget(self._goal_add_button)

        self._goal_update_button = QPushButton("수정")
        self._bind_widget_text(self._goal_update_button, "settings.behavior.goals.update", "수정")
        self._goal_update_button.clicked.connect(self._on_goal_update_clicked)
        buttons_layout.addWidget(self._goal_update_button)

        self._goal_complete_button = QPushButton("완료")
        self._bind_widget_text(self._goal_complete_button, "settings.behavior.goals.complete", "완료")
        self._goal_complete_button.clicked.connect(self._on_goal_complete_clicked)
        buttons_layout.addWidget(self._goal_complete_button)

        self._goal_cancel_button = QPushButton("취소")
        self._bind_widget_text(self._goal_cancel_button, "settings.behavior.goals.cancel", "취소")
        self._goal_cancel_button.clicked.connect(self._on_goal_cancel_clicked)
        buttons_layout.addWidget(self._goal_cancel_button)
        goals_layout.addLayout(buttons_layout)

        return goals_group

    def _connect_goal_bridge(self) -> None:
        if self._goal_bridge_connected or self._bridge is None:
            return
        signal = getattr(self._bridge, "goal_items_updated", None)
        connect = getattr(signal, "connect", None)
        if callable(connect):
            try:
                connect(self._on_goal_items_updated)
                self._goal_bridge_connected = True
            except Exception:
                self._goal_bridge_connected = False

    def _request_goal_items(self) -> None:
        request = getattr(self._bridge, "request_goal_items", None) if self._bridge is not None else None
        if callable(request):
            try:
                request()
            except Exception:
                return

    def _goal_bridge_method(self, name: str):
        if self._bridge is None:
            return None
        method = getattr(self._bridge, name, None)
        return method if callable(method) else None

    def _selected_goal_id(self) -> str:
        if self._goal_active_list is None:
            return ""
        selected_items = self._goal_active_list.selectedItems()
        item = selected_items[0] if selected_items else None
        if item is None:
            return ""
        goal_id = item.data(Qt.ItemDataRole.UserRole)
        return str(goal_id or "").strip()

    def _goal_type_label(self, goal_type: str) -> str:
        if goal_type == "long_term":
            return self._translated_text("settings.behavior.goals.long_term", "장기")
        return self._translated_text("settings.behavior.goals.short_term", "단기")

    def _format_goal_item_text(self, goal: dict, *, include_status: bool = False) -> str:
        goal_type = self._goal_type_label(str(goal.get("type") or "short_term"))
        title = str(goal.get("title") or "").strip()
        if not title:
            title = self._translated_text("settings.behavior.goals.empty", "표시할 목표가 아직 없습니다.")
        if include_status:
            status = str(goal.get("status") or "").strip()
            if status:
                return f"[{goal_type}] {title} · {status}"
        return f"[{goal_type}] {title}"

    def _normalize_goal_snapshot(self, payload) -> tuple[list[dict], list[dict]]:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            payload = {}

        active_goals = payload.get("active_goals")
        if active_goals is None:
            active_source = payload.get("active", {})
            active_goals = []
            if isinstance(active_source, dict):
                for goal_type in ("short_term", "long_term"):
                    for goal in active_source.get(goal_type, []) or []:
                        if isinstance(goal, dict):
                            active_goals.append(goal)
            elif isinstance(active_source, list):
                active_goals = active_source

        history = payload.get("history", [])
        active = [goal for goal in active_goals or [] if isinstance(goal, dict)]
        history_items = [goal for goal in history or [] if isinstance(goal, dict)]
        return active, history_items

    def _render_goal_items(self, active_goals: list[dict], history_items: list[dict]) -> None:
        self._goal_active_snapshot = [dict(goal) for goal in active_goals if isinstance(goal, dict)]
        self._goal_history_snapshot = [dict(goal) for goal in history_items if isinstance(goal, dict)]
        self._goal_items = {}
        if self._goal_active_list is not None:
            self._goal_active_list.clear()
            for goal in self._goal_active_snapshot:
                goal_id = str(goal.get("id") or "").strip()
                if not goal_id:
                    continue
                self._goal_items[goal_id] = dict(goal)
                item = QListWidgetItem(self._format_goal_item_text(goal))
                item.setData(Qt.ItemDataRole.UserRole, goal_id)
                self._goal_active_list.addItem(item)

        if self._goal_history_list is not None:
            self._goal_history_list.clear()
            for goal in self._goal_history_snapshot[-20:]:
                goal_id = str(goal.get("id") or "").strip()
                if goal_id:
                    self._goal_items[goal_id] = dict(goal)
                item = QListWidgetItem(self._format_goal_item_text(goal, include_status=True))
                item.setData(Qt.ItemDataRole.UserRole, goal_id)
                self._goal_history_list.addItem(item)

        has_items = bool(self._goal_active_snapshot or self._goal_history_snapshot)
        if self._goal_empty_label is not None:
            self._goal_empty_label.setVisible(not has_items)
        self._refresh_ene_goal_controls()

    def _on_goal_items_updated(self, payload) -> None:
        active_goals, history_items = self._normalize_goal_snapshot(payload)
        self._render_goal_items(active_goals, history_items)

    def _on_goal_selection_changed(self, current, previous=None) -> None:
        if current is not None and self._goal_history_list is not None:
            self._goal_history_list.blockSignals(True)
            self._goal_history_list.clearSelection()
            self._goal_history_list.setCurrentRow(-1)
            self._goal_history_list.blockSignals(False)
        goal_id = self._selected_goal_id()
        goal = self._goal_items.get(goal_id, {})
        if goal and self._goal_type_combo is not None:
            goal_type_index = self._goal_type_combo.findData(str(goal.get("type") or "short_term"))
            self._goal_type_combo.setCurrentIndex(goal_type_index if goal_type_index >= 0 else 0)
        if self._goal_title_edit is not None:
            self._goal_title_edit.setText(str(goal.get("title") or ""))
        if self._goal_reason_edit is not None:
            self._goal_reason_edit.setPlainText(str(goal.get("reason") or ""))
        self._refresh_ene_goal_controls()

    def _on_goal_history_selected(self, current, previous=None) -> None:
        if current is None:
            return
        if self._goal_active_list is not None:
            self._goal_active_list.blockSignals(True)
            self._goal_active_list.clearSelection()
            self._goal_active_list.setCurrentRow(-1)
            self._goal_active_list.blockSignals(False)
        goal_id = str(current.data(Qt.ItemDataRole.UserRole) or "").strip()
        goal = self._goal_items.get(goal_id, {})
        if self._goal_type_combo is not None and goal:
            goal_type_index = self._goal_type_combo.findData(str(goal.get("type") or "short_term"))
            self._goal_type_combo.setCurrentIndex(goal_type_index if goal_type_index >= 0 else 0)
        if self._goal_title_edit is not None:
            self._goal_title_edit.setText(str(goal.get("title") or ""))
        if self._goal_reason_edit is not None:
            self._goal_reason_edit.setPlainText(str(goal.get("reason") or goal.get("completion_reason") or ""))
        self._refresh_ene_goal_controls()

    def _refresh_ene_goal_controls(self) -> None:
        goals_enabled = bool(self.enable_ene_goals_check and self.enable_ene_goals_check.isChecked())
        if self.show_ene_goal_button_check is not None:
            self.show_ene_goal_button_check.setEnabled(goals_enabled)

        has_selection = bool(self._selected_goal_id())
        edit_widgets = [
            self._goal_active_list,
            self._goal_history_list,
            self._goal_title_edit,
            self._goal_reason_edit,
            *self._goal_form_labels,
        ]
        for widget in edit_widgets:
            if widget is not None:
                widget.setEnabled(goals_enabled)
        if self._goal_type_combo is not None:
            self._goal_type_combo.setEnabled(goals_enabled and not has_selection)

        button_rules = (
            (self._goal_add_button, "add_manual_goal", not has_selection),
            (self._goal_update_button, "update_goal_item", has_selection),
            (self._goal_complete_button, "complete_goal_item", has_selection),
            (self._goal_cancel_button, "cancel_goal_item", has_selection),
        )
        for button, method_name, extra_enabled in button_rules:
            if button is not None:
                button.setEnabled(goals_enabled and extra_enabled and self._goal_bridge_method(method_name) is not None)

    def _on_ene_goals_toggle(self, checked: bool):
        self._refresh_ene_goal_controls()
        self._on_setting_changed()

    def _on_goal_add_clicked(self) -> None:
        method = self._goal_bridge_method("add_manual_goal")
        if method is None or self._goal_type_combo is None or self._goal_title_edit is None or self._goal_reason_edit is None:
            return
        title = self._goal_title_edit.text().strip()
        if not title:
            return
        goal_type = str(self._goal_type_combo.currentData() or "short_term")
        method(goal_type, title, self._goal_reason_edit.toPlainText().strip())

    def _on_goal_update_clicked(self) -> None:
        method = self._goal_bridge_method("update_goal_item")
        if method is None or self._goal_title_edit is None or self._goal_reason_edit is None:
            return
        goal_id = self._selected_goal_id()
        title = self._goal_title_edit.text().strip()
        if not goal_id or not title:
            return
        method(goal_id, title, self._goal_reason_edit.toPlainText().strip())

    def _on_goal_complete_clicked(self) -> None:
        method = self._goal_bridge_method("complete_goal_item")
        if method is None or self._goal_reason_edit is None:
            return
        goal_id = self._selected_goal_id()
        if goal_id:
            method(goal_id, self._goal_reason_edit.toPlainText().strip())

    def _on_goal_cancel_clicked(self) -> None:
        method = self._goal_bridge_method("cancel_goal_item")
        if method is None or self._goal_reason_edit is None:
            return
        goal_id = self._selected_goal_id()
        if goal_id:
            method(goal_id, self._goal_reason_edit.toPlainText().strip())
