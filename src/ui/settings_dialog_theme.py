"""
설정 대화상자 테마 제어 mixin.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QVBoxLayout, QWidget

from ..core.system_theme import THEME_PRESETS, THEME_VARIANT_PRESETS, get_theme_preset, get_windows_theme_mode
from .settings_dialog_widgets import ClickableFrame, ThemeColorPickerPopup


class SettingsDialogThemeMixin:
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

    def _theme_status_suffix(self, status: str, fallback: str) -> str:
        return self._translated_text(f"settings.theme.status.{status}", fallback)

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
        popup.set_title(
            self._theme_color_titles.get(
                key,
                self._translated_text("settings.theme.picker.popup.title", "색상 선택"),
            )
        )
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
            self._theme_picker_popup = ThemeColorPickerPopup(
                self,
                fallback_title=self._translated_text("settings.theme.picker.popup.title", "색상 선택"),
            )
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
        self._bind_widget_text(title, "settings.theme.picker.panel.title", "색상 미세 조정")
        title.setStyleSheet("font-size: 12px; font-weight: 800;")
        header_text.addWidget(title)
        value_label = QLabel(self._theme_defaults[key])
        self._theme_picker_value_labels[key] = value_label
        header_text.addWidget(value_label)
        header_row.addLayout(header_text)
        header_row.addStretch()

        close_button = QPushButton("닫기")
        self._bind_widget_text(close_button, "settings.theme.picker.panel.close", "닫기")
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
            ("settings.theme.picker.slider.hue", "색조", 0, 359, self._theme_picker_hue_sliders),
            ("settings.theme.picker.slider.saturation", "채도", 0, 255, self._theme_picker_saturation_sliders),
            ("settings.theme.picker.slider.lightness", "밝기", 0, 255, self._theme_picker_lightness_sliders),
        ]
        for label_key, label_text, minimum, maximum, slider_store in slider_specs:
            row = QHBoxLayout()
            row.setSpacing(10)
            label = QLabel(label_text)
            self._bind_widget_text(label, label_key, label_text)
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
        self._theme_color_text_meta[key] = (
            f"settings.theme.color.{key}.title",
            title,
            f"settings.theme.color.{key}.description",
            description,
        )

        title_label = QLabel(title)
        self._theme_color_title_labels[key] = title_label
        title_label.setStyleSheet("font-size: 13px; font-weight: 700; color: #111827;")
        layout.addWidget(title_label)

        desc_label = QLabel(description)
        self._theme_color_desc_labels[key] = desc_label
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
        self._bind_tooltip(swatch, "settings.theme.color.swatch.tooltip", "클릭해서 색상 선택")
        swatch.clicked.connect(lambda field_key=key: self._pick_theme_color(field_key))
        self._theme_color_swatches[key] = swatch
        setattr(self, f"{key}_swatch", swatch)
        row.addWidget(swatch)

        reset_button = QPushButton("기본값")
        self._bind_widget_text(reset_button, "settings.theme.color.reset", "기본값")
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
        self._bind_widget_text(assistant, "settings.theme.preview.assistant", "응답")
        assistant.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        assistant.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sample_row.addWidget(assistant, 1)
        user = QLabel("사용자")
        self._bind_widget_text(user, "settings.theme.preview.user", "사용자")
        user.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        user.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sample_row.addWidget(user, 1)
        layout.addLayout(sample_row)
        self._theme_preset_assistant[mode] = assistant
        self._theme_preset_user[mode] = user

        input_preview = QLabel("입력 필드 예시")
        self._bind_widget_text(input_preview, "settings.theme.preview.input", "입력 필드 예시")
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
            meta_suffix = (
                self._theme_status_suffix("follow_system", "윈도우와 동기화 중")
                if self._follow_system_theme and self._theme_mode == mode
                else (
                    self._theme_status_suffix("selected", "현재 선택됨")
                    if is_active
                    else self._theme_status_suffix("apply", "클릭해서 적용")
                )
            )
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
                suffix = (
                    self._theme_status_suffix("current_palette", "현재 팔레트")
                    if is_active
                    else self._theme_status_suffix("apply", "클릭해서 적용")
                )
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
                self.theme_status_label.setText(
                    self._translated_text(
                        "settings.theme.status.invalid_hex",
                        "모든 테마 값은 `#RRGGBB` 형식의 6자리 HEX 코드여야 합니다.",
                    )
                )
            else:
                self.theme_status_label.setStyleSheet("color: #6B7280; font-size: 12px; font-weight: 600;")
                if self._follow_system_theme:
                    current_mode_text = (
                        self._translated_text("settings.theme.mode.light.short", "라이트")
                        if self._theme_mode == "light"
                        else self._translated_text("settings.theme.mode.dark.short", "다크")
                    )
                    self.theme_status_label.setText(
                        self._translated_text_format(
                            "settings.theme.status.follow_system_detail",
                            "현재 윈도우 앱 테마({mode})를 따라가고 있습니다.",
                            mode=current_mode_text,
                        )
                    )
                else:
                    self.theme_status_label.setText(
                        self._translated_text(
                            "settings.theme.status.shared_mode",
                            "설정창과 채팅창이 같은 테마 모드로 함께 움직이도록 구성되어 있습니다.",
                        )
                    )

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
