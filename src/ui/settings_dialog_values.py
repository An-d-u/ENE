"""
설정 대화상자 값 로드/저장 mixin.
"""

from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QFileDialog, QListWidgetItem, QMessageBox

from ..ai.llm_provider import LLMFormat
from ..ai.openai_model_policy import normalize_reasoning_effort, resolve_openai_model_policy
from ..core.app_paths import relativize_for_storage
from ..core.hotkey_utils import normalize_hotkey_text
from ..core.image_avatar import build_image_avatar_payload
from ..core.system_theme import THEME_PRESETS, get_windows_theme_mode


class SettingsDialogValuesMixin:
    def _normalize_path_for_storage(self, path_text: str) -> str:
        return relativize_for_storage(
            path_text,
            user_root=self._user_data_root,
            bundle_root=self._bundle_root,
        )

    def _browse_live2d_model_path(self):
        start_dir = self._bundle_root / "assets" / "live2d_models"
        if not start_dir.exists():
            start_dir = self._user_data_root / "assets" / "live2d_models"
        selected, _ = QFileDialog.getOpenFileName(
            self,
            self._translated_text("settings.model.path.dialog.title", "Live2D 모델 파일 선택"),
            str(start_dir),
            self._translated_text(
                "settings.model.path.dialog.filter",
                "Live2D 모델 (*.model3.json);;JSON 파일 (*.json);;모든 파일 (*.*)",
            ),
        )
        if not selected:
            return
        self.model_json_path_edit.setText(self._normalize_path_for_storage(selected))

    def _browse_image_avatar_folder(self):
        raw_folder = self.image_avatar_folder_edit.text().strip()
        start_dir = Path(raw_folder).expanduser() if raw_folder else None
        if start_dir is None or not start_dir.exists() or not start_dir.is_dir():
            start_dir = self._user_data_root / "avatar_images"
        if not start_dir.exists():
            start_dir = self._bundle_root / "avatar_images"

        selected = QFileDialog.getExistingDirectory(
            self,
            self._translated_text("settings.model.image.path.dialog.title", "이미지 아바타 폴더 선택"),
            str(start_dir),
        )
        if not selected:
            return
        self.image_avatar_folder_edit.setText(self._normalize_path_for_storage(selected))
        self._refresh_image_avatar_emotion_list()
        self._on_setting_changed()

    def _on_avatar_mode_changed(self, *_):
        self._sync_avatar_mode_visibility()
        self._on_setting_changed()

    def _on_image_avatar_folder_editing_finished(self):
        self._refresh_image_avatar_emotion_list()
        self._on_setting_changed()

    def _sync_avatar_mode_visibility(self):
        if not hasattr(self, "avatar_mode_combo"):
            return
        avatar_mode = str(self.avatar_mode_combo.currentData() or "live2d")
        is_image_mode = avatar_mode == "image"
        if hasattr(self, "live2d_model_group"):
            self.live2d_model_group.setVisible(not is_image_mode)
        if hasattr(self, "image_avatar_group"):
            self.image_avatar_group.setVisible(is_image_mode)

    def _selected_image_avatar_emotion(self) -> str:
        if not hasattr(self, "image_avatar_emotion_list"):
            return "normal"
        item = self.image_avatar_emotion_list.currentItem()
        if item is None:
            return str(getattr(self, "_image_avatar_preview_emotion", "normal") or "normal")
        return str(item.data(Qt.ItemDataRole.UserRole + 1) or item.text() or "normal")

    def _read_selected_image_avatar_placement(self) -> dict:
        return {
            "scale": round(float(self.image_avatar_scale_spin.value()), 2),
            "x_percent": int(self.image_avatar_x_slider.value()),
            "y_percent": int(self.image_avatar_y_slider.value()),
        }

    def _write_selected_image_avatar_placement(self, item: QListWidgetItem | None = None):
        if not hasattr(self, "image_avatar_emotion_list"):
            return
        target_item = item or self.image_avatar_emotion_list.currentItem()
        if target_item is None:
            return
        storage_key = str(target_item.data(Qt.ItemDataRole.UserRole) or "").strip()
        if not storage_key:
            return
        self._image_avatar_placements[storage_key] = self._read_selected_image_avatar_placement()

    def _normalized_image_avatar_placement(self, storage_key: str) -> dict:
        raw = self._image_avatar_placements.get(storage_key, {})
        if not isinstance(raw, dict):
            raw = {}

        def clamp_number(value, default, minimum, maximum):
            try:
                number = float(value)
            except (TypeError, ValueError):
                number = default
            if not math.isfinite(number):
                number = default
            return min(max(number, minimum), maximum)

        return {
            "scale": clamp_number(raw.get("scale"), 1.0, 0.1, 2.0),
            "x_percent": int(clamp_number(raw.get("x_percent"), 50, -100, 200)),
            "y_percent": int(clamp_number(raw.get("y_percent"), 50, -100, 200)),
        }

    def _load_image_avatar_placement_controls(self, item: QListWidgetItem | None):
        storage_key = str(item.data(Qt.ItemDataRole.UserRole) or "").strip() if item is not None else ""
        placement = self._normalized_image_avatar_placement(storage_key)
        was_loading = self._loading
        self._loading = True
        try:
            self.image_avatar_scale_spin.setValue(float(placement["scale"]))
            self.image_avatar_x_slider.setValue(int(placement["x_percent"]))
            self.image_avatar_y_slider.setValue(int(placement["y_percent"]))
        finally:
            self._loading = was_loading

    def _refresh_image_avatar_emotion_list(self):
        if not hasattr(self, "image_avatar_emotion_list"):
            return
        self._write_selected_image_avatar_placement()
        selected_emotion = self._selected_image_avatar_emotion()
        if not selected_emotion:
            selected_emotion = str(getattr(self, "_image_avatar_preview_emotion", "normal") or "normal")

        payload = build_image_avatar_payload(
            {
                "image_avatar_folder": self.image_avatar_folder_edit.text().strip(),
                "image_avatar_placements": self._image_avatar_placements,
            },
            base_path=self._bundle_root,
        )
        images = payload.get("images", {})
        emotions = payload.get("availableEmotions", ["normal"])

        self.image_avatar_emotion_list.blockSignals(True)
        try:
            self.image_avatar_emotion_list.clear()
            target_row = 0
            for row, emotion in enumerate(emotions):
                item = QListWidgetItem(str(emotion))
                image_info = images.get(emotion, {}) if isinstance(images, dict) else {}
                item.setData(Qt.ItemDataRole.UserRole, str(image_info.get("storageKey", "")))
                item.setData(Qt.ItemDataRole.UserRole + 1, str(emotion))
                self.image_avatar_emotion_list.addItem(item)
                if str(emotion) == selected_emotion:
                    target_row = row
            if self.image_avatar_emotion_list.count():
                self.image_avatar_emotion_list.setCurrentRow(target_row)
        finally:
            self.image_avatar_emotion_list.blockSignals(False)

        self._load_image_avatar_placement_controls(self.image_avatar_emotion_list.currentItem())

    def _on_image_avatar_emotion_selected(self, current, previous):
        if previous is not None:
            self._write_selected_image_avatar_placement(previous)
        self._load_image_avatar_placement_controls(current)
        self._on_setting_changed()

    def _on_ui_language_changed(self, *_):
        if self._loading:
            return
        selected_language = str(self.ui_language_combo.currentData() or "auto")
        self._set_dialog_preview_language(selected_language)
        self._retranslate_ui()
        self._on_setting_changed()

    def _sync_llm_custom_api_visibility(self, provider: str | None = None):
        normalized = str(provider or self.llm_provider_combo.currentData() or "gemini").strip().lower()
        is_custom_api = normalized == "custom_api"
        if hasattr(self, "custom_api_group"):
            self.custom_api_group.setVisible(is_custom_api)
        for attr_name in (
            "llm_api_key_label",
            "llm_api_key_row",
            "llm_api_key_hint",
            "llm_model_label",
            "llm_model_edit",
        ):
            widget = getattr(self, attr_name, None)
            if widget is not None:
                widget.setVisible(not is_custom_api)

    def _on_llm_provider_changed(self, *_):
        if self._loading:
            return
        provider = str(self.llm_provider_combo.currentData() or "gemini")

        self._loading = True
        try:
            self.llm_api_key_edit.setText(str(self._llm_api_keys.get(provider, "")))
            model_text = str(self._llm_models.get(provider, ""))
            self.llm_model_edit.setText(model_text)
            self._active_model_key_by_provider[provider] = self._model_param_key(model_text)
            self._apply_model_params_to_widgets(provider, model_text)
            self._sync_llm_custom_api_visibility(provider)
        finally:
            self._loading = False

        self._on_setting_changed()

    def _on_llm_api_key_changed(self, text: str):
        provider = str(self.llm_provider_combo.currentData() or "gemini")
        self._llm_api_keys[provider] = text
        self._on_setting_changed()

    def _on_llm_model_changed(self, text: str):
        if self._loading:
            return
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

    def _embedding_default_model(self, provider: str) -> str:
        return {
            "voyage": "voyage-3",
            "openai": "text-embedding-3-small",
            "openai_compatible": "text-embedding-3-small",
            "gemini": "gemini-embedding-2",
        }.get(str(provider or "voyage").strip().lower(), "voyage-3")

    def _embedding_default_api_url(self, provider: str) -> str:
        return {
            "openai": "https://api.openai.com/v1",
            "openai_compatible": "http://127.0.0.1:8000/v1",
        }.get(str(provider or "").strip().lower(), "")

    def _current_embedding_provider(self) -> str:
        return str(self.embedding_provider_combo.currentData() or "voyage").strip().lower()

    def _set_embedding_model_text(self, model: str):
        normalized = str(model or "").strip() or self._embedding_default_model(self._current_embedding_provider())
        model_index = self.embedding_model_combo.findData(normalized)
        if model_index < 0:
            self.embedding_model_combo.addItem(normalized, normalized)
            model_index = self.embedding_model_combo.findData(normalized)
        self.embedding_model_combo.setCurrentIndex(model_index)
        if self.embedding_model_combo.currentText() != normalized:
            self.embedding_model_combo.setEditText(normalized)

    def _load_embedding_provider_controls(self, provider: str):
        config = self._embedding_provider_configs.setdefault(provider, {})
        if not isinstance(config, dict):
            config = {}
            self._embedding_provider_configs[provider] = config
        self.embedding_api_key_edit.setText(str(self._embedding_api_keys.get(provider, "")))
        self.embedding_api_url_edit.setText(str(config.get("api_url", self._embedding_default_api_url(provider))))
        self._set_embedding_model_text(
            self._embedding_models_by_provider.get(provider, self._embedding_default_model(provider))
        )
        self._sync_embedding_api_url_visibility(provider)

    def _sync_embedding_api_url_visibility(self, provider: str | None = None):
        normalized = str(provider or self._current_embedding_provider()).strip().lower()
        is_visible = normalized == "openai_compatible"
        if hasattr(self, "embedding_api_url_label"):
            self.embedding_api_url_label.setVisible(is_visible)
        if hasattr(self, "embedding_api_url_edit"):
            self.embedding_api_url_edit.setVisible(is_visible)

    def _store_current_embedding_provider_controls(self):
        if not hasattr(self, "embedding_provider_combo"):
            return
        provider = self._current_embedding_provider()
        self._embedding_api_keys[provider] = self.embedding_api_key_edit.text().strip()
        self._embedding_models_by_provider[provider] = self.embedding_model_combo.currentText().strip()
        config = self._embedding_provider_configs.setdefault(provider, {})
        if not isinstance(config, dict):
            config = {}
            self._embedding_provider_configs[provider] = config
        config["api_url"] = self.embedding_api_url_edit.text().strip()

    def _on_embedding_provider_changed(self, *_):
        if self._loading:
            return
        provider = self._current_embedding_provider()
        self._loading = True
        try:
            self._load_embedding_provider_controls(provider)
        finally:
            self._loading = False
        self._on_setting_changed()

    def _on_embedding_api_key_changed(self, text: str):
        if self._loading:
            return
        self._embedding_api_keys[self._current_embedding_provider()] = text.strip()
        self._on_setting_changed()

    def _on_embedding_api_url_changed(self, text: str):
        if self._loading:
            return
        provider = self._current_embedding_provider()
        config = self._embedding_provider_configs.setdefault(provider, {})
        if isinstance(config, dict):
            config["api_url"] = text.strip()
        self._on_setting_changed()

    def _current_web_search_provider(self) -> str:
        if not hasattr(self, "web_search_provider_combo"):
            return "tavily"
        return str(self.web_search_provider_combo.currentData() or "tavily").strip().lower()

    def _load_web_search_provider_controls(self, provider: str):
        if not hasattr(self, "web_search_api_key_edit"):
            return
        self.web_search_api_key_edit.setText(str(self._web_search_api_keys.get(provider, "")))

    def _on_web_search_provider_changed(self, *_):
        if self._loading:
            return
        provider = self._current_web_search_provider()
        self._loading = True
        try:
            self._load_web_search_provider_controls(provider)
        finally:
            self._loading = False
        self._on_setting_changed()

    def _on_web_search_api_key_changed(self, text: str):
        if self._loading:
            return
        self._web_search_api_keys[self._current_web_search_provider()] = text.strip()
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
        if "reasoning_effort" in params:
            normalized["reasoning_effort"] = normalize_reasoning_effort(params.get("reasoning_effort"))
        return normalized

    def _normalize_model_params_for_policy(self, provider: str, model_name: str, params) -> dict:
        normalized = self._normalize_model_params(params)
        policy = resolve_openai_model_policy(provider, model_name)
        if policy.supports_reasoning_effort:
            normalized["reasoning_effort"] = normalize_reasoning_effort(
                normalized.get("reasoning_effort"),
                policy.default_reasoning_effort,
            )
        else:
            normalized.pop("reasoning_effort", None)
        return normalized

    def _get_model_params(self, provider: str, model_name: str) -> dict:
        store = self._llm_model_params.setdefault(provider, {})
        model_key = self._model_param_key(model_name)
        params = store.get(model_key)
        if not isinstance(params, dict):
            params = store.get("__default__")
        if not isinstance(params, dict):
            params = self._default_model_params()
        normalized = self._normalize_model_params_for_policy(provider, model_name, params)
        store[model_key] = dict(normalized)
        if "__default__" not in store:
            store["__default__"] = self._normalize_model_params_for_policy(
                provider,
                "__default__",
                normalized,
            )
        return normalized

    def _set_current_model_params(self):
        provider = str(self.llm_provider_combo.currentData() or "gemini")
        if provider == "custom_api":
            model_text = self.custom_api_request_model_edit.text().strip()
        else:
            model_text = self.llm_model_edit.text().strip()
        model_key = self._model_param_key(model_text)
        self._active_model_key_by_provider[provider] = model_key
        provider_store = self._llm_model_params.setdefault(provider, {})
        params = {
            "temperature": self.llm_temperature_spin.value(),
            "top_p": self.llm_top_p_spin.value(),
            "max_tokens": self.llm_max_tokens_spin.value(),
        }
        policy = resolve_openai_model_policy(provider, model_text)
        if policy.supports_reasoning_effort:
            params["reasoning_effort"] = normalize_reasoning_effort(
                self.llm_reasoning_effort_combo.currentData(),
                policy.default_reasoning_effort,
            )
        provider_store[model_key] = self._normalize_model_params(params)
        if "__default__" not in provider_store:
            provider_store["__default__"] = self._normalize_model_params_for_policy(
                provider,
                "__default__",
                provider_store[model_key],
            )

    def _refresh_llm_model_policy_controls(self, provider: str, model_name: str):
        policy = resolve_openai_model_policy(provider, model_name)
        self.llm_temperature_spin.setEnabled(policy.supports_temperature)
        self.llm_temperature_label.setEnabled(policy.supports_temperature)
        self.llm_top_p_spin.setEnabled(policy.supports_top_p)
        self.llm_top_p_label.setEnabled(policy.supports_top_p)

        shows_reasoning_effort = policy.supports_reasoning_effort
        self.llm_reasoning_effort_label.setVisible(shows_reasoning_effort)
        self.llm_reasoning_effort_combo.setVisible(shows_reasoning_effort)
        self.llm_gpt_5_6_hint.setVisible(shows_reasoning_effort)
        self.llm_model_params_hint.setVisible(not shows_reasoning_effort)

    def _apply_model_params_to_widgets(self, provider: str, model_name: str):
        params = self._get_model_params(provider, model_name)
        reasoning_effort = normalize_reasoning_effort(params.get("reasoning_effort"))
        reasoning_index = self.llm_reasoning_effort_combo.findData(reasoning_effort)
        if reasoning_index < 0:
            reasoning_index = self.llm_reasoning_effort_combo.findData("low")

        was_loading = self._loading
        self._loading = True
        try:
            self.llm_temperature_spin.setValue(float(params["temperature"]))
            self.llm_top_p_spin.setValue(float(params["top_p"]))
            self.llm_max_tokens_spin.setValue(int(params["max_tokens"]))
            self.llm_reasoning_effort_combo.setCurrentIndex(reasoning_index if reasoning_index >= 0 else 0)
            self._refresh_llm_model_policy_controls(provider, model_name)
        finally:
            self._loading = was_loading

    def _on_setting_changed(self):
        if self._loading:
            return
        self._preview_settings()

    def _refresh_typing_effect_controls(self, enabled: bool | None = None):
        is_enabled = bool(self.typing_effect_check.isChecked()) if enabled is None else bool(enabled)
        if hasattr(self, "typing_effect_speed_label") and self.typing_effect_speed_label:
            self.typing_effect_speed_label.setEnabled(is_enabled)
        if hasattr(self, "typing_effect_speed_combo") and self.typing_effect_speed_combo:
            self.typing_effect_speed_combo.setEnabled(is_enabled)

    def _on_typing_effect_toggle(self, checked: bool):
        self._refresh_typing_effect_controls(bool(checked))
        self._on_setting_changed()

    def _refresh_ene_thought_context_controls(self):
        thoughts_enabled = bool(self.enable_ene_thoughts_check.isChecked())
        context_enabled = bool(
            self.include_ene_thoughts_in_context_check
            and self.include_ene_thoughts_in_context_check.isChecked()
        )
        if self.include_ene_thoughts_in_context_check is not None:
            self.include_ene_thoughts_in_context_check.setEnabled(thoughts_enabled)
        if self.ene_thought_context_limit_spin is not None:
            self.ene_thought_context_limit_spin.setEnabled(thoughts_enabled and context_enabled)

    def _on_ene_thoughts_toggle(self, checked: bool):
        self._refresh_ene_thought_context_controls()
        self._on_setting_changed()

    def _on_ene_thought_context_toggle(self, checked: bool):
        self._refresh_ene_thought_context_controls()
        self._on_setting_changed()

    def _refresh_mood_button_controls(self):
        mood_enabled = bool(
            self.enable_mood_system_check
            and self.enable_mood_system_check.isChecked()
        )
        if self.show_mood_toggle_button_check is not None:
            self.show_mood_toggle_button_check.setEnabled(mood_enabled)
        if self.mood_personality_profile_combo is not None:
            self.mood_personality_profile_combo.setEnabled(mood_enabled)

    def _on_mood_system_toggle(self, checked: bool):
        self._refresh_mood_button_controls()
        self._on_setting_changed()

    def _on_response_analysis_toggle(self, checked: bool):
        self._refresh_mood_button_controls()
        self._on_setting_changed()

    def _on_note_context_toggle(self, checked: bool):
        self.note_recent_context_turns_spin.setEnabled(bool(checked))
        self._on_setting_changed()

    def _refresh_away_input_grace_limit(self):
        if not hasattr(self, "away_input_grace_minutes_spin"):
            return
        idle_minutes = max(1, int(self.away_idle_minutes_spin.value()))
        self.away_input_grace_minutes_spin.setMaximum(idle_minutes)
        if self.away_input_grace_minutes_spin.value() > idle_minutes:
            self.away_input_grace_minutes_spin.setValue(idle_minutes)

    def _on_away_idle_minutes_changed(self, *_):
        self._refresh_away_input_grace_limit()
        self._on_setting_changed()

    def _refresh_life_record_controls(self) -> None:
        enabled = bool(self.enable_life_records_check.isChecked())
        self._life_record_min_inactive_label.setEnabled(enabled)
        self.life_record_min_inactive_minutes_spin.setEnabled(enabled)

    def _on_life_records_toggle(self, *_):
        self._refresh_life_record_controls()
        self._on_setting_changed()

    def _load_values(self):
        self._loading = True
        try:
            ui_language = str(self._original_settings.get("ui_language", "auto")).strip().lower() or "auto"
            if ui_language not in {"auto", "ko", "en", "ja"}:
                ui_language = "auto"
            if hasattr(self, "ui_language_combo"):
                language_index = self.ui_language_combo.findData(ui_language)
                self.ui_language_combo.setCurrentIndex(language_index if language_index >= 0 else 0)
            if self.assistant_display_name_edit is not None:
                self.assistant_display_name_edit.setText(
                    str(self._original_settings.get("assistant_display_name", "") or "").strip()
                )
            if self.user_address_name_edit is not None:
                self.user_address_name_edit.setText(
                    str(self._original_settings.get("user_address_name", "") or "").strip()
                )
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
            self.typing_effect_check.setChecked(
                self._original_settings.get("typing_effect_enabled", True)
            )
            self.message_split_check.setChecked(
                self._original_settings.get("message_split_enabled", False)
            )
            self.enable_ene_thoughts_check.setChecked(
                self._original_settings.get("enable_ene_thoughts", True)
            )
            self.enable_ene_goals_check.setChecked(
                self._original_settings.get("enable_ene_goals", True)
            )
            self.include_ene_thoughts_in_context_check.setChecked(
                self._original_settings.get("include_ene_thoughts_in_context", False)
            )
            self.enable_proactive_conversation_check.setChecked(
                self._original_settings.get("enable_proactive_conversation", True)
            )
            self.enable_response_analysis_check.setChecked(
                self._original_settings.get("enable_response_analysis", True)
            )
            self.enable_mood_system_check.setChecked(
                self._original_settings.get("enable_mood_system", True)
            )
            mood_profile_aliases = {
                "calm": "calm",
                "affectionate": "balanced",
                "balanced": "balanced",
                "playful": "expressive",
                "expressive": "expressive",
            }
            saved_mood_profile = self._original_settings.get(
                "mood_personality_profile"
            )
            mood_profile = (
                mood_profile_aliases.get(saved_mood_profile, "balanced")
                if isinstance(saved_mood_profile, str)
                else "balanced"
            )
            mood_profile_index = self.mood_personality_profile_combo.findData(
                mood_profile
            )
            self.mood_personality_profile_combo.setCurrentIndex(
                mood_profile_index if mood_profile_index >= 0 else 1
            )
            self.enable_schedule_recognition_check.setChecked(
                self._original_settings.get("enable_schedule_recognition", True)
            )
            self.enable_conversation_promises_check.setChecked(
                self._original_settings.get("enable_conversation_promises", True)
            )
            self.enable_synthetic_gestures_check.setChecked(
                self._original_settings.get("enable_synthetic_gestures", True)
            )
            self.synthetic_gesture_scale_spin.setValue(
                float(self._original_settings.get("synthetic_gesture_scale", 1.0))
            )
            self.enable_idle_synthetic_gestures_check.setChecked(
                self._original_settings.get("enable_idle_synthetic_gestures", False)
            )
            idle_frequency = str(
                self._original_settings.get("idle_synthetic_gesture_frequency", "normal")
            ).strip().lower()
            if idle_frequency not in {"low", "normal", "high"}:
                idle_frequency = "normal"
            idle_frequency_index = self.idle_synthetic_gesture_frequency_combo.findData(idle_frequency)
            self.idle_synthetic_gesture_frequency_combo.setCurrentIndex(
                idle_frequency_index if idle_frequency_index >= 0 else 1
            )
            try:
                thought_context_limit = int(self._original_settings.get("ene_thought_context_limit", 2) or 0)
            except Exception:
                thought_context_limit = 2
            self.ene_thought_context_limit_spin.setValue(max(0, min(thought_context_limit, 20)))
            typing_effect_speed = str(self._original_settings.get("typing_effect_speed", "normal")).strip().lower()
            if typing_effect_speed not in {"fast", "normal", "slow"}:
                typing_effect_speed = "normal"
            typing_speed_index = self.typing_effect_speed_combo.findData(typing_effect_speed)
            self.typing_effect_speed_combo.setCurrentIndex(typing_speed_index if typing_speed_index >= 0 else 1)
            self._refresh_typing_effect_controls(bool(self.typing_effect_check.isChecked()))
            self._refresh_ene_thought_context_controls()
            self.show_manual_summary_button_check.setChecked(
                self._original_settings.get("show_manual_summary_button", True)
            )
            self.show_obsidian_note_button_check.setChecked(
                self._original_settings.get("show_obsidian_note_button", True)
            )
            self.show_mood_toggle_button_check.setChecked(
                self._original_settings.get("show_mood_toggle_button", True)
            )
            self._refresh_mood_button_controls()
            self.show_ene_goal_button_check.setChecked(
                self._original_settings.get("show_ene_goal_button", True)
            )
            self._refresh_ene_goal_controls()
            self.enable_global_ptt_check.setChecked(
                self._original_settings.get("enable_global_ptt", True)
            )
            self.interrupt_tts_on_ptt_check.setChecked(
                self._original_settings.get("interrupt_tts_on_ptt", True)
            )
            ptt_language = str(self._original_settings.get("stt_language", "ko")).strip().lower() or "ko"
            ptt_language_index = self.ptt_language_combo.findData(ptt_language)
            if ptt_language_index < 0:
                ptt_language_index = self.ptt_language_combo.findData("ko")
            self.ptt_language_combo.setCurrentIndex(ptt_language_index if ptt_language_index >= 0 else 0)
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
            if self.obsidian_checked_max_chars_per_file_spin is not None:
                try:
                    checked_max_chars = int(self._original_settings.get("obsidian_checked_max_chars_per_file", 3000) or 3000)
                except Exception:
                    checked_max_chars = 3000
                self.obsidian_checked_max_chars_per_file_spin.setValue(max(100, min(checked_max_chars, 200000)))
            if self.obsidian_checked_total_max_chars_spin is not None:
                try:
                    checked_total_chars = int(self._original_settings.get("obsidian_checked_total_max_chars", 12000) or 12000)
                except Exception:
                    checked_total_chars = 12000
                self.obsidian_checked_total_max_chars_spin.setValue(max(100, min(checked_total_chars, 1000000)))
            self.mouse_tracking_check.setChecked(self._original_settings.get("mouse_tracking_enabled", True))

            self.idle_motion_check.setChecked(self._original_settings.get("enable_idle_motion", True))
            self.builtin_idle_motion_check.setChecked(
                self._original_settings.get("enable_builtin_idle_motion", True)
            )
            self.auto_eye_blink_check.setChecked(
                self._original_settings.get("enable_auto_eye_blink", True)
            )
            self.idle_motion_strength_spin.setValue(float(self._original_settings.get("idle_motion_strength", 1.0)))
            self.idle_motion_speed_spin.setValue(float(self._original_settings.get("idle_motion_speed", 1.0)))
            self.expressive_motion_check.setChecked(self._original_settings.get("enable_expressive_motion", False))
            self.expressive_pose_transitions_check.setChecked(
                self._original_settings.get("enable_expressive_pose_transitions", False)
            )
            self.expressive_motion_strength_spin.setValue(float(self._original_settings.get("expressive_motion_strength", 1.0)))
            self.expressive_motion_speed_spin.setValue(float(self._original_settings.get("expressive_motion_speed", 1.0)))
            self.expressive_motion_speech_boost_spin.setValue(
                float(self._original_settings.get("expressive_motion_speech_boost", 1.0))
            )

            self.head_pat_check.setChecked(self._original_settings.get("enable_head_pat", True))
            self.head_pat_strength_spin.setValue(float(self._original_settings.get("head_pat_strength", 1.0)))
            self.head_pat_fade_in_spin.setValue(int(self._original_settings.get("head_pat_fade_in_ms", 180)))
            self.head_pat_fade_out_spin.setValue(int(self._original_settings.get("head_pat_fade_out_ms", 220)))

            active_default_emotion = str(
                self._original_settings.get("head_pat_active_emotion_default", "normal")
            ).strip() or "normal"
            if active_default_emotion not in self._emotion_options:
                active_default_emotion = "normal"
            self.head_pat_active_emotion_combo.setCurrentText(active_default_emotion)
            self.head_pat_active_emotion_custom_edit.setText(
                str(self._original_settings.get("head_pat_active_emotion_custom", ""))
            )

            default_emotion = str(self._original_settings.get("head_pat_end_emotion_default", "normal")).strip() or "normal"
            if default_emotion not in self._emotion_options:
                default_emotion = "normal"
            self.head_pat_end_emotion_combo.setCurrentText(default_emotion)
            self.head_pat_end_emotion_custom_edit.setText(
                str(self._original_settings.get("head_pat_end_emotion_custom", ""))
            )
            self.head_pat_end_emotion_duration_spin.setValue(
                int(self._original_settings.get("head_pat_end_emotion_duration_sec", 5))
            )
            self.enable_away_nudge_check.setChecked(self._original_settings.get("enable_away_nudge", True))
            away_idle_minutes = int(self._original_settings.get("away_idle_minutes", 60))
            self.away_idle_minutes_spin.setValue(away_idle_minutes)
            self._refresh_away_input_grace_limit()
            away_input_grace_minutes = int(self._original_settings.get("away_input_grace_minutes", 5))
            self.away_input_grace_minutes_spin.setValue(max(1, min(away_input_grace_minutes, away_idle_minutes)))
            self.away_retry_limit_spin.setValue(int(self._original_settings.get("away_additional_retry_limit", 0)))
            self.enable_life_records_check.setChecked(
                bool(self._original_settings.get("enable_life_records", False))
            )
            try:
                life_record_min_inactive_minutes = int(
                    self._original_settings.get("life_record_min_inactive_minutes", 60)
                )
            except (TypeError, ValueError):
                life_record_min_inactive_minutes = 60
            self.life_record_min_inactive_minutes_spin.setValue(
                max(1, life_record_min_inactive_minutes)
            )
            self._refresh_life_record_controls()

            self.model_scale_spin.setValue(self._original_settings.get("model_scale", 1.0))
            self.model_x_slider.setValue(int(self._original_settings.get("model_x_percent", 50)))
            self.model_y_slider.setValue(int(self._original_settings.get("model_y_percent", 50)))
            self.model_json_path_edit.setText(
                self._normalize_path_for_storage(
                    str(self._original_settings.get("model_json_path", "assets/live2d_models/hiyori/runtime/hiyori_pro_t11.model3.json"))
                )
            )
            avatar_mode = str(self._original_settings.get("avatar_mode", "live2d") or "live2d").strip().lower()
            if avatar_mode not in {"live2d", "image"}:
                avatar_mode = "live2d"
            avatar_mode_index = self.avatar_mode_combo.findData(avatar_mode)
            self.avatar_mode_combo.setCurrentIndex(avatar_mode_index if avatar_mode_index >= 0 else 0)
            self.image_avatar_folder_edit.setText(
                self._normalize_path_for_storage(
                    str(self._original_settings.get("image_avatar_folder", ""))
                )
            )
            raw_image_avatar_placements = self._original_settings.get("image_avatar_placements", {})
            self._image_avatar_placements = (
                dict(raw_image_avatar_placements)
                if isinstance(raw_image_avatar_placements, dict)
                else {}
            )
            self._image_avatar_preview_emotion = (
                str(self._original_settings.get("image_avatar_preview_emotion", "normal") or "normal").strip()
                or "normal"
            )
            self._refresh_image_avatar_emotion_list()
            self._sync_avatar_mode_visibility()

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
                            mapped[str(model_name)] = self._normalize_model_params_for_policy(
                                str(provider_name),
                                str(model_name),
                                params,
                            )
                        self._llm_model_params[str(provider_name)] = mapped
            for provider_name in self._provider_values:
                provider_store = self._llm_model_params.setdefault(provider_name, {})
                active_key = self._active_model_key_by_provider.get(provider_name, "__default__")
                if active_key not in provider_store:
                    provider_store[active_key] = self._default_model_params()
                if "__default__" not in provider_store:
                    provider_store["__default__"] = self._normalize_model_params_for_policy(
                        provider_name,
                        "__default__",
                        provider_store[active_key],
                    )

            if llm_provider in self._provider_values:
                idx = self.llm_provider_combo.findData(llm_provider)
                if idx >= 0:
                    self.llm_provider_combo.setCurrentIndex(idx)

            custom_api_secret = str(self._original_settings.get("custom_api_key_or_password", "")).strip()
            if not custom_api_secret:
                custom_api_secret = str(self._llm_api_keys.get("custom_api", "")).strip()
            self._llm_api_keys["custom_api"] = ""
            custom_api_model = str(self._original_settings.get("custom_api_request_model", "")).strip()
            if not custom_api_model:
                custom_api_model = str(self._llm_models.get("custom_api", "")).strip()
            if custom_api_model:
                self._llm_models["custom_api"] = custom_api_model

            selected_provider = str(self.llm_provider_combo.currentData() or "gemini")
            self.llm_model_edit.setText(str(self._llm_models.get(selected_provider, "")))
            self._apply_model_params_to_widgets(selected_provider, self.llm_model_edit.text())

            self.custom_api_url_edit.setText(str(self._original_settings.get("custom_api_url", "")))
            self.custom_api_key_or_password_edit.setText(custom_api_secret)
            self.custom_api_request_model_edit.setText(custom_api_model)
            custom_api_format = str(self._original_settings.get("custom_api_format", LLMFormat.OPENAI_COMPATIBLE.value))
            format_index = self.custom_api_format_combo.findData(custom_api_format)
            if format_index >= 0:
                self.custom_api_format_combo.setCurrentIndex(format_index)

            self.web_search_enabled_check.setChecked(self._original_settings.get("web_search_enabled", False))
            self.web_search_auto_enabled_check.setChecked(
                self._original_settings.get("web_search_auto_enabled", True)
            )
            web_search_provider = str(self._original_settings.get("web_search_provider", "tavily")).strip().lower()
            web_search_provider_index = self.web_search_provider_combo.findData(web_search_provider)
            if web_search_provider_index < 0:
                web_search_provider = "tavily"
                web_search_provider_index = self.web_search_provider_combo.findData(web_search_provider)
            self.web_search_provider_combo.setCurrentIndex(web_search_provider_index if web_search_provider_index >= 0 else 0)
            loaded_web_search_keys = self._original_settings.get("web_search_api_keys", {})
            self._web_search_api_keys = (
                dict(loaded_web_search_keys)
                if isinstance(loaded_web_search_keys, dict)
                else {}
            )
            self._web_search_api_keys.setdefault("tavily", "")
            self._load_web_search_provider_controls(web_search_provider)
            try:
                web_search_max_results = int(self._original_settings.get("web_search_max_results", 5) or 5)
            except Exception:
                web_search_max_results = 5
            self.web_search_max_results_spin.setValue(max(1, min(web_search_max_results, 10)))
            try:
                web_search_timeout_sec = int(self._original_settings.get("web_search_timeout_sec", 12) or 12)
            except Exception:
                web_search_timeout_sec = 12
            self.web_search_timeout_sec_spin.setValue(max(1, min(web_search_timeout_sec, 60)))

            embedding_provider = str(self._original_settings.get("embedding_provider", "voyage")).strip().lower()
            if embedding_provider not in {"voyage", "openai", "openai_compatible", "gemini"}:
                embedding_provider = "voyage"
            loaded_embedding_keys = self._original_settings.get("embedding_api_keys", {})
            self._embedding_api_keys = dict(loaded_embedding_keys) if isinstance(loaded_embedding_keys, dict) else {}
            for provider_name in ("voyage", "openai", "openai_compatible", "gemini"):
                self._embedding_api_keys.setdefault(provider_name, "")

            loaded_embedding_configs = self._original_settings.get("embedding_provider_configs", {})
            self._embedding_provider_configs = (
                dict(loaded_embedding_configs)
                if isinstance(loaded_embedding_configs, dict)
                else {}
            )
            for provider_name in ("voyage", "openai", "openai_compatible", "gemini"):
                provider_config = self._embedding_provider_configs.get(provider_name, {})
                if not isinstance(provider_config, dict):
                    provider_config = {}
                provider_config.setdefault("api_url", self._embedding_default_api_url(provider_name))
                self._embedding_provider_configs[provider_name] = provider_config

            self._embedding_models_by_provider = {
                provider_name: self._embedding_default_model(provider_name)
                for provider_name in ("voyage", "openai", "openai_compatible", "gemini")
            }
            self._embedding_models_by_provider[embedding_provider] = (
                str(self._original_settings.get("embedding_model", self._embedding_default_model(embedding_provider))).strip()
                or self._embedding_default_model(embedding_provider)
            )
            provider_index = self.embedding_provider_combo.findData(embedding_provider)
            if provider_index < 0:
                provider_index = 0
            self.embedding_provider_combo.setCurrentIndex(provider_index)
            self._load_embedding_provider_controls(embedding_provider)

            self.llm_api_key_edit.setText(str(self._llm_api_keys.get(selected_provider, "")))
            self._sync_llm_custom_api_visibility(selected_provider)
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
        self._write_selected_image_avatar_placement()
        current_provider = str(self.llm_provider_combo.currentData() or "gemini")
        if current_provider == "custom_api":
            self._llm_api_keys[current_provider] = ""
            self._llm_models[current_provider] = self.custom_api_request_model_edit.text().strip()
        else:
            self._llm_api_keys[current_provider] = self.llm_api_key_edit.text()
            self._llm_models[current_provider] = self.llm_model_edit.text().strip()
        self._set_current_model_params()
        web_search_provider = self._current_web_search_provider()
        self._web_search_api_keys[web_search_provider] = self.web_search_api_key_edit.text().strip()

        active_custom_emotion = self.head_pat_active_emotion_custom_edit.text().strip()
        active_default_emotion = self.head_pat_active_emotion_combo.currentText().strip() or "normal"
        resolved_active_emotion = active_custom_emotion if active_custom_emotion else active_default_emotion

        custom_emotion = self.head_pat_end_emotion_custom_edit.text().strip()
        default_emotion = self.head_pat_end_emotion_combo.currentText().strip() or "normal"
        resolved_emotion = custom_emotion if custom_emotion else default_emotion

        if not resolved_active_emotion:
            resolved_active_emotion = "normal"
        if not resolved_emotion:
            resolved_emotion = "normal"

        preserved_hidden_settings = {
            key: self._original_settings[key]
            for key in (
                "stt_model_size",
                "stt_device",
                "stt_compute_type",
                "stt_min_record_sec",
                "stt_max_record_sec",
            )
            if key in self._original_settings
        }
        self._store_current_embedding_provider_controls()
        embedding_provider = self._current_embedding_provider()
        embedding_api_keys = dict(self._embedding_api_keys)
        embedding_provider_configs = {}
        for provider_name, provider_config in self._embedding_provider_configs.items():
            if isinstance(provider_config, dict):
                embedding_provider_configs[provider_name] = dict(provider_config)
        memory_search_recent_turns = (
            self.memory_search_recent_turns_spin.value()
            if self.memory_search_recent_turns_spin is not None
            else int(self._original_settings.get("memory_search_recent_turns", 2) or 0)
        )

        return {
            **preserved_hidden_settings,
            "ui_language": str(self.ui_language_combo.currentData() or "auto"),
            "assistant_display_name": self.assistant_display_name_edit.text().strip(),
            "user_address_name": self.user_address_name_edit.text().strip(),
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
            "typing_effect_enabled": self.typing_effect_check.isChecked(),
            "typing_effect_speed": str(self.typing_effect_speed_combo.currentData() or "normal"),
            "message_split_enabled": self.message_split_check.isChecked(),
            "enable_ene_thoughts": self.enable_ene_thoughts_check.isChecked(),
            "enable_proactive_conversation": self.enable_proactive_conversation_check.isChecked(),
            "enable_response_analysis": self.enable_response_analysis_check.isChecked(),
            "enable_mood_system": self.enable_mood_system_check.isChecked(),
            "mood_personality_profile": str(
                self.mood_personality_profile_combo.currentData() or "balanced"
            ),
            "enable_schedule_recognition": self.enable_schedule_recognition_check.isChecked(),
            "enable_conversation_promises": self.enable_conversation_promises_check.isChecked(),
            "enable_synthetic_gestures": self.enable_synthetic_gestures_check.isChecked(),
            "synthetic_gesture_scale": self.synthetic_gesture_scale_spin.value(),
            "enable_idle_synthetic_gestures": self.enable_idle_synthetic_gestures_check.isChecked(),
            "idle_synthetic_gesture_frequency": str(
                self.idle_synthetic_gesture_frequency_combo.currentData() or "normal"
            ),
            "enable_ene_goals": self.enable_ene_goals_check.isChecked(),
            "include_ene_thoughts_in_context": self.include_ene_thoughts_in_context_check.isChecked(),
            "ene_thought_context_limit": self.ene_thought_context_limit_spin.value(),
            "show_manual_summary_button": self.show_manual_summary_button_check.isChecked(),
            "show_obsidian_note_button": self.show_obsidian_note_button_check.isChecked(),
            "show_mood_toggle_button": self.show_mood_toggle_button_check.isChecked(),
            "show_ene_goal_button": self.show_ene_goal_button_check.isChecked(),
            "enable_global_ptt": self.enable_global_ptt_check.isChecked(),
            "interrupt_tts_on_ptt": self.interrupt_tts_on_ptt_check.isChecked(),
            "stt_language": str(self.ptt_language_combo.currentData() or "ko"),
            "enable_tts": self.enable_tts_check.isChecked(),
            "tts_language": str(self.tts_language_combo.currentData() or "ja"),
            "tts_streaming_enabled": self.tts_streaming_enabled_check.isChecked(),
            "viseme_lipsync_enabled": self.viseme_lipsync_enabled_check.isChecked(),
            "tts_streaming_emit_message_on_first_chunk": bool(
                self._original_settings.get("tts_streaming_emit_message_on_first_chunk", True)
            ),
            "tts_output_device_id": str(self.tts_output_device_combo.currentData() or "").strip(),
            "tts_output_volume": round(self.tts_output_volume_spin.value() / 100.0, 2),
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
            "obsidian_checked_max_chars_per_file": (
                self.obsidian_checked_max_chars_per_file_spin.value()
                if self.obsidian_checked_max_chars_per_file_spin is not None
                else int(self._original_settings.get("obsidian_checked_max_chars_per_file", 3000) or 3000)
            ),
            "obsidian_checked_total_max_chars": (
                self.obsidian_checked_total_max_chars_spin.value()
                if self.obsidian_checked_total_max_chars_spin is not None
                else int(self._original_settings.get("obsidian_checked_total_max_chars", 12000) or 12000)
            ),
            "memory_search_recent_turns": max(0, min(memory_search_recent_turns, 50)),
            "mouse_tracking_enabled": self.mouse_tracking_check.isChecked(),
            "enable_idle_motion": self.idle_motion_check.isChecked(),
            "enable_builtin_idle_motion": self.builtin_idle_motion_check.isChecked(),
            "enable_auto_eye_blink": self.auto_eye_blink_check.isChecked(),
            "idle_motion_strength": self.idle_motion_strength_spin.value(),
            "idle_motion_speed": self.idle_motion_speed_spin.value(),
            "enable_expressive_motion": self.expressive_motion_check.isChecked(),
            "enable_expressive_pose_transitions": self.expressive_pose_transitions_check.isChecked(),
            "expressive_motion_strength": self.expressive_motion_strength_spin.value(),
            "expressive_motion_speed": self.expressive_motion_speed_spin.value(),
            "expressive_motion_speech_boost": self.expressive_motion_speech_boost_spin.value(),
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
            "away_input_grace_minutes": min(
                self.away_input_grace_minutes_spin.value(),
                self.away_idle_minutes_spin.value(),
            ),
            "away_additional_retry_limit": self.away_retry_limit_spin.value(),
            "enable_life_records": self.enable_life_records_check.isChecked(),
            "life_record_min_inactive_minutes": self.life_record_min_inactive_minutes_spin.value(),
            "model_scale": self.model_scale_spin.value(),
            "model_x_percent": self.model_x_slider.value(),
            "model_y_percent": self.model_y_slider.value(),
            "model_json_path": self._normalize_path_for_storage(self.model_json_path_edit.text()),
            "avatar_mode": str(self.avatar_mode_combo.currentData() or "live2d"),
            "image_avatar_folder": self._normalize_path_for_storage(self.image_avatar_folder_edit.text()),
            "image_avatar_placements": dict(self._image_avatar_placements),
            "image_avatar_preview_emotion": self._selected_image_avatar_emotion(),
            "llm_provider": str(self.llm_provider_combo.currentData() or "gemini"),
            "llm_model": self.llm_model_edit.text().strip() or "gemini-3-flash-preview",
            "llm_models": dict(self._llm_models),
            "llm_model_params": dict(self._llm_model_params),
            "llm_api_keys": dict(self._llm_api_keys),
            "custom_api_url": self.custom_api_url_edit.text().strip(),
            "custom_api_key_or_password": self.custom_api_key_or_password_edit.text().strip(),
            "custom_api_request_model": self.custom_api_request_model_edit.text().strip(),
            "custom_api_format": str(self.custom_api_format_combo.currentData() or LLMFormat.OPENAI_COMPATIBLE.value),
            "web_search_enabled": self.web_search_enabled_check.isChecked(),
            "web_search_auto_enabled": self.web_search_auto_enabled_check.isChecked(),
            "web_search_provider": web_search_provider,
            "web_search_max_results": self.web_search_max_results_spin.value(),
            "web_search_timeout_sec": self.web_search_timeout_sec_spin.value(),
            "web_search_api_keys": dict(self._web_search_api_keys),
            "embedding_api_keys": embedding_api_keys,
            "embedding_provider": embedding_provider,
            "embedding_model": self.embedding_model_combo.currentText().strip() or "voyage-3",
            "embedding_provider_configs": embedding_provider_configs,
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
                self._translated_text("settings.theme.warning.invalid_hex.title", "테마 색상 확인"),
                self._translated_text(
                    "settings.theme.warning.invalid_hex.body",
                    "모든 테마 값은 `#RRGGBB` 형식의 6자리 HEX 코드만 사용할 수 있습니다.",
                ),
            )
            self._theme_color_edits[invalid_key].setFocus()
            return
        self._saved = True
        self.settings_changed.emit(self._get_current_values())
        self.close()

    def _cancel_settings(self):
        self._saved = False
        self._restore_original_ui_language()
        self.settings_cancelled.emit()
        self.close()
