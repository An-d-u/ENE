"""
설정 대화상자 사용자 프로필 편집 mixin.
"""

from __future__ import annotations

import json
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListView, QListWidget, QMessageBox


class SettingsDialogProfileMixin:
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
            QMessageBox.warning(
                self,
                self._translated_text("settings.profile.message.basic_info_missing.title", "기본 정보 저장 실패"),
                self._translated_text("settings.profile.message.basic_info_missing.body", "항목 이름을 입력하세요."),
            )
            return

        duplicate_index = next((idx for idx, item in enumerate(self._basic_info_items) if item[0] == key), -1)
        if duplicate_index != -1 and duplicate_index != self._basic_info_current_index:
            QMessageBox.warning(
                self,
                self._translated_text("settings.profile.message.basic_info_duplicate.title", "기본 정보 저장 실패"),
                self._translated_text_format(
                    "settings.profile.message.basic_info_duplicate.body",
                    "'{key}' 항목은 이미 존재합니다.",
                    key=key,
                ),
            )
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
            QMessageBox.warning(
                self,
                self._translated_text("settings.profile.message.preference_duplicate.title", "항목 추가 실패"),
                self._translated_text("settings.profile.message.preference_duplicate.body", "이미 같은 항목이 있습니다."),
            )
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
            self.fact_list.addItem(f"[{self._fact_category_label(fact['category'])}] {preview}")

    def _new_fact_item(self):
        self._fact_current_index = -1
        self.fact_list.clearSelection()
        self.fact_content_edit.clear()
        default_index = self.fact_category_combo.findData("basic")
        self.fact_category_combo.setCurrentIndex(default_index if default_index >= 0 else 0)
        self.fact_source_input.clear()
        self._set_fact_timestamp("settings.profile.facts.timestamp.new", "신규 항목")
        self.fact_content_edit.setFocus()

    def _on_fact_selected(self, row: int):
        self._fact_current_index = row
        if 0 <= row < len(self._fact_items):
            fact = self._fact_items[row]
            self.fact_content_edit.setPlainText(fact["content"])
            fact_index = self.fact_category_combo.findData(fact["category"])
            self.fact_category_combo.setCurrentIndex(fact_index if fact_index >= 0 else 0)
            self.fact_source_input.setText(fact["source"])
            self._set_fact_timestamp(
                "settings.profile.facts.timestamp.saved",
                "기록 시각: {timestamp}",
                timestamp=fact["timestamp"],
            )
            return
        self.fact_content_edit.clear()
        self.fact_source_input.clear()
        self._set_fact_timestamp("settings.profile.facts.timestamp.new", "신규 항목")

    def _apply_fact_item(self):
        content = self.fact_content_edit.toPlainText().strip()
        category = str(self.fact_category_combo.currentData() or "basic").strip() or "basic"
        source = self.fact_source_input.text().strip()
        if not content:
            QMessageBox.warning(
                self,
                self._translated_text("settings.profile.message.fact_missing.title", "facts 저장 실패"),
                self._translated_text("settings.profile.message.fact_missing.body", "기억 내용을 입력하세요."),
            )
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

            self._set_profile_status(
                "settings.profile.status.load_done",
                "user_profile.json 로드 완료",
            )
        except Exception as e:
            self._set_profile_status("settings.profile.status.load_failed", "로드 실패: {error}", error=e)
            QMessageBox.warning(
                self,
                self._translated_text("settings.profile.message.load_failed.title", "불러오기 실패"),
                self._translated_text_format(
                    "settings.profile.message.load_failed.body",
                    "user_profile.json을 불러오지 못했습니다.\n{error}",
                    error=e,
                ),
            )

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

            self._set_profile_status(
                "settings.profile.status.save_done",
                "user_profile.json 저장 완료",
            )
            QMessageBox.information(
                self,
                self._translated_text("settings.profile.message.save_done.title", "저장 완료"),
                self._translated_text("settings.profile.message.save_done.body", "사용자 기억 정보를 저장했습니다."),
            )
        except Exception as e:
            self._set_profile_status("settings.profile.status.save_failed", "저장 실패: {error}", error=e)
            QMessageBox.warning(
                self,
                self._translated_text("settings.profile.message.save_failed.title", "저장 실패"),
                self._translated_text_format(
                    "settings.profile.message.save_failed.body",
                    "user_profile.json을 저장하지 못했습니다.\n{error}",
                    error=e,
                ),
            )
