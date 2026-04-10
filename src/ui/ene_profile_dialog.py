"""
에네 자기 정보 관리 다이얼로그
"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ..ai.ene_profile import EneProfileFact
from ..core.i18n import tr as t


class EneProfileDialog(QDialog):
    """에네 자기 정보 CRUD 다이얼로그."""

    CORE_GROUPS = ("identity", "speaking_style", "relationship_tone")
    FACT_CATEGORIES = ("basic", "preference", "goal", "habit", "speaking_style", "relationship_tone")

    def __init__(self, ene_profile, parent=None):
        super().__init__(parent)
        self.ene_profile = ene_profile
        self._core_current_index = -1
        self._fact_current_index = -1
        self._core_items: list[dict] = []
        self._fact_items: list[dict] = []

        self.setWindowTitle(t("ene_profile.window.title"))
        self.setMinimumSize(860, 620)

        self._setup_ui()
        self._load_profile()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        stats_layout = QHBoxLayout()
        self.stats_label = QLabel()
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        layout.addLayout(stats_layout)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)

        self.core_group = QGroupBox(t("ene_profile.section.core"))
        core_layout = QHBoxLayout(self.core_group)
        core_layout.setSpacing(10)

        self.core_list = QListWidget()
        self.core_list.currentRowChanged.connect(self._on_core_selected)
        core_layout.addWidget(self.core_list, 1)

        core_editor = QVBoxLayout()
        core_editor.setSpacing(8)
        self.core_group_combo = QComboBox()
        for group in self.CORE_GROUPS:
            self.core_group_combo.addItem(t(f"ene_profile.core.{group}"), group)
        core_editor.addWidget(self.core_group_combo)

        self.core_content_edit = QPlainTextEdit()
        self.core_content_edit.setPlaceholderText(t("ene_profile.core.content.placeholder"))
        self.core_content_edit.setMinimumHeight(120)
        core_editor.addWidget(self.core_content_edit, 1)

        core_actions = QHBoxLayout()
        self.core_new_btn = QPushButton(t("ene_profile.button.new"))
        self.core_new_btn.clicked.connect(self._new_core_item)
        core_actions.addWidget(self.core_new_btn)
        self.core_apply_btn = QPushButton(t("ene_profile.button.apply"))
        self.core_apply_btn.clicked.connect(self._apply_core_item)
        core_actions.addWidget(self.core_apply_btn)
        self.core_delete_btn = QPushButton(t("ene_profile.button.delete"))
        self.core_delete_btn.clicked.connect(self._delete_core_item)
        core_actions.addWidget(self.core_delete_btn)
        core_editor.addLayout(core_actions)
        core_layout.addLayout(core_editor, 1)

        self.fact_group = QGroupBox(t("ene_profile.section.facts"))
        fact_layout = QHBoxLayout(self.fact_group)
        fact_layout.setSpacing(10)

        self.fact_list = QListWidget()
        self.fact_list.currentRowChanged.connect(self._on_fact_selected)
        fact_layout.addWidget(self.fact_list, 1)

        fact_editor = QVBoxLayout()
        fact_editor.setSpacing(8)

        self.fact_content_edit = QPlainTextEdit()
        self.fact_content_edit.setPlaceholderText(t("ene_profile.fact.content.placeholder"))
        self.fact_content_edit.setMinimumHeight(140)
        fact_editor.addWidget(self.fact_content_edit)

        fact_meta_row = QHBoxLayout()
        self.fact_category_combo = QComboBox()
        for category in self.FACT_CATEGORIES:
            self.fact_category_combo.addItem(t(f"ene_profile.category.{category}"), category)
        fact_meta_row.addWidget(self.fact_category_combo)

        self.fact_origin_combo = QComboBox()
        self.fact_origin_combo.addItem(t("ene_profile.origin.auto"), "auto")
        self.fact_origin_combo.addItem(t("ene_profile.origin.manual"), "manual")
        fact_meta_row.addWidget(self.fact_origin_combo)
        fact_editor.addLayout(fact_meta_row)

        self.fact_source_input = QLineEdit()
        self.fact_source_input.setPlaceholderText(t("ene_profile.fact.source.placeholder"))
        fact_editor.addWidget(self.fact_source_input)

        self.fact_auto_update_check = QCheckBox(t("ene_profile.fact.auto_update"))
        self.fact_auto_update_check.setChecked(True)
        fact_editor.addWidget(self.fact_auto_update_check)

        self.fact_timestamp_label = QLabel()
        fact_editor.addWidget(self.fact_timestamp_label)

        fact_actions = QHBoxLayout()
        self.fact_new_btn = QPushButton(t("ene_profile.button.new"))
        self.fact_new_btn.clicked.connect(self._new_fact_item)
        fact_actions.addWidget(self.fact_new_btn)
        self.fact_apply_btn = QPushButton(t("ene_profile.button.apply"))
        self.fact_apply_btn.clicked.connect(self._apply_fact_item)
        fact_actions.addWidget(self.fact_apply_btn)
        self.fact_delete_btn = QPushButton(t("ene_profile.button.delete"))
        self.fact_delete_btn.clicked.connect(self._delete_fact_item)
        fact_actions.addWidget(self.fact_delete_btn)
        fact_editor.addLayout(fact_actions)
        fact_layout.addLayout(fact_editor, 1)

        grid.addWidget(self.core_group, 0, 0)
        grid.addWidget(self.fact_group, 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        self.refresh_btn = QPushButton(t("ene_profile.button.refresh"))
        self.refresh_btn.clicked.connect(self._load_profile)
        footer.addWidget(self.refresh_btn)
        self.save_btn = QPushButton(t("ene_profile.button.save"))
        self.save_btn.clicked.connect(self._save_profile)
        footer.addWidget(self.save_btn)
        self.close_btn = QPushButton(t("ene_profile.button.close"))
        self.close_btn.clicked.connect(self.accept)
        footer.addWidget(self.close_btn)
        layout.addLayout(footer)

    def _core_group_label(self, group: str) -> str:
        return t(f"ene_profile.core.{group}")

    def _fact_category_label(self, category: str) -> str:
        translated = t(f"ene_profile.category.{category}")
        return translated if translated != f"ene_profile.category.{category}" else category

    def _fact_origin_label(self, origin: str) -> str:
        translated = t(f"ene_profile.origin.{origin}")
        return translated if translated != f"ene_profile.origin.{origin}" else origin

    def _format_timestamp(self, timestamp: str) -> str:
        try:
            return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(timestamp or "")[:16]

    def _set_fact_timestamp_label(self, timestamp: str = ""):
        if timestamp:
            self.fact_timestamp_label.setText(t("ene_profile.fact.timestamp.saved", timestamp=self._format_timestamp(timestamp)))
        else:
            self.fact_timestamp_label.setText(t("ene_profile.fact.timestamp.new"))

    def _load_profile(self):
        self._core_items = []
        core_profile = getattr(self.ene_profile, "core_profile", {}) or {}
        for group in self.CORE_GROUPS:
            for content in core_profile.get(group, []) or []:
                text = str(content or "").strip()
                if text:
                    self._core_items.append({"group": group, "content": text})

        self._fact_items = []
        for fact in getattr(self.ene_profile, "facts", []) or []:
            self._fact_items.append(
                {
                    "content": str(getattr(fact, "content", "") or "").strip(),
                    "category": str(getattr(fact, "category", "basic") or "basic").strip(),
                    "timestamp": str(getattr(fact, "timestamp", "") or "").strip(),
                    "source": str(getattr(fact, "source", "") or "").strip(),
                    "origin": str(getattr(fact, "origin", "auto") or "auto").strip(),
                    "auto_update": bool(getattr(fact, "auto_update", True)),
                    "confidence": getattr(fact, "confidence", None),
                }
            )

        self._refresh_core_list()
        self._refresh_fact_list()
        self._update_stats()
        self._new_core_item()
        self._new_fact_item()

    def _update_stats(self):
        self.stats_label.setText(
            t(
                "ene_profile.stats.summary",
                core_count=str(len(self._core_items)),
                fact_count=str(len(self._fact_items)),
            )
        )

    def _refresh_core_list(self):
        self.core_list.clear()
        for item in self._core_items:
            preview = item["content"]
            if len(preview) > 40:
                preview = preview[:40] + "..."
            self.core_list.addItem(f"{self._core_group_label(item['group'])}: {preview}")

    def _refresh_fact_list(self):
        self.fact_list.clear()
        for fact in self._fact_items:
            preview = fact["content"].replace("\n", " ")
            if len(preview) > 36:
                preview = preview[:36] + "..."
            self.fact_list.addItem(f"[{self._fact_category_label(fact['category'])}] {preview}")

    def _new_core_item(self):
        self._core_current_index = -1
        self.core_list.clearSelection()
        self.core_content_edit.clear()
        self.core_group_combo.setCurrentIndex(0)

    def _on_core_selected(self, row: int):
        self._core_current_index = row
        if 0 <= row < len(self._core_items):
            item = self._core_items[row]
            group_index = self.core_group_combo.findData(item["group"])
            self.core_group_combo.setCurrentIndex(group_index if group_index >= 0 else 0)
            self.core_content_edit.setPlainText(item["content"])
            return
        self._new_core_item()

    def _apply_core_item(self):
        content = self.core_content_edit.toPlainText().strip()
        group = str(self.core_group_combo.currentData() or "identity").strip()
        if not content:
            QMessageBox.warning(self, t("ene_profile.message.core_missing.title"), t("ene_profile.message.core_missing.body"))
            return

        payload = {"group": group, "content": content}
        if 0 <= self._core_current_index < len(self._core_items):
            self._core_items[self._core_current_index] = payload
            target_index = self._core_current_index
        else:
            self._core_items.append(payload)
            target_index = len(self._core_items) - 1

        self._refresh_core_list()
        self._update_stats()
        self.core_list.setCurrentRow(target_index)

    def _delete_core_item(self):
        row = self.core_list.currentRow()
        if row < 0:
            return
        del self._core_items[row]
        self._refresh_core_list()
        self._update_stats()
        self._new_core_item()

    def _new_fact_item(self):
        self._fact_current_index = -1
        self.fact_list.clearSelection()
        self.fact_content_edit.clear()
        self.fact_source_input.clear()
        self.fact_category_combo.setCurrentIndex(0)
        self.fact_origin_combo.setCurrentIndex(0)
        self.fact_auto_update_check.setChecked(True)
        self._set_fact_timestamp_label("")

    def _on_fact_selected(self, row: int):
        self._fact_current_index = row
        if 0 <= row < len(self._fact_items):
            fact = self._fact_items[row]
            self.fact_content_edit.setPlainText(fact["content"])
            category_index = self.fact_category_combo.findData(fact["category"])
            self.fact_category_combo.setCurrentIndex(category_index if category_index >= 0 else 0)
            origin_index = self.fact_origin_combo.findData(fact["origin"])
            self.fact_origin_combo.setCurrentIndex(origin_index if origin_index >= 0 else 0)
            self.fact_source_input.setText(fact["source"])
            self.fact_auto_update_check.setChecked(bool(fact["auto_update"]))
            self._set_fact_timestamp_label(fact["timestamp"])
            return
        self._new_fact_item()

    def _apply_fact_item(self):
        content = self.fact_content_edit.toPlainText().strip()
        if not content:
            QMessageBox.warning(self, t("ene_profile.message.fact_missing.title"), t("ene_profile.message.fact_missing.body"))
            return

        payload = {
            "content": content,
            "category": str(self.fact_category_combo.currentData() or "basic").strip(),
            "timestamp": datetime.now().isoformat(),
            "source": self.fact_source_input.text().strip(),
            "origin": str(self.fact_origin_combo.currentData() or "auto").strip(),
            "auto_update": self.fact_auto_update_check.isChecked(),
            "confidence": None,
        }
        if 0 <= self._fact_current_index < len(self._fact_items):
            payload["timestamp"] = self._fact_items[self._fact_current_index].get("timestamp") or payload["timestamp"]
            self._fact_items[self._fact_current_index] = payload
            target_index = self._fact_current_index
        else:
            self._fact_items.append(payload)
            target_index = len(self._fact_items) - 1

        self._refresh_fact_list()
        self._update_stats()
        self.fact_list.setCurrentRow(target_index)

    def _delete_fact_item(self):
        row = self.fact_list.currentRow()
        if row < 0:
            return
        del self._fact_items[row]
        self._refresh_fact_list()
        self._update_stats()
        self._new_fact_item()

    def _save_profile(self):
        core_profile = {group: [] for group in self.CORE_GROUPS}
        for item in self._core_items:
            core_profile.setdefault(item["group"], []).append(item["content"])
        self.ene_profile.core_profile = core_profile
        self.ene_profile.facts = [
            EneProfileFact(
                content=item["content"],
                category=item["category"],
                timestamp=item["timestamp"],
                source=item["source"],
                origin=item["origin"],
                auto_update=item["auto_update"],
                confidence=item.get("confidence"),
            )
            for item in self._fact_items
        ]
        save = getattr(self.ene_profile, "save", None)
        if callable(save):
            save()
