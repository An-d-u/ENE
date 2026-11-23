"""
설정 대화상자 테마 제어 mixin.
"""

from __future__ import annotations

import re

from PyQt6.QtCore import QPoint, QSignalBlocker, QSize, Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget

from ..core.system_theme import THEME_PRESETS, THEME_VARIANT_PRESETS, get_theme_preset, get_windows_theme_mode
from .settings_theme_art import PALETTE_ART, PaletteArtwork, theme_icon
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
            if self._theme_editor_active:
                self.theme_color_dialog.reject()
        self.theme_edit_button.setEnabled(enabled)

    def _set_palette_values(self, values, *, emit_preview=True):
        self._close_all_theme_pickers()
        self._theme_live_update_timer.stop()
        self._theme_values.update(values)
        for key, edit in self._theme_color_edits.items():
            with QSignalBlocker(edit):
                edit.setText(self._theme_values[key])
        self._apply_stylesheet()
        self._refresh_theme_editor_state()
        if emit_preview and not self._loading:
            self._preview_settings()

    def _apply_theme_mode(self, mode: str, *, emit_preview: bool = True) -> None:
        self._theme_mode = mode if mode in THEME_PRESETS else "light"
        self._theme_base_variant = None
        self._set_palette_values(get_theme_preset(self._theme_mode), emit_preview=emit_preview)

    def _remember_manual_palette(self):
        if not self._follow_system_theme:
            mode = self._theme_mode
            variant = self._theme_base_variant or self._current_theme_variant_id(mode)
            self._theme_mode_choices[mode] = variant
            self._theme_palette_drafts[(mode, variant)] = dict(self._theme_values)

    def _select_manual_palette(self, mode, variant):
        self._remember_manual_palette()
        self._follow_system_theme = False
        self._theme_mode = mode
        self._theme_base_variant = variant
        self._set_theme_editors_enabled(True)
        bundle = THEME_VARIANT_PRESETS[mode].get(variant, THEME_PRESETS[mode])
        self._set_palette_values(self._theme_palette_drafts.get((mode, variant), bundle["colors"]))

    def _on_theme_mode_selected(self, mode: str) -> None:
        if mode == "system":
            self._on_follow_system_theme_toggled(True)
        elif not self._follow_system_theme and self._theme_mode == mode:
            self._refresh_theme_editor_state()
        else:
            default_variant = next(iter(THEME_VARIANT_PRESETS[mode]))
            self._select_manual_palette(mode, self._theme_mode_choices.get(mode, default_variant))

    def _on_follow_system_theme_toggled(self, checked: bool) -> None:
        if not checked:
            self._on_theme_mode_selected(self._theme_mode)
            return
        self._remember_manual_palette()
        self._follow_system_theme = True
        self._set_theme_editors_enabled(False)
        self._apply_theme_mode(get_windows_theme_mode())

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
        popup.set_color(self._normalize_theme_color(self._theme_color_edits[key].text(), self._theme_values[key]), emit_signal=False)
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
                self.theme_color_dialog,
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
        if variant_id in THEME_VARIANT_PRESETS.get(mode, {}):
            self._select_manual_palette(mode, variant_id)

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
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 3, 0, 3)
        row.setSpacing(8)
        self._theme_color_titles[key] = title
        self._theme_color_text_meta[key] = (
            f"settings.theme.color.{key}.title", title,
            f"settings.theme.color.{key}.description", description,
        )
        title_label = QLabel(title)
        title_label.setWordWrap(True)
        self._theme_color_title_labels[key] = title_label
        title_label.setToolTip(description)
        row.addWidget(title_label, 1)

        line_edit = QLineEdit()
        line_edit.setFixedWidth(90)
        line_edit.setPlaceholderText(self._theme_defaults[key])
        line_edit.setMaxLength(7)
        line_edit.textChanged.connect(lambda text: self._on_theme_color_field_changed(key, text))
        title_label.setBuddy(line_edit)
        self._theme_color_edits[key] = line_edit
        row.addWidget(line_edit)

        swatch = QPushButton()
        swatch.setFixedSize(30, 30)
        swatch.setCursor(Qt.CursorShape.PointingHandCursor)
        self._register_text_binding(swatch.setAccessibleName, f"settings.theme.color.{key}.title", title)
        self._bind_tooltip(swatch, "settings.theme.color.swatch.tooltip", "클릭해서 색상 선택")
        swatch.clicked.connect(lambda: self._pick_theme_color(key))
        self._theme_color_swatches[key] = swatch
        row.addWidget(swatch)

        reset = self._bind_widget_text(QPushButton(), "settings.theme.color.reset", "기본값")
        reset.clicked.connect(lambda: line_edit.setText(self._theme_editor_defaults()[key]))
        self._theme_color_reset_buttons[key] = reset
        row.addWidget(reset)
        return container

    def _theme_editor_defaults(self):
        variant_id = self._theme_base_variant or self._current_theme_variant_id(self._theme_mode)
        bundle = THEME_VARIANT_PRESETS[self._theme_mode].get(variant_id, THEME_PRESETS[self._theme_mode])
        return bundle["colors"]

    def _open_theme_color_editor(self):
        if self._follow_system_theme:
            return
        self._theme_base_variant = self._theme_base_variant or self._current_theme_variant_id(self._theme_mode)
        self._theme_editor_active = True
        self._refresh_theme_editor_state()
        self.theme_color_dialog.open()

    def _finish_theme_color_editor(self, result):
        self._close_all_theme_pickers()
        self._theme_editor_active = False
        if result == QDialog.DialogCode.Accepted:
            values = {key: self._normalize_theme_color(edit.text(), self._theme_values[key])
                      for key, edit in self._theme_color_edits.items()}
            self._set_palette_values(values)
        else:
            for key, edit in self._theme_color_edits.items():
                with QSignalBlocker(edit):
                    edit.setText(self._theme_values[key])
            self._refresh_theme_editor_state()

    def _build_theme_mode_preview(self, mode: str) -> QPushButton:
        button = QPushButton()
        button.setCheckable(True)
        button.setAutoDefault(False)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        if mode == "system":
            self._bind_widget_text(button, "settings.theme.studio.system", "시스템")
        else:
            self._bind_widget_text(button, f"settings.theme.mode.{mode}.short", "라이트" if mode == "light" else "다크")
        button.clicked.connect(lambda: self._on_theme_mode_selected(mode))
        self._theme_preset_frames[mode] = button
        return button

    def _build_theme_variant_preview(self, mode: str, variant_id: str, title: str) -> QPushButton:
        button = QPushButton(self.theme_palette_grid)
        button.setObjectName("ThemePaletteCard")
        button.setCheckable(True)
        button.setAutoDefault(False)
        button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda: self._apply_theme_variant(mode, variant_id))
        row = QHBoxLayout(button)
        row.setContentsMargins(12, 9, 12, 9)
        row.setSpacing(10)
        first, second, subtitle = PALETTE_ART[variant_id]
        art = PaletteArtwork(compact=True)
        art.set_colors(first, second, THEME_VARIANT_PRESETS[mode][variant_id]["colors"]["theme_accent_color"])
        row.addWidget(art)
        copy = QVBoxLayout()
        copy.setSpacing(1)
        heading = QLabel(title)
        self._theme_variant_titles[variant_id] = heading
        heading.setStyleSheet("font-size: 13px; font-weight: 750;")
        copy.addWidget(heading)
        sub = self._create_form_label(f"settings.theme.studio.{variant_id}", subtitle)
        sub.setObjectName("ThemeCardSubtitle")
        copy.addWidget(sub)
        row.addLayout(copy, 1)
        tick = QLabel()
        tick.setObjectName("ThemeCardCheck")
        tick.setFixedSize(17, 17)
        tick.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(tick)
        for child in (art, heading, sub, tick):
            child.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._theme_variant_frames[variant_id] = button
        return button

    def _refresh_theme_color_controls(self):
        invalid = False
        for key, edit in self._theme_color_edits.items():
            raw = edit.text().strip()
            color = self._normalize_theme_color(raw, self._theme_values[key])
            self._theme_color_swatches[key].setStyleSheet(
                f"background: {color}; border: 1px solid {self._theme_border_color(color, 0.25)}; border-radius: 8px;"
            )
            if not self._is_valid_theme_color(raw):
                invalid = True
        self.theme_color_apply_button.setEnabled(not invalid)
        self.theme_status_label.setVisible(invalid)
        self.theme_status_label.setText(self._translated_text(
            "settings.theme.status.invalid_hex", "모든 테마 값은 `#RRGGBB` 형식의 6자리 HEX 코드여야 합니다."
        ))

    def _style_theme_studio(self):
        values = self._theme_values
        card, field = values["settings_card_bg_color"], values["settings_input_bg_color"]
        accent = values["theme_accent_color"]
        ink, muted = self._theme_text_color(card), self._theme_muted_text_color(card)
        border = self._theme_border_color(card, 0.16)
        self.theme_section_rule.setStyleSheet(f"background: {border}; border: none;")
        self.theme_color_dialog.setStyleSheet(
            f"QDialog#ThemeColorDialog, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {card}; color: {ink}; }}"
            f"QLabel {{ background: transparent; color: {ink}; }}"
            f"QPushButton#ThemeApply:enabled {{background: {accent}; color: {self._theme_text_color(accent)};}}"
        )
        self.theme_edit_button.setIcon(theme_icon("edit", muted))
        self.theme_edit_button.setIconSize(QSize(14, 14))
        self.theme_segments.setStyleSheet(
            f"QFrame#ThemeSegments {{background: {field}; border: 1px solid {border}; border-radius: 10px;}}"
            f"QPushButton {{background: transparent; color: {muted}; border: 1px solid transparent;"
            "border-radius: 7px; padding: 4px 9px; font-size: 12px; min-height: 19px;}"
            f"QPushButton:checked {{background: {card}; color: {ink}; border-color: {border}; font-weight: 700;}}"
            f"QPushButton:focus {{border-color: {accent};}}"
        )
        self.theme_edit_button.setStyleSheet(
            f"QPushButton {{background: transparent; color: {muted}; border: 1px solid transparent; padding: 4px;}}"
            f"QPushButton:hover, QPushButton:focus {{color: {accent}; border-color: {accent};}}"
            f"QPushButton:disabled {{color: {self._theme_rgba(ink, 0.4)};}}"
        )
        self.theme_palette_grid.setStyleSheet(
            f"QPushButton#ThemePaletteCard {{background: {card}; color: {ink}; border: 1px solid {border};"
            "border-radius: 13px; padding: 0; min-height: 58px;}"
            f"QPushButton#ThemePaletteCard:checked {{background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
            f"stop:0 {card},stop:1 {field}); border: 1px solid {accent};}}"
            f"QPushButton#ThemePaletteCard:hover, QPushButton#ThemePaletteCard:focus {{border: 2px solid {accent};}}"
            f"QLabel {{background: transparent; color: {ink}; border: none;}}"
            f"QLabel#ThemeCardSubtitle {{color: {muted}; font-size: 11px;}}"
            f"QLabel#ThemeCardCheck {{background: {accent}; color: {self._theme_text_color(accent)};"
            "border-radius: 8px; font-size: 11px; font-weight: 800;}"
        )
    def _refresh_theme_choices(self, active):
        card = self._theme_values["settings_card_bg_color"]
        check = theme_icon("check", self._theme_text_color(self._theme_values["theme_accent_color"])).pixmap(13, 13)
        for mode, button in self._theme_preset_frames.items():
            selected = (mode == "system") if self._follow_system_theme else (mode == self._theme_mode)
            button.setChecked(selected)
            color = self._theme_text_color(card) if selected else self._theme_muted_text_color(card)
            button.setIcon(theme_icon(mode, color))
            button.setIconSize(QSize(14, 14))
            if mode == "system":
                description = self._translated_text("settings.theme.follow_system", "현재 윈도우 앱 테마(라이트/다크)를 따라가기")
            else:
                status = self._theme_status_suffix("selected", "현재 선택됨") if selected else self._theme_status_suffix("apply", "클릭해서 적용")
                if self._follow_system_theme and self._theme_mode == mode:
                    status = self._theme_status_suffix("follow_system", "윈도우와 동기화 중")
                description = f"{self._resolve_theme_bundle_text(THEME_PRESETS[mode], 'description')} · {status}"
            button.setToolTip(description)
        for mode, variants in THEME_VARIANT_PRESETS.items():
            for key, bundle in variants.items():
                button = self._theme_variant_frames[key]
                title = self._resolve_theme_bundle_text(bundle, "title")
                self._theme_variant_titles[key].setText(title)
                selected = key == active
                status = self._theme_status_suffix("current_palette", "현재 팔레트") if selected else self._theme_status_suffix("apply", "클릭해서 적용")
                description = f"{self._resolve_theme_bundle_text(bundle, 'description')} · {status}"
                button.setToolTip(description)
                button.setAccessibleName(title)
                button.setAccessibleDescription(description)
                button.setChecked(selected)
                mark = button.findChild(QLabel, "ThemeCardCheck")
                mark.setPixmap(check)
                mark.setVisible(selected)
        self.theme_palette_grid.show_mode(self._theme_mode)

    def _refresh_theme_hero(self, active):
        values = self._theme_values
        card, accent = values["settings_card_bg_color"], values["theme_accent_color"]
        if active:
            name = self._resolve_theme_bundle_text(THEME_VARIANT_PRESETS[self._theme_mode][active], "title")
        elif values == get_theme_preset(self._theme_mode):
            name = self._resolve_theme_bundle_text(THEME_PRESETS[self._theme_mode], "title")
        else:
            name = self._translated_text("settings.theme.studio.custom", "사용자 지정")
        self.theme_palette_name.setText(name)
        base = active or self._theme_base_variant
        first, second = PALETTE_ART[base][:2] if base in PALETTE_ART else ("#FAC9AD", "#C6B1EB")
        self.theme_hero.set_colors(first, second, accent)
        for dot, color in zip(self.theme_pigments, (first, second, card, accent)):
            dot.setStyleSheet(f"background: {color}; border: 1px solid #FFF8EF; border-radius: 10px;")
            dot.setToolTip(color)
        panel = values["chat_panel_bg_color"]
        self.theme_chat_preview.setStyleSheet(
            f"QFrame#ThemeSampleChat {{background: {panel}; border: 1px solid {self._theme_border_color(panel)}; border-radius: 11px;}}"
            f"QLabel {{background: transparent; color: {self._theme_text_color(panel)}; font-size: 11px; font-weight: 700;}}"
        )
        for bubble, color in ((self.theme_chat_assistant, values["chat_assistant_bubble_color"]),
                              (self.theme_chat_user, values["chat_user_bubble_color"])):
            bubble.setStyleSheet(f"background: {color}; color: {self._theme_text_color(color)}; border-radius: 7px; padding: 4px 8px; font-size: 11px;")
        self.theme_chat_input.setStyleSheet(
            f"background: {values['chat_input_bg_color']}; border: 1px solid {self._theme_border_color(panel)}; border-radius: 5px;"
        )

    def _refresh_theme_editor_state(self) -> None:
        if not hasattr(self, "theme_color_dialog"):
            return
        if self._loading:
            self._theme_base_variant = None
        self._refresh_theme_color_controls()
        self._style_theme_studio()
        active = self._current_theme_variant_id(self._theme_mode)
        self._refresh_theme_choices(active)
        self._refresh_theme_hero(active)

    def _on_theme_color_field_changed(self, key: str, text: str) -> None:
        if self._theme_editor_active:
            self._refresh_theme_color_controls()
            return
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
