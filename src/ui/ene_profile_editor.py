"""
에네 자기 정보 편집 패널
"""
from __future__ import annotations

from datetime import datetime

from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
    QWidget,
)

from ..ai.ene_profile import EneProfileFact
from ..core.i18n import tr as t


class EneProfileEditorPanel(QWidget):
    """에네 자기 정보를 편집하는 재사용 패널."""

    CORE_GROUPS = ("identity", "speaking_style", "relationship_tone")
    FACT_CATEGORIES = ("basic", "preference", "goal", "habit", "speaking_style", "relationship_tone")

    def __init__(
        self,
        ene_profile,
        parent=None,
        *,
        translate=None,
        translate_format=None,
        show_close_button: bool = False,
    ):
        super().__init__(parent)
        self.ene_profile = ene_profile
        self._translate = translate or self._default_translate
        self._translate_format = translate_format or self._default_translate_format
        self._show_close_button = show_close_button
        self._core_current_index = -1
        self._fact_current_index = -1
        self._core_items: list[dict] = []
        self._fact_items: list[dict] = []
        self.close_btn: QPushButton | None = None

        self._setup_ui()
        self._retranslate_ui()
        self.refresh_profile()

    def _default_translate(self, key: str, fallback: str) -> str:
        translated = t(key)
        return fallback if translated == key else translated

    def _default_translate_format(self, key: str, fallback: str, **kwargs) -> str:
        translated = t(key, **kwargs)
        if translated == key:
            try:
                return fallback.format(**kwargs)
            except Exception:
                return fallback
        return translated

    def _tr(self, key: str, fallback: str) -> str:
        return self._translate(key, fallback)

    def _trf(self, key: str, fallback: str, **kwargs) -> str:
        return self._translate_format(key, fallback, **kwargs)

    def set_translators(self, translate=None, translate_format=None) -> None:
        if translate is not None:
            self._translate = translate
        if translate_format is not None:
            self._translate_format = translate_format
        self._retranslate_ui()

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

        self.core_group = QGroupBox()
        core_layout = QHBoxLayout(self.core_group)
        core_layout.setSpacing(10)

        self.core_list = QListWidget()
        self.core_list.currentRowChanged.connect(self._on_core_selected)
        core_layout.addWidget(self.core_list, 1)

        core_editor = QVBoxLayout()
        core_editor.setSpacing(8)
        self.core_group_combo = QComboBox()
        core_editor.addWidget(self.core_group_combo)

        self.core_content_edit = QPlainTextEdit()
        self.core_content_edit.setMinimumHeight(120)
        core_editor.addWidget(self.core_content_edit, 1)

        core_actions = QHBoxLayout()
        self.core_new_btn = QPushButton()
        self.core_new_btn.clicked.connect(self._new_core_item)
        core_actions.addWidget(self.core_new_btn)
        self.core_apply_btn = QPushButton()
        self.core_apply_btn.clicked.connect(self._apply_core_item)
        core_actions.addWidget(self.core_apply_btn)
        self.core_delete_btn = QPushButton()
        self.core_delete_btn.clicked.connect(self._delete_core_item)
        core_actions.addWidget(self.core_delete_btn)
        core_editor.addLayout(core_actions)
        core_layout.addLayout(core_editor, 1)

        self.fact_group = QGroupBox()
        fact_layout = QHBoxLayout(self.fact_group)
        fact_layout.setSpacing(10)

        self.fact_list = QListWidget()
        self.fact_list.currentRowChanged.connect(self._on_fact_selected)
        fact_layout.addWidget(self.fact_list, 1)

        fact_editor = QVBoxLayout()
        fact_editor.setSpacing(8)

        self.fact_content_edit = QPlainTextEdit()
        self.fact_content_edit.setMinimumHeight(140)
        fact_editor.addWidget(self.fact_content_edit)

        fact_meta_row = QHBoxLayout()
        self.fact_category_combo = QComboBox()
        fact_meta_row.addWidget(self.fact_category_combo)

        self.fact_origin_combo = QComboBox()
        fact_meta_row.addWidget(self.fact_origin_combo)
        fact_editor.addLayout(fact_meta_row)

        self.fact_source_input = QLineEdit()
        fact_editor.addWidget(self.fact_source_input)

        self.fact_auto_update_check = QCheckBox()
        self.fact_auto_update_check.setChecked(True)
        fact_editor.addWidget(self.fact_auto_update_check)

        self.fact_timestamp_label = QLabel()
        fact_editor.addWidget(self.fact_timestamp_label)

        fact_actions = QHBoxLayout()
        self.fact_new_btn = QPushButton()
        self.fact_new_btn.clicked.connect(self._new_fact_item)
        fact_actions.addWidget(self.fact_new_btn)
        self.fact_apply_btn = QPushButton()
        self.fact_apply_btn.clicked.connect(self._apply_fact_item)
        fact_actions.addWidget(self.fact_apply_btn)
        self.fact_delete_btn = QPushButton()
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
        self.refresh_btn = QPushButton()
        self.refresh_btn.clicked.connect(self.refresh_profile)
        footer.addWidget(self.refresh_btn)
        self.save_btn = QPushButton()
        self.save_btn.clicked.connect(self.save_profile)
        footer.addWidget(self.save_btn)
        if self._show_close_button:
            self.close_btn = QPushButton()
            footer.addWidget(self.close_btn)
        layout.addLayout(footer)

    def _retranslate_ui(self):
        self.core_group.setTitle(self._tr("ene_profile.section.core", "기본 설정"))
        self.fact_group.setTitle(self._tr("ene_profile.section.facts", "학습 정보"))
        self.core_content_edit.setPlaceholderText(
            self._tr("ene_profile.core.content.placeholder", "고정 설정으로 둘 에네 정보를 입력하세요.")
        )
        self.fact_content_edit.setPlaceholderText(
            self._tr("ene_profile.fact.content.placeholder", "대화에서 학습된 에네 정보를 입력하세요.")
        )
        self.fact_source_input.setPlaceholderText(
            self._tr("ene_profile.fact.source.placeholder", "출처를 입력하세요.")
        )
        self.fact_auto_update_check.setText(self._tr("ene_profile.fact.auto_update", "자동 갱신 허용"))
        self.core_new_btn.setText(self._tr("ene_profile.button.new", "새 항목"))
        self.core_apply_btn.setText(self._tr("ene_profile.button.apply", "적용"))
        self.core_delete_btn.setText(self._tr("ene_profile.button.delete", "삭제"))
        self.fact_new_btn.setText(self._tr("ene_profile.button.new", "새 항목"))
        self.fact_apply_btn.setText(self._tr("ene_profile.button.apply", "적용"))
        self.fact_delete_btn.setText(self._tr("ene_profile.button.delete", "삭제"))
        self.refresh_btn.setText(self._tr("ene_profile.button.refresh", "새로고침"))
        self.save_btn.setText(self._tr("ene_profile.button.save", "저장"))
        if self.close_btn is not None:
            self.close_btn.setText(self._tr("ene_profile.button.close", "닫기"))
        self._refresh_core_group_combo_labels()
        self._refresh_fact_combo_labels()
        self._refresh_core_list()
        self._refresh_fact_list()
        self._update_stats()
        if 0 <= self._fact_current_index < len(self._fact_items):
            self._set_fact_timestamp_label(self._fact_items[self._fact_current_index].get("timestamp", ""))
        else:
            self._set_fact_timestamp_label("")

    def _refresh_core_group_combo_labels(self):
        current_data = self.core_group_combo.currentData()
        self.core_group_combo.blockSignals(True)
        self.core_group_combo.clear()
        for group in self.CORE_GROUPS:
            self.core_group_combo.addItem(self._core_group_label(group), group)
        index = self.core_group_combo.findData(current_data)
        self.core_group_combo.setCurrentIndex(index if index >= 0 else 0)
        self.core_group_combo.blockSignals(False)

    def _refresh_fact_combo_labels(self):
        category_data = self.fact_category_combo.currentData()
        origin_data = self.fact_origin_combo.currentData()

        self.fact_category_combo.blockSignals(True)
        self.fact_category_combo.clear()
        for category in self.FACT_CATEGORIES:
            self.fact_category_combo.addItem(self._fact_category_label(category), category)
        category_index = self.fact_category_combo.findData(category_data)
        self.fact_category_combo.setCurrentIndex(category_index if category_index >= 0 else 0)
        self.fact_category_combo.blockSignals(False)

        self.fact_origin_combo.blockSignals(True)
        self.fact_origin_combo.clear()
        self.fact_origin_combo.addItem(self._fact_origin_label("auto"), "auto")
        self.fact_origin_combo.addItem(self._fact_origin_label("manual"), "manual")
        origin_index = self.fact_origin_combo.findData(origin_data)
        self.fact_origin_combo.setCurrentIndex(origin_index if origin_index >= 0 else 0)
        self.fact_origin_combo.blockSignals(False)

    def _core_group_label(self, group: str) -> str:
        fallback_map = {"identity": "자기 정의", "speaking_style": "말투", "relationship_tone": "관계 톤"}
        return self._tr(f"ene_profile.core.{group}", fallback_map.get(group, group))

    def _fact_category_label(self, category: str) -> str:
        fallback_map = {
            "basic": "기본",
            "preference": "취향",
            "goal": "목표",
            "habit": "습관",
            "speaking_style": "말투",
            "relationship_tone": "관계 톤",
        }
        return self._tr(f"ene_profile.category.{category}", fallback_map.get(category, category))

    def _fact_origin_label(self, origin: str) -> str:
        fallback_map = {"auto": "자동 추출", "manual": "수동 입력"}
        return self._tr(f"ene_profile.origin.{origin}", fallback_map.get(origin, origin))

    def _format_timestamp(self, timestamp: str) -> str:
        try:
            return datetime.fromisoformat(timestamp).strftime("%Y-%m-%d %H:%M")
        except Exception:
            return str(timestamp or "")[:16]

    def _set_fact_timestamp_label(self, timestamp: str = ""):
        if timestamp:
            self.fact_timestamp_label.setText(
                self._trf("ene_profile.fact.timestamp.saved", "저장 시각: {timestamp}", timestamp=self._format_timestamp(timestamp))
            )
        else:
            self.fact_timestamp_label.setText(self._tr("ene_profile.fact.timestamp.new", "저장 전 새 항목"))

    def refresh_profile(self):
        load = getattr(self.ene_profile, "load", None)
        if callable(load):
            load()
        self._load_profile()

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
            self._trf(
                "ene_profile.stats.summary",
                "기본 설정 {core_count}개 | 학습 정보 {fact_count}개",
                core_count=str(len(self._core_items)),
                fact_count=str(len(self._fact_items)),
            )
        )

    def _refresh_core_list(self):
        selected_row = self.core_list.currentRow()
        self.core_list.clear()
        for item in self._core_items:
            preview = item["content"]
            if len(preview) > 40:
                preview = preview[:40] + "..."
            self.core_list.addItem(f"{self._core_group_label(item['group'])}: {preview}")
        if 0 <= selected_row < self.core_list.count():
            self.core_list.setCurrentRow(selected_row)

    def _refresh_fact_list(self):
        selected_row = self.fact_list.currentRow()
        self.fact_list.clear()
        for fact in self._fact_items:
            preview = fact["content"].replace("\n", " ")
            if len(preview) > 36:
                preview = preview[:36] + "..."
            self.fact_list.addItem(f"[{self._fact_category_label(fact['category'])}] {preview}")
        if 0 <= selected_row < self.fact_list.count():
            self.fact_list.setCurrentRow(selected_row)

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
            QMessageBox.warning(
                self,
                self._tr("ene_profile.message.core_missing.title", "기본 설정 입력 필요"),
                self._tr("ene_profile.message.core_missing.body", "기본 설정 내용이 비어 있습니다."),
            )
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
            QMessageBox.warning(
                self,
                self._tr("ene_profile.message.fact_missing.title", "학습 정보 입력 필요"),
                self._tr("ene_profile.message.fact_missing.body", "학습 정보 내용이 비어 있습니다."),
            )
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

    def save_profile(self):
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
