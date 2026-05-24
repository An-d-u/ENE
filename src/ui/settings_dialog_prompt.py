"""
설정 대화상자 프롬프트 편집 mixin.
"""

from __future__ import annotations

import re

from PyQt6.QtWidgets import QMessageBox

from ..ai import prompt_config


class SettingsDialogPromptMixin:
    def _prompt_text(self, key: str, fallback: str) -> str:
        translator = getattr(self, "_translated_text", None)
        if callable(translator):
            return translator(key, fallback)
        return fallback

    def _prompt_text_format(self, key: str, fallback: str, **kwargs) -> str:
        translator = getattr(self, "_translated_text_format", None)
        if callable(translator):
            return translator(key, fallback, **kwargs)
        try:
            return fallback.format(**kwargs) if kwargs else fallback
        except Exception:
            return fallback

    def _set_prompt_status_text(self, key: str, fallback: str, **kwargs) -> None:
        setter = getattr(self, "_set_prompt_status", None)
        if callable(setter):
            setter(key, fallback, **kwargs)
            return
        status_label = getattr(self, "_prompt_status_label", None)
        if status_label is not None:
            status_label.setText(SettingsDialogPromptMixin._prompt_text_format(self, key, fallback, **kwargs))

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
        return self._translated_text_format(
            "settings.prompt.token_count",
            "{title} 현재 토큰: {token_count:,}개 · 문자 수: {char_count:,}자",
            title=title,
            token_count=token_count,
            char_count=char_count,
        )

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
            QMessageBox.warning(
                self,
                self._translated_text("settings.prompt.message.emotion_missing.title", "감정 저장 실패"),
                self._translated_text("settings.prompt.message.emotion_missing.body", "감정 키를 입력하세요."),
            )
            return

        duplicate_index = next((idx for idx, item in enumerate(self._emotion_items) if item["name"] == name), -1)
        if duplicate_index != -1 and duplicate_index != self._emotion_current_index:
            QMessageBox.warning(
                self,
                self._translated_text("settings.prompt.message.emotion_duplicate.title", "감정 저장 실패"),
                self._translated_text_format(
                    "settings.prompt.message.emotion_duplicate.body",
                    "'{name}' 감정은 이미 존재합니다.",
                    name=name,
                ),
            )
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
            config = prompt_config.load_prompt_config()
            emotions = list(config.get("emotions", []))
            guides = dict(config.get("emotion_guides", {}))

            merged_items = [{"name": name, "guide": guides.get(name, "")} for name in emotions]
            known_names = {item["name"] for item in merged_items}
            for name, guide in guides.items():
                if name not in known_names:
                    merged_items.append({"name": name, "guide": guide})

            self.base_prompt_editor.setPlainText(str(config.get("base_system_prompt", "")).strip("\n"))
            self.sub_prompt_editor.setPlainText(str(config.get("sub_prompt_body", "")).strip("\n"))
            self._emotion_items = merged_items
            self._refresh_emotion_list()
            self._sync_emotion_combo_options()
            self._new_emotion_item()

            SettingsDialogPromptMixin._set_prompt_status_text(
                self,
                "settings.prompt.status.load_done",
                "프롬프트 Markdown 로드 완료",
            )
        except Exception as e:
            SettingsDialogPromptMixin._set_prompt_status_text(
                self,
                "settings.prompt.status.load_failed",
                "로드 실패: {error}",
                error=e,
            )
            QMessageBox.warning(
                self,
                SettingsDialogPromptMixin._prompt_text(
                    self,
                    "settings.prompt.message.load_failed.title",
                    "불러오기 실패",
                ),
                SettingsDialogPromptMixin._prompt_text_format(
                    self,
                    "settings.prompt.message.load_failed.body",
                    "프롬프트 설정을 불러오지 못했습니다.\n{error}",
                    error=e,
                ),
            )

    def _save_prompt_configuration(self):
        try:
            emotion_names = [item["name"] for item in self._emotion_items if item["name"].strip()]
            if not emotion_names:
                raise ValueError("감정은 하나 이상 있어야 합니다.")

            prompt_config.save_prompt_config(
                {
                    "base_system_prompt": self.base_prompt_editor.toPlainText(),
                    "sub_prompt_body": self.sub_prompt_editor.toPlainText(),
                    "emotions": emotion_names,
                    "emotion_guides": {
                        item["name"]: item["guide"]
                        for item in self._emotion_items
                        if item["name"].strip()
                    },
                }
            )
            self._sync_emotion_combo_options()

            SettingsDialogPromptMixin._set_prompt_status_text(
                self,
                "settings.prompt.status.save_done",
                "프롬프트 Markdown 저장 완료",
            )
            QMessageBox.information(
                self,
                SettingsDialogPromptMixin._prompt_text(
                    self,
                    "settings.prompt.message.save_done.title",
                    "저장 완료",
                ),
                SettingsDialogPromptMixin._prompt_text(
                    self,
                    "settings.prompt.message.save_done.body",
                    "프롬프트 설정을 저장했습니다.",
                ),
            )
        except Exception as e:
            SettingsDialogPromptMixin._set_prompt_status_text(
                self,
                "settings.prompt.status.save_failed",
                "저장 실패: {error}",
                error=e,
            )
            QMessageBox.warning(
                self,
                SettingsDialogPromptMixin._prompt_text(
                    self,
                    "settings.prompt.message.save_failed.title",
                    "저장 실패",
                ),
                SettingsDialogPromptMixin._prompt_text_format(
                    self,
                    "settings.prompt.message.save_failed.body",
                    "프롬프트 설정을 저장하지 못했습니다.\n{error}",
                    error=e,
                ),
            )
